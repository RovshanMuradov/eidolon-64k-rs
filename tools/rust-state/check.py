#!/usr/bin/env python3
"""Read-only target audit; emitted metadata is never a candidate runtime dump."""
import hashlib
import json
import os
from pathlib import Path
import struct
import tarfile

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ["EIDOLON_DATA"])


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def checked(path, expected):
    raw = path.read_bytes()
    assert sha(raw) == expected, str(path)
    return raw


def main():
    pointer = json.loads((ROOT / "artifacts/rust/engine/candidate.json").read_text())
    bundle = Path(pointer["directory"])
    publication = json.loads(checked(bundle / "candidate.json", pointer["manifest_sha256"]))
    for item in publication["files"].values():
        assert len(checked(bundle / item["path"], item["sha256"])) == item["bytes"]
    pe = (bundle / "eidolon-runtime.exe").read_bytes()
    build = json.loads((bundle / "build.json").read_text())
    source_names = ["src/audio/runtime.rs", "src/audio/graph.rs", "src/audio/math.rs",
                    "src/audio/glitch.rs", "src/engine.rs", "src/physics.rs",
                    "src/runtime.rs", "src/observe.rs", "src/graphics.rs"]
    source_pins = {}
    with tarfile.open(bundle / "source.tar") as archive:
        for name in source_names:
            raw = archive.extractfile(name).read()
            assert sha(raw) == build["inputs"][name]
            assert raw == (ROOT / name).read_bytes()
            source_pins[name] = sha(raw)

    nt = struct.unpack_from("<I", pe, 0x3c)[0]
    count, optional_size = struct.unpack_from("<H", pe, nt + 6)[0], struct.unpack_from("<H", pe, nt + 20)[0]
    image_base = struct.unpack_from("<I", pe, nt + 24 + 28)[0]
    assert image_base == 0x400000
    sections = []
    for i in range(count):
        at = nt + 24 + optional_size + i * 40
        size, rva, raw_size, offset = struct.unpack_from("<4I", pe, at + 8)
        sections.append((rva, raw_size, offset))

    def bytes_at(va, size):
        rva = va - image_base
        for start, length, offset in sections:
            if start <= rva and rva + size <= start + length:
                return pe[offset + rva - start:offset + rva - start + size]
        raise AssertionError(hex(va))

    # Bind the proposed GL gate to the import's actual identity, not just an address.
    imports_rva = struct.unpack_from("<I", pe, nt + 24 + 104)[0]
    descriptor = image_base + imports_rva
    recti_iat = None
    while True:
        original, timestamp, forwarder, dll_name, first = struct.unpack("<5I", bytes_at(descriptor, 20))
        if not (original or dll_name or first):
            break
        for i in range(1000):
            name = struct.unpack("<I", bytes_at(image_base + original + i*4, 4))[0]
            if not name:
                break
            if not name & 0x80000000:
                label = bytes_at(image_base + name + 2, 8).split(b"\0")[0]
                if label == b"glRecti":
                    recti_iat = first + i*4
        descriptor += 20
    assert recti_iat == 0xb26b8

    # Exact instruction boundaries from this immutable PE, not another build's symbols.
    points = [
        ("audio_initialized_pregraph", 0x40a3b5, "8b5c241831ff8930be000d0000",
         "before instruction: ESI=Runtime; seed=ESI+0x1400 (16 bytes); state=*(ESI+0x168c); tick=*state (4 bytes)",
         "initial seed/tick before any graph node creation; synthesis thread, NOT native prethread storage phase"),
        ("engine_evaluate_entry", 0x409767, "5589e553575681ec14010000",
         "before prologue: EDX=Engine; physics=EDX+8 (256 bytes); previous_seconds=EDX+0x108 (4 bytes); cursor=*(ESP+4)",
         "gate return address base+0x12a9c for timeline calls; base+0x12991 is initialization evaluation"),
        ("previous_seconds_consumption", 0x40983e, "f30f5ca108010000",
         "ECX=Engine; read ECX+0x108 before SUBSS; not XMM4 after subtraction",
         "dt calculation before previous_seconds is overwritten"),
        ("previous_seconds_write", 0x409e8c, "f30f11a908010000",
         "ECX=Engine; XMM5.low=current seconds",
         "end of successful evaluate; post-update previous_seconds now means current seconds"),
        ("marker_entry", 0x41155d, "5589e55683ec0c",
         "cdecl kind=*(ESP+4),data=*(ESP+8),bytes=*(ESP+12); original EBP is runtime caller frame",
         "kind1 return address base+0x12a09; read original_EBP-0x570 (4 bytes), physics original_EBP-0x670 (256 bytes)"),
        ("marker1_call", 0x412a04, "e854ebffff",
         "kind1 after evaluate(0), before first waveOutGetPosition",
         "native first-query/previous-seconds corresponds here; existing snapshot does not serialize that field"),
        ("draw_import_thunk", 0x44532c, "ff25b8264b00",
         "jmp [image_base+0xb26b8] (glRecti IAT); use import-name resolution and rebased pointer fingerprint",
         "timeline draw return address base+0x143d5; loading return base+0x13a25"),
        ("timeline_draw_call", 0x4143d0, "e8570f0300",
         "glRecti immediately after all pass uniform uploads",
         "record only between marker2 and marker3; initialization uses the same draw routine"),
    ]
    observed_points = []
    for name, va, fingerprint, fields, phase in points:
        assert bytes_at(va, len(bytes.fromhex(fingerprint))).hex() == fingerprint, name
        observed_points.append(dict(name=name, rva=hex(va-image_base), preferred_va=hex(va),
                                    instruction_bytes=fingerprint, fields=fields, phase=phase))
    # Independently pin stores that establish Runtime's private optimized layout.
    stores = {0x40a17f: "c7870014000001000000", 0x40a1a0: "c78708140000697a0000",
              0x40a280: "89878c160000", 0x40a35b: "c70001000000",
              0x412982: "8d9588f9ffff", 0x4129bd: "8d8590f9ffff"}
    for va, fingerprint in stores.items():
        assert bytes_at(va, len(bytes.fromhex(fingerprint))).hex() == fingerprint

    scope_path = Path(os.environ["EIDOLON_ROOT"]) / ".worktrees/T24/artifacts/verification/rust/state-scope.json"
    scope = json.loads(scope_path.read_text())
    reference_path = ROOT / "artifacts/reference/proxy-b-d13-detached-20261016-1-reference.json"
    reference = checked(reference_path, "36c1f7f330682bb4f818ad22cd0dab99359ffcdf2b4abc60cfb9381d98e37c64")
    native_dir = DATA / "reference/proxy-b-d13-detached-20261016-1"
    payloads = {}
    for role, desc in scope["initial_payloads"].items():
        name = "native-" + role.replace("/", "-") + ".bin"
        raw = checked(native_dir / name, desc["sha256"])
        assert len(raw) == desc["bytes"]
        payloads[role] = dict(path=str(native_dir/name), sha256=sha(raw), bytes=len(raw))
    native_image_path = DATA / "reverse/confirmed-debug/postfix-00400000.bin"
    image = checked(native_image_path, "da9cc65b64aa7d322807d93cb4361bc864a10f00ed47246f5df96fb5b9ecf504")
    rng = (native_dir / "native-prethread-rng.bin").read_bytes()
    assert struct.unpack("<4I", rng[:16]) == (1023, 1023, 0, 0)
    assert struct.unpack("<2q", rng[16:32]) == (1, 31337)
    assert rng[32:48] == b"\xff"*16
    for i in range(79):
        assert rng[48+i*16:56+i*16] == rng[56+i*16:64+i*16] == image[0x90b8+i*8:0x90c0+i*8]
    constants = dict(block_bytes=1312, mutable_seed_bytes=16, immutable_bytes=1296,
                     exp2_offset=dict(offset=0, bytes=16, u32=[1023,1023,0,0]),
                     seed=dict(offset=16, bytes=16, i64=[1,31337]),
                     allbits=dict(offset=32, bytes=16, hex="ff"*16),
                     duplicated_f64=dict(offset=48, count=79, stride=16, native_literal_va="0x4090b8",
                                         source_literal_stride=8, matched_saved_native_bytes=True))
    job = DATA / "verification/rust/live-d26-full01"
    state = json.loads((job / "state.json").read_text())
    desc = state["output"]["output/events.bin"]
    ledger = checked(job / "output/events.bin", desc["sha256"])
    assert ledger[:8] == b"EIDCAP01" and len(ledger) == desc["bytes"]
    at, n, initial, current, changed = 8, 0, None, None, 0
    trajectory = hashlib.sha256()
    while at < len(ledger):
        sequence, tid, kind, size = struct.unpack_from("<4I", ledger, at)
        raw = ledger[at+16:at+16+size]
        assert len(raw) == size
        at += 16+size
        if kind == 1:
            initial = raw[28:]
            assert size == 284 and initial == (native_dir / "native-first-query-physics.bin").read_bytes()
        if kind == 2:
            assert size == 284 and struct.unpack_from("<I", raw)[0] == n
            current = raw
            trajectory.update(raw[28:])
            changed += raw[28:] != initial
            n += 1
        if kind in (3, 4):
            assert raw == current, "candidate pre/post draw snapshot phase differs"
    assert at == len(ledger) and n == 27000 and initial is not None
    result = dict(schema="eidolon-state-correspondence-static-1", target_executed_by_this_audit=False,
                  evidence_kind="static source/binary mapping and existing payload audit; observation protocol is proposed",
                  executable_sha256=pointer["executable_sha256"], source_archive_sha256=publication["files"]["source.tar"]["sha256"],
                  source_commit=publication["source_commit"], source_sha256=source_pins,
                  native_image=dict(path=str(native_image_path), sha256=sha(image)),
                  native_reference=dict(path=str(reference_path.relative_to(ROOT)), sha256=sha(reference)),
                  scope_input=dict(path=str(scope_path), sha256=sha(scope_path.read_bytes())),
                  environment="host-only Python; no new target/GPU/Wine observations; runtime environment remains bound by T24",
                  initial_native_payloads=payloads, native_rng_block=constants,
                  candidate_observation_points=observed_points,
                  private_layout_store_fingerprints={hex(k):v for k,v in stores.items()},
                  candidate_saved_physics=dict(path=str(job/"output/events.bin"), sha256=sha(ledger),
                     frames=n, kind2_kind3_kind4_identical=True, snapshot_reused_not_three_independent_engine_reads=True,
                     frames_different_from_initial=changed,
                     trajectory_sha256=trajectory.hexdigest(), native_later_oracle_available=False),
                  production_accepted=False)
    destination = ROOT / "artifacts/rust/state/correspondence.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(dict(status="PASS", native_payloads=7, constants=79, instruction_points=len(points),
                          candidate_physics_frames=n, changed_physics_frames=changed,
                          candidate_new_runtime_payloads=0)))


if __name__ == "__main__":
    main()
