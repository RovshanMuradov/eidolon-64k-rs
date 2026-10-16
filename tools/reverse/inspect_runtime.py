#!/usr/bin/env python3
"""Hash-check T1's preserved diagnostic and decode its hook/state constants."""
import hashlib
import json
import os
from pathlib import Path
import struct

import zstandard


def main():
    manifest = json.loads(Path("reports/evidence/reverse/manifest.json").read_text())
    data_root = Path(os.environ["EIDOLON_DATA"])
    files = {}
    for name, item in manifest["runtime_diagnostic"]["files"].items():
        data = (data_root / item["path"]).read_bytes()
        assert len(data) == item["bytes"], name
        assert hashlib.sha256(data).hexdigest() == item["sha256"], name
        files[name] = data
    item = manifest["runtime_diagnostic"]["log_evidence"]
    packed_log = Path(item["path"]).read_bytes()
    assert len(packed_log) == item["bytes"]
    assert hashlib.sha256(packed_log).hexdigest() == item["sha256"]
    assert zstandard.ZstdDecompressor().decompress(packed_log) == files["log"]
    image = files["postfix"]

    def image_at(address, fmt):
        return struct.unpack_from("<" + fmt, image, address - 0x400000)

    assert image[0x4d7b:0x4d81].hex() == "f20f1044c108"
    assert image[0x4d20:0x4d26].hex() == "8b8af0000000"
    assert image[0x4fc2:0x4fc7].hex() == "e829fdffff"
    assert not any(files["samples"]), "Expected missing DLS tables"
    log = files["log"].decode()
    for required in (
        "CREATEFILE path=C:\\windows\\system32\\drivers\\gm.dls",
        "CREATEFILE_RETURN handle=ffffffff last_error=3",
        "READFILE_RETURN result=0 bytes=0 last_error=6",
        "index=127 length=0 pointer=00000000",
        "code=c0000005 address=00404D7B",
        "WINE_EXIT=5 GAMESCOPE_EXIT=0",
    ):
        assert required in log, required

    timeline = [image_at(0x42fc50 + 8 * i, "2f") for i in range(50)]
    assert timeline[0][0] == 0
    assert all(a[1] == b[0] for a, b in zip(timeline, timeline[1:]))
    fmt = image_at(0x43702c, "HHIIHHH")
    header = image_at(0x43edd0, "8I")
    bpm, frames, block, score_bytes = image_at(0x437040, "fIII")
    assert header[1] == frames * fmt[4]
    state = files["fault_state"]
    dimensions = [struct.unpack_from("<I", state, a - 0xb16b000)[0]
                  for a in (0xb17bf2c, 0xb17bfac)]
    seed = struct.unpack_from("<4I", files["synth_init"], 0x10)
    assert seed == image_at(0x437000, "4I") == (1, 0, 31337, 0)
    assert struct.unpack_from("<4I", files["synth_init"], 0x30) == (16007, 0, 16007, 0)

    imports = {}
    packed_image = files["fault_image"]
    p = 0x1977f
    while True:
        slot, = struct.unpack_from("<I", packed_image, p)
        p += 4
        if slot == 0:
            break
        end = packed_image.index(0, p)
        module = packed_image[p:end].decode()
        p = end + 1
        while packed_image[p]:
            end = packed_image.index(0, p)
            name = packed_image[p:end].decode()
            p = end + 1
            imports[f"{module}!{name}"] = hex(slot)
            slot += 4
        p += 1

    print(json.dumps({
        "hashes": "pass",
        "cause": "Missing gm.dls; sample 127 has zero length and null buffer",
        "fault": "0x404d7b movsd xmm0,[ecx+eax*8+8]; caller return 0x404fc7",
        "client_dimensions": dimensions,
        "audio_static": {"wave_format_tag": fmt[0], "channels": fmt[1], "sample_rate": fmt[2],
                         "byte_rate": fmt[3], "block_align": fmt[4], "bits": fmt[5],
                         "buffer_va": hex(header[0]), "bytes": header[1], "frames": frames,
                         "duration_seconds": frames / fmt[2]},
        "clock_static": {"mmtime_type": image_at(0x437020, "I")[0],
                         "call_site": "0x407b91", "result": "0x437024", "sample_step_at_60hz": fmt[2] // 60},
        "rng": {"state_va": "0xb16b810", "seed_dwords": seed, "signed_multiplier": 16007,
                "output_scale": image_at(0x4090c0, "d")[0], "function": "0x401038"},
        "timeline_static": {"bpm": bpm, "segments": timeline,
                            "end_seconds": timeline[-1][1] * 60 / bpm},
        "import_slots": imports,
        "coverage": "Diagnostic fault and unpacked code only; playback and recovery not verified",
    }, indent=2))


if __name__ == "__main__":
    main()
