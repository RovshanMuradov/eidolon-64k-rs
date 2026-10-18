"""Small GLSL lexer and top-level splitter for the CG29 shader pool."""
import re

TOKEN = re.compile(r'(?P<pp>#[^\n]*\n?)|(?P<space>[ \t\r\n]+)|(?P<comment>//[^\n]*|/\*.*?\*/)|'
                   r'(?P<number>(?:0[xX][0-9a-fA-F]+|(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)[uUfFlL]*)|'
                   r'(?P<id>[A-Za-z_]\w*)|(?P<op>\+\+|--|<<=?|>>=?|<=|>=|==|!=|&&|\|\||\^\^|[+*/%&|^!=<>-]=|.)', re.S)


def lex(text):
    """List of (kind, text) covering the whole input."""
    out = []
    for m in TOKEN.finditer(text):
        out.append((m.lastgroup, m.group()))
    assert ''.join(t for _, t in out) == text
    return out


def items(text):
    """Split a fragment into top-level items: list of (kind, text) with kind in pp/func/decl/space.

    func items are `type name(params){...}`; decl items end with ';' at depth 0."""
    toks = lex(text)
    out = []
    cur = []
    depth = 0
    i = 0
    while i < len(toks):
        kind, t = toks[i]
        if depth == 0 and not cur and kind in ('pp', 'space'):
            out.append((kind, t))
            i += 1
            continue
        cur.append((kind, t))
        if kind == 'pp':
            pass
        elif t in '({[':
            depth += 1
        elif t in ')}]':
            depth -= 1
            if depth == 0 and t == '}':
                # function body ends unless this is an initializer/struct (followed by ';')
                j = i + 1
                while j < len(toks) and toks[j][0] == 'space':
                    j += 1
                if j >= len(toks) or toks[j][1] != ';':
                    out.append(('func', ''.join(x for _, x in cur)))
                    cur = []
        elif t == ';' and depth == 0:
            out.append(('decl', ''.join(x for _, x in cur)))
            cur = []
        i += 1
    if cur:
        out.append(('tail', ''.join(x for _, x in cur)))
    assert ''.join(t for _, t in out) == text
    return out


def func_name(text):
    m = re.match(r'\s*(?:\w+\s+)+?(\w+)\s*\(', text)
    return m.group(1) if m else None


def ids(text):
    return re.findall(r'[A-Za-z_]\w*', text)
