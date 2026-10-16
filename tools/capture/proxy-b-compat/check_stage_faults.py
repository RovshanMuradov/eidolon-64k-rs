#!/usr/bin/env python3
"""Apply T12's unchanged primitives to new stage data and disposable faults."""
from copy import deepcopy
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import zstandard

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from tools.verify import reference as ref, review_short as review


def rejects(call):
    try:
        call()
    except ref.InvalidCapture:
        return
    raise AssertionError('independent checker accepted deliberately changed data')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle',type=Path)
    args = parser.parse_args()
    bundle = json.loads(args.bundle.read_text())
    directory = Path(os.environ['EIDOLON_DATA'])/'reference'/bundle['run_id']
    index = [ref.load_json(line) for line in (args.bundle.parent/bundle['video']['index']).read_text().splitlines()]
    events = [ref.load_json(line) for line in (directory/'backend.jsonl').read_text().splitlines()]
    valid = review.check_frames(index,events,bundle['video'],directory)
    for fault in ('missing','duplicate','reorder','time-shift','audio-shift','missing-raw'):
        changed = deepcopy(index)
        if fault == 'missing': changed.pop()
        elif fault == 'duplicate': changed[1] = deepcopy(changed[0])
        elif fault == 'reorder': changed.reverse()
        elif fault == 'time-shift': changed[0]['clock_tick'] += 1
        elif fault == 'audio-shift': changed[0]['audio_position'] += 735
        else: changed[0]['raw_zst'] = 'absent-frame.raw.zst'
        rejects(lambda:review.check_frames(changed,events,bundle['video'],directory))
    with tempfile.TemporaryDirectory(prefix='stage-faults-',dir='/tmp/opencode/eidolon/T11') as scratch:
        scratch = Path(scratch)
        row = index[1439]
        packed = (directory/row['raw_zst']).read_bytes()
        pixels = bytearray(zstandard.ZstdDecompressor().decompress(packed)); pixels[3] ^= 1
        variants = [zstandard.ZstdCompressor().compress(pixels),packed[:-1],packed+b'trailing',packed+packed]
        changed = scratch/'changed.raw.zst'
        for payload in variants:
            changed.write_bytes(payload)
            rejects(lambda:ref.verify_raw(changed,8294400,row['sha256']))
        pcm = directory/'pcm.f32le'
        for fault in ('first-byte','retained-tail-byte','sample-shift'):
            changed = scratch/'changed.pcm'
            if fault == 'sample-shift':
                with pcm.open('rb') as source,changed.open('wb') as target:
                    first = source.read(8); shutil.copyfileobj(source,target); target.write(first)
            else:
                shutil.copyfile(pcm,changed)
                offset = 0 if fault == 'first-byte' else 159716351
                with changed.open('r+b') as stream:
                    stream.seek(offset); byte = stream.read(1); stream.seek(offset); stream.write(bytes([byte[0]^1]))
            rejects(lambda:ref.verify_pcm_file(changed,159716352,bundle['audio']['sha256']))
            ref.verify_pcm_file(changed,159716352,ref.hash_file(changed))
            difference = ref.first_byte_difference(pcm,changed)
            assert difference is not None
            if fault != 'sample-shift': assert difference == offset
        ref.verify_pcm_file(pcm,159716352,bundle['audio']['sha256'])
    print(json.dumps(dict(status='DIAGNOSTIC_ONLY',valid_frames=len(index),valid_raw_buffers=len(valid),
                          disposable_faults_rejected=13,reference_accepted=False)))


if __name__ == '__main__':
    main()
