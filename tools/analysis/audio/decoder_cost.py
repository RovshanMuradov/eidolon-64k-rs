#!/usr/bin/env python3
"""Build an unexecuted PE32 LZMA decoder scaffold; validate same source on Linux."""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import struct
import subprocess
import urllib.request

PIN = '5e96a8279489832924056b1fa82f29d5837c9469'
FILES = ('LzmaDec.c', 'LzmaDec.h', '7zTypes.h', 'Precomp.h', 'Compiler.h', '7zWindows.h')


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--acquire', action='store_true')
    ap.add_argument('--manifest', type=Path)
    args = ap.parse_args()
    root, data = Path(os.environ['EIDOLON_ROOT']), Path(os.environ['EIDOLON_DATA'])
    source = root / '.tools/analysis/audio/lzma-25.01'
    source.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        path = source / name
        if args.acquire and not path.exists():
            path.write_bytes(urllib.request.urlopen(
                f'https://raw.githubusercontent.com/ip7z/7zip/{PIN}/C/{name}', timeout=30).read())
        assert path.exists(), f'run with --acquire: {name}'
    source_hashes = {name: sha((source / name).read_bytes()) for name in FILES}
    known = Path('analysis/audio/decoder-cost.json')
    if known.exists():
        assert json.loads(known.read_text())['source']['files'] == source_hashes
    recovery = json.loads(Path('analysis/audio/manifest.json').read_text())
    native = (data / recovery['inputs']['postfix']['path']).read_bytes()
    assert sha(native) == recovery['inputs']['postfix']['sha256']
    lo = int(recovery['measurement_domain']['start'], 16) - 0x400000
    hi = int(recovery['measurement_domain']['end_exclusive'], 16) - 0x400000
    native = native[lo:hi]
    base = data / 'analysis/audio/T19'
    pcm = (base / 'gmdls-referenced-pcm16.bin').read_bytes()
    assert sha(pcm) == recovery['sizes']['referenced_dls_pcm']['sha256']
    delta, pos, wave_data, wave_delta = bytearray(), 0, {}, {}
    for sample in recovery['patch']['gmdls_samples']:
        wave = pcm[pos:pos + sample['bytes']]
        pos += len(wave)
        values = struct.unpack('<' + 'H' * (len(wave) // 2), wave)
        diff = [(v - (values[i - 1] if i else 0)) & 65535 for i, v in enumerate(values)]
        transformed = bytes(v & 255 for v in diff) + bytes(v >> 8 for v in diff)
        wave_data[sample['index']], wave_delta[sample['index']] = wave, transformed
        delta.extend(transformed)
    assert sha(delta) == recovery['sizes']['referenced_dls_delta16_planar']['sha256']
    audit_path = Path('analysis/audio/audit.json')
    audit = json.loads(audit_path.read_text())
    retained = audit['event_closure']['event_reachable_samples']
    pruned_samples = [s for s in recovery['patch']['gmdls_samples'] if s['index'] in retained]
    pruned_delta = b''.join(wave_delta[s['index']] for s in pruned_samples)
    flags = ['-Os', '-DZ7_LZMA_SIZE_OPT', '-ffunction-sections',
             '-fno-builtin', '-fno-stack-protector', '-fno-asynchronous-unwind-tables']
    results = {}
    for name, raw, samples in [('system_bank_payload', native, []),
                              ('bundled_sample_payload', native + delta, recovery['patch']['gmdls_samples']),
                              ('bundled_event_closed_payload', native + pruned_delta, pruned_samples)]:
        build = base / 'decoder' / name
        build.mkdir(parents=True, exist_ok=True)
        compressed = lzma.compress(raw, format=lzma.FORMAT_ALONE, preset=9 | lzma.PRESET_EXTREME)
        assert lzma.decompress(compressed, format=lzma.FORMAT_ALONE) == raw
        (build / 'payload.lzma').write_bytes(compressed)
        sample_bytes = sum(s['bytes'] for s in samples)
        table = ','.join('{' + str(s['index']) + ',' + str(s['bytes']) + '}' for s in samples) or '{0,0}'
        (build / 'payload.h').write_text(
            f'#define OUTPUT_BYTES {len(raw)}\n#define SAMPLE_COUNT {len(samples)}\n'
            f'#define SAMPLE_BYTES {sample_bytes}\n#define SAMPLE_OFFSET {len(native)}\n'
            'static const unsigned sample_table[][2]={' + table + '};\n'
            'static const unsigned char payload[]={' + ','.join(str(b) for b in compressed) + '};\n')
        common = flags + ['-I', str(source), '-I', str(build),
                           'tools/analysis/audio/decoder_probe.c', str(source / 'LzmaDec.c')]
        host = build / 'decode-host'
        pe = build / 'decode-only.exe'
        host_cmd = ['gcc'] + common + ['-Wl,--gc-sections', '-o', str(host)]
        pe_cmd = ['i686-w64-mingw32-gcc'] + common + ['-nostdlib',
                    '-Wl,--entry,_entry,--gc-sections,--no-insert-timestamp,-s', '-lkernel32', '-o', str(pe)]
        subprocess.run(host_cmd, check=True)
        subprocess.run(pe_cmd, check=True)
        output = build / 'decoded.bin'
        subprocess.run([str(host), str(output)], check=True, timeout=30)
        expected = native + b''.join(wave_data[s['index']] for s in samples)
        assert output.read_bytes() == expected
        blob = pe.read_bytes()
        nt, = struct.unpack_from('<I', blob, 0x3c)
        count, = struct.unpack_from('<H', blob, nt + 6)
        optional_bytes, = struct.unpack_from('<H', blob, nt + 20)
        sections = []
        for i in range(count):
            p = nt + 24 + optional_bytes + i * 40
            vs, va, rs, off = struct.unpack_from('<4I', blob, p + 8)
            sections.append({'name': blob[p:p+8].rstrip(b'\0').decode(), 'virtual_bytes': vs,
                             'rva': hex(va), 'raw_bytes': rs, 'file_offset': off})
        def file_offset(rva):
            for s in sections:
                start = int(s['rva'], 16)
                if start <= rva < start + s['raw_bytes']:
                    return s['file_offset'] + rva - start
            raise ValueError(hex(rva))
        def string(rva):
            p = file_offset(rva)
            return blob[p:blob.index(0, p)].decode()
        import_rva, = struct.unpack_from('<I', blob, nt + 24 + 96 + 8)
        descriptor, imports = file_offset(import_rva), {}
        while any(blob[descriptor:descriptor + 20]):
            original, _, _, dll, first = struct.unpack_from('<5I', blob, descriptor)
            thunk, names = file_offset(original or first), []
            while (name_rva := struct.unpack_from('<I', blob, thunk)[0]):
                assert not name_rva & 0x80000000
                names.append(string(name_rva + 2))
                thunk += 4
            imports[string(dll)] = names
            descriptor += 20
        assert imports == {'KERNEL32.dll': ['ExitProcess']}
        results[name] = {'input_bytes': len(raw), 'input_sha256': sha(raw),
                         'lzma_alone_bytes': len(compressed), 'pe_bytes': len(blob),
                         'pe_sha256': sha(blob), 'measured_scaffold_overhead': len(blob)-len(compressed),
                         'sample_indices': [s['index'] for s in samples], 'sample_pcm_bytes': sample_bytes,
                         'imports': imports,
                         'sections': sections, 'host_command': host_cmd, 'pe_command': pe_cmd,
                         'host_decode_byte_equality': True, 'pe_executed': False}
    result = {'source': {'repository': 'https://github.com/ip7z/7zip', 'tag': '25.01',
                          'commit': PIN, 'files': source_hashes},
              'closure_manifest_sha256': sha(audit_path.read_bytes()),
              'tools': {c: subprocess.check_output([c, '--version'], text=True).splitlines()[0]
                        for c in ('gcc', 'i686-w64-mingw32-gcc')},
              'results': results,
              'limitations': ['PE is an unexecuted decoder-only scaffold, not the demo.',
                              'No native payload execution, import reconstruction, fixups or Rust startup.',
                              'Bundled scaffold includes delta16 inverse and index/length table, not synth integration.',
                              'System-bank variant preserves an external OS bank dependency; bundled variant carries sample bytes.']}
    (base / 'decoder/summary.json').write_text(json.dumps(result, indent=2) + '\n')
    if args.manifest:
        args.manifest.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: {f: v[f] for f in ('lzma_alone_bytes', 'pe_bytes', 'measured_scaffold_overhead')}
                      for k, v in results.items()}, indent=2))


if __name__ == '__main__':
    main()
