"""Recursive-descent parser for the GLSL function bodies of the CG29 pool.

Works on the significant tokens of glsl.lex(); returns trees of tuples. Used to validate token
deletions: a deletion is kept only if the reparsed tree is unchanged after normalization."""
import re

TYPES = {'float', 'int', 'bool', 'uint', 'vec2', 'vec3', 'vec4', 'ivec2', 'ivec3', 'ivec4', 'bvec2', 'bvec3',
         'bvec4', 'mat2', 'mat3', 'mat4', 'void', 'sampler2D', 'sampler3D'}
QUALS = {'const', 'in', 'out', 'inout', 'uniform', 'highp', 'mediump', 'lowp'}
ASSIGN = {'=', '+=', '-=', '*=', '/=', '%=', '<<=', '>>=', '&=', '^=', '|='}
BINARY = [('||',), ('^^',), ('&&',), ('|',), ('^',), ('&',), ('==', '!='), ('<', '>', '<=', '>='),
          ('<<', '>>'), ('+', '-'), ('*', '/', '%')]


class Fail(Exception):
    pass


class Parser:
    def __init__(self, toks, structs=()):
        self.t = toks  # list of strings
        self.i = 0
        self.structs = set(structs)

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else None

    def take(self, want=None):
        tok = self.peek()
        if tok is None or (want is not None and tok != want):
            raise Fail(f'expected {want} got {tok} at {self.i}')
        self.i += 1
        return tok

    def is_type(self, tok):
        return tok in TYPES or tok in self.structs

    # ---------------------------------------------------------- statements
    def block(self):
        self.take('{')
        body = []
        while self.peek() != '}':
            body.append(self.statement())
        self.take('}')
        return ('block', tuple(body))

    def statement(self):
        tok = self.peek()
        if tok is None:
            raise Fail('eof')
        if tok.startswith('#'):
            raise Fail('preprocessor inside function')
        if tok == '{':
            return self.block()
        if tok == 'if':
            self.take()
            self.take('(')
            c = self.expr()
            self.take(')')
            s = self.statement()
            e = None
            if self.peek() == 'else':
                self.take()
                e = self.statement()
            return ('if', c, s, e)
        if tok == 'for':
            self.take()
            self.take('(')
            init = self.simple(';')
            cond = None if self.peek() == ';' else self.expr()
            self.take(';')
            inc = None if self.peek() == ')' else self.expr()
            self.take(')')
            return ('for', init, cond, inc, self.statement())
        if tok == 'while':
            self.take()
            self.take('(')
            c = self.expr()
            self.take(')')
            return ('while', c, self.statement())
        if tok == 'return':
            self.take()
            e = None if self.peek() == ';' else self.expr()
            self.take(';')
            return ('return', e)
        if tok in ('break', 'continue', 'discard'):
            self.take()
            self.take(';')
            return (tok,)
        if tok == ';':
            self.take()
            return ('empty',)
        return self.simple(';')

    def simple(self, end):
        """Declaration or expression statement terminated by `end` (consumed)."""
        if self.peek() == end:
            self.take()
            return ('empty',)
        quals = []
        j = self.i
        while self.peek() in QUALS:
            quals.append(self.take())
        if self.is_type(self.peek()) and (self.peek(1) is not None and re.match(r'[A-Za-z_]', self.peek(1))):
            ty = self.take()
            decls = []
            while True:
                name = self.take()
                arr = None
                if self.peek() == '[':
                    self.take()
                    arr = self.expr() if self.peek() != ']' else None
                    self.take(']')
                init = None
                if self.peek() == '=':
                    self.take()
                    init = self.assign()
                decls.append(('var', name, arr, init))
                if self.peek() == ',':
                    self.take()
                    continue
                break
            self.take(end)
            return ('decl', tuple(quals), ty, tuple(decls))
        if quals:
            raise Fail('qualifier without type')
        self.i = j
        e = self.expr()
        self.take(end)
        return ('expr', e)

    # ---------------------------------------------------------- expressions
    def expr(self):
        e = self.assign()
        while self.peek() == ',':
            self.take()
            e = ('seq', e, self.assign())
        return e

    def assign(self):
        lhs = self.ternary()
        if self.peek() in ASSIGN:
            op = self.take()
            return ('assign', op, lhs, self.assign())
        return lhs

    def ternary(self):
        c = self.binary(0)
        if self.peek() == '?':
            self.take()
            a = self.expr()
            self.take(':')
            b = self.assign()
            return ('?', c, a, b)
        return c

    def binary(self, level):
        if level == len(BINARY):
            return self.unary()
        e = self.binary(level + 1)
        while self.peek() in BINARY[level]:
            op = self.take()
            e = ('bin', op, e, self.binary(level + 1))
        return e

    def unary(self):
        tok = self.peek()
        if tok in ('+', '-', '!', '~', '++', '--'):
            self.take()
            return ('un', tok, self.unary())
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while True:
            tok = self.peek()
            if tok == '(':
                self.take()
                args = []
                if self.peek() != ')':
                    args.append(self.assign())
                    while self.peek() == ',':
                        self.take()
                        args.append(self.assign())
                self.take(')')
                e = ('call', e, tuple(args))
            elif tok == '[':
                self.take()
                idx = self.expr()
                self.take(']')
                e = ('index', e, idx)
            elif tok == '.':
                self.take()
                e = ('field', e, self.take())
            elif tok in ('++', '--'):
                self.take()
                e = ('post', tok, e)
            else:
                return e

    def primary(self):
        tok = self.peek()
        if tok == '(':
            self.take()
            e = self.expr()
            self.take(')')
            return ('paren', e)
        if tok is None:
            raise Fail('eof in expression')
        if re.match(r'[A-Za-z_]', tok):
            self.take()
            if self.peek() == '[' and self.peek(1) == ']':  # array constructor type: vec3[](...)
                self.take()
                self.take()
                return ('id', tok + '[]')
            return ('id', tok)
        if re.match(r'[0-9.]', tok):
            self.take()
            return ('num', tok)
        raise Fail(f'unexpected {tok}')


SWZ = str.maketrans('rgbastpq', 'xyzwxyzw')


def number(tok):
    """('f', value) for float literals, ('i', value) for int literals."""
    t = tok.rstrip('fF')
    if re.fullmatch(r'\d+', t):
        return ('i', int(t))
    return ('f', float(t))


def strip(tree):
    """Normalize: drop parens, unwrap single-statement blocks used as if/for bodies, split decls,
    canonical literal spelling, rgba/stpq swizzles as xyzw, and vecN(c,..,c) of one literal as vecN(c)."""
    if not isinstance(tree, tuple):
        return tree
    if tree and tree[0] == 'paren':
        return strip(tree[1])
    if tree and tree[0] == 'num':
        return ('num', number(tree[1]))
    if tree and tree[0] == 'field' and re.fullmatch(r'[rgbastpq]{1,4}', tree[2]):
        return ('field', strip(tree[1]), tree[2].translate(SWZ))
    if tree and tree[0] == 'call' and tree[1][0] == 'id' and re.fullmatch(r'[ib]?vec[234]', tree[1][1]):
        args = tuple(strip(a) for a in tree[2])
        if len(args) == int(tree[1][1][-1]) and all(a[0] == 'num' for a in args) and len(set(args)) == 1:
            args = args[:1]
        return ('call', tree[1], args)
    if tree and tree[0] == 'block':
        out = []
        for s in tree[1]:
            s = strip(s)
            if s[0] == 'decl':
                for d in s[3]:
                    out.append(('decl', s[1], s[2], (d,)))
            else:
                out.append(s)
        return ('block', tuple(out))
    if tree and tree[0] in ('if', 'for', 'while'):
        parts = [strip(x) for x in tree]
        def body(s):
            if isinstance(s, tuple) and s and s[0] == 'block' and len(s[1]) == 1 and s[1][0][0] != 'decl':
                return s[1][0]
            return s
        if tree[0] == 'if':
            return ('if', parts[1], body(parts[2]), body(parts[3]) if parts[3] is not None else None)
        if tree[0] == 'for':
            return ('for', parts[1], parts[2], parts[3], body(parts[4]))
        return ('while', parts[1], body(parts[2]))
    return tuple(strip(x) for x in tree)
