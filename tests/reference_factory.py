"""Tiny synthetic captures, generated independently of the verifier implementation."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct

import zstandard


def sha(data):
    return hashlib.sha256(data).hexdigest()


@dataclass
class Capture:
    root: Path
    manifest: dict
    records: list

    @property
    def path(self):
        return self.root / "manifest.json"

    @property
    def pcm(self):
        return self.root / self.manifest["audio"]["path"]

    def save(self):
        index = b"".join((json.dumps(record, sort_keys=True) + "\n").encode()
                         for record in self.records)
        (self.root / "frames.jsonl").write_bytes(index)
        self.manifest["video"]["index_sha256"] = sha(index)
        self.path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def update_pcm(self, data):
        self.pcm.write_bytes(data)
        self.manifest["audio"]["sha256"] = sha(data)
        self.manifest["completion"]["pcm"]["stable_sha256"] = sha(data)
        self.save()


def make_capture(root, run_id, storage="reference", native_shape=False):
    root.mkdir(parents=True)
    count, rate = 65, 22050  # Half-sample ideal positions on odd frames.
    samples = count * rate // 60 + 17  # Preserve a generated PCM tail.
    sample_format, block_align = "s16le", 4
    if native_shape:
        count, rate, samples = 27000, 44100, 19964544
        sample_format, block_align = "f32le", 8
        # Sparse synthetic silence with a nonzero final stereo frame, not native PCM.
        with (root / "audio.pcm").open("wb") as stream:
            stream.truncate(159716352)
            stream.seek(159716344)
            stream.write(struct.pack("<ff", 0.25, -0.5))
    else:
        pcm = b"".join(struct.pack("<hh", (n * 101) % 65536 - 32768,
                                  (n * 313 + 19) % 65536 - 32768)
                       for n in range(samples))
        (root / "audio.pcm").write_bytes(pcm)
    with (root / "audio.pcm").open("rb") as stream:
        pcm_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    evidence = b"Synthetic fixture observations only; no original process or live hooks.\n"
    (root / "pcm-completion.txt").write_bytes(evidence)
    scenes = [{"id": "a", "first": 0, "last": 7},
              {"id": "b", "first": 8, "last": 42},
              {"id": "c", "first": 43, "last": 64}]
    # Explicit golden anchor set, not calculated using the verifier's rule.
    anchors = {0, 7, 8, 42, 43, 60, 64}
    if native_shape:
        scenes = [{"id": "synthetic-native-shape", "first": 0, "last": 26999}]
        anchors = set(range(0, 27000, 60)) | {26999}
    records = []
    compressor = zstandard.ZstdCompressor(write_checksum=True)
    for n in range(count):
        raw = bytes((n * 13 + byte * 29) % 256 for byte in range(24))
        record = {"n": n, "tick": n, "clock_tick": n,
                  "audio_position": n * 735 if native_shape else (n * 735) // 2,
                  "audio_position_num": n * rate, "audio_position_den": 60,
                  "sha256": sha(raw)}
        if storage == "reference" and n in anchors:
            name = f"{n:06d}.raw.zst"
            (root / name).write_bytes(compressor.compress(raw))
            record["raw_zst"] = name
        records.append(record)
    manifest = {
        "schema": "eidolon-reference-draft-3", "run_id": run_id,
        "source": {"kind": "synthetic", "exe_sha256": sha(b"fixture, not original"),
                   "inputs": {"fixture-seed": sha(b"T9 fixture version 3")}},
        "capture": {"kind": "synthetic-reference", "tool_sha256": sha(b"synthetic producer v3"),
                    "command": ["python", "-m", "pytest", "tests/test_reference.py"]},
        "conditions": {
            "environment": {"os": "synthetic Linux", "arch": "synthetic x86",
                            "wine": "synthetic; no Wine", "gpu": "synthetic; no GPU",
                            "driver": "synthetic; no driver", "graphics_api": "synthetic bytes",
                            "gamescope": "synthetic; no gamescope",
                            "display": {"kind": "gamescope-headless", "width": 1920, "height": 1080,
                                        "launcher": "tools/wine-headless", "wine_virtual_desktop": False}},
            "settings": {"fixture_version": 3},
            "clock": {"numerator": 1, "denominator": 60, "method": "synthetic exact ticks"},
            "rng": {"method": "synthetic deterministic arithmetic",
                    "initial_state_sha256": sha(b"synthetic RNG state")},
            "initial_state_sha256": sha(b"synthetic initial state"),
        },
        "video": {"width": 3, "height": 2, "row_stride": 12, "pixel_format": "rgba8",
                  "row_order": "bottom-up", "color_space": "synthetic byte values",
                  "frame_count": count, "index": "frames.jsonl", "index_sha256": "0" * 64,
                  "storage": storage},
        "audio": {"path": "audio.pcm", "sha256": pcm_hash, "sample_format": sample_format,
                  "sample_rate": rate, "channels": ["L", "R"], "layout": "interleaved",
                  "sample_frames": samples, "start_sample": 0},
        "scenes": scenes,
        "termination": {"reason": "natural_exit", "end_tick": count,
                        "audio_position": 19845000 if native_shape else 23887,
                        "audio_position_num": 1190700000 if native_shape else 1433250,
                        "audio_position_den": 60, "exit_code": 0,
                        "timeline_end_tick": None, "evidence": "synthetic exit event"},
        "completion": {"finalized": True, "frames_observed": count, "frames_hashed": count,
                       "audio_sample_frames": samples, "dropped_frames": 0,
                       "dropped_audio_sample_frames": 0, "errors": [],
                       "pcm": {"submitted_bytes": samples * block_align,
                               "initial_tick": 1, "final_tick": samples + 1,
                               "final_cursor_offset": samples * block_align,
                               "events": {"synth_complete": 2, "readback_begin": 3,
                                          "readback_end": 4, "stability_check": 5},
                               "stable_sha256": pcm_hash, "evidence": "pcm-completion.txt",
                               "evidence_sha256": sha(evidence)}},
    }
    capture = Capture(root, manifest, records)
    capture.save()
    return capture
