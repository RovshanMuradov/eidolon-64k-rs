"""Frozen-layout invariants: crate portability, membership drift, stable identities."""
from copy import deepcopy
from fnmatch import fnmatchcase
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'size/crate/tools/rust'))
import coff
import layout


def object_with(entries):
    """Small valid COFF container, including long section names in its string table."""
    headers = bytearray()
    content = bytearray()
    strings = bytearray(b'\0' * 4)
    offset = 20 + 40 * len(entries)
    for name, data in entries:
        raw = name.encode()
        if len(raw) > 8:
            raw = f'/{len(strings)}'.encode()
            strings += name.encode() + b'\0'
        headers += struct.pack('<8sIIIIIIHHI', raw, 0, 0, len(data), offset + len(content), 0, 0, 0, 0, 0)
        content += data
    struct.pack_into('<I', strings, 0, len(strings))
    header = struct.pack('<HHIIIHH', 0x14c, len(entries), 0, offset + len(content), 0, 0, 0)
    return bytes(header + headers + content + strings)


class LayoutTests(unittest.TestCase):
    def test_explicit_migration_filters_stale_seed_and_adds_new_members(self):
        source = object_with([('.text$new', b'new'), ('.text$kept', b'kept'),
                              ('.text$dead', b'dead'), ('.rdata', b'new graphics')])
        seed = {'text': ['    *(.text$missing)', '    *(.text$kept)', '    *(.text$dead)'],
                'rdata': ['.rd$1234'], 'discarded': ['.text$dead']}
        manifest, changes = layout.migrate_order(seed, source)
        self.assertEqual(manifest['text'], ['.text$kept', '.text$new'])
        self.assertEqual(manifest['discarded'], ['.text$dead'])
        self.assertEqual(changes['removed'], ['.text$missing', '.rd$1234'])
        self.assertIn('.text$new', changes['added'])
        data, _ = coff.rename_anonymous_rdata(source)
        layout.validate(data, manifest)
        with self.assertRaisesRegex(ValueError, 'ambiguous seed pattern'):
            layout.migrate_order({'text': ['.text$*'], 'rdata': []}, source)

    def test_candidate_layout_overrides_require_a_pair_and_candidate_mode(self):
        for args in [('--candidate', '--link-order', 'test.ld'),
                     ('--candidate', '--layout-manifest', 'test.json'),
                     ('--link-order', 'test.ld', '--layout-manifest', 'test.json')]:
            result = subprocess.run([sys.executable, ROOT / 'size/build.py', *args],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('--link-order', result.stderr)
            self.assertIn('--layout-manifest', result.stderr)

    def test_real_symbols_with_different_length_crate_hashes_and_uppercase_backrefs(self):
        symbols = [
            '.text$_RNvMs2_NtCs3a47Jk7K1QY_5alloc7raw_vecNtB5_11RawVecInner10deallocateB7_',
            '.text$_RINvNtCsf0Nl4b2Crfk_4core3ptr9drop_glueINtNtB4_6option6OptionINtNtB4_6result6ResultINtNtCs3a47Jk7K1QY_5alloc3vec3VecfENtCsdS0cmLiCcKc_7eidolon12RuntimeErrorEEEB1U_',
            '.text$_RINvNtCsf0Nl4b2Crfk_4core3ptr9drop_glueINtNtCs3a47Jk7K1QY_5alloc5boxed3BoxNtNtNtCsdS0cmLiCcKc_7eidolon5audio7runtime7RuntimeEEB1g_',
        ]
        for name in symbols:
            pat = layout.pattern(name)
            changed = name.replace('Cs3a47Jk7K1QY_', 'CsZ_').replace('Csf0Nl4b2Crfk_', 'Cs_')
            changed = changed.replace('CsdS0cmLiCcKc_', 'Cs0123456789ABCD_')
            changed = changed.replace('B1U_', 'B2Z_').replace('B5_', 'BA_').replace('B1g_', 'BaZ_')
            self.assertTrue(fnmatchcase(changed, pat), (changed, pat))
            self.assertEqual(layout.pattern(changed), pat)
        self.assertIn('3BoxNtNtNt', layout.pattern(symbols[-1]))

    def test_anonymous_names_are_independent_of_object_order(self):
        entries = [('.rdata', b'first'), ('.rdata', b'second'), ('.text$x', b'code')]
        one, ids1 = coff.rename_anonymous_rdata(object_with(entries))
        two, ids2 = coff.rename_anonymous_rdata(object_with(entries[::-1]))
        self.assertEqual(ids1, ids2)
        self.assertEqual({s['content']: s['name'] for s in coff.sections(one)},
                         {s['content']: s['name'] for s in coff.sections(two)})

    def test_colliding_anonymous_identities_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'identity collision'):
            coff.rename_anonymous_rdata(object_with([('.rdata', b'same'), ('.rdata', b'same')]))

    def test_missing_extra_and_ambiguous_members_are_rejected(self):
        manifest = {'text': ['.text$a', '.text$b'], 'rdata': [], 'discarded': [], 'anonymous': {}}
        layout.validate(object_with([('.text$a', b'a'), ('.text$b', b'b')]), manifest)
        for entries in [[('.text$a', b'a')],
                        [('.text$a', b'a'), ('.text$b', b'b'), ('.text$c', b'c')]]:
            with self.assertRaisesRegex(ValueError, 'membership changed'):
                layout.validate(object_with(entries), manifest)
        ambiguous = deepcopy(manifest)
        ambiguous['text'] = ['.text$*', '.text$b']
        with self.assertRaisesRegex(ValueError, 'membership changed'):
            layout.validate(object_with([('.text$a', b'a'), ('.text$b', b'b')]), ambiguous)

    def test_same_short_id_with_changed_contents_is_rejected(self):
        data, digests = coff.rename_anonymous_rdata(object_with([('.rdata', b'original')]))
        name = next(iter(digests))
        manifest = {'text': [], 'rdata': [name], 'discarded': [], 'anonymous': digests}
        layout.validate(data, manifest)
        with self.assertRaisesRegex(ValueError, 'full digest membership changed'):
            layout.validate(object_with([(name, b'replaced')]), manifest)

    def test_invalid_model_dimensions_are_rejected(self):
        path = ROOT / 'size/packer/generate_model.py'
        spec = importlib.util.spec_from_file_location('generate_model', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cfg = json.loads((path.parent / 'model.json').read_text())
        for key, value in [('mix', [1] * 6), ('masks', [0] * 15), ('posm', [0])]:
            bad = dict(cfg, **{key: value})
            with self.assertRaises(ValueError):
                module.generate(bad)


if __name__ == '__main__':
    unittest.main()
