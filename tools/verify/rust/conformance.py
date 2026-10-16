#!/usr/bin/env python3
"""Independent file-only native-reference1 conformance. Never executes a target."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

import zstandard

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.verify import reference as ref

RUN = "proxy-b-d13-detached-20261016-1"
# Independent of the supplied manifest and of either port branch.
PIN = "36c1f7f330682bb4f818ad22cd0dab99359ffcdf2b4abc60cfb9381d98e37c64"
N, PCM_BYTES = 27000, 159716352
ROOT = Path(os.environ.get("EIDOLON_ROOT", Path(__file__).resolve().parents[3]))
DATA = Path(os.environ.get("EIDOLON_DATA", ROOT / "data"))
CHECKOUT = Path(__file__).resolve().parents[3]


class Failure(ValueError):
    pass


def need(ok, message):
    if not ok:
        raise Failure(message)


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def checked(path, digest):
    path = Path(path)
    need(isinstance(digest, str) and len(digest) == 64 and
         all(c in "0123456789abcdef" for c in digest), "invalid SHA-256")
    need(sha(path) == digest, f"identity mismatch: {path}")
    return path


def load(path):
    return ref.load_json(Path(path).read_bytes())


def same(a, b, message):
    need(ref.exact_equal(a, b), message)


def fields(value, names):
    need(type(value) is dict and set(value) == set(names.split()), "unexpected/missing object fields")


def binding(root, item):
    fields(item, "path sha256")
    return checked(ref.payload_path(root, item["path"]), item["sha256"])


def exact_files(expected, actual, size=None):
    expected, actual = Path(expected), Path(actual)
    expected_size = expected.stat().st_size if size is None else size
    need(expected.stat().st_size == actual.stat().st_size == expected_size,
         f"byte length differs: {actual}")
    with expected.open("rb") as a, actual.open("rb") as b:
        offset = 0
        while left := a.read(1 << 20):
            right = b.read(len(left))
            if left != right:
                first = next(i for i, (x, y) in enumerate(zip(left, right)) if x != y)
                raise Failure(f"byte mismatch at {offset + first}: {actual}")
            offset += len(left)
    return expected_size


def read_index(path):
    data = Path(path).read_bytes()
    need(data.endswith(b"\n"), "unterminated frame index")
    return [ref.load_json(line) for line in data.splitlines()]


class Native:
    def __init__(self, capture=CHECKOUT, data=DATA):
        self.capture, self.data = Path(capture), Path(data)
        self.directory = self.data / "reference" / RUN
        self.path = self.capture / "artifacts/reference" / f"{RUN}-reference.json"
        self.manifest = load(checked(self.path, PIN))
        m = self.manifest
        self.roots = {"checkout": self.capture, "data": self.data, "shared": ROOT}
        self.sidecar = load(self.bound(m["provenance"]["eligibility"]))
        self.producer = load(self.bound(self.sidecar["run_manifest"]))
        self.frames = read_index(checked(self.path.parent / m["video"]["index"], m["video"]["index_sha256"]))
        need(len(self.frames) == N, "native frame coverage")
        self.pcm = checked(self.directory / m["audio"]["path"], m["audio"]["sha256"])
        need(self.pcm.stat().st_size == PCM_BYTES, "native PCM extent")
        checked(self.path.parent / m["completion"]["pcm"]["evidence"], m["completion"]["pcm"]["evidence_sha256"])
        self.states = {}
        for e in self.producer["observations"]:
            if e["event"] == "native_state":
                p = checked(ref.payload_path(self.directory, e["file"]), e["sha256"])
                need(p.stat().st_size == e["bytes"], "native state extent")
                self.states[e["phase"] + "/" + e["role"]] = p
        need(len(self.states) == 7, "native initial state coverage")

    def bound(self, item):
        fields(item, "root path sha256")
        need(item["root"] in self.roots, "unknown native binding root")
        return checked(ref.payload_path(self.roots[item["root"]], item["path"]), item["sha256"])

    def times(self):
        """Project observed words, never regenerate seconds/local beat with port code."""
        desc = self.producer["ordered_stream"]
        source = checked(ref.payload_path(self.directory, desc["path"]), desc["sha256"])
        decoder, digest = zstandard.ZstdDecompressor().decompressobj(), hashlib.sha256()
        pending, size, scenes, clocks, endpoint = b"", 0, [], [], []
        with source.open("rb") as f:
            while block := f.read(1 << 20):
                need(not decoder.eof, "trailing native compressed stream")
                raw = decoder.decompress(block)
                need(not decoder.unused_data, "concatenated native stream")
                digest.update(raw); size += len(raw)
                lines = (pending + raw).split(b"\n"); pending = lines.pop()
                for line in lines:
                    if b'"event":"scene_state"' in line:
                        scenes.append(ref.load_json(line))
                    elif b'"event":"clock"' in line and b'"api":"waveOutGetPosition"' in line:
                        clocks.append(ref.load_json(line))
                    elif b'"event":"native_endpoint"' in line:
                        endpoint.append(ref.load_json(line))
        need(decoder.eof and not pending, "truncated native stream")
        need(size == desc["decoded_bytes"] and digest.hexdigest() == desc["decoded_sha256"], "native decoded stream identity")
        same([s["n"] for s in scenes], list(range(N)), "native scene coverage")
        same([c["n"] for c in clocks], list(range(N + 1)), "native clock coverage")
        need(len(endpoint) == 1 and endpoint[0]["sample_cursor"] == 19845000 and
             endpoint[0]["exit_code"] == 0 and clocks[-1]["value"] == 19845000, "native endpoint")
        # Tuple fields are native observations; row attribution is checked separately.
        result = []
        for s, c in zip(scenes, clocks):
            need(c["wType"] == 2 and c["caller"] == "0x00407b97" and c["seq"] < s["seq"], "native clock/scene ordering")
            result.append((s["n"], c["value"], s["seconds_f32_bits"], s["scene_local_beat_f32_bits"], s["scene_token"]))
        return result


def compare_frames(native, records, directory, require_raw=True):
    need(len(records) == N, "candidate frame count")
    retained = 0
    for i, (expected, actual) in enumerate(zip(native.frames, records)):
        fields(actual, "n tick clock_tick audio_position audio_position_num audio_position_den sha256" +
               (" raw_zst" if "raw_zst" in actual else ""))
        same({k: v for k, v in actual.items() if k != "raw_zst"},
             {k: v for k, v in expected.items() if k != "raw_zst"}, f"frame/time/hash mismatch at {i}")
        if require_raw and "raw_zst" in expected:
            need("raw_zst" in actual, f"missing retained frame {i}")
        if "raw_zst" in actual:
            ref.verify_raw(ref.payload_path(directory, actual["raw_zst"]), 1920 * 1080 * 4, expected["sha256"])
            retained += 1
    return {"frames": N, "retained_raws": retained, "comparison": "exact SHA-256 including alpha; every supplied raw rehashed"}


def words(stream, count):
    raw = stream.read(4 * count)
    need(len(raw) == 4 * count, "truncated candidate stream")
    return struct.unpack("<" + "I" * count, raw)


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def compare_probe(native, path, times):
    need(len(times) == N and [t[0] for t in times] == list(range(N)), "native vector coverage")
    rows = [i for i, row in enumerate(native.manifest["scenes"]) for _ in range(row["last"] - row["first"] + 1)]
    previous = 0.0
    with Path(path).open("rb") as stream:
        magic = stream.read(8)
        need(magic in (b"EIDRAW01", b"EIDSTA01"), "candidate probe magic")
        for n, cursor, seconds, local, _token in times:
            header = words(stream, 8)
            need(header[:3] == (n, cursor, seconds) and header[4:6] == (rows[n], local), f"native time/row mismatch at {n}")
            sec = struct.unpack("<f", struct.pack("<I", seconds))[0]
            # Explicitly DERIVED checks: reference1 has no authenticated beat/dt vector.
            need(header[3] == bits(f32(sec * f32(80 / 60))) and
                 header[6] == bits(f32(sec - previous)), f"derived beat/dt mismatch at {n}")
            previous = sec
            need(header[7] <= 1024, "invalid uniform count")
            names = set()
            for _ in range(header[7]):
                name, components = words(stream, 2)
                need(name not in names and 1 <= components <= 4, "duplicate/invalid uniform")
                names.add(name); words(stream, components)
            if magic == b"EIDSTA01":
                state = struct.pack("<64I", *words(stream, 64))
                if n == 0:
                    need(state == native.states["first-query/physics"].read_bytes(), "native frame-zero physics mismatch")
        need(not stream.read(1), "extra candidate records/trailing bytes")
    return {"native_time_frames": N, "native_state_frames": int(magic == b"EIDSTA01"),
            "derived_only": ["beat", "dt"], "unchecked": ["uniform values", "post-update physics after frame zero"]}


def compare_shaders(native, path):
    calls = native.sidecar["calls"]
    need(len(calls) == 31, "native shader role count")
    ordered = calls[1:] + calls[:1]  # Probe ABI puts the loading program last.
    elements = 0
    with Path(path).open("rb") as stream:
        need(stream.read(8) == b"EIDGLS01" and words(stream, 1) == (31,), "shader stream header")
        for call in ordered:
            need(words(stream, 1) == (call["count"],), "shader source-array count")
            for item in call["forwarded"]:
                expected = native.bound(item).read_bytes() + b"\0"
                need(words(stream, 1) == (len(expected),), "shader source length")
                need(stream.read(len(expected)) == expected, "shader bytes differ from native effective source")
                elements += 1
        need(not stream.read(1), "trailing shader data")
    return {"native_effective_shader_elements": elements}


def pe_identity(path):
    """Read PE32 headers/import descriptors; this is static identity, not execution."""
    raw = Path(path).read_bytes()
    need(len(raw) >= 64 and raw[:2] == b"MZ", "not a PE")
    pe = struct.unpack_from("<I", raw, 60)[0]
    need(pe + 256 <= len(raw) and raw[pe:pe+4] == b"PE\0\0", "invalid PE header")
    machine, count = struct.unpack_from("<HH", raw, pe + 4)
    optsize = struct.unpack_from("<H", raw, pe + 20)[0]
    opt = pe + 24
    need(machine == 0x14c and struct.unpack_from("<H", raw, opt)[0] == 0x10b and optsize >= 112, "candidate must be i386 PE32")
    sections = []
    for i in range(count):
        offset = opt + optsize + 40 * i
        need(offset + 40 <= len(raw), "truncated PE section table")
        vsize, va, size, ptr = struct.unpack_from("<4I", raw, offset + 8)
        sections.append((va, size, ptr))
    def rva(address, size):
        for va, length, ptr in sections:
            if va <= address and address + size <= va + length:
                start = ptr + address - va
                need(start + size <= len(raw), "truncated PE data")
                return start
        raise Failure("unmapped PE RVA")
    address, length = struct.unpack_from("<II", raw, opt + 104)
    imports = []
    need(address and length >= 20, "missing PE import directory")
    for i in range(length // 20):
        entry = struct.unpack_from("<5I", raw, rva(address + i * 20, 20))
        if entry == (0, 0, 0, 0, 0):
            break
        p = rva(entry[3], 1)
        end = raw.find(b"\0", p, p + 256)
        need(end >= p, "unterminated PE import name")
        imports.append(raw[p:end].decode("ascii"))
    else:
        raise Failure("unterminated PE import directory")
    return {"machine": machine, "bytes": len(raw), "sha256": sha(path), "imports": imports}


def candidate_metadata(native, m):
    fields(m, "schema kind reference_sha256 executable inputs runtime video frames audio pcm pcm_completion state completion endpoint observations")
    same(m["schema"], "eidolon-rust-candidate-1", "candidate schema")
    same(m["kind"], "production-rust-capture", "hybrid/probe is not production")
    same(m["reference_sha256"], PIN, "candidate reference identity")
    same(m["video"], {k: v for k, v in native.manifest["video"].items() if k not in ("index", "index_sha256", "storage")}, "video layout/count")
    same(m["audio"], {k: v for k, v in native.manifest["audio"].items() if k not in ("path", "sha256")}, "PCM format/extent")
    need(type(m["state"]) is dict and set(m["state"]) == set(native.states), "initial state coverage")
    same(m["completion"], dict(finalized=True, frames_observed=N, frames_hashed=N,
         audio_sample_frames=19964544, dropped_frames=0, dropped_audio_sample_frames=0, errors=[]), "incomplete/lossy candidate")
    same(m["endpoint"], dict(reason="natural_exit", exit_code=0, queries=N+1, frames=N,
         last_present=N-1, terminal_cursor=19845000, wrapper_stop=False), "not a complete native-duration endpoint")
    proof = m["pcm_completion"]
    fields(proof, "rendered_sample_frames submitted_bytes stable_sha256 events")
    same(proof["rendered_sample_frames"], 19964544, "rendered PCM extent")
    same(proof["submitted_bytes"], PCM_BYTES, "submitted PCM extent")
    same(proof["stable_sha256"], native.manifest["audio"]["sha256"], "unstable/altered PCM")
    order = "render_complete readback_begin readback_end stability_check".split()
    fields(proof["events"], " ".join(order))
    ids = [proof["events"][k] for k in order]
    need(all(type(i) is int and i > 0 for i in ids) and all(a < b for a, b in zip(ids, ids[1:])), "PCM completion/acquisition order")
    fields(m["observations"], "identity clock state pcm_completion endpoint")


def full_run(native, path):
    """Candidate files may pass this contract but cannot self-certify production/G6."""
    m, root = load(path), Path(path).resolve().parent
    candidate_metadata(native, m)
    exe = binding(root, m["executable"])
    identity = pe_identity(exe)
    need(type(m["inputs"]) is dict and m["inputs"], "missing build/dependency inventory")
    for item in m["inputs"].values():
        binding(root, item)
    runtime = m["runtime"]
    fields(runtime, "environment exe_before_sha256 exe_after_sha256 command capture_tool")
    same(runtime["environment"], native.manifest["conditions"]["environment"], "runtime environment differs")
    same(runtime["exe_before_sha256"], identity["sha256"], "executed EXE before identity")
    same(runtime["exe_after_sha256"], identity["sha256"], "executed EXE after identity")
    need(type(runtime["command"]) is list and runtime["command"] and
         all(type(x) is str and x for x in runtime["command"]), "missing invocation")
    binding(root, runtime["capture_tool"])
    frame_result = compare_frames(native, read_index(binding(root, m["frames"])), root)
    exact_files(native.pcm, binding(root, m["pcm"]), PCM_BYTES)
    for key, expected in native.states.items():
        exact_files(expected, binding(root, m["state"][key]))
    for item in m["observations"].values():
        p = binding(root, item)
        need(p.stat().st_size > 0, "empty observation evidence")
    return dict(frame_result, identity=identity, pcm_bytes=PCM_BYTES,
                runtime_evidence_authenticated=False, production_accepted=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, default=CHECKOUT)
    parser.add_argument("--data-root", type=Path, default=DATA)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("native")
    for command in ("probe", "shaders", "identity", "full-run"):
        sub.add_parser(command).add_argument("path", type=Path)
    pcm = sub.add_parser("pcm"); pcm.add_argument("path", type=Path)
    pcm.add_argument("--kind", required=True, choices=("standalone-rust-diagnostic", "hybrid-source-oracle-diagnostic"))
    frames = sub.add_parser("frames"); frames.add_argument("path", type=Path)
    frames.add_argument("--payload-root", type=Path, required=True)
    args = parser.parse_args(argv)
    result = dict(operation=args.operation, reference_accepted=True, production_accepted=False)
    try:
        if args.operation == "identity":
            detail = pe_identity(args.path)
        else:
            native = Native(args.capture_root, args.data_root)
            if args.operation == "native":
                detail = compare_frames(native, native.frames, native.directory)
                vectors = b"".join(struct.pack("<5I", *r) for r in native.times())
                detail.update(native_time_vector_sha256=hashlib.sha256(vectors).hexdigest(), native_states=len(native.states), pcm_bytes=PCM_BYTES)
            elif args.operation == "pcm":
                detail = {"pcm_bytes": exact_files(native.pcm, args.path, PCM_BYTES), "candidate_kind": args.kind}
            elif args.operation == "probe":
                detail = compare_probe(native, args.path, native.times())
            elif args.operation == "shaders":
                detail = compare_shaders(native, args.path)
            elif args.operation == "frames":
                detail = compare_frames(native, read_index(args.path), args.payload_root)
            else:
                detail = full_run(native, args.path)
        result.update(status="OFFLINE_CONFORMANCE_ONLY", **detail)
    except (ValueError, OSError, KeyError, TypeError, struct.error, zstandard.ZstdError, ref.InvalidCapture) as exc:
        result.update(status="FAIL", reason=str(exc))
    print(json.dumps(result, sort_keys=True))
    return int(result["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
