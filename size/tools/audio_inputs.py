"""Repository-owned fixed audio inputs and checked generator output."""
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
CRATE = ROOT / 'size/crate'
MODE_WORDS = {3: 2, 5: 1, 6: 1, 7: 1, 9: 1, 22: 1, 25: 1, 29: 1, 30: 1,
              32: 1, 33: 1, 40: 17, 42: 1, 43: 1, 49: 1, 51: 1, 52: 1, 57: 1}


def array(path, name):
    source = path.read_text()
    match = re.search(r'pub (?:static|const) ' + name + r':[^=]+ = &?\[(.*?)\];', source, re.S)
    if match is None:
        raise ValueError(f'{path}: missing {name}')
    return [int(v.strip()) for v in match.group(1).split(',') if v.strip()]


def patch_words():
    return array(CRATE / 'src/audio/data.rs', 'PATCH')


def records(patch):
    """Validate record boundaries and every edge before doing any static walk."""
    out, at = [], 0
    while at < 3328:
        out.append(at)
        refs = (patch[at] >> 8) & 127
        assert refs <= 16, 'too many graph inputs'
        at += 1 + refs + MODE_WORDS.get(patch[at] & 127, 0)
    assert at == 3328 and len(patch) >= 3836
    targets = set(out) | set(range(3328, 3728, 2)) | set(range(3728, 3836, 4))
    for at in out:
        n = (patch[at] >> 8) & 127
        assert all(ref in targets for ref in patch[at + 1:at + 1 + n]), 'invalid graph edge'
    # These offsets are addressed arithmetically by voice::eidolon_note.
    assert patch[0] & 127 == 0
    assert all(r in out and patch[r] & 127 == 1 for r in range(3, 51, 3))
    at = 51
    for _ in range(16):
        assert at in out and patch[at] & 127 == 2
        at += 1 + ((patch[at] >> 8) & 127)
    return out


def emit(path, text):
    parser = argparse.ArgumentParser(description='Generate a fixed audio table, or check it without writing.')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        if not path.exists() or path.read_bytes() != text.encode():
            raise SystemExit(f'STALE {path.relative_to(ROOT)}; regenerate with {Path(sys.argv[0]).name}')
        print(f'PASS generated {path.relative_to(ROOT)}')
    else:
        path.write_text(text)
