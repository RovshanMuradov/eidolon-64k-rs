#!/usr/bin/env python3
"""Independent, exact integrity/comparison checks for the draft capture format."""

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import zstandard


SCHEMA = "eidolon-reference-draft-1"
ORIGINAL_SHA256 = "376b476c358a969da7d5d45c091355520453086ee8cd22625fdbb4fa3a9fd6be"
SAMPLE_BYTES = {"s16le": 2, "s24le": 3, "s32le": 4, "f32le": 4, "f64le": 8}
CHUNK = 1024 * 1024


class InvalidCapture(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidCapture(message)


def fields(value, required, optional=()):
    require(isinstance(value, dict), "expected an object")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    require(not missing and not extra,
            f"invalid fields: missing={sorted(missing)}, extra={sorted(extra)}")


def integer(value, label, minimum=0):
    require(type(value) is int and value >= minimum,
            f"{label}: expected integer >= {minimum}")
    return value


def text(value, label):
    require(isinstance(value, str) and bool(value.strip()), f"{label}: expected nonempty text")


def digest(value, label):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
            f"{label}: expected lowercase SHA-256")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def invalid_constant(value):
    raise InvalidCapture(f"non-finite JSON number: {value}")


def finite_float(value):
    number = float(value)
    require(math.isfinite(number), f"non-finite JSON number: {value}")
    return number


def load_json(data):
    return json.loads(data, object_pairs_hook=unique_object, parse_constant=invalid_constant,
                      parse_float=finite_float)


def payload_path(root, relative):
    text(relative, "payload path")
    require("\\" not in relative and all(part not in ("", ".", "..")
                                         for part in relative.split("/")),
            f"payload path must be root-relative: {relative}")
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()), f"payload path escapes root: {relative}")
    require(path.is_file(), f"missing payload: {relative}")
    return path


def hash_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_raw(path, size, expected_hash):
    decoder = zstandard.ZstdDecompressor().decompressobj()
    checksum = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            require(not decoder.eof, f"raw frame has trailing compressed data: {path.name}")
            raw = decoder.decompress(chunk)
            require(not decoder.unused_data, f"raw frame has trailing compressed data: {path.name}")
            total += len(raw)
            require(total <= size, f"raw frame size exceeds layout: {path.name}")
            checksum.update(raw)
    require(decoder.eof, f"truncated Zstandard frame: {path.name}")
    require(total == size, f"raw frame size does not match layout: {path.name}")
    require(checksum.hexdigest() == expected_hash, f"raw frame SHA-256 mismatch: {path.name}")


@dataclass
class Run:
    manifest_path: Path
    manifest: dict
    frames: list
    audio_path: Path


def load_run(manifest_path, data_root=None):
    manifest_path = Path(manifest_path).resolve()
    root = Path(data_root).resolve() if data_root is not None else manifest_path.parent
    m = load_json(manifest_path.read_text(encoding="utf-8"))
    fields(m, ("schema", "run_id", "source", "capture", "conditions", "video", "audio",
               "scenes", "termination", "completion"))
    require(m["schema"] == SCHEMA, "unsupported reference schema")
    text(m["run_id"], "run_id")

    source = m["source"]
    fields(source, ("kind", "exe_sha256", "inputs"))
    require(source["kind"] in ("original", "synthetic"), "invalid source kind")
    digest(source["exe_sha256"], "exe_sha256")
    if source["kind"] == "original":
        require(source["exe_sha256"] == ORIGINAL_SHA256, "original executable SHA-256 is not approved native EXE")
    require(isinstance(source["inputs"], dict), "source.inputs: expected name/hash object")
    for name, checksum in source["inputs"].items():
        text(name, "input name")
        digest(checksum, f"input {name}")

    capture = m["capture"]
    fields(capture, ("kind", "tool_sha256", "command"))
    expected_kind = "controlled-reference" if source["kind"] == "original" else "synthetic-reference"
    require(capture["kind"] == expected_kind, "capture kind is not a controlled/synthetic reference")
    digest(capture["tool_sha256"], "capture.tool_sha256")
    require(isinstance(capture["command"], list) and bool(capture["command"]), "missing capture command")
    for arg in capture["command"]:
        text(arg, "capture command argument")

    conditions = m["conditions"]
    fields(conditions, ("environment", "settings", "clock", "rng", "initial_state_sha256"))
    environment = conditions["environment"]
    fields(environment, ("os", "arch", "wine", "gpu", "driver", "graphics_api", "desktop"))
    for key in environment.keys() - {"desktop"}:
        text(environment[key], f"environment.{key}")
    require(environment["desktop"] == [1920, 1080], "desktop must be 1920x1080")
    require(isinstance(conditions["settings"], dict), "settings must be an object")
    fields(conditions["clock"], ("numerator", "denominator", "method"))
    integer(conditions["clock"]["numerator"], "clock numerator", 1)
    integer(conditions["clock"]["denominator"], "clock denominator", 1)
    require((conditions["clock"]["numerator"], conditions["clock"]["denominator"]) == (1, 60),
            "clock must use exact 1/60 s ticks")
    text(conditions["clock"]["method"], "clock method")
    fields(conditions["rng"], ("method", "initial_state_sha256"))
    text(conditions["rng"]["method"], "RNG method")
    digest(conditions["rng"]["initial_state_sha256"], "RNG initial state")
    digest(conditions["initial_state_sha256"], "initial state")

    video = m["video"]
    fields(video, ("width", "height", "row_stride", "pixel_format", "row_order", "color_space",
                   "frame_count", "index", "index_sha256", "storage"))
    width = integer(video["width"], "width", 1)
    height = integer(video["height"], "height", 1)
    integer(video["row_stride"], "row_stride", 1)
    require(video["pixel_format"] in ("rgba8", "bgra8"), "unsupported pixel format")
    require(video["row_stride"] == width * 4, "row stride must be width * 4")
    require(video["row_order"] in ("top-down", "bottom-up"), "unsupported row order")
    text(video["color_space"], "color_space")
    count = integer(video["frame_count"], "frame_count", 1)
    require(video["storage"] in ("reference", "hashes"), "unsupported frame storage mode")
    digest(video["index_sha256"], "index_sha256")

    audio = m["audio"]
    fields(audio, ("path", "sha256", "sample_format", "sample_rate", "channels", "layout",
                   "sample_frames", "start_sample"))
    digest(audio["sha256"], "audio.sha256")
    require(isinstance(audio["sample_format"], str) and audio["sample_format"] in SAMPLE_BYTES,
            "unsupported PCM format")
    rate = integer(audio["sample_rate"], "sample_rate", 1)
    channels = audio["channels"]
    require(isinstance(channels, list) and bool(channels), "missing audio channels")
    for channel in channels:
        text(channel, "audio channel")
    require(len(set(channels)) == len(channels), "duplicate audio channel")
    require(audio["layout"] == "interleaved", "PCM must be interleaved")
    samples = integer(audio["sample_frames"], "sample_frames", 1)
    integer(audio["start_sample"], "start_sample")
    require(audio["start_sample"] == 0, "PCM start sample must be zero")

    term = m["termination"]
    fields(term, ("reason", "end_tick", "audio_position", "audio_position_num", "audio_position_den",
                  "exit_code", "timeline_end_tick", "evidence"))
    require(term["reason"] in ("natural_exit", "timeline_end"), "termination is not a successful end")
    integer(term["end_tick"], "termination end_tick", 1)
    require(term["end_tick"] == count, "end_tick must equal frame_count")
    integer(term["audio_position"], "termination audio_position")
    require(term["audio_position"] == count * rate // 60, "termination audio position is shifted")
    integer(term["audio_position_num"], "termination audio_position_num")
    integer(term["audio_position_den"], "termination audio_position_den", 1)
    require((term["audio_position_num"], term["audio_position_den"]) == (count * rate, 60),
            "termination rational audio position is shifted")
    require(samples >= term["audio_position"], "PCM does not cover the controlled timeline")
    text(term["evidence"], "termination evidence")
    if term["reason"] == "natural_exit":
        integer(term["exit_code"], "exit_code")
        require(term["exit_code"] == 0 and term["timeline_end_tick"] is None,
                "natural exit requires exit_code=0 and no timeline cutoff")
    else:
        integer(term["timeline_end_tick"], "timeline_end_tick", 1)
        require(term["timeline_end_tick"] == count and term["exit_code"] is None,
                "timeline end requires matching cutoff and null exit_code")

    completion = m["completion"]
    fields(completion, ("finalized", "frames_observed", "frames_hashed", "audio_sample_frames",
                        "dropped_frames", "dropped_audio_sample_frames", "errors"))
    require(completion["finalized"] is True, "capture not finalized")
    for key, expected in (("frames_observed", count), ("frames_hashed", count),
                          ("audio_sample_frames", samples), ("dropped_frames", 0),
                          ("dropped_audio_sample_frames", 0)):
        integer(completion[key], key)
        require(completion[key] == expected, f"completion {key} does not match required count {expected}")
    require(completion["errors"] == [], "capture reports errors")

    scenes = m["scenes"]
    require(isinstance(scenes, list) and bool(scenes), "missing scene partition")
    anchors = set(range(0, count, 60))
    next_frame = 0
    scene_ids = set()
    for scene in scenes:
        fields(scene, ("id", "first", "last"))
        text(scene["id"], "scene id")
        require(scene["id"] not in scene_ids, "duplicate scene id")
        scene_ids.add(scene["id"])
        integer(scene["first"], "scene first")
        integer(scene["last"], "scene last")
        require(scene["first"] == next_frame and scene["first"] <= scene["last"] < count,
                "scene partition has a gap, overlap, or invalid boundary")
        anchors.update((scene["first"], scene["last"]))
        next_frame = scene["last"] + 1
    require(next_frame == count, "scene partition does not cover all frames")

    index = payload_path(manifest_path.parent, video["index"])
    index_hash = hashlib.sha256()
    frames = []
    stored = set()
    with index.open("rb") as stream:
        for n, line in enumerate(stream):
            require(n < count, "frame index has extra records")
            index_hash.update(line)
            record = load_json(line.decode("utf-8"))
            fields(record, ("n", "tick", "clock_tick", "audio_position", "audio_position_num",
                            "audio_position_den", "sha256"), ("raw_zst",))
            for key, expected in (("n", n), ("tick", n), ("clock_tick", n),
                                  ("audio_position", n * rate // 60),
                                  ("audio_position_num", n * rate), ("audio_position_den", 60)):
                integer(record[key], f"frame {n} {key}")
                require(record[key] == expected, f"frame {n} {key}: expected {expected}, got {record[key]}")
            digest(record["sha256"], f"frame {n} sha256")
            if "raw_zst" in record:
                require(video["storage"] == "reference", "hash-only run contains raw frames")
                raw = payload_path(root, record["raw_zst"])
                verify_raw(raw, height * video["row_stride"], record["sha256"])
                stored.add(n)
            frames.append(record)
    require(len(frames) == count, f"missing frame records: expected {count}, got {len(frames)}")
    require(index_hash.hexdigest() == video["index_sha256"], "frame index SHA-256 mismatch")
    if video["storage"] == "reference":
        require(anchors <= stored, f"missing required raw frames: {sorted(anchors - stored)}")

    audio_path = payload_path(root, audio["path"])
    expected_bytes = samples * len(channels) * SAMPLE_BYTES[audio["sample_format"]]
    require(audio_path.stat().st_size == expected_bytes, "PCM byte length does not match sample count/layout")
    require(hash_file(audio_path) == audio["sha256"], "PCM SHA-256 mismatch")
    return Run(manifest_path, m, frames, audio_path)


def first_byte_difference(left, right):
    offset = 0
    with left.open("rb") as a, right.open("rb") as b:
        while True:
            x, y = a.read(CHUNK), b.read(CHUNK)
            if x != y:
                for n, (u, v) in enumerate(zip(x, y)):
                    if u != v:
                        return offset + n
                return offset + min(len(x), len(y))
            if not x:
                return None
            offset += len(x)


def without(value, *keys):
    return {key: item for key, item in value.items() if key not in keys}


def exact_equal(left, right):
    # Python's ordinary equality conflates True, 1 and 1.0 in free-form settings.
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def compare_runs(reference, candidate):
    a, b = reference.manifest, candidate.manifest
    reasons = []
    if reference.manifest_path == candidate.manifest_path or a["run_id"] == b["run_id"]:
        reasons.append("comparison requires distinct run IDs and manifests")
    if a["video"]["storage"] != "reference":
        reasons.append("left run must contain the sparse reference raw frames")
    for key in ("source", "conditions", "scenes", "termination"):
        if not exact_equal(a[key], b[key]):
            reasons.append(f"{key} mismatch")
    if without(a["capture"], "command") != without(b["capture"], "command"):
        reasons.append("capture tool SHA-256 mismatch")
    if without(a["video"], "index", "index_sha256", "storage") != without(b["video"], "index", "index_sha256", "storage"):
        reasons.append("video layout/count mismatch")
    if without(a["audio"], "path", "sha256") != without(b["audio"], "path", "sha256"):
        reasons.append("audio layout/count mismatch")
    changed = [n for n, (x, y) in enumerate(zip(reference.frames, candidate.frames))
               if without(x, "raw_zst") != without(y, "raw_zst")]
    if changed:
        reasons.append(f"frame content mismatch: {len(changed)} frame(s); first={changed[0]}")
    offset = first_byte_difference(reference.audio_path, candidate.audio_path)
    if offset is not None:
        reasons.append(f"PCM byte mismatch at offset {offset}")
    return reasons


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    validate = subparsers.add_parser("validate", help="check one capture's integrity/completeness")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--data-root", type=Path)
    compare = subparsers.add_parser("compare", help="compare two separately captured runs exactly")
    compare.add_argument("reference", type=Path)
    compare.add_argument("candidate", type=Path)
    compare.add_argument("--reference-data", type=Path)
    compare.add_argument("--candidate-data", type=Path)
    args = parser.parse_args(argv)
    targets = [("capture", args.manifest, args.data_root)] if args.operation == "validate" else [
        ("reference", args.reference, args.reference_data),
        ("candidate", args.candidate, args.candidate_data),
    ]
    runs, reasons = [], []
    for label, path, root in targets:
        try:
            runs.append(load_run(path, root))
        except (OSError, ValueError, UnicodeError, zstandard.ZstdError) as error:
            reasons.append(f"{label}: {error}")
    if not reasons and args.operation == "compare":
        reasons.extend(compare_runs(*runs))
    kinds = sorted({run.manifest["source"]["kind"] for run in runs})
    result = {"status": "FAIL" if reasons else "PASS", "schema": SCHEMA,
              "operation": args.operation, "source_kinds": kinds, "draft": True,
              "reasons": reasons}
    print(json.dumps(result, sort_keys=True))
    return 1 if reasons else 0


if __name__ == "__main__":
    sys.exit(main())
