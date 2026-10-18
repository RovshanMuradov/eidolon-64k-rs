#!/usr/bin/env python3
"""Regression tests for the old false-positive shader checker (no GPU)."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import astcheck
import cg29
import gparse
import minify
import poolcost

ROOT = Path(__file__).resolve().parents[2]


class ShaderValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work = ROOT / '.build/shader-tests'
        work.mkdir(parents=True, exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(dir=work)
        cls.work = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compare(self, a, b, expected, **opts):
        a, b = a.encode(), b.encode()
        if expected != 'COMPILE_FAILURE':
            # Negative semantic tests must be valid shaders on BOTH sides.
            self.assertTrue(astcheck.compile_source(a, temp_dir=self.work)[0])
            self.assertTrue(astcheck.compile_source(b, temp_dir=self.work)[0])
        status, detail = astcheck.compare(a, b, temp_dir=self.work, **opts)
        self.assertEqual(status, expected, detail)

    def test_original_a_plus_b_false_positive(self):
        a = '#version 450\nuniform float a,b;out vec4 c;void main(){c=vec4(a+b);}'
        self.compare(a, a.replace('a+b', 'a+a'), 'DIFFERS')

    def test_alpha_rename_and_shadow_binding(self):
        a = '#version 450\nuniform float a,b;out vec4 c;void main(){float x=a;{float y=b;c=vec4(x+y);}}'
        good = a.replace('float x=a', 'float z=a').replace('x+y', 'z+y')
        self.compare(a, good, 'PASS')
        self.compare(a, a.replace('float y=b', 'float x=b').replace('x+y', 'x+x'), 'DIFFERS')

    def test_same_name_different_scope(self):
        a = '#version 450\nuniform float a;out vec4 c;void main(){float x=a;{float y=2.;x=y;}c=vec4(x);}'
        b = a.replace('float y=2.;x=y;', 'float x=2.;x=x;')
        self.compare(a, b, 'DIFFERS')

    def test_initializer_resolves_before_new_declaration(self):
        a = '#version 450\nuniform float x,y;out vec4 c;void main(){float x=x;c=vec4(x);}'
        good = a.replace('float x=x', 'float z=x').replace('vec4(x)', 'vec4(z)')
        bad = a.replace('float x=x', 'float y=y').replace('vec4(x)', 'vec4(y)')
        self.compare(a, good, 'PASS')
        self.compare(a, bad, 'DIFFERS')

    def test_loop_scope_and_parameters(self):
        a = '#version 450\nuniform float a;out vec4 c;float f(float x){for(int i=0;i<2;i++){x+=i;}return x;}void main(){c=vec4(f(a));}'
        b = a.replace('float x', 'float y').replace('x+=', 'y+=').replace('return x', 'return y').replace('int i', 'int j').replace('i<', 'j<').replace('i++', 'j++').replace('+=i', '+=j')
        self.compare(a, b, 'PASS')

    def test_macro_capture(self):
        a = '#version 450\n#define GET x\nuniform float a,b;out vec4 c;void main(){float x=a,y=b;c=vec4(GET+y);}'
        self.compare(a, a.replace('#define GET x', '#define GET y'), 'DIFFERS')
        b = a.replace('#define GET x', '#define GET z').replace('float x=a', 'float z=a')
        self.compare(a, b, 'PASS')

    def test_types_and_interfaces(self):
        a = '#version 450\nlayout(location=2) uniform float a;layout(location=0) out vec4 c;void main(){c=vec4(a);}'
        for b in [a.replace('uniform float', 'uniform int'), a.replace('location=2', 'location=3'),
                  a.replace('location=0', 'location=1'), a.replace('float a', 'float b').replace('vec4(a)', 'vec4(b)')]:
            with self.subTest(candidate=b):
                self.compare(a, b, 'DIFFERS')

    def test_output_order_and_global_initializers(self):
        a = '#version 450\nout vec4 a;out vec4 b;void main(){a=vec4(1);b=vec4(2);}'
        self.compare(a, a.replace('out vec4 a;out vec4 b;', 'out vec4 b;out vec4 a;'), 'DIFFERS', reorder=True, uniforms_by_name=True)
        a = '#version 450\nuniform float u;float a=u;float b=a;out vec4 c;void main(){c=vec4(b);}'
        b = a.replace('float a=u;float b=a;', 'float b=u;float a=b;')
        self.compare(a, b, 'DIFFERS', reorder=True, uniforms_by_name=True)

    def test_overload_binding(self):
        a = '#version 450\nuniform float u;out vec4 c;float f(float x){return x;}float f(int x){return -x;}void main(){c=vec4(f(u));}'
        self.compare(a, a.replace('f(u)', 'f(int(u))'), 'DIFFERS')
        self.compare(a, a.replace('f(', 'g('), 'PASS', names={'g': 'f'})

    def test_entrypoint_cannot_be_alpha_renamed(self):
        a = '#version 450\nout vec4 c;void f(){c=vec4(1);}void main(){c=vec4(2);}'
        b = a.replace('void f()', 'void TEMP()').replace('void main()', 'void f()').replace('void TEMP()', 'void main()')
        self.compare(a, b, 'UNSUPPORTED_SYNTAX', names={'main': 'f', 'f': 'main'}, reorder=True)

    def test_builtin_overload_does_not_hide_builtin_calls(self):
        a = '#version 450\nuniform float u;out vec4 c;float sin(int x){return float(x);}void main(){c=vec4(sin(u));}'
        self.compare(a, a.replace('sin', 'cos'), 'UNSUPPORTED_SYNTAX', names={'cos': 'sin'})

    def test_fields_swizzles_and_struct_types(self):
        a = '#version 450\nuniform vec2 u;out vec4 c;struct S{float r;float x;};void main(){S s=S(u.r,u.x);c=vec4(s.r);}'
        self.compare(a, a.replace('vec4(s.r)', 'vec4(s.x)'), 'DIFFERS')
        self.compare(a, a.replace('u.r,u.x', 'u.g,u.x'), 'DIFFERS')
        a = '#version 450\nuniform float u;out vec4 c;struct S{float field;};void main(){S s=S(u);c=vec4(s.field);}'
        self.compare(a, a.replace('field', 'renamed'), 'PASS', fields={'renamed': 'field'})
        self.compare(a, a.replace('field', 'x'), 'UNSUPPORTED_SYNTAX', fields={'x': 'field'})

    def test_identical_failure_is_failure(self):
        a = '#version 450\nout vec4 c;void main(){c=vec4(unknown);}'
        self.compare(a, a, 'COMPILE_FAILURE')
        self.compare(a.replace('unknown', '1'), a, 'COMPILE_FAILURE')

    def test_texture2d_is_not_silently_rewritten(self):
        a = '#version 450\nuniform sampler2D s;out vec4 c;void main(){c=texture2D(s,vec2(0));}'
        self.compare(a, a, 'COMPILE_FAILURE')

    def directory(self, name, sources, recipes=None):
        p = self.work / name
        p.mkdir()
        for i, s in enumerate(sources):
            (p / f'{i:02d}.glsl').write_text(s)
        (p / 'recipes.json').write_text(json.dumps(recipes if recipes is not None else [[i] for i in range(len(sources))]))
        return p

    def cli(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = astcheck.main([*(str(a) for a in args), '--work', str(self.work)])
        return code, output.getvalue()

    def test_count_and_recipe_validation(self):
        shader = '#version 450\nout vec4 c;void main(){c=vec4(1);}'
        a = self.directory('one', [shader])
        b = self.directory('two', [shader, shader])
        code, out = self.cli([a, b])
        self.assertEqual(code, 1)
        self.assertIn('unequal program counts', out)
        for name, recipes in [('missing', [[1]]), ('empty', []), ('boolean', [[True]])]:
            code, _ = self.cli([a, self.directory(name, [shader], recipes)])
            self.assertEqual(code, 1)

    def test_unsupported_baseline_is_never_pass(self):
        src = astcheck.programs(ROOT / 'size/shaders/checkpoint-tx.cg29')[21]
        a = self.directory('unsupported', [src.decode('latin1')])
        code, out = self.cli([a, a, '--unsupported', '0'])
        self.assertEqual(code, 2)
        self.assertIn('0 passed; 0 failed; 1 unsupported', out)
        code, out = self.cli([a, a])
        self.assertEqual(code, 1)
        self.assertIn('COMPILE_FAILURE', out)

    def test_malformed_blobs(self):
        blob = (ROOT / 'size/shaders/checkpoint-tx.cg29').read_bytes()
        for bad in [b'', b'CG28' + blob[4:], blob[:-1], blob + b'x', blob[:8] + b'\xff' * 5 + blob[13:]]:
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                cg29.parse(bad)
        with self.assertRaises(ValueError):
            cg29.uv(-1)

    def test_untyped_optimizer_does_not_erase_fields_or_round_literals(self):
        a = ('field', ('id', 's'), 'r')
        b = ('field', ('id', 's'), 'x')
        self.assertNotEqual(gparse.strip(a), gparse.strip(b))
        self.assertNotEqual(gparse.number('1.00000000000000001'), gparse.number('1.00000000000000002'))
        self.assertNotEqual(gparse.number('010'), gparse.number('10'))
        self.assertEqual(gparse.number('.50'), gparse.number('0.5'))

    def test_atomic_experiments_never_overwrite(self):
        p = self.work / 'immutable-experiment'
        minify.save(p, ['first'], [[0]])
        with self.assertRaises(FileExistsError):
            minify.save(p, ['second'], [[0]])
        self.assertEqual((p / '00.glsl').read_text(), 'first')
        self.assertFalse(p.with_name(p.name + '.lock').exists())

    def test_proxy_requires_explicit_tool_and_enforces_budget(self):
        with mock.patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(ValueError):
                poolcost.packer()
        with mock.patch.object(poolcost, '_pack', '/usr/bin/cat'), \
             mock.patch.object(poolcost, '_used', 0), mock.patch.object(poolcost, '_limit', 2):
            self.assertEqual(poolcost.cost(b'x'), 1)
            self.assertEqual(poolcost.cost(b'xx'), 2)
            with self.assertRaises(ValueError):
                poolcost.cost(b'xxx')


if __name__ == '__main__':
    unittest.main()
