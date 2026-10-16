#!/usr/bin/env python3
"""Build D7 diagnostics from preserved B commands without rebuilding old outputs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    temporary = Path('/tmp/opencode/eidolon/T2/build-tmp')
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ['TMPDIR'] = str(temporary)
    original_path = Path('artifacts/reference/proxy-b-g1-20261016.json')
    original = json.loads(original_path.read_text())['build']
    old = Path(original['build_directory'])
    for path, digest in original['sources'].items():
        assert sha(path) == digest, path
    for path, digest in original['outputs'].items():
        assert sha(old / path) == digest, path
    compiler = subprocess.check_output(['i686-w64-mingw32-gcc', '--version'], text=True).splitlines()[0]
    assert compiler == original['compiler']
    for backend in original['backends'].values():
        assert sha(backend['path']) == backend['sha256']
    sources = {str(p): sha(p) for p in sorted(Path('tools/capture/proxy-b-diagnostic').glob('*')) if p.is_file()}
    identity = dict(sources=sources, original_manifest_sha256=sha(original_path), compiler=compiler,
                    flags=original['flags'], original_build_id=original['build_id'], backends=original['backends'])
    build_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    out = Path(os.environ['EIDOLON_ROOT']) / '.tools/capture/B-diagnostic' / build_id
    if (out / 'build.json').exists():
        saved = json.loads((out / 'build.json').read_text())
        for path, digest in saved['outputs'].items():
            assert sha(out / path) == digest, path
        print(out)
        return
    out.mkdir(parents=True, exist_ok=False)
    for path in original['outputs']:
        if not path.endswith(('.dll', '.exe')):
            target = out / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(old / path, target)
    commands = []
    for command in original['commands']:
        command = [arg.replace(str(old), str(out)) for arg in command]
        command = ['tools/capture/proxy-b-diagnostic/core.c' if arg == 'tools/capture/proxy-b/core.c' else arg for arg in command]
        subprocess.run(command, check=True)
        commands.append(command)
    for path in dict(original['sources'], **sources):
        target = out / 'source-snapshot' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    manifest = dict(identity, build_id=build_id, build_directory=str(out), commands=commands,
                    original_sources=original['sources'], static_checks=original['static_checks'],
                    outputs={str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*')) if p.is_file()})
    (out / 'build.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(out)


if __name__ == '__main__':
    main()
