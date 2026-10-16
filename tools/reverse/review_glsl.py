#!/usr/bin/env python3
"""Read-only D7 evidence/source review; never loads GL or executes the target."""
import hashlib
import json
import os
from pathlib import Path
import re
import struct

import zstandard


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked(path, digest):
    data = Path(path).read_bytes()
    assert sha(data) == digest, str(path)
    return data


def one(events, name, **fields):
    matches = [event for event in events if event['event'] == name
               and all(event.get(key) == value for key, value in fields.items())]
    assert len(matches) == 1, (name, fields, len(matches))
    return matches[0]


def main():
    data_root = Path(os.environ['EIDOLON_DATA'])
    review_path = Path('artifacts/reference/proxy-b-gl-diagnosis-review.json')
    review = json.loads(review_path.read_text())
    manifests = {}
    for run, identity in review['runs'].items():
        manifest = json.loads(checked(identity['manifest'], identity['sha256']))
        assert manifest['status'] == 'G1_failed' and not manifest['reference_eligible']
        assert manifest['launcher_exit'] == 125
        for name, digest in manifest['evidence'].items():
            checked(data_root / name, digest)
        manifests[run] = manifest

    # Recheck the actual producer sources, including prior snapshots, without
    # invoking the capture audit (which writes outside Reverse's ownership).
    final_id = 'proxy-b-gl-shader-20261016'
    build = manifests[final_id]['build']
    snapshot = Path(build['build_directory']) / 'source-snapshot'
    for name, digest in dict(build['original_sources'], **build['sources']).items():
        checked(snapshot / name, digest)
        checked(name, digest)

    evidence = {}
    for name, identity in review['compressed_evidence'].items():
        packed = checked(name, identity['sha256'])
        raw = zstandard.ZstdDecompressor().decompress(packed)
        assert len(raw) == identity['source_bytes']
        assert sha(raw) == identity['source_sha256']
        evidence[Path(name).name.removesuffix('.zst')] = raw
    attribution = [json.loads(line) for line in evidence[
        'proxy-b-gl-attribution-20261016-backend.jsonl'].splitlines()]
    final = [json.loads(line) for line in evidence[
        final_id + '-backend.jsonl'].splitlines()]
    for events in (attribution, final):
        sequence = [e['seq'] for e in events if 'seq' in e]
        assert sequence == list(range(1, len(sequence) + 1))
        assert not any(e['event'] == 'pre_present' for e in events)
    precheck = one(attribution, 'gl_check', phase='preexisting')
    assert precheck['enum'] == '0x0502' and precheck['n'] == 0
    assert not any(e.get('phase') == 'original_state_query' for e in attribution)
    context = {}
    for parameter, expected in (('0x821b', 4), ('0x821c', 6),
                                ('0x9126', 2), ('0x821e', 0)):
        event = one(attribution, 'gl_check', parameter=parameter)
        assert event['enum'] == '0x0000' and event['output_value'] == expected
        context[parameter] = expected
    version = one(attribution, 'gl_context_string', parameter='0x1f02')['value']
    assert version == '4.6.0 NVIDIA 610.57.04'

    before = one(final, 'application_glUseProgram_before', call_pc='0x004076a8')
    driver = one(final, 'driver_error')
    after = one(final, 'driver_error_returned')
    exists = one(final, 'program_is_program')
    link = one(final, 'program_query', parameter='0x8b82')
    assert before['program'] == 2 and before['enum'] == '0x0000'
    assert driver['id'] == 1282 and driver['last_lookup_caller'] == before['call_pc']
    assert after['enum'] == '0x0502'
    assert exists['program'] == link['program'] == 2
    assert exists['value'] == 1 and link['value'] == 0
    assert before['seq'] < driver['seq'] < after['seq'] < link['seq']
    assert not any(e['event'] == 'readback_begin' for e in final)

    runner = evidence[final_id + '-runner.log'].decode()
    for text in ('hardware_pc=00406dcc', 'stack=00008b30,00000001,',
                 'shader_source index=0 pointer=00409918 bytes=1310',
                 'DEBUG shader_program=2', 'hardware_pc=004076a8',
                 'hardware_pc=004076aa'):
        assert text in runner, text
    stack_base = int(re.search(r'DEBUG stack_base=([0-9a-f]+)', runner)[1], 16)
    run_data = data_root / 'reference' / final_id
    stack = (run_data / 'debug-stack-0.bin').read_bytes()
    assert struct.unpack_from('<II', stack, 0x22fb0c - stack_base) == (0x4076aa, 2)
    source = checked(run_data / 'program-source-0.glsl', review['shader']['sha256'])
    compiler_log = (run_data / 'program-2-link.log').read_text()
    assert compiler_log == review['shader']['compiler_log']
    assert 'error C7616: global variable gl_FragColor is removed after version 420' in compiler_log
    image = checked(data_root / 'reverse/confirmed-debug/postfix-00400000.bin',
                    review['shader']['unchanged_original_dump_sha256'])
    assert len(source) == 1310 and image[0x9918:0x9918 + 1311] == source + b'\0'

    def at(address, size):
        return image[address - 0x400000:address - 0x400000 + size]

    def words(address, count):
        return struct.unpack('<' + 'I' * count, at(address, 4 * count))

    # Pins for the statically reviewed call/argument/table paths. Inspect with:
    # objdump -D -b binary -m i386 -M intel --adjust-vma=0x400000
    #   --start-address=... --stop-address=... <postfix dump>
    pins = {
        0x405fa9: '8b8ad45843008b82d8584300890e890785c975078b4508891e8907'
                  '8b8adc5843008b0699f7f989068b0799f7f98907',
        0x4063ef: 'ff3528bf170bff155490400050ff3528bf170bff1540904000',
        0x4064e7: 'a1f06143008985f8fbffff',
        0x406dad: '8b46048d8df8fbffff8d048150ff3668308b000068a4f84100ff1550904000ffd0',
        0x40768b: '8b04fdd05943008b048530bf170b50684c6642008945f8ff1550904000ffd0',
        0x4076c3: '6bc61468f4634300ffb0d0584300686c124200ff1550904000ffd0',
        0x407959: '6a016a016aff6affff155c904000',
        0x4079c1: '68f0bf170b680614000068081900005668e10d0000ff1544904000',
        0x407a2b: '68f0bf170b6806140000680819000033c9b88000000051505050681488000051bf6f8000005768c86d4200ffd6ffd0',
    }
    for address, encoded in pins.items():
        expected = bytes.fromhex(encoded)
        assert at(address, len(expected)) == expected, hex(address)
    assert words(0x4361f0, 1) == (0x409918,)  # first source pointer
    assert words(0x4357e0, 2) == (1, 0)       # source count / pointer-array offset
    assert words(0x4359d0, 2) == (0, 1)       # program index / framebuffer index + 1
    assert words(0x435e2c, 2) == (19, 0)      # first initialization pass index
    assert words(0x4358d0, 5) == (1, 16384, 128, 1, 1)
    assert words(0x4363f4, 1) == (0x8ce0,)    # GL_COLOR_ATTACHMENT0

    header, body = source.split(b'\n', 1)
    assert header == b'#version 450' and b'#' not in body
    assert set(re.findall(rb'\bgl_\w+', body)) == {b'gl_FragCoord', b'gl_FragColor'}
    assert body.count(b'gl_FragColor') == 1 and b'gl_FragColor=vec4(' in body
    assert not re.search(rb'\bout\b', body)
    compatibility = b'#version 450 compatibility\n' + body
    declaration = b'layout(location=0) out vec4 eidolon_FragColor;\n'
    explicit_output = header + b'\n' + declaration + body.replace(
        b'gl_FragColor', b'eidolon_FragColor')
    assert compatibility.split(b'\n', 1)[1] == body
    assert explicit_output.split(b'\n', 2)[2].replace(
        b'eidolon_FragColor', b'gl_FragColor') == body
    print(json.dumps({
        'static_review': 'PASS',
        'proof': str(review_path),
        'run_manifest_identities_checked': len(manifests),
        'compressed_evidence_checked': len(evidence),
        'context': {'version': version, 'profile_mask': context['0x9126'],
                    'flags': context['0x821e']},
        'shader_failure': 'C7616; program exists, LINK_STATUS=0; original glUseProgram raises 0x0502',
        'shader_source_matches_dump': True,
        'initial_pass_static': {'draw_buffers': ['GL_COLOR_ATTACHMENT0'],
                                'atlas_dimensions': [16384, 128],
                                'volume_dimensions': [128, 128, 128],
                                'volume_internal_format': 'GL_RGBA32F'},
        'candidate_inputs_only': {
            name: {'bytes_excluding_nul': len(value), 'sha256': sha(value)}
            for name, value in (('450-compatibility', compatibility),
                                ('450-explicit-output-0', explicit_output))},
        'coverage': 'Saved evidence and static bytes only; candidate compilation, draw routing and pixel equivalence untested',
        'reference_eligible': False,
    }, indent=2))


if __name__ == '__main__':
    main()
