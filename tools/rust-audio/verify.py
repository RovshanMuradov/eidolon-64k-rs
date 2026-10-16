#!/usr/bin/env python3
"""CPU-only slice substitution in independently PCM-validated pinned source player.

This is deliberately a hybrid diagnostic, never a standalone Rust synth candidate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

def sha(b):
    return hashlib.sha256(b).hexdigest()

def replace_body(text, marker, body):
    start = text.index('{', text.index(marker))
    level, end = 1, start + 1
    while level:
        level += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[:start] + '{\n' + body + '\n}' + text[end:]

def run(command, **kwargs):
    subprocess.run([str(x) for x in command], check=True, **kwargs)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frames', type=int, default=19964544)
    args = p.parse_args()
    assert 0 < args.frames <= 19964544 and args.frames % 64 == 0
    root, data = Path(os.environ['EIDOLON_ROOT']), Path(os.environ['EIDOLON_DATA'])
    build = data / 'builds/T23'
    build.mkdir(parents=True, exist_ok=True)
    pin = json.loads(Path('analysis/audio/source-check.json').read_text())
    adapted = data / 'analysis/audio/T19/source-player'
    files = {}
    for name, digest in pin['build_files'].items():
        raw = (adapted / name).read_bytes()
        assert sha(raw) == digest, name
        files[name] = raw.decode().replace('\r\n', '\n')
    functions = {'s_exp2': 'eidolon_exp2', 's_log2': 'eidolon_log2', 's_sin': 'eidolon_sin'}
    text = files['sample_t.cpp']
    declarations = ''
    for old, new in functions.items():
        declarations += f'extern "C" void {new}(const double*, double*);\n'
        text = replace_body(text, f'sample_t __fastcall {old}(', f'    sample_t out; {new}(x.d, out.d); return out;')
    declarations += 'extern "C" void eidolon_rand(void*, double*);\n'
    text = replace_body(text, 'sample_t __fastcall s_rand(',
                        '    sample_t out; eidolon_rand(SC[S_RAND_SEED].l, out.d); return out;')
    files['sample_t.cpp'] = declarations + text
    text = files['SynthNode.cpp']
    text = text.replace('#include "SynthAllocator.h"', '#include "SynthAllocator.h"\n#include "graph_bridge.h"')
    text = replace_body(text, 'SynthNode* CreateNode(',
                        '    rust_check_layout(); return eidolon_create_node(&rust_graph,id,refnodes,offset,isGlobal);')
    text = replace_body(text, 'SynthNode* CreateNodes(',
                        '    return eidolon_create_nodes(&rust_graph,offset,global);')
    text = replace_body(text, 'void DestroyVoiceNodes(',
                        '    eidolon_destroy_voice(&rust_graph,node);')
    node_ports = {'CHANNELROOT':1, 'NOTECONTROLLER':2, 'VOICEROOT':4, 'ADSR':5,
                  'ONEPOLEFILTER':10, 'ONEZEROFILTER':11, 'PANNING':13, 'MUL':15, 'DIV':16,
                  'ADD':17, 'SUB':18, 'CLIP':19, 'MIX':20, 'MONO':22, 'ENVFOLLOWER':23,
                  'DCFILTER':34, 'NEG':45, 'MIN':47, 'MAX':48, 'CONSTANT':64, 'VOICEPARAM':65}
    for name, opcode in node_ports.items():
        text = replace_body(text, f'void SYNTHCALL {name}_tick(',
                            f'    source_seen[n->valueOffset] = 1; eidolon_node_tick(n,&SynthGlobalState,{opcode});')
    text = replace_body(text, 'void SYNTHCALL VOICEMANAGER_tick(',
                        '    source_seen[n->valueOffset] = 1; eidolon_voice_tick(n,&rust_graph);')
    text = replace_body(text, 'inline sample_t GetDelayTimeFraction(',
                        '    sample_t out; eidolon_fraction(&SynthGlobalState,&value,&out); return out;')
    text = replace_body(text, 'void ArpeggiatorStep(',
                        '    eidolon_arp_step(n,&SynthGlobalState,mode);')
    text = replace_body(text, 'inline sample_t Sampler_Sample(',
                        '    sample_t out; eidolon_sample((void*)n->v[11].l[0], n->v[10].d, index.d, out.d); return out;')
    files['SynthNode.cpp'] = 'extern "C" void eidolon_sample(const void*, const double*, const double*, double*);\n' + text
    files['graph_bridge.h'] = Path('tools/rust-audio/graph_bridge.h').read_text()
    text = files['Synth.cpp']
    text = replace_body(text, 'void AddToNoteController(', '    rust_note_event(channel,note,velocity,on);')
    start = text.index('\tchar lpGMDLSName[1024];')
    end = text.index('\t// write out gmdls wave names', start)
    text = text[:start] + '''    for (unsigned index = 0; index < 512; ++index) {
        size_t count = eidolon_wave(index, nullptr, 0);
        GMDLS_NumSamples[index] = count;
        if (!count) continue;
        sample_t* buffer = (sample_t*)SynthMalloc(count * sizeof(sample_t));
        GMDLS_SampleBuffer[index] = buffer;
        if (eidolon_wave(index, buffer->d, count) != count) __builtin_trap();
    }
''' + text[end:]
    marker = '// process song streams\n'
    assert text.count(marker) == 1
    text = text.replace(marker, marker + '    void* rust_score = eidolon_score_new();\n    if (!rust_score) __builtin_trap();\n')
    start = text.index('\t\tDeltaStream = SynthGlobalState.SongStream+16;', text.index('void _64klang_Render(float*'))
    end = text.index('\t\t// tick samples until next frame', start)
    text = text[:start] + '        eidolon_score_dispatch(rust_score, currentTimeStamp, eidolon_emit_event);\n' + text[end:]
    text = text.replace('\trenderDone = true;', '\teidolon_score_free(rust_score);\n\teidolon_graph_report();\n\trenderDone = true;')
    text = text.replace('void _64klang_Render(float* dstbuffer)', '''static void eidolon_emit_event(unsigned channel, unsigned kind, unsigned special, unsigned value, unsigned velocity) {
    if (kind == 3) _64klang_MidiSignal(channel, value, special);
    else AddToNoteController(channel, value, velocity, kind == 1);
}
void _64klang_Render(float* dstbuffer)''')
    files['Synth.cpp'] = '''#include <cstddef>
extern void eidolon_graph_report();
extern void rust_note_event(unsigned, unsigned, unsigned, bool);
extern "C" size_t eidolon_wave(unsigned, double*, size_t);
extern "C" void* eidolon_score_new();
extern "C" void eidolon_score_dispatch(void*, unsigned, void(*)(unsigned,unsigned,unsigned,unsigned,unsigned));
extern "C" void eidolon_score_free(void*);
''' + text
    for name, text in files.items():
        (build / name).write_text(text)
    harness = Path('tools/analysis/audio/source_player.cpp')
    assert sha(harness.read_bytes()) == pin['harness_sha256']
    rust_command = ['rustc', '--edition=2021', '--crate-type=staticlib', '--crate-name=eidolon_audio',
                    '-C', 'opt-level=2', '-C', 'target-feature=+sse4.1', 'src/audio/mod.rs', '-o', build / 'libeidolon_audio.a']
    rust_files = {str(p): sha(p.read_bytes()) for p in Path('src/audio').glob('*.rs')}
    run(rust_command)
    command = ['g++', '-O2', '-msse4.1', '-D_M_X64', '-ffp-contract=off', '-fno-fast-math',
               '-frounding-math', '-Wno-unknown-pragmas', '-include', build / '64k2Patch.h', '-I', build,
               harness, *[build / n for n in ('Synth.cpp', 'SynthNode.cpp', 'sample_t.cpp')],
               build / 'libeidolon_audio.a', '-ldl', '-lpthread', '-lm', '-o', build / 'slice-player']
    run(command)
    base = data / 'analysis/audio/T19'
    assets = json.loads(Path('artifacts/rust/audio/assets.json').read_text())
    assert sha((base/'score-encoded.bin').read_bytes()) == assets['assets']['SCORE']['sha256']
    assert sha((base/'patch-and-trailer.bin').read_bytes()) == assets['assets']['PATCH']['sha256']
    output = build / f'hybrid-{args.frames}.f32le'
    started = time.monotonic()
    run_command = [build / 'slice-player', base / 'score-encoded.bin', base / 'patch-and-trailer.bin',
                   '/unused-embedded-bank', output, str(args.frames), build / 'coverage.bin']
    completed = subprocess.run(list(map(str,run_command)), check=True, timeout=360, capture_output=True, text=True)
    print(completed.stdout, end='')
    elapsed = time.monotonic() - started
    reference_manifest = root / '.worktrees/T16/artifacts/reference/proxy-b-d13-detached-20261016-1-reference.json'
    refpin = json.loads(reference_manifest.read_text())
    reference_path = data / 'reference/proxy-b-d13-detached-20261016-1/pcm.f32le'
    reference = reference_path.read_bytes()
    assert sha(reference) == refpin['audio']['sha256']
    actual = output.read_bytes()
    expected = reference[:args.frames * 8]
    assert len(actual) == len(expected)
    first = next((i for i, (a,b) in enumerate(zip(actual, expected)) if a != b), None)
    result = {'schema': 'eidolon-rust-audio-slices-v1', 'kind': 'hybrid-source-oracle-diagnostic',
              'standalone_rust_synth': False, 'source_commit': pin['source_commit'],
              'source_manifest_sha256': sha(Path('analysis/audio/source-check.json').read_bytes()),
              'assets_manifest_sha256': sha(Path('artifacts/rust/audio/assets.json').read_bytes()),
              'rust_slices': ['exp2', 'log2', 'sin', 'signed-two-lane-rng', 'sampler-interpolation', 'embedded-15-wave-bank-initialization', 'fixed-score-decoder-and-event-scheduler'],
              'rust_graph': ['creation', 'global-cache', 'creation-tick-cycle-cache', 'recursive-voice-destruction'],
              'rust_node_ticks': node_ports,
              'diagnostic_stdout': completed.stdout,
              'rust_voice': ['note-routing', 'key-rescan', 'polyphony-slot-selection', 'stealing', 'glide', 'voice-create-render-destroy', 'arpeggiator', 'bpm-delay-fraction'],
              'remaining_source': 'unlisted node/effect tick/init functions; allocator callbacks',
              'rustc': subprocess.check_output(['rustc', '--version'], text=True).strip(),
              'compiler': subprocess.check_output(['g++', '--version'], text=True).splitlines()[0],
              'rust_command': list(map(str, rust_command)), 'compile_command': list(map(str, command)),
              'run_command': list(map(str, run_command)), 'frames': args.frames, 'elapsed_seconds': elapsed,
              'mxcsr': '0xffc0', 'environment': {'resolution': None, 'gpu': None, 'driver': None, 'wine': None},
              'reference_manifest': str(reference_manifest), 'reference_manifest_sha256': sha(reference_manifest.read_bytes()),
              'reference_pcm_sha256': sha(reference), 'output': str(output), 'output_sha256': sha(actual),
              'equal': first is None, 'first_mismatch_byte': first,
              'adapted_files': {name: sha((build/name).read_bytes()) for name in files},
              'rust_files': rust_files,
              'binary_sha256': sha((build/'slice-player').read_bytes())}
    Path('artifacts/rust/audio/slices.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['frames', 'elapsed_seconds', 'equal', 'first_mismatch_byte', 'output_sha256']}))
    if first is not None:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
