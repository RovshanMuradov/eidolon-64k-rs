#!/usr/bin/env python3
"""Static native packing accounting; never loads or executes target instructions."""

import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import urllib.request
import zipfile

import zstandard


REV = "8c8f82c2ae01133370e649bbc05916e7aceecadd"
SOURCE_FILES = ("depacker.asm", "depack2.asm", "exepacker.cpp", "dis.cpp")
ROOT = Path(os.environ["EIDOLON_ROOT"])
DATA = Path(os.environ["EIDOLON_DATA"])
SOURCE = ROOT / ".tools/analysis/packing/fr_public/kkrunchy_k7"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked(path, sha):
    data = path.read_bytes()
    assert digest(data) == sha, f"changed input: {path}"
    return data


def u32(data, offset=0):
    return struct.unpack_from("<I", data, offset)[0]


def unfilter(stage, base=0x3F9000):
    """File-data transcription of pinned dis.cpp:476-704 / depack2.asm."""
    table = stage[0x3F967A - base:0x3F977A - base]
    sizes = struct.unpack_from("<20I", stage, 0x3F99BA - base)
    starts = [0x3F9A0A - base]
    for size in sizes:
        starts.append(starts[-1] + size)
    assert starts[-1] + base == 0x401000
    cursors = starts[:-1].copy()

    def take(index, size):
        pos = cursors[index]
        assert pos + size <= starts[index + 1], (index, pos, size)
        cursors[index] += size
        return stage[pos:pos + size]

    def byte(index=0):
        return take(index, 1)[0]

    def word(index):
        return u32(take(index, 4))

    out = bytearray()
    funcs = [0] * 256
    funcpos = 1
    nextfunc = True
    lastjump = 0
    jumptable = 0xFFFFFFFF

    def addfunc(value):
        nonlocal funcpos
        funcs[funcpos] = value
        funcpos = (funcpos + 1) % 256 or 1

    def emit32(value):
        out.extend(struct.pack("<I", value & 0xFFFFFFFF))

    while cursors[0] < starts[1]:
        address = 0x401000 + len(out)
        if address == jumptable:
            out.extend(take(15, word(15) * 4))
            jumptable = 0xFFFFFFFF
            continue
        if address > jumptable:
            jumptable = 0xFFFFFFFF
        code = byte()
        if nextfunc and code != 0xCC:
            addfunc(len(out))
            nextfunc = False
        if code == 0xCE:
            out.append(byte())
            continue
        out.append(code)
        o16 = code == 0x66
        if o16:
            code = byte()
            out.append(code)
        if code in (0xC2, 0xC3, 0xCC):
            nextfunc = True
        opcode = code
        if code == 0x0F:
            code2 = byte()
            out.append(code2)
            opcode = 256 + code2
        flags = (table[opcode // 2] >> (4 * (opcode % 2))) & 15
        if flags & 2:
            modrm = byte()
            out.append(modrm)
            if flags & 3 == 3:
                flags = 2
                if not modrm & 0x38 and not code & 8:
                    flags += 8 if code & 1 else 4
            sib = 0
            if modrm & 7 == 4 and modrm & 0xC0 != 0xC0:
                sib = byte(19)
                out.append(sib)
            if modrm & 0xC0 == 0x40:
                out.append(byte((modrm & 7) + 1))
            if (modrm & 0xC0 == 0x80 or modrm & 0xC7 == 5
                    or modrm & 0xC0 == 0 and sib & 7 == 5):
                value = int.from_bytes(take(14 if modrm & 0xC7 == 5 else 13, 4), "big")
                emit32(value)
                if code == 0xFF and modrm == 0x24:
                    jumptable = min(jumptable, value)
        kind = flags & 12
        if flags & 3 == 1:
            if kind == 0:
                out.extend(take(15, 4))
            elif kind == 4:
                out.append(byte(9))
            elif kind == 12:
                if code == 0xE8:
                    index = byte(16)
                    if index:
                        value = funcs[index]
                    else:
                        value = word(18)
                        addfunc(value)
                else:
                    value = word(17)
                    value = ~(value >> 1) if value & 1 else value >> 1
                    lastjump = (lastjump + value) & 0xFFFFFFFF
                    value = lastjump
                emit32(value - len(out) - 4)
            else:
                raise AssertionError("unsupported address mode")
        elif kind == 4:
            out.append(byte(10))
        elif kind == 8 and not o16:
            out.extend(take(12, 4))
        elif kind in (8, 12):
            out.extend(take(11, 2))
    assert cursors == starts[1:], "unconsumed filter bytes"
    return bytes(out), list(sizes)


def imports(stage):
    block = stage[0x77E:0x9BA]
    cursor = 0
    rows = []

    def string():
        nonlocal cursor
        end = block.index(0, cursor)
        result = block[cursor:end].decode("ascii")
        cursor = end + 1
        return result

    while True:
        assert block[cursor] == 0
        cursor += 1
        iat = u32(block, cursor)
        cursor += 4
        if not iat:
            break
        dll = string()
        names = []
        while block[cursor]:
            assert block[cursor] < 128, "ordinal imports require separate accounting"
            names.append(string())
        rows.append({"dll": dll, "iat_va": hex(iat), "names": names})
    assert cursor == len(block)
    return rows


def compressed(data):
    zstd = zstandard.ZstdCompressor(level=19, threads=0).compress(data)
    xz = lzma.compress(data, preset=9 | lzma.PRESET_EXTREME)
    assert zstandard.ZstdDecompressor().decompress(zstd) == data
    assert lzma.decompress(xz) == data
    return {"raw": len(data), "zstd19": len(zstd), "xz9e": len(xz)}


def code_closure(data, base, expected_calls, external_jumps=()):
    """Check continuous instruction coverage and static control-flow boundaries."""
    folder = DATA / "analysis/packing"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"code-{base:x}.bin"
    path.write_bytes(data)
    text = subprocess.check_output([
        "objdump", "-D", "-w", "-b", "binary", "-m", "i386", "-Mintel",
        f"--adjust-vma={base}", str(path)], text=True)
    instructions = []
    for line in text.splitlines():
        match = re.match(r"\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)", line)
        if match:
            address, raw, asm = match.groups()
            instructions.append((int(address, 16), bytes.fromhex(raw), asm))
    assert b"".join(row[1] for row in instructions) == data
    starts = {row[0] for row in instructions}
    calls = set()
    indirect = set()
    for address, raw, asm in instructions:
        assert "(bad)" not in asm
        op = asm.split()[0]
        if op.startswith("j") or op in ("loop", "call"):
            target = re.search(r"\b0x([0-9a-f]+)", asm)
            if target and "PTR" not in asm:
                target = int(target.group(1), 16)
                assert target in starts or target in external_jumps, (hex(address), asm)
                if op == "call":
                    calls.add(target)
            else:
                indirect.add(asm)
    assert calls == set(expected_calls)
    return {"bytes": len(data), "instructions": len(instructions),
            "direct_call_targets": [hex(n) for n in sorted(calls)],
            "indirect_control_flow": sorted(indirect),
            "allowed_external_jumps": [hex(n) for n in external_jumps],
            "coverage": "all bytes decoded; direct targets land on instruction boundaries; ret edges validated separately by source/transfer immediates"}


def measure():
    reverse = json.loads(Path("reports/evidence/reverse/manifest.json").read_text())
    archive = ROOT / reverse["inputs"]["archive"]["path"]
    checked(archive, reverse["inputs"]["archive"]["sha256"])
    with zipfile.ZipFile(archive) as z:
        exe = z.read(reverse["inputs"]["native"]["archive_member"])
    assert digest(exe) == reverse["inputs"]["native"]["sha256"]
    saved = reverse["runtime_diagnostic"]["files"]
    stage = checked(DATA / saved["stage1"]["path"], saved["stage1"]["sha256"])
    post = checked(DATA / saved["postfix"]["path"], saved["postfix"]["sha256"])
    assert len(exe) == 60928
    pe = u32(exe, 0x3C)
    assert pe == 12 and exe[pe:pe + 4] == b"PE\0\0"
    opt = pe + 24
    sec = opt + struct.unpack_from("<H", exe, pe + 20)[0]
    assert sec + 40 == 0xD4
    assert u32(exe, opt + 16) == 0xE786
    assert u32(exe, opt + 28) == 0x3E0000
    assert exe[sec:sec + 8] == b"kkrunchy"
    assert struct.unpack_from("<III", exe, sec + 12) == (0x1000, 0xDE00, 0x1000)
    # The short PE header shares its header mapping with the compressed stream.
    assert u32(exe, 0xE78E) == 0x3E00D4
    assert u32(exe, 0xE793) == 0x3F942D
    assert u32(exe, 0xE7A1) == 0xCD82BDA
    assert u32(exe, 0xE787) == 0xD183DD3
    assert exe[0xE92C:0xE945] == bytes.fromhex(
        "0f 77 58 68 00 00 40 00 68 00 00 3e 00 50 be 7a 97 3f 00 bb ec ec 3e 00 c3")
    # Work offsets referenced by original instructions, independent of source labels.
    assert exe[0xE6F5:0xE6FC] == bytes.fromhex("8d 84 85 18 01 20 00")
    assert exe[0xEB8F:0xEB96] == bytes.fromhex("8b 84 85 90 f7 a0 00")
    assert exe[0xEC60:0xEC67] == bytes.fromhex("8b 8c 85 90 03 a1 00")
    assert exe[0xE8A6:0xE8AC] == bytes.fromhex("8d bd 90 43 a1 00")
    assert exe[0xE6B0:0xE6B5] == bytes.fromhex("3d 01 f8 ff ff")
    assert exe[0xEC8F:0xEC94] == bytes.fromhex("e9 3b fc ff ff")
    squash = (1, 2, 4, 6, 10, 17, 27, 45, 74, 120, 194, 311, 488, 747,
              1102, 1546, 2048, 2550, 2994, 3349, 3608, 3785, 3902, 3976,
              4022, 4051, 4069, 4079, 4086, 4090, 4092, 4094, 4095)
    assert exe[0xEC94:0xECD6] == struct.pack("<33H", *squash)
    assert exe[0xECD6:0xECEC] == bytes.fromhex("1f2788070a090503040201 ffffffe0ffffffffffffff")
    assert struct.unpack_from("<6I", exe, 0xECEC) == (0xED10, 0xED1E, 0, 0xED10, 0xED1E, 0)
    assert exe[0xED04:0xED30] == b"KERNEL32.DLL\0\0LoadLibraryA\0\0GetProcAddress\0\0"
    assert struct.unpack_from("<5I", exe, 0xED30) == (0xECF8, 0, 0, 0xED04, 0xECEC)
    assert not any(exe[0xED44:])
    assert stage[0x4A4:0x4A9] == bytes.fromhex("e9 d0 ce 00 00")
    assert stage[0x46D:0x474] == bytes.fromhex("5e 5b 58 5f ab 55 46")
    assert u32(stage, 0x77A) == 572
    rebuilt, streams = unfilter(stage)
    assert post[0x1000:0x1000 + len(rebuilt)] == rebuilt
    assert u32(post) == 0x3E0000
    # Patch stores and import writes are independently accounted for.
    import_rows = imports(stage)
    for row in import_rows:
        pos = int(row["iat_va"], 16) - 0x400000
        assert all(u32(post, pos + i * 4) for i in range(len(row["names"])))
    closures = {
        "stage0": code_closure(exe[0xE6B0:0xEC94], 0x3EE6B0,
                               (0x3EE6B0, 0x3EE6EB, 0x3EE71D, 0x3EE74F)),
        "stage2": code_closure(stage[0x42D:0x67A], 0x3F942D, (), (0x406379,)),
    }
    assert closures["stage0"]["indirect_control_flow"] == []
    assert closures["stage2"]["indirect_control_flow"] == ["call   DWORD PTR [ebx+0x4]", "call   DWORD PTR [ebx]"]
    ranges = [
        ("compact_PE_headers", 0, 0xD4),
        ("joint_range_coded_stream", 0xD4, 0xE6B0),
        ("decoder_helpers", 0xE6B0, 0xE786),
        ("decoder_entry_model_and_transfer", 0xE786, 0xEC94),
        ("decoder_constant_tables", 0xEC94, 0xECEC),
        ("bootstrap_IAT_ILT", 0xECEC, 0xED04),
        ("bootstrap_import_names", 0xED04, 0xED30),
        ("bootstrap_import_descriptor_and_terminator", 0xED30, 0xED58),
        ("remaining_file_alignment", 0xED58, 0xEE00),
    ]
    assert all(a[2] == b[1] for a, b in zip(ranges, ranges[1:]))
    prefix = stage[0x42D:0x9BA]
    metadata = stage[0x9BA:0xA0A]
    overhead = prefix + metadata
    payload = post[0x1000:0x40C5C]
    proxies = {name: compressed(value) for name, value in {
        "stage2_code_tables": stage[0x42D:0x77A],
        "import_size_and_records": stage[0x77A:0x9BA],
        "all_inner_overhead": overhead,
        "postfix_payload_proxy": payload,
        "overhead_then_postfix_payload": overhead + payload,
        "zeroed_overhead_then_postfix_payload": bytes(len(overhead)) + payload,
        "postfix_payload_then_overhead": payload + overhead,
    }.items()}
    margins = {}
    for codec in ("zstd19", "xz9e"):
        margins[codec] = {
            "prepend_minus_payload": proxies["overhead_then_postfix_payload"][codec] - proxies["postfix_payload_proxy"][codec],
            "append_minus_payload": proxies["postfix_payload_then_overhead"][codec] - proxies["postfix_payload_proxy"][codec],
            "prepend_minus_zeroed": proxies["overhead_then_postfix_payload"][codec] - proxies["zeroed_overhead_then_postfix_payload"][codec],
        }
    return {
        "schema": "eidolon-static-packing-v1",
        "scope": "static files and Python data transformations; no target execution",
        "environment": {"python": platform.python_version(), "zstandard_module": zstandard.__version__,
                        "objdump": subprocess.check_output(["objdump", "--version"], text=True).splitlines()[0],
                        "zstd": list(zstandard.ZSTD_VERSION), "resolution_gpu_driver_wine": "not applicable: file-only analysis",
                        "xz": "Python lzma FORMAT_XZ, preset=9|PRESET_EXTREME", "zstd_settings": "level=19,threads=0"},
        "inputs": {"native": {"sha256": digest(exe), "bytes": len(exe), "archive_member": reverse["inputs"]["native"]["archive_member"]},
                   "archive": reverse["inputs"]["archive"], "stage1": saved["stage1"], "postfix": saved["postfix"]},
        "source": {"repository": "https://github.com/farbrausch/fr_public", "commit": REV,
                   "subdirectory": "kkrunchy_k7", "sha256": {name: digest((SOURCE / name).read_bytes()) for name in SOURCE_FILES},
                   "limitation": "corresponding public algorithm/layout; not claimed byte-identical build of original packer"},
        "physical_file_ranges": [{"name": name, "start": hex(lo), "end": hex(hi), "bytes": hi - lo,
                                  "sha256": digest(exe[lo:hi])} for name, lo, hi in ranges],
        "physical_outer_overhead_bytes": 2084,
        "static_code_closure": closures,
        "physical_joint_stream_bytes": 58844,
        "inner_decompressed_ranges": [
            {"name": name, "start_va": hex(lo), "end_va": hex(hi), "bytes": hi - lo,
             "sha256": digest(stage[lo - 0x3F9000:hi - 0x3F9000])}
            for name, lo, hi in (
                ("unfilter_setup", 0x3F942D, 0x3F946D),
                ("patch_and_import_loader", 0x3F946D, 0x3F94A4),
                ("OEP_transfer", 0x3F94A4, 0x3F94A9),
                ("unfilter_body", 0x3F94A9, 0x3F967A),
                ("opcode_tables", 0x3F967A, 0x3F977A),
                ("import_size_and_records", 0x3F977A, 0x3F99BA),
                ("filter_stream_sizes", 0x3F99BA, 0x3F9A0A),
                ("filtered_application_code", 0x3F9A0A, 0x401000))],
        "inner_overhead_uncompressed_bytes": len(overhead),
        "filter_stream_bytes": streams,
        "reconstructed_application_code": {"start_va": "0x401000", "end_va": hex(0x401000 + len(rebuilt)),
                                           "bytes": len(rebuilt), "sha256": digest(rebuilt), "all_20_streams_consumed": True,
                                           "exact_postfix_match": True},
        "application_imports": import_rows,
        "logical_decoder_output_bytes": 0xCD82BDA,
        "logical_decoder_output_end_va": hex(0x3F942D + 0xCD82BDA),
        "decoder_work_base_va": "0xd183dd3",
        "decoder_work_source_layout_bytes": 0xA14390 + 8192 * 33 * 4,
        "decoder_work_source_layout_end_va": hex(0xD183DD3 + 0xA14390 + 8192 * 33 * 4),
        "decoder_work_source_layout_basis": "depacker.asm Work layout: modelMem=0x200118, runTable=0xa0f790, stretch=0xa10390, APM=0xa14390; matching native operands",
        "proxies_not_original_packer_attribution": proxies,
        "non_additive_marginal_proxies": margins,
        "limitations": ["Saved stage1 mapping is partial; original range decoder is not re-executed.",
                        "Compressed stream jointly stores loader, metadata and application; no unique additive inner byte attribution.",
                        "Proxy uses post-fixup memory, not a reconstructed original linker or full precompression image.",
                        "Outer physical overhead plus proxy margins is a scenario estimate, not original measured total overhead.",
                        "No startup time/peak working-set measurement; reserved memory and zero skips are not stored bytes."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("analysis/packing/manifest.json"))
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--acquire", action="store_true")
    args = parser.parse_args()
    if args.acquire:
        SOURCE.mkdir(parents=True, exist_ok=True)
        for name in SOURCE_FILES:
            url = f"https://raw.githubusercontent.com/farbrausch/fr_public/{REV}/kkrunchy_k7/{name}"
            if not (SOURCE / name).exists():
                (SOURCE / name).write_bytes(urllib.request.urlopen(url, timeout=30).read())
    if args.write:
        result = measure()
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(result, indent=2) + "\n")
    else:
        expected = json.loads(args.manifest.read_text())
        for name, sha in expected["source"]["sha256"].items():
            checked(SOURCE / name, sha)
        result = measure()
        assert result == expected, "measurement differs from pinned manifest"
    print(json.dumps({"status": "PASS", "outer_overhead": result["physical_outer_overhead_bytes"],
                      "joint_stream": result["physical_joint_stream_bytes"],
                      "inner_raw_overhead": result["inner_overhead_uncompressed_bytes"],
                      "reconstructed_code": result["reconstructed_application_code"],
                      "marginal_proxies": result["non_additive_marginal_proxies"]}, indent=2))


if __name__ == "__main__":
    main()
