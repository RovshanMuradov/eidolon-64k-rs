#!/usr/bin/env python3
"""File-only recheck of bounded live failure evidence; no gate acceptance."""
import argparse
import hashlib
import json
import os
from pathlib import Path


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    args = parser.parse_args()
    summary = json.loads(args.manifest.read_text())
    assert not summary['reference_eligible'] and summary['resources_released']
    assert sha(summary['host_tool']['path']) == summary['host_tool']['sha256']
    root = Path(os.environ['EIDOLON_DATA'])
    expected = {'fingerprint':'completion_fingerprint_rejected_before_patch',
                'wrong-thread':'wrong_hook_thread','unknown-route':'unknown_hook_route',
                'shader-count':'shader_source_array_extent','wrong-hdc':'GL_owning_context',
                'wrong-hglrc':'GL_owning_context','preexisting-error':'GL_initial_error',
                'readback-error':'GL_readback_state_or_error','restore-error':'GL_readback_state_or_error',
                'backend-missing':'backend_load_failed','backend-wrong':'backend_symbol_missing_or_self',
                'backend-self':'backend_is_proxy'}
    assert len(summary['results']) == 12
    assert {r['fault'] for r in summary['results']} == set(expected)
    for case in summary['results']:
        fault = case['fault']
        if 'manifest' in case:
            assert sha(case['manifest']) == case['sha256']
            m = json.loads(Path(case['manifest']).read_text())
            assert m['status'] == 'failed' and m['launcher_exit'] == 125 and not m['reference_eligible']
            assert not m['supervisor_timeout']
            assert m['first_failed_check']['reason'] == expected[fault] == case['observed']
            assert m['resources']['prefix_processes_released'] and m['resources']['private_sink_unloaded']
            assert not m['resources']['errors']
            assert any('WINE_EXIT=125 ' in x for x in m['runner_terminal'])
            assert sha(m['host_runner']['path']) == m['host_runner']['sha256']
            assert m['build'] == summary['build']
            evidence = m['evidence']
        else:
            assert case['launcher_exit'] == 125
            assert case['observations'][0]['result'] == expected[fault]
            evidence = case['evidence']
        for name,digest in evidence.items():
            assert sha(root/name) == digest, name
        log, = [root/name for name in evidence if name.endswith('backend.jsonl')]
        events = [json.loads(line) for line in log.read_text().splitlines()]
        assert not any(e['event']=='pre_present' for e in events)
        if fault == 'wrong-thread':
            install, = [e for e in events if e['event']=='hooks_installed']
            failure, = [e for e in events if e['event']=='failure']
            assert install['main_tid'] != failure['tid']
        if fault == 'restore-error':
            state, = [e for e in events if e['event']=='frame_state']
            assert state['before'] != state['after']
        if fault == 'readback-error':
            state, = [e for e in events if e['event']=='frame_state']
            assert state['before'] == state['after']
    for name,digest in summary['build']['outputs'].items():
        assert sha(Path(summary['build']['build_directory'])/name) == digest
    print(json.dumps(dict(status='DIAGNOSTIC_ONLY',bounded_rejections=12,reference_accepted=False,
                          limitation='Controls cover the recorded routes and injected faults; independent G1 review remains required.')))


if __name__ == '__main__':
    main()
