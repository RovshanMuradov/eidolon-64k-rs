"""Conservative, binding-aware GLSL token comparison (the CG29 subset).

Run only on glslang-preprocessed text, after compiling the *unmodified* input.
This is deliberately stricter than algebraic/AST equivalence: expressions, scopes,
declaration types, initializer order, fields and swizzles are retained. Unsupported
syntax raises Fail. No floating-point rewriting or AST name erasure is performed.
"""
import re

import glsl
import gparse

Fail = gparse.Fail
IDENT = re.compile(r'[A-Za-z_]\w*\Z')
SWIZZLE = re.compile(r'(?:[xyzw]{1,4}|[rgba]{1,4}|[stpq]{1,4})\Z')
INTERFACE = {'uniform', 'in', 'out', 'attribute', 'varying', 'buffer'}
QUALS = gparse.QUALS | INTERFACE | {'flat', 'smooth', 'noperspective', 'centroid',
                                 'sample', 'invariant', 'precise', 'readonly', 'writeonly'}


class Parser(gparse.Parser):
    def statement(self):
        if self.peek() == 'switch':
            self.take()
            self.take('(')
            value = self.expr()
            self.take(')')
            return ('switch', value, self.block())
        if self.peek() in ('case', 'default'):
            tag = self.take()
            value = self.expr() if tag == 'case' else None
            self.take(':')
            return (tag, value)
        return super().statement()

    def name(self):
        name = self.take()
        if not IDENT.fullmatch(name):
            raise Fail(f'expected identifier, got {name}')
        return name

    def qualifiers(self):
        quals = []
        while self.peek() in QUALS or self.peek() == 'layout':
            q = self.take()
            if q == 'layout':
                self.take('(')
                layout = []
                while self.peek() != ')':
                    layout.append(self.take())
                self.take(')')
                q = ('layout', tuple(layout))
            quals.append(q)
        return tuple(quals)

    def type(self):
        ty = self.take()
        if not self.is_type(ty):
            raise Fail(f'unsupported type {ty}')
        return ty

    def array(self):
        dims = []
        while self.peek() == '[':
            self.take()
            dims.append(None if self.peek() == ']' else self.expr())
            self.take(']')
        return tuple(dims)

    def declaration(self, quals, ty, name):
        decls = []
        while True:
            dims = self.array()
            init = None
            if self.peek() == '=':
                self.take()
                init = self.assign()
            decls.append(('var', name, dims, init))
            if self.peek() != ',':
                break
            self.take()
            name = self.name()
        self.take(';')
        return ('global', quals, ty, tuple(decls))

    def program(self):
        result = []
        while self.peek() is not None:
            if self.peek() == 'struct':
                self.take()
                name = self.name()
                self.take('{')
                fields = []
                while self.peek() != '}':
                    q, ty = self.qualifiers(), self.type()
                    fields.append(self.declaration(q, ty, self.name()))
                self.take('}')
                self.take(';')  # inline instances / anonymous structs are unsupported
                if name in self.structs:
                    raise Fail(f'duplicate struct {name}')
                self.structs.add(name)
                result.append(('struct', name, tuple(fields)))
                continue
            quals, ty, name = self.qualifiers(), self.type(), self.name()
            if self.peek() != '(':
                result.append(self.declaration(quals, ty, name))
                continue
            self.take('(')
            params = []
            if self.peek() == 'void' and self.peek(1) == ')':
                self.take()
            elif self.peek() != ')':
                while True:
                    q, pt = self.qualifiers(), self.type()
                    pn = None if self.peek() in (',', ')') else self.name()
                    params.append((q, pt, pn, self.array()))
                    if self.peek() != ',':
                        break
                    self.take()
            self.take(')')
            if self.peek() == ';':
                self.take()
                body = None
            else:
                body = self.block()
            result.append(('function', quals, ty, name, tuple(params), body))
        return result


class Binder:
    def __init__(self, nodes, names, fields, keep_names, reorder, uniforms_by_name, builtins):
        self.nodes = nodes
        self.names = names
        self.fields = fields
        self.keep_names = keep_names
        self.reorder = reorder
        self.uniforms_by_name = uniforms_by_name
        self.scopes = [{}]
        self.local = 0
        self.types = {n[1] for n in nodes if n[0] == 'struct'}
        self.functions = {n[3] for n in nodes if n[0] == 'function'}
        for mapping in (names, fields):
            if not isinstance(mapping, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                    or not IDENT.fullmatch(k) or not IDENT.fullmatch(v) for k, v in mapping.items()):
                raise Fail('rename maps must contain identifiers')
            if len(set(mapping.values())) != len(mapping):
                raise Fail('rename map is not injective')
        if any(SWIZZLE.fullmatch(k) or SWIZZLE.fullmatch(v) for k, v in fields.items() if k != v):
            raise Fail('field map may not rewrite swizzles')
        # A user overload named sin does not make sin(float) a user call. Reject
        # such overload sets rather than guess compiler overload resolution from
        # spelling. The inventory comes from this actual compiler/profile.
        if any(n in builtins or self.name(n) in builtins for n in self.functions):
            raise Fail('overloading builtin functions is unsupported')
        # Include unchanged names in the injectivity check, in each GLSL namespace.
        for group in (self.types, self.functions):
            if len({self.name(n) for n in group}) != len(group):
                raise Fail('rename captures an unchanged name')

    def name(self, name):
        if name == 'main' or name.startswith('gl_'):
            return name
        return self.names.get(name, name)

    def type(self, ty):
        return self.name(ty) if ty in self.types else ty

    def declare(self, name, global_=False, external=False):
        scope = self.scopes[-1]
        if name in scope:
            raise Fail(f'duplicate declaration in scope: {name}')
        if global_:
            binding = ('interface' if external else 'global', name if external else self.name(name))
            if binding in scope.values():
                raise Fail('global rename collision')
        else:
            binding = ('local', self.local, name if self.keep_names else '')
            self.local += 1
        scope[name] = binding
        return binding

    def expr(self, tree):
        if tree is None:
            return None
        tag = tree[0]
        if tag == 'id':
            name = tree[1]
            for scope in reversed(self.scopes):
                if name in scope:
                    return ('ref', scope[name])
            if name in self.functions:
                return ('function-ref', self.name(name))
            base = name.removesuffix('[]')
            if base in self.types:
                return ('type-ref', self.name(base), name.endswith('[]'))
            return ('builtin', name)  # compilation has already resolved/checked it
        if tag == 'field':
            return (tag, self.expr(tree[1]), self.fields.get(tree[2], tree[2]))
        if tag == 'num':
            return tree  # retain literal spelling; do not round through Python floats
        if tag == 'call':
            return (tag, self.expr(tree[1]), tuple(self.expr(a) for a in tree[2]))
        if tag in ('bin', 'assign', 'un', 'post'):
            return (tag, tree[1], *(self.expr(a) for a in tree[2:]))
        if tag in ('paren', 'index', '?', 'seq'):
            return (tag, *(self.expr(a) for a in tree[1:]))
        raise Fail(f'unsupported expression {tag}')

    def scoped(self, stmt):
        self.scopes.append({})
        result = self.stmt(stmt)
        self.scopes.pop()
        return result

    def stmt(self, tree):
        if tree is None:
            return None
        tag = tree[0]
        if tag == 'block':
            self.scopes.append({})
            body = tuple(self.stmt(t) for t in tree[1])
            self.scopes.pop()
            return (tag, body)
        if tag == 'decl':
            decls = []
            for _, name, arr, init in tree[3]:
                # Unlike C, GLSL resolves an initializer before introducing its
                # declarator: `float x=x` can read an outer x. Array dimensions
                # also precede the newly declared binding.
                array, initializer = self.expr(arr), self.expr(init)
                binding = self.declare(name)
                decls.append((binding, array, initializer))
            return (tag, tree[1], self.type(tree[2]), tuple(decls))
        if tag == 'for':
            self.scopes.append({})
            result = (tag, self.stmt(tree[1]), self.expr(tree[2]), self.expr(tree[3]), self.scoped(tree[4]))
            self.scopes.pop()
            return result
        if tag == 'if':
            return (tag, self.expr(tree[1]), self.scoped(tree[2]), self.scoped(tree[3]))
        if tag in ('while', 'switch'):
            return (tag, self.expr(tree[1]), self.scoped(tree[2]))
        if tag in ('return', 'expr', 'case', 'default'):
            return (tag, self.expr(tree[1]))
        if tag in ('break', 'continue', 'discard', 'empty'):
            return tree
        raise Fail(f'unsupported statement {tag}')

    def program(self):
        ordered, functions, types, uniforms = [], [], [], []
        for node in self.nodes:
            tag = node[0]
            if tag == 'struct':
                fs = []
                seen = set()
                for _, q, ty, decls in node[2]:
                    for _, name, dims, init in decls:
                        if init is not None:
                            raise Fail('struct initializer unsupported')
                        name = self.fields.get(name, name)
                        if name in seen:
                            raise Fail('field rename collision')
                        seen.add(name)
                        fs.append((q, self.type(ty), name, tuple(self.expr(x) for x in dims)))
                result = (tag, self.name(node[1]), tuple(fs))
                (types if self.reorder else ordered).append(result)
            elif tag == 'global':
                _, q, ty, decls = node
                for _, name, dims, init in decls:
                    array, initializer = tuple(self.expr(x) for x in dims), self.expr(init)
                    binding = self.declare(name, global_=True, external=bool(INTERFACE.intersection(q)))
                    result = (tag, q, self.type(ty), binding, array, initializer)
                    # Only named uniforms can move. Outputs, other globals and all
                    # executable global initializer dependencies retain their order.
                    (uniforms if self.uniforms_by_name and 'uniform' in q else ordered).append(result)
            else:
                _, q, ty, name, params, body = node
                self.local = 0
                self.scopes.append({})
                ps = []
                for pq, pt, pn, dims in params:
                    array = tuple(self.expr(x) for x in dims)
                    binding = self.declare(pn) if pn is not None else None
                    ps.append((pq, self.type(pt), binding, array))
                result = (tag, q, self.type(ty), self.name(name), tuple(ps), self.stmt(body))
                self.scopes.pop()
                (functions if self.reorder else ordered).append(result)
        return tuple(ordered), tuple(sorted(functions, key=repr)), tuple(sorted(types, key=repr)), \
            tuple(sorted(uniforms, key=repr))


def canonical(source, *, builtins, names=None, fields=None, keep_names=False, reorder=False, uniforms_by_name=False):
    directives, tokens = [], []
    for kind, text in glsl.lex(source):
        if kind in ('space', 'comment'):
            continue
        if kind == 'pp':
            if re.match(r'#\s*line\b', text):
                continue
            if tokens or not re.match(r'#\s*(version|extension)\b', text):
                raise Fail(f'unexpanded directive: {text.strip()}')
            directives.append(' '.join(text.split()))
        else:
            tokens.append(text)
    nodes = Parser(tokens).program()
    return tuple(directives), Binder(nodes, names or {}, fields or {}, keep_names, reorder,
                                     uniforms_by_name, builtins).program()
