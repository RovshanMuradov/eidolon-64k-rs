"""Lossless ordered runtime stream; bounded-memory readers and closed-file packing."""
import hashlib
import io
import json
import os
from pathlib import Path

import zstandard


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def events(path):
    path = Path(path)
    if path.suffix == '.zst':
        with path.open('rb') as source, zstandard.ZstdDecompressor().stream_reader(source) as decoded:
            with io.TextIOWrapper(decoded, encoding='utf-8') as lines:
                for line in lines:
                    yield json.loads(line)
    else:
        with path.open() as lines:
            for line in lines:
                yield json.loads(line)


def pack(path):
    """Only discard this new closed log after a complete decoded byte/hash check."""
    path = Path(path)
    digest, size = sha(path), path.stat().st_size
    packed = path.with_suffix(path.suffix + '.zst')
    with path.open('rb') as source, packed.open('xb') as destination:
        zstandard.ZstdCompressor(level=3).copy_stream(source, destination)
        destination.flush()
        os.fsync(destination.fileno())
    decoded_hash, decoded_size = hashlib.sha256(), 0
    with packed.open('rb') as source, zstandard.ZstdDecompressor().stream_reader(source) as decoded:
        while block := decoded.read(1048576):
            decoded_hash.update(block)
            decoded_size += len(block)
    assert (decoded_hash.hexdigest(), decoded_size) == (digest, size)
    descriptor = dict(format='zstandard-single-frame-jsonl', path=packed.name,
                      sha256=sha(packed), decoded_sha256=digest, decoded_bytes=size)
    path.unlink()
    return descriptor
