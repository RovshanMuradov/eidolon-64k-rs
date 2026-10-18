"""Real i386 PE regressions for constant redirection's safety boundary."""
import importlib.machinery
import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'size/crate/tools/rust/merge-constants'
loader = importlib.machinery.SourceFileLoader('merge_constants', str(TOOL))
spec = importlib.util.spec_from_loader(loader.name, loader)
merger = importlib.util.module_from_spec(spec)
loader.exec_module(merger)

ASM = r'''
.intel_syntax noprefix
.text
.globl _start
_start:
    movsd xmm0, QWORD PTR canonical
    addsd xmm0, QWORD PTR duplicate
    movaps xmm1, XMMWORD PTR vector
    xorps xmm1, XMMWORD PTR vector_copy
    movss xmm2, DWORD PTR narrow
    movss xmm3, DWORD PTR wide_copy
    movsd xmm4, QWORD PTR wide_copy
    movups xmm5, XMMWORD PTR unaligned
    movups xmm6, XMMWORD PTR aligned_copy
    movsd xmm0, QWORD PTR table_copy
    lea eax, table
    movsd xmm0, QWORD PTR [eax + 4096]
    movsd xmm0, QWORD PTR [ecx*8 + table]
    movsd xmm0, QWORD PTR overlap
    movsd xmm0, QWORD PTR overlap+4
    movsd xmm0, QWORD PTR relocated
    movsd xmm0, QWORD PTR relocated_copy
    movsd QWORD PTR store_target, xmm0
    add DWORD PTR store_target, 1
    lea eax, duplicate
    mov eax, OFFSET duplicate
    ret
.section .rdata,"dr"
.balign 16
canonical: .quad 0x3ff0000000000000
.balign 16
duplicate: .quad 0x3ff0000000000000
.balign 16
vector: .quad 0xbff0000000000000, 0x4000000000000000
.balign 16
vector_copy: .quad 0xbff0000000000000, 0x4000000000000000
.balign 16
narrow: .long 0x3f800000
.balign 16
wide_copy: .long 0x3f800000, 0x40100000
.balign 16
.byte 0
unaligned: .quad 0x5555555555555555, 0x5555555555555555
.balign 16
aligned_copy: .quad 0x5555555555555555, 0x5555555555555555
.balign 16
table:
.space 4096
table_copy: .quad 0x3ff0000000000000
.balign 16
overlap: .long 0, 0x3ff00000, 0x40000000
.balign 16
relocated: .long canonical, 0
.balign 16
relocated_copy: .long canonical, 0
.balign 16
store_target: .quad 0x3ff0000000000000
'''


@unittest.skipUnless(shutil.which('i686-w64-mingw32-gcc') and shutil.which('objdump'),
                     'requires MinGW i386 gcc and GNU objdump')
class MergeConstantsTests(unittest.TestCase):
    def setUp(self):
        work = ROOT / '.build/merge-constants-tests'
        work.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name)
        source, self.image = path / 'test.s', path / 'test.exe'
        source.write_text(ASM)
        subprocess.run(['i686-w64-mingw32-gcc', '-nostdlib', '-Wl,-e,_start',
                        '-Wl,--no-insert-timestamp', str(source), '-o', str(self.image)], check=True)
        self.before = self.image.read_bytes()
        self.pe = merger.PE(self.before)
        self.insns = list(merger.instructions(self.image))

    def loads(self):
        result = []
        for va, code in self.insns:
            read = merger.absolute_read(code)
            if read:
                disp, width = read
                result.append((va + disp, struct.unpack_from('<I', code, disp)[0], width))
        return result

    def test_real_pe_preserves_tables_overlaps_and_relocated_values(self):
        after = bytearray(self.before)
        self.assertEqual(merger.merge(after, self.insns), 4)
        # This checks *all* data, including the indexed table > 1 KiB past its
        # address-taken base, its duplicate element, and overlapping FP reads.
        for name, (_, size, raw, _) in self.pe.sections.items():
            if name != b'.text':
                self.assertEqual(after[raw:raw + size], self.before[raw:raw + size], name)
        loads = self.loads()
        redirected = {}
        for site, old, width in loads:
            new = struct.unpack_from('<I', after, self.pe.offset(site, 4))[0]
            if new != old:
                redirected[old] = new
            a, b = self.pe.offset(old, width), self.pe.offset(new, width)
            self.assertEqual(after[a:a + width], after[b:b + width])
        # 0/1 = scalar pair; 2/3 = vector pair; 4/5/6 = mixed widths;
        # 7/8 = identical vector with incompatible alignment; 9 = table element;
        # 10/11 = overlapping ranges; 12/13 contain base relocations.
        self.assertEqual(redirected[loads[1][1]], loads[0][1])
        self.assertEqual(redirected[loads[3][1]], loads[2][1])
        self.assertEqual(redirected[loads[9][1]], loads[0][1])
        for i in (4, 5, 6, 7, 8, 11, 12, 13):
            self.assertNotIn(loads[i][1], redirected)
        allowed = {self.pe.offset(site, 4) + j for site, _, _ in loads for j in range(4)}
        for i, (a, b) in enumerate(zip(self.before, after)):
            if a != b:
                self.assertIn(i, allowed)
        # Loader rebasing must still relocate the redirected code addresses;
        # any FP constant containing a rebased pointer is excluded.
        rebased = bytearray(after)
        delta = 0x100000
        for site in self.pe.relocations:
            off = self.pe.offset(site, 4)
            struct.pack_into('<I', rebased, off, (struct.unpack_from('<I', after, off)[0] + delta) & 0xffffffff)
        for site, _, _ in loads:
            off = self.pe.offset(site, 4)
            self.assertEqual(struct.unpack_from('<I', rebased, off)[0],
                             struct.unpack_from('<I', after, off)[0] + delta)

    def test_cli_is_idempotent(self):
        subprocess.run(['python3', str(TOOL), str(self.image)], check=True, capture_output=True)
        after = self.image.read_bytes()
        self.assertNotEqual(after, self.before)
        subprocess.run(['python3', str(TOOL), str(self.image)], check=True, capture_output=True)
        self.assertEqual(self.image.read_bytes(), after)

    def test_write_index_address_and_prefix_encodings_are_not_reads(self):
        for code in ('f20f110500104000', '83050010400001', '8d0500104000',
                     'b800104000', 'f20f1004cd00104000', 'f20f108000104000',
                     '64f20f100500104000', '67f20f100500104000', 'dd0500104000'):
            self.assertIsNone(merger.absolute_read(bytes.fromhex(code)), code)

    def test_absent_relocation_is_not_redirected(self):
        # Removing the source instruction's relocation must leave it unchanged.
        after = bytearray(self.before)
        site = self.loads()[1][0]
        old = self.pe.offset(site, 4)
        # Relocations are in 4K blocks; replace precisely this entry with ABSOLUTE.
        _, size, raw, _ = self.pe.sections[b'.reloc']
        p = raw
        while p < raw + size:
            page, block = struct.unpack_from('<II', after, p)
            if not block:
                break
            for off in range(p + 8, p + block, 2):
                e = struct.unpack_from('<H', after, off)[0]
                if self.pe.base + page + (e & 4095) == site:
                    struct.pack_into('<H', after, off, 0)
            p += block
        merger.merge(after, self.insns)
        self.assertEqual(after[old:old + 4], self.before[old:old + 4])

    def test_read_crossing_section_end_is_not_redirected(self):
        after = bytearray(self.before)
        site, _, _ = self.loads()[3]
        start, size, _, _ = self.pe.sections[b'.rdata']
        target = start + size - 4  # an XMM read would extend beyond this object
        struct.pack_into('<I', after, self.pe.offset(site, 4), target)
        insns = [(va, bytes(after[self.pe.offset(va, len(code)):self.pe.offset(va, len(code)) + len(code)]))
                 for va, code in self.insns]
        merger.merge(after, insns)
        self.assertEqual(struct.unpack_from('<I', after, self.pe.offset(site, 4))[0], target)

    def test_writable_rdata_is_not_merged(self):
        after = bytearray(self.before)
        pe = struct.unpack_from('<I', after, 60)[0]
        table = pe + 24 + struct.unpack_from('<H', after, pe + 20)[0]
        for i in range(struct.unpack_from('<H', after, pe + 6)[0]):
            entry = table + 40 * i
            if after[entry:entry + 8].rstrip(b'\0') == b'.rdata':
                flags = struct.unpack_from('<I', after, entry + 36)[0]
                struct.pack_into('<I', after, entry + 36, flags | 0x80000000)
        before = bytes(after)
        self.assertEqual(merger.merge(after, self.insns), 0)
        self.assertEqual(after, before)


if __name__ == '__main__':
    unittest.main()
