#!/usr/bin/env python3
"""Acquire/verify the pinned Microsoft GM bank using file operations only."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import urllib.request


MANIFEST = Path(__file__).resolve().parents[3] / "artifacts/reference/dependencies/gm-dls.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_blob(blob, entry):
    require(len(blob) == entry["bytes"], f"{entry['filename']}: size mismatch")
    require(hashlib.sha256(blob).hexdigest() == entry["sha256"],
            f"{entry['filename']}: SHA-256 mismatch")


def chunks(blob, start, end):
    result = []
    while start < end:
        require(start + 8 <= end, "truncated RIFF chunk header")
        tag, size = struct.unpack_from("<4sI", blob, start)
        payload = start + 8
        next_chunk = payload + size + (size & 1)
        require(next_chunk <= end, "RIFF chunk exceeds its parent")
        children = []
        kind = None
        if tag == b"LIST":
            require(size >= 4, "short LIST")
            kind = blob[payload:payload + 4]
            children = chunks(blob, payload + 4, payload + size)
        result.append((tag, start, payload, size, kind, children))
        start = next_chunk
    return result


def one(items, tag, kind=None):
    matches = [item for item in items if item[0] == tag and item[4] == kind]
    require(len(matches) == 1, f"expected one {tag!r}/{kind!r}")
    return matches[0]


def payload(blob, item):
    return blob[item[2]:item[2] + item[3]]


def info(blob, items):
    return {item[0].decode("ascii"): payload(blob, item).rstrip(b"\0").decode("ascii")
            for item in one(items, b"LIST", b"INFO")[5]}


def inspect_bank(blob):
    require(len(blob) >= 12 and blob[:4] == b"RIFF" and blob[8:12] == b"DLS ",
            "expected RIFF/DLS bank")
    require(struct.unpack_from("<I", blob, 4)[0] + 8 == len(blob), "RIFF size mismatch")
    root = chunks(blob, 12, len(blob))
    count = struct.unpack("<I", payload(blob, one(root, b"colh")))[0]
    instruments = one(root, b"LIST", b"lins")[5]
    require(len(instruments) == count and all(x[4] == b"ins " for x in instruments),
            "instrument count mismatch")
    ms, ls = struct.unpack("<II", payload(blob, one(root, b"vers")))
    version = f"{ms >> 16}.{ms & 65535}.{ls >> 16}.{ls & 65535}"
    pool = one(root, b"LIST", b"wvpl")
    waves = pool[5]
    table = payload(blob, one(root, b"ptbl"))
    header_size, cues = struct.unpack_from("<II", table)
    require(header_size == 8 and len(table) == 8 + 4 * cues and cues == len(waves),
            "pool table size/count mismatch")
    offsets = list(struct.unpack_from(f"<{cues}I", table, 8))
    require(offsets == [wave[1] - (pool[2] + 4) for wave in waves],
            "pool table does not match physical wave ordering")
    formats = Counter()
    data_offsets = []
    selected = None
    for index, wave in enumerate(waves):
        require(wave[0] == b"LIST" and wave[4] == b"wave", "unexpected wave container")
        fmt = payload(blob, one(wave[5], b"fmt "))
        require(len(fmt) >= 16, "short PCM format")
        tag, channels, rate, byte_rate, align, bits = struct.unpack_from("<HHIIHH", fmt)
        require((tag, channels, align, bits) == (1, 1, 2, 16) and byte_rate == rate * align,
                "expected mono PCM16")
        data = one(wave[5], b"data")
        require(data[3] > 0 and data[3] % align == 0, "empty or unaligned PCM")
        data_offsets.append(data[1])
        formats[rate] += 1
        if index == 127:
            selected = {
                "physical_wave_index_zero_based": index,
                "name": info(blob, wave[5])["INAM"],
                "data_chunk_offset": data[1],
                "pcm_offset": data[2],
                "pcm_bytes": data[3],
                "pcm_frames": data[3] // align,
                "sample_rate_hz": rate,
                "pcm_sha256": hashlib.sha256(payload(blob, data)).hexdigest(),
            }
    # The demo scans literal data tags rather than resolving GM program numbers.
    raw_offsets = []
    cursor = 0
    while (cursor := blob.find(b"data", cursor)) != -1:
        raw_offsets.append(cursor)
        cursor += 4
    require(raw_offsets == data_offsets, "literal data scan differs from wave order")
    require(selected is not None, "sample 127 missing")
    return {
        "riff_type": "DLS ",
        "version": version,
        "info": info(blob, root),
        "instrument_count": count,
        "wave_count": len(waves),
        "pool_cues": cues,
        "pcm_format": "signed little-endian 16-bit mono",
        "sample_rate_hz_counts": {str(k): v for k, v in sorted(formats.items())},
        "literal_data_scan_matches_wave_order": True,
        "sample_127": selected,
    }


def extract(archive, member):
    return subprocess.run(["bsdtar", "-xOf", str(archive), member],
                          check=True, stdout=subprocess.PIPE).stdout


def verify_signature(blob, source_dir, expected):
    """Check this hash-pinned PE's digest/signature; NOT certificate trust/time."""
    pe = struct.unpack_from("<I", blob, 60)[0]
    opt = pe + 24
    require(blob[pe:pe + 4] == b"PE\0\0" and struct.unpack_from("<H", blob, opt)[0] == 0x10B,
            "expected PE32 archive")
    security = opt + 96 + 4 * 8
    certificate, certificate_size = struct.unpack_from("<II", blob, security)
    require(certificate + certificate_size == len(blob), "unexpected certificate layout")
    section_count = struct.unpack_from("<H", blob, pe + 6)[0]
    optional_size = struct.unpack_from("<H", blob, pe + 20)[0]
    cursor = struct.unpack_from("<I", blob, opt + 60)[0]
    for index in range(section_count):
        size, offset = struct.unpack_from("<II", blob, opt + optional_size + 40 * index + 16)
        require(offset == cursor, "noncontiguous sections need a different PE digest procedure")
        cursor += size
    require(cursor == certificate, "unexpected PE overlay")
    digest = hashlib.sha1(blob[:opt + 64] + blob[opt + 68:security] +
                          blob[security + 8:certificate]).digest()
    require(digest.hex() == expected["authenticode_sha1"], "PE Authenticode digest mismatch")
    length, revision, kind = struct.unpack_from("<IHH", blob, certificate)
    require((revision, kind) == (0x200, 2) and 8 < length <= certificate_size,
            "unexpected WIN_CERTIFICATE")
    signature = source_dir / "redist-signature.der"
    signature.write_bytes(blob[certificate + 8:certificate + length])
    signer = source_dir / "redist-signer.pem"
    signed = subprocess.run([
        "openssl", "smime", "-verify", "-inform", "DER", "-in", str(signature),
        "-noverify", "-binary", "-signer", str(signer),
    ], check=True, stdout=subprocess.PIPE).stdout
    sha1_digest_info = bytes.fromhex("3021300906052b0e03021a05000414") + digest
    require(signed.endswith(sha1_digest_info), "signed content does not bind the PE digest")
    fingerprint = subprocess.run([
        "openssl", "x509", "-in", str(signer), "-noout", "-fingerprint", "-sha256",
    ], check=True, stdout=subprocess.PIPE, text=True).stdout.strip().split("=", 1)[1]
    require(fingerprint.replace(":", "").lower() == expected["signer_certificate_sha256"],
            "signer certificate mismatch")


def store(path, blob):
    if path.exists():
        require(path.read_bytes() == blob, f"refusing to overwrite different file: {path}")
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", delete=False) as f:
        temporary = Path(f.name)
        f.write(blob)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def acquire(manifest, directory):
    source_dir = directory / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    source = manifest["source"]
    archive = source_dir / source["filename"]
    if archive.exists():
        blob = archive.read_bytes()
    else:
        with urllib.request.urlopen(source["archive_url"], timeout=240) as response:
            require(response.url.startswith("https://web.archive.org/"), "unexpected download origin")
            blob = response.read(source["bytes"] + 1)
    check_blob(blob, source)
    store(archive, blob)
    verify_signature(blob, source_dir, manifest["signature_check"])
    cabinet = source_dir / manifest["cabinet"]["filename"]
    cab_blob = extract(archive, cabinet.name)
    check_blob(cab_blob, manifest["cabinet"])
    store(cabinet, cab_blob)
    installer = extract(cabinet, "directx.inf")
    require(b"[GM98_Drivers]\r\ngm.dls,gm16.dls\r\n" in installer,
            "missing vendor gm16.dls to gm.dls mapping")
    store(source_dir / "directx.inf", installer)
    store(source_dir / "gmreadme.txt", extract(cabinet, "gmreadme.txt"))
    bank = extract(cabinet, manifest["bank"]["archive_member"])
    check_blob(bank, manifest["bank"])
    require(inspect_bank(bank) == manifest["dls"], "DLS metadata mismatch")
    store(directory / manifest["bank"]["filename"], bank)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("acquire", "verify"))
    parser.add_argument("--bank", type=Path, help="verify a particular installed/copied bank")
    args = parser.parse_args()
    require("EIDOLON_DATA" in os.environ, "invoke through bash tools/run")
    require(args.action == "verify" or args.bank is None, "--bank is only for verify")
    manifest = json.loads(MANIFEST.read_text())
    directory = Path(os.environ["EIDOLON_DATA"]) / "reference/dependencies"
    if args.action == "acquire":
        acquire(manifest, directory)
    bank = args.bank if args.bank is not None else directory / manifest["bank"]["filename"]
    blob = bank.read_bytes()
    check_blob(blob, manifest["bank"])
    details = inspect_bank(blob)
    require(details == manifest["dls"], "DLS metadata mismatch")
    print(json.dumps({"status": "PASS", "bank": str(bank), "dls": details}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, struct.error, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
