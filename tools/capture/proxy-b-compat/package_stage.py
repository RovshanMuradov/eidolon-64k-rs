#!/usr/bin/env python3
"""Version-2 staged envelope; retain the hash-bound original package.py unchanged."""
import importlib.util
import json
import os
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('legacy_package', Path(__file__).with_name('package.py'))
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
original_write = package.write


def write(path, value):
    if value.get('schema') == 'eidolon-d9-eligibility-1':
        m = json.loads(Path(sys.argv[1]).read_text())
        if 'host_runner' in m:
            runner = Path(m['host_runner']['path'])
            assert package.sha(runner) == m['host_runner']['sha256']
            value['build']['inputs']['executing-host-runner'] = dict(root='shared',
                path=str(runner.relative_to(Path(os.environ['EIDOLON_ROOT']))),sha256=package.sha(runner))
    if value.get('schema') == 'eidolon-small-real-capture-diagnostic-1':
        m = json.loads(Path(sys.argv[1]).read_text())
        assert any(e['event'] == 'stage_runtime' for e in m['observations'])
        root = Path(os.environ['EIDOLON_ROOT'])
        tool_source = Path(__file__)
        tool = root / '.tools/capture/package-tools' / package.sha(tool_source) / tool_source.name
        tool.parent.mkdir(parents=True,exist_ok=True)
        for source in (tool_source,tool_source.with_name('package.py')):
            saved = tool.parent / source.name
            if saved.exists():
                assert saved.read_bytes() == source.read_bytes()
            else:
                saved.write_bytes(source.read_bytes())
        backend = Path(os.environ['EIDOLON_DATA']) / 'reference' / m['run_id'] / 'backend.jsonl'
        value.update(schema='eidolon-small-real-capture-diagnostic-2',status=m['status'],
                     state_observations=dict(root='data',path=str(backend.relative_to(Path(os.environ['EIDOLON_DATA']))),
                                             sha256=package.sha(backend)),
                     pack_state_query_order=['draw_fbo','read_fbo','read_buffer','pack_alignment','pack_row_length',
                     'pack_skip_rows','pack_skip_pixels','pack_swap_bytes','pack_lsb_first','pack_image_height',
                     'pack_skip_images','pixel_pack_buffer','red_bits','green_bits','blue_bits','alpha_bits','samples','framebuffer_srgb'],
                     publication=dict(payloads_closed=True,index_closed=True),
                     raw_local_interpretation={'seconds_f32_bits':'[EBP-0x34], original sample-to-seconds float path',
                         'scene_local_beat_f32_bits':'[EBP-0x14], original scene-local beat',
                         'scene_token':'[EBP-0x18], original selected scene token',
                         'delta_f32_bits':'Legacy field name: raw [EBP-0x2c] is the LAST PASS TOKEN at pre-present, overwritten at 0x4082c6; NOT frame delta'},
                     scene_boundaries_observed=False,
                     package_tool=dict(root='shared',path=str(tool.relative_to(root)),sha256=package.sha(tool)),
                     original_package_tool=dict(root='shared',path=str(tool.with_name('package.py').relative_to(root)),
                                                sha256=package.sha(tool.with_name('package.py'))))
        value['completion'].update(dropped_frames=0,dropped_audio_sample_frames=0,errors=[])
        value['limits']=['Staged diagnostic; T13 review and Reverse reconciliation required before full capture.',
                        'Live scene locals are observations, not an independently established scene boundary.',
                        'Exception-context comparison does not independently execute the resumed synthesis epilogue.',
                        'Historical compiler/bank/scene fidelity remains unknown.']
    original_write(path,value)


if __name__ == '__main__':
    package.write = write
    package.main()
