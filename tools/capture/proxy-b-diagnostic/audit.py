#!/usr/bin/env python3
"""Verify D7 call attribution, immutable failures and resource release; no G1 PASS."""
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

import zstandard

sys.dont_write_bytecode = True


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    root = Path(os.environ['EIDOLON_ROOT'])
    data = Path(os.environ['EIDOLON_DATA'])
    artifacts = Path('artifacts/reference')
    originals = ['proxy-b-g1-20261016', 'frida-a-g1-20261016',
                 'frida-a-g1-ancestor-20261016', 'frida-a-g1-runnable-20261016']
    preserved = {}
    for run in originals:
        path = artifacts / (run + '.json')
        manifest = json.loads(path.read_text())
        assert manifest['status'] == 'G1_failed' and manifest['launcher_exit'] == 125
        for name, digest in manifest['evidence'].items():
            assert sha(data / name) == digest, name
        build = Path(manifest['build'].get('build_directory', root / '.tools/capture/A' / manifest['build']['build_id']))
        for name, digest in manifest['build']['outputs'].items():
            assert sha(build / name) == digest, name
        original = manifest['input']
        assert sha(original['archive']) == original['archive_sha256']
        assert sha(original['executed_copy']) == original['exe_sha256']
        if run in (originals[0], originals[-1]):
            for name, digest in manifest['build']['sources'].items():
                assert sha(name) == digest, name
        preserved[str(path)] = dict(sha256=sha(path), build_id=manifest['build']['build_id'],
                                    evidence_files=len(manifest['evidence']), outputs=len(manifest['build']['outputs']))
    for name in ('proxy-b-g1-failure-review', 'frida-a-failure-review'):
        path = artifacts / (name + '.json')
        review = json.loads(path.read_text())
        for filename, identity in review['compressed_evidence'].items():
            assert sha(filename) == identity['sha256'], filename
        preserved[str(path)] = dict(sha256=sha(path), compressed_evidence='unchanged')

    runs = ['proxy-b-gl-attribution-20261016', 'proxy-b-gl-debugger-20261016',
            'proxy-b-gl-callsite-20261016', 'proxy-b-gl-shader-20261016']
    manifests, all_events = {}, {}
    spec = importlib.util.spec_from_file_location('exports', 'tools/capture/proxy-b/build.py')
    exports = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exports)
    for run in runs:
        path = artifacts / (run + '.json')
        manifest = json.loads(path.read_text())
        assert manifest['status'] == 'G1_failed' and not manifest['reference_eligible']
        assert manifest['launcher_exit'] == 125 and len(manifest['runner_terminal']) == 1
        assert manifest['runner_terminal'][0].startswith('WINE_EXIT=125 GAMESCOPE_EXIT=139 ')
        for name, digest in manifest['evidence'].items():
            assert sha(data / name) == digest, name
        build = Path(manifest['build']['build_directory'])
        for name, digest in manifest['build']['outputs'].items():
            assert sha(build / name) == digest, name
        for name, digest in dict(manifest['build']['original_sources'], **manifest['build']['sources']).items():
            assert sha(build / 'source-snapshot' / name) == digest, name
        for dll, backend in manifest['build']['backends'].items():
            assert sha(backend['path']) == backend['sha256']
            actual = exports.exports(build / (dll + '.dll'))
            expected = exports.exports(backend['path'])
            assert all(actual[key] == value for key, value in expected.items())
        events = [json.loads(line) for line in (data / 'reference' / run / 'backend.jsonl').read_text().splitlines()]
        ordered = [e['seq'] for e in events if 'seq' in e]
        assert ordered == list(range(1, len(ordered) + 1))
        assert not any(e['event'] in ('pre_present', 'post_present', 'planned_partial_stop') for e in events)
        assert not list((data / 'reference' / run).glob('frame-*'))
        all_events[run] = events
        manifests[run] = manifest

    first = all_events[runs[0]]
    prior = next(e for e in first if e['event'] == 'gl_check')
    assert prior['phase'] == 'preexisting' and prior['enum'] == '0x0502' and prior['n'] == 0
    assert not any(e.get('phase') == 'original_state_query' for e in first)
    profile = next(e for e in first if e.get('parameter') == '0x9126')
    assert profile['output_value'] == 2 and profile['enum'] == '0x0000'
    final = all_events[runs[-1]]
    by_event = lambda name: [e for e in final if e['event'] == name]
    before = by_event('application_glUseProgram_before')[-1]
    assert before['call_pc'] == '0x004076a8' and before['program'] == 2 and before['enum'] == '0x0000'
    driver = by_event('driver_error')[0]
    assert len(by_event('driver_error')) == 1 and driver['id'] == 1282
    assert driver['last_lookup_caller'] == '0x004076a8'
    assert by_event('driver_error_returned')[0]['enum'] == '0x0502'
    assert by_event('program_is_program')[0]['value'] == 1
    assert by_event('program_query')[0]['parameter'] == '0x8b82' and by_event('program_query')[0]['value'] == 0
    assert all(e['enum'] == '0x0000' for e in by_event('program_query'))
    final_data = data / 'reference' / runs[-1]
    log = (final_data / 'runner.log').read_text(errors='replace')
    assert 'hardware_pc=00406dcc' in log and 'stack=00008b30,00000001,' in log
    assert 'shader_source index=0 pointer=00409918 bytes=1310' in log
    assert 'DEBUG shader_program=2' in log
    assert 'hardware_pc=004076a8' in log and 'eax=795d9cb0 stack=00000002,' in log
    assert 'hardware_pc=004076aa' in log and 'DEBUG child_exit=125 error_breakpoints=1' in log
    stack_base = int(re.search(r'DEBUG stack_base=([0-9a-f]+)', log)[1], 16)
    stack = (final_data / 'debug-stack-0.bin').read_bytes()
    assert struct.unpack_from('<II', stack, 0x22fb0c - stack_base) == (0x4076aa, 2)
    shader = (final_data / 'program-source-0.glsl').read_bytes()
    dump_path = data / 'reverse/confirmed-debug/postfix-00400000.bin'
    original = dump_path.read_bytes()
    assert len(shader) == 1310 and original[0x9918:0x9918 + len(shader)] == shader
    assert original[0x76a8:0x76aa] == b'\xff\xd0'
    assert shader.startswith(b'#version 450\n') and b'gl_FragColor=' in shader
    compiler_log = (final_data / 'program-2-link.log').read_text()
    assert 'error C7616: global variable gl_FragColor is removed after version 420' in compiler_log
    assert not by_event('readback_begin') and not by_event('synth_complete')

    compressed = {}
    for run in (runs[0], runs[-1]):
        for filename in ('backend.jsonl', 'runner.log'):
            source = data / 'reference' / run / filename
            target = Path('reports/evidence/capture') / f'{run}-{filename}.zst'
            encoded = zstandard.ZstdCompressor(level=19).compress(source.read_bytes())
            if target.exists():
                assert target.read_bytes() == encoded
            else:
                target.write_bytes(encoded)
            assert zstandard.ZstdDecompressor().decompress(encoded) == source.read_bytes()
            compressed[str(target)] = dict(sha256=sha(target), source_sha256=sha(source), source_bytes=source.stat().st_size)
    runtime = []
    for process in Path('/proc').glob('[0-9]*'):
        try:
            env = (process / 'environ').read_bytes().split(b'\0')
            comm = (process / 'comm').read_text().strip()
            command = (process / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
            if b'WINEPREFIX=/tmp/opencode/eidolon/T2/prefix' in env or comm in ('gamescope', 'gamescopereaper') or (comm == 'Xwayland' and ' :0 ' not in command):
                runtime.append(dict(pid=int(process.name), comm=comm))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    sinks = json.loads(subprocess.check_output(['pactl', '--format=json', 'list', 'sinks', 'short'], text=True))
    assert not runtime and not any(s['name'].startswith('eidolon_T2') for s in sinks)
    for path in Path('tools/capture/proxy-b-diagnostic').glob('*.py'):
        ast.parse(path.read_text(), filename=str(path))
    result = dict(kind='D7-exact-GL-callsite-diagnosis', reference_eligible=False, diagnosis='verified',
                  first_gl_error='GL_INVALID_OPERATION (0x0502), preexisting at acquisition entry',
                  producing_call=dict(api='glUseProgram', arguments={'program': 2}, app_call='0x004076a8', app_return='0x004076aa',
                                      target='0x795d9cb0', pid=driver['pid'], tid=driver['tid'], hdc=driver['hdc'], hglrc=driver['hglrc'],
                                      before_error=before['enum'], after_error='0x0502', stage='initialization/pre-render before PCM acquisition'),
                  driver_message=bytes.fromhex(driver['message_hex']).decode(), program_is_program=True, program_link_status=False,
                  shader=dict(creation_call='0x00406dcc', creation_return='0x00406dce', type='GL_FRAGMENT_SHADER (0x8b30)', count=1,
                              source_pointer='0x00409918', bytes=len(shader), sha256=sha(final_data / 'program-source-0.glsl'),
                              unchanged_original_dump_sha256=sha(dump_path), source_matches_original_dump=True, version='#version 450',
                              incompatible_symbol='gl_FragColor', compiler_log=compiler_log),
                  attribution='Original application shader fails compilation/link; application glUseProgram(2) raises the sticky error. No acquisition query/readback produced this first error.',
                  context=manifests[runs[0]]['environment'], original_failures_preserved=preserved,
                  runs={run: dict(manifest=str(artifacts / (run + '.json')), sha256=sha(artifacts / (run + '.json'))) for run in runs},
                  compressed_evidence=compressed,
                  limitations=['First attributed reproduction consumed the pending error only to fail; no state query/readback or reference continuation followed.',
                               'Native fallback enabled synchronous driver debug output; that state change and native breakpoints are diagnosis-only, not G1 state-fidelity proof.',
                               'Historical driver behavior and any proposed GLSL-profile remediation remain untested; G1 and later reference gates remain unpassed.'],
                  recommendation='Keep capture blocked. Seek explicit authorization for an isolated proxy-only GLSL compatibility-profile experiment; preserve and label changed shader inputs. Do not clear errors to pass G1 or accept changed inputs as the original reference.',
                  runtime_release=dict(checked_utc=datetime.now(timezone.utc).isoformat(), processes=runtime, private_audio_sink_present=False))
    output = artifacts / 'proxy-b-gl-diagnosis-review.json'
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(diagnosis='PASS', gl_error='0x0502', producer='0x4076a8 glUseProgram(2)',
                         shader='original #version 450 + gl_FragColor', reference_eligible=False, runtime_processes=0, review=str(output))))


if __name__ == '__main__':
    main()
