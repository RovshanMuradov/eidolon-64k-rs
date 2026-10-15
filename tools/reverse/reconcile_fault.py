#!/usr/bin/env python3
"""Recheck the packed PE and preserved T2 fault trace without running the EXE."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct

import zstandard


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked_bytes(path, digest):
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == digest, f"Hash mismatch: {path}")
    return data


def inspect_pe(data, fault):
    u16 = lambda offset: struct.unpack_from("<H", data, offset)[0]
    u32 = lambda offset: struct.unpack_from("<I", data, offset)[0]
    pe = u32(0x3C)
    require(data[:2] == b"MZ" and data[pe:pe + 4] == b"PE\0\0", "Invalid PE")
    optional = pe + 24
    require(u16(pe + 4) == 0x14C and u16(optional) == 0x10B, "Expected PE32/i386")
    base = u32(optional + 28)
    sections = []
    table = optional + u16(pe + 20)
    for i in range(u16(pe + 6)):
        offset = table + 40 * i
        virtual_size, rva, raw_size, raw = struct.unpack_from("<IIII", data, offset + 8)
        sections.append((base + rva, virtual_size, raw, raw_size))

    def file_offset(va):
        rva = va - base
        if 0 <= rva < min(u32(optional + 60), len(data)):
            return rva
        for start, _, raw, raw_size in sections:
            if start <= va < start + raw_size:
                offset = raw + va - start
                require(offset < len(data), "Truncated section")
                return offset
        return None

    def expect(va, expected):
        offset = file_offset(va)
        require(offset is not None, f"Missing wrapper bytes at {va:#x}")
        require(data[offset:offset + len(expected)] == expected, f"Changed bytes at {va:#x}")

    expect(0x3EE792, bytes.fromhex("b8 2d 94 3f 00"))
    expect(0x3EE79E, bytes.fromhex("c7 45 10 da 2b d8 0c"))
    expect(0x3EE92C, bytes.fromhex(
        "0f 77 58 68 00 00 40 00 68 00 00 3e 00 50 be 7a 97 3f 00 bb ec ec 3e 00 c3"
    ))
    destination = u32(file_offset(0x3EE792) + 1)
    span = u32(file_offset(0x3EE79E) + 3)
    return {
        "image_base": hex(base),
        "entry": hex(base + u32(optional + 16)),
        "section_ranges_half_open": [
            {"virtual": [hex(start), hex(start + virtual_size)],
             "file_backed_va": [hex(start), hex(start + raw_size)],
             "file": [hex(raw), hex(raw + raw_size)]}
            for start, virtual_size, raw, raw_size in sections
        ],
        "fault_va": hex(fault),
        "fault_rva": hex(fault - base),
        "fault_file_offset": file_offset(fault),
        "decoder_destination_span_half_open": [hex(destination), hex(destination + span)],
        "fault_in_decoder_span": destination <= fault < destination + span,
        "fault_offset_from_decoder_destination": hex(fault - destination),
        "completion_bytes_match": True,
        "fault_instruction_and_pointer_producer": "unknown: unpacked bytes required",
    }


def inspect_trace(trace, observation):
    events = []
    for number, line in enumerate(trace.decode().splitlines(), 1):
        match = re.match(r"(\d+\.\d+):([0-9a-f]+):([0-9a-f]+):(.*)", line)
        if match:
            time, pid, tid, text = match.groups()
            if pid == observation["wine_process_id"]:
                events.append((number, float(time), tid, text))
    fault_va = int(observation["instruction_address"], 16)
    faults = [event for event in events if re.search(
        rf"dispatch_exception code=c0000005 .*addr=0*{fault_va:x}$", event[3], re.I
    )]
    require(bool(faults), "Missing access violation")
    fault = faults[0]
    swaps = [event for event in events if event[0] < fault[0]
             and event[3].startswith("trace:wgl:win32u_wglSwapBuffers ")]
    require(bool(swaps), "Missing pre-fault swaps")
    require(len(swaps) == observation["wgl_swap_calls"], "Swap count differs from manifest")
    require(fault[2] == observation["faulting_wine_thread_id"], "Fault thread differs")
    context = [event for event in events
               if fault[0] <= event[0] < fault[0] + 27 and event[2] == fault[2]]
    registers = {}
    for _, _, _, text in context:
        for name, value in re.findall(r"\b(e[abcd]x|e[sd]i|e[bs]p|eip|mxcsr)=([0-9a-f]+)", text):
            registers.setdefault(name, int(value, 16))
    require(registers.get("eip") == fault_va, "Missing x86 context")
    reads = [int(match.group(1), 16) for _, _, _, text in context
             if (match := re.search(r"info\[1\]=([0-9a-fA-F]+)", text))]
    require(bool(reads) and set(reads) == {int(observation["read_address"], 16)},
            "Read address differs from manifest")
    mxcsr = registers["mxcsr"]
    return {
        "first_fault_line": fault[0],
        "fault_thread": fault[2],
        "read_address": hex(reads[0]),
        "registers": {name: hex(value) for name, value in registers.items()},
        "mxcsr": {"ftz": bool(mxcsr & 0x8000), "daz": bool(mxcsr & 0x40),
                  "rounding_control": (mxcsr >> 13) & 3,
                  "all_exceptions_masked": (mxcsr & 0x1F80) == 0x1F80,
                  "precision_status": bool(mxcsr & 0x20)},
        "pre_fault_swaps": len(swaps),
        "swap_threads": sorted({event[2] for event in swaps}),
        "first_swap_line": swaps[0][0],
        "last_swap_line": swaps[-1][0],
        "first_to_last_swap_seconds": round(swaps[-1][1] - swaps[0][1], 3),
        "first_swap_to_fault_seconds": round(fault[1] - swaps[0][1], 3),
        "last_swap_to_fault_seconds": round(fault[1] - swaps[-1][1], 3),
        "application_clock_source": "unknown: Wine timestamps are observer time",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--capture-root", type=Path,
                        default=Path(os.environ["EIDOLON_ROOT"]) / ".worktrees/T2")
    args = parser.parse_args()
    static = json.loads(Path("reports/evidence/reverse/manifest.json").read_text())
    native = static["inputs"]["native"]
    data = checked_bytes(args.exe or Path(native["copy_path"]), native["sha256"])
    capture = json.loads((args.capture_root / "artifacts/reference/wine-smoke-manifest.json").read_text())
    require(capture["input"]["exe_sha256"] == native["sha256"], "Different captured EXE")
    evidence = capture["evidence"]
    packed = checked_bytes(args.capture_root / evidence["path"], evidence["compressed_sha256"])
    trace = zstandard.ZstdDecompressor().decompress(packed)
    require(hashlib.sha256(trace).hexdigest() == evidence["uncompressed_sha256"], "Trace hash differs")
    result = {
        "pe": inspect_pe(data, int(capture["observation"]["instruction_address"], 16)),
        "preserved_trace": inspect_trace(trace, capture["observation"]),
        "coverage": "Packed PE and preserved failure only; no fresh runtime verification",
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
