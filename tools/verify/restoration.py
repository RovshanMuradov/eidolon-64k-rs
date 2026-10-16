"""D12's explicit D9-restored-native contract; file integrity, not live acceptance."""

import struct

if __package__:
    from . import compatibility as compat, reference as ref
    from .review_short import original_roles
else:
    import compatibility as compat
    import reference as ref
    from review_short import original_roles


EFFECTIVE_HASH = "cb62ed7fd0878836b763b892f64cb9e4a789f49f304d32d0a2fc334aecb433ea"
SHIMS = ("opengl32.dll", "winmm.dll")


def check_identity(source):
    ref.require(source["kind"] == ref.RESTORED_KIND, "draft-4 requires explicit D9-restored-native identity")
    identity = source["restoration"]
    ref.fields(identity, ("decision", "transformation", "raw_shader_sha256",
                          "effective_shader_sha256", "shim_sha256"))
    ref.require(identity["decision"] == "D12" and identity["transformation"] == "450-compatibility",
                "D12 authorizes only the directive-only D9 variant")
    ref.require(identity["raw_shader_sha256"] == compat.SOURCE_HASH
                and identity["effective_shader_sha256"] == EFFECTIVE_HASH,
                "D9 raw/effective shader identity changed")
    ref.fields(identity["shim_sha256"], SHIMS)
    for name, checksum in identity["shim_sha256"].items():
        ref.digest(checksum, f"restoration shim {name}")
    for name in ("archive", "bank"):
        ref.require(source["inputs"].get(name) == compat.INPUT_HASHES[name],
                    f"restored native requires pinned {name}")


def native_scenes(image, count):
    """Original float32 audio-time path and 50 row identities, not reused tokens."""
    def f32(value):
        return struct.unpack("<f", struct.pack("<f", value))[0]

    rows = [struct.unpack_from("<ff", image, 0x2fc50 + 8*i) for i in range(50)]
    scenes = []
    for n in range(count):
        seconds = f32(f32(n * 735) / 44100)
        beat = f32(seconds * f32(80 / 60))
        row = next((i for i, (_, end) in enumerate(rows) if beat < end), None)
        ref.require(row is not None, "frame beyond native row table")
        name = f"row-{row:02d}"
        if not scenes or scenes[-1]["id"] != name:
            scenes.append({"id": name, "first": n, "last": n})
        else:
            scenes[-1]["last"] = n
    return scenes


def verify(m, roots):
    """Bind each run independently; run-specific locations are not pair identity."""
    provenance = m["provenance"]
    ref.fields(provenance, ("eligibility", "native_image"))
    sidecar_path = compat.bound_file(provenance["eligibility"], roots)
    compat.assess(sidecar_path, roots)
    sidecar = ref.load_json(sidecar_path.read_text())
    ref.require(sidecar["run_id"] == m["run_id"], "restoration provenance run mismatch")
    ref.require(sidecar["transformation"] == "450-compatibility" and sidecar["fallback"] is None,
                "D12 does not authorize a fallback reference variant")
    identity = m["source"]["restoration"]
    for name in SHIMS:
        ref.require(sidecar["build"]["outputs"][name]["sha256"] == identity["shim_sha256"][name],
                    "restoration shim differs from bound build")
    image = compat.bound_file(provenance["native_image"], roots).read_bytes()
    roles = original_roles(image)  # Independently pins the entire reviewed native image.
    ref.require(len(sidecar["calls"]) == len(roles), "incomplete original shader ledger")
    for call, (ret, addresses) in zip(sidecar["calls"], roles):
        ref.require(call["stage"] == 0x8b30 and call["count"] == len(addresses)
                    and call["caller"] == f"0x{ret-2:08x}" and call["return"] == f"0x{ret:08x}"
                    and call["source_addresses"] == [f"0x{a:08x}" for a in addresses],
                    "shader ledger differs from original roles")
        for binding, address in zip(call["input"], addresses):
            raw = compat.bound_file(binding, roots).read_bytes()
            offset = address - 0x400000
            ref.require(image[offset:offset + len(raw) + 1] == raw + b"\0",
                        "raw shader differs from immutable native image")
    count = ref.integer(m["video"]["frame_count"], "frame_count", 1)
    ref.require(count <= ref.ORIGINAL_VISUAL_END_TICK, "frame count exceeds native endpoint")
    ref.require(ref.exact_equal(m["scenes"], native_scenes(image, count)),
                "restored native scenes must follow original row identities/ranges")

    # A new producer envelope must bind the actual stop and observed file/memory
    # identities. Old partial runs lack this envelope and cannot be relabeled.
    run = ref.load_json(compat.bound_file(sidecar["run_manifest"], roots).read_text())
    proof = run.get("reference_contract")
    expected = {
        "schema": m["schema"], "source": m["source"],
        "capture_tool_sha256": m["capture"]["tool_sha256"],
        "video_index_sha256": m["video"]["index_sha256"], "frame_count": count,
        "audio_sha256": m["audio"]["sha256"], "termination": m["termination"],
        "finalized": m["completion"]["finalized"],
        "exe_before_sha256": ref.ORIGINAL_SHA256, "exe_after_sha256": ref.ORIGINAL_SHA256,
        "target_memory_before_sha256": compat.SOURCE_HASH,
        "target_memory_after_sha256": compat.SOURCE_HASH,
        "loaded_shim_sha256": identity["shim_sha256"],
    }
    ref.fields(proof, (*expected, "observations"))
    ref.require(ref.exact_equal(ref.without(proof, "observations"), expected),
                "producer restoration/stop envelope disagrees with capture")
    ref.require(isinstance(proof["observations"], dict) and bool(proof["observations"]),
                "missing restoration runtime observations")
    for name, binding in proof["observations"].items():
        ref.text(name, "restoration observation name")
        ref.require(compat.bound_file(binding, roots).stat().st_size > 0,
                    "empty restoration runtime observation")
