#!/usr/bin/env python3
"""Read-only integrity check of the published build bundle; no runtime acceptance claim."""
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    pointer = json.loads((ROOT / 'artifacts/rust/engine/candidate.json').read_bytes())
    directory = Path(pointer['directory'])
    raw = (directory / 'candidate.json').read_bytes()
    assert sha(raw) == pointer['manifest_sha256']
    manifest = json.loads(raw)
    assert manifest['source_commit'] == pointer['source_commit']
    assert manifest['executable_sha256'] == pointer['executable_sha256']
    assert manifest['target_executed'] is False and manifest['production_accepted'] is False
    for name, item in manifest['files'].items():
        assert item['path'] == name and Path(name).name == name
        path = directory / name
        assert not path.is_symlink()
        data = path.read_bytes()
        assert len(data) == item['bytes'] and sha(data) == item['sha256'], name
    inventory = json.loads((directory / 'source-inventory.json').read_bytes())
    with tarfile.open(directory / 'source.tar') as archive:
        members = archive.getmembers()
        assert len(members) == len(inventory)
        assert {entry.name for entry in members} == set(inventory)
        for entry in members:
            assert entry.isfile()
            data = archive.extractfile(entry).read()
            assert len(data) == inventory[entry.name]['bytes']
            assert sha(data) == inventory[entry.name]['sha256']
    build = json.loads((directory / 'build.json').read_bytes())
    audio = json.loads((directory / 'audio-integration.json').read_bytes())
    feedback = json.loads((directory / 'native-feedback.json').read_bytes())
    assert audio['build_manifest_sha256'] == sha((directory / 'build.json').read_bytes())
    assert build['runtime_candidate']['sha256'] == audio['production_pe_sha256'] == pointer['executable_sha256']
    assert build['host_probe_sha256'] == audio['host_probe_sha256'] == feedback['host_probe_sha256']
    assert audio['equal'] and audio['bytes'] == 159716352
    print(json.dumps({'status': 'CANDIDATE_BUNDLE_INTEGRITY_VERIFIED', 'sha256': pointer['executable_sha256'],
                      'source_files': len(inventory), 'target_executed': False, 'production_accepted': False}))


if __name__ == '__main__':
    main()
