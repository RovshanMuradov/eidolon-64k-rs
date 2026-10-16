#!/usr/bin/env python3
"""Reconcile saved T2 playback with T1's post-fixup code; never run the target."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked_bytes(path, digest):
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == digest, f"Hash mismatch: {path}")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path,
                        default=Path(os.environ["EIDOLON_ROOT"]) / ".worktrees/T2")
    args = parser.parse_args()
    data_root = Path(os.environ["EIDOLON_DATA"])
    reverse = json.loads(Path("reports/evidence/reverse/manifest.json").read_text())
    playback = json.loads((args.capture_root / "artifacts/reference/playback-manifest.json").read_text())
    smoke = json.loads((args.capture_root / "artifacts/reference/wine-smoke-manifest.json").read_text())
    require(smoke["input"]["exe_sha256"] == reverse["inputs"]["native"]["sha256"],
            "T1 and T2 native inputs differ")
    dependency = json.loads((args.capture_root / playback["dependency_identity"]).read_text())
    bank = checked_bytes(data_root / "reference/dependencies" / dependency["bank"]["filename"],
                         dependency["bank"]["sha256"])
    require(len(bank) == dependency["bank"]["bytes"], "Unexpected bank size")
    source_path = "tools/capture/diagnose-playback.c"
    checked_bytes(args.capture_root / source_path, playback["tools"][source_path])

    def dump(name):
        item = reverse["runtime_diagnostic"]["files"][name]
        data = checked_bytes(data_root / item["path"], item["sha256"])
        require(len(data) == item["bytes"], f"Unexpected dump size: {name}")
        return data, int(item["mapped_base"], 16)

    image, base = dump("postfix")
    initial, initial_base = dump("synth_init")

    def unpack(address, fmt):
        return struct.unpack_from("<" + fmt, image, address - base)

    def expect(address, expected):
        expected = bytes.fromhex(expected)
        require(image[address - base:address - base + len(expected)] == expected,
                f"Changed instructions at {address:#x}")

    # Initialization increments the tick before creating the synthesis thread.
    expect(0x401153, "ff 05 20 bd 16 0b")
    expect(0x406387, "e8 57 ad ff ff")
    expect(0x406393, "68 70 20 f0 00 68 36 16 40 00 57 57 ff 15 18 90 40 00")
    counter = 0xB16BD20
    initial_tick, = struct.unpack_from("<I", initial, counter - initial_base)
    require(initial_tick == 1, "Unexpected pre-synthesis tick")

    # All literal references within the application code are two increments or
    # A1 loads. This bounded check is not a proof about arbitrary pointer aliases.
    refs = list(re.finditer(re.escape(struct.pack("<I", counter)),
                            image[0x401000 - base:0x408647 - base]))
    increments = []
    for ref in refs:
        offset = 0x401000 - base + ref.start()
        if image[offset - 2:offset] == b"\xff\x05":
            increments.append(base + offset - 2)
        else:
            require(image[offset - 1] == 0xA1, "Unexpected direct tick reference")
    require(increments == [0x401153, 0x40171F], "Unexpected tick writers")
    # The sampler's node+0x14 cache uses this tick, not a zero-based PCM index.
    expect(0x404DDE, "56 8b f1 57 39 46 14 0f 84 4a 03 00 00 89 46 14")

    expect(0x401681, "8b 70 04 8b 40 08")  # score frame limit and block size
    expect(0x4016A9, "33 ff 85 f6 0f 8e a5 00 00 00")
    expect(0x4016DE, "03 fe 89 7c 24 10 8b 7d 08")
    expect(0x401703, "f3 0f 11 07")  # L at cursor, R at cursor+4
    expect(0x401717, "f3 0f 11 47 04 83 c7 08 ff 05 20 bd 16 0b")
    expect(0x401743, "85 f6 75 a0 89 7d 08 8b 7c 24 10 3b 7c 24 18 0f 8c 5b ff ff ff")
    # The completion hook is after the stores, deferred frees and MXCSR restore.
    expect(0x401758, "8b 44 24 1c 89 44 24 1c 0f ae 54 24 1c 5f 5e 8b e5 5d c3")
    expect(0x40163F, "0f ae 5c 24 08 8b 44 24 08 b9 c0 ff 00 00 23 c1")
    expect(0x401653, "89 44 24 14")  # return EAX is saved MXCSR & 0xffc0

    fmt = unpack(0x43702C, "HHIIHHH")
    buffer, length, *_ = unpack(0x43EDD0, "8I")
    bpm, frame_limit, block_frames, _ = unpack(0x437040, "fIII")
    require(fmt == (3, 2, 44100, 352800, 8, 32, 0), "Unexpected WAVEFORMATEX")
    require(frame_limit % block_frames == 0, "Partial final synthesis block")
    require(length == frame_limit * fmt[4], "WAVEHDR/score size mismatch")

    diagnostic = playback["diagnostic_run"]
    trace = checked_bytes(args.capture_root / diagnostic["evidence"],
                          diagnostic["evidence_sha256"]).decode()
    events = {}
    for line in trace.splitlines():
        if line.startswith("DIAG "):
            fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
            events.setdefault(fields["event"], []).append(fields)

    def event(name):
        require(len(events.get(name, [])) == 1, f"Expected one {name} event")
        return events[name][0]

    def number(fields, key):
        return int(fields[key], 0)

    require(number(event("bank_open_return"), "eax") not in (0, 0xFFFFFFFF), "Bank open failed")
    require(number(event("bank_read_return"), "eax") == 1, "Bank read failed")
    require(number(event("bank_read_return"), "bytes_read") == len(bank), "Bank read incomplete")
    require(number(event("bank_loaded"), "sample127_bytes") == dependency["dls"]["sample_127"]["pcm_bytes"],
            "Sample 127 length differs")
    require(number(event("bank_loaded"), "sample127_pointer") != 0, "Sample 127 is null")
    for name in ("wave_open_return", "wave_prepare_return", "wave_write_return", "first_position_return"):
        require(number(event(name), "eax") == 0, f"Failed {name}")
    live_format = event("wave_open_call")
    require(tuple(number(live_format, k) for k in ("tag", "channels", "hz", "bits", "align"))
            == (fmt[0], fmt[1], fmt[2], fmt[5], fmt[4]), "Live audio format differs")
    entry, write = event("synth_entry"), event("wave_write_return")
    complete, thread_exit = event("synth_complete"), event("synth_thread_exit")
    require(number(entry, "buffer") == number(write, "buffer") == buffer, "PCM pointer differs")
    require(number(write, "bytes") == length and number(write, "synth_done") == 0,
            "Unexpected submission state")
    require(number(complete, "address") == 0x401765, "Unexpected completion hook")
    require(entry["tid"] == complete["tid"] == thread_exit["tid"], "Different synth threads")
    require(number(entry, "t_ms") < number(write, "t_ms") < number(complete, "t_ms")
            <= number(thread_exit, "t_ms"), "Unexpected synthesis/submission order")
    final_tick = number(complete, "generated_frames")  # T2 label is the raw tick.
    generated = final_tick - initial_tick
    require(generated == frame_limit, "Generated and submitted extents differ")
    require(number(complete, "eax") == number(thread_exit, "code") == 0x1F80,
            "Thread result differs from observed restored-MXCSR value")

    end, child_exit = event("native_exit_call"), event("child_exit")
    timeline_end = unpack(0x42FC50 + 49 * 8, "2f")[1] * 60 / bpm
    require(float(end["seconds"]) == timeline_end == diagnostic["timeline_seconds_at_exit"],
            "Visual endpoint differs")
    played = number(end, "sample_position")
    require(number(end, "mmtime_type") == 2 and played == timeline_end * fmt[2], "Exit cursor differs")
    require(number(end, "eax") == 0xFFFFFFFF and number(end, "exit_argument") == 0,
            "Unexpected exit branch")
    require(number(end, "synth_done") == 1 and number(child_exit, "code") == 0, "Playback incomplete")
    require(number(end, "swaps") == number(child_exit, "swaps") == diagnostic["timeline_swaps"],
            "Swap count differs")
    require(number(end, "swap_failures") == number(child_exit, "swap_failures") == 0, "Failed swaps")
    require("WINE_EXIT=0 GAMESCOPE_EXIT=139" in trace, "Missing D2 exit ordering result")
    direct = playback["direct_native_run"]
    direct_trace = checked_bytes(args.capture_root / direct["evidence"], direct["evidence_sha256"]).decode()
    require("WINE_EXIT=0 GAMESCOPE_EXIT=139" in direct_trace, "Direct run did not exit zero")

    print(json.dumps({
        "hashes_and_invariants": "pass",
        "capture_manifest": str(args.capture_root / "artifacts/reference/playback-manifest.json"),
        "recovery": {"bank_bytes_read": len(bank), "sample127_pointer_nonzero": True,
                     "timeline_swaps": number(end, "swaps"), "native_exit": number(child_exit, "code")},
        "pcm": {"initial_tick": initial_tick, "final_tick": final_tick,
                "generated_and_submitted_frames": generated, "bytes": length,
                "half_open_va": [hex(buffer), hex(buffer + length)],
                "last_stereo_frame_va": hex(buffer + length - fmt[4]),
                "sample_rate_hz": fmt[2], "seconds": generated / fmt[2],
                "visual_end_sample_position": played, "tail_frames": generated - played},
        "completion": {"hook_va": "0x401765", "write_t_ms": number(write, "t_ms"),
                       "completion_t_ms": number(complete, "t_ms"),
                       "thread_result": "0x1f80 = saved MXCSR & 0xffc0; not PCM count/status",
                       "expected_final_cursor_at_ebp_plus_8": hex(buffer + length)},
        "coverage": "Saved code/trace reconciliation only; no full PCM bytes or final pixels inspected",
        "remaining": ["Live full-buffer readback/immutability and deterministic replay",
                      "Final GL bindings/layout and scene pixels", "Controlled clock/scene boundaries"],
    }, indent=2))


if __name__ == "__main__":
    main()
