"""Every runtime scratch region the patch claims, and who may share one.

  python tools/scratch_map.py verify

src/mods/base/asm/common/scratch_map.tsv lists each region the patch writes at runtime
outside its own images (name, start, end, users), as expressions over the
assembler constants (addresses.inc, vwf/smallfont_defs.asm). Two regions may
overlap only when each names the other in `shares` and the row says why the
two are never live at once. Fails the build on an undeclared overlap, a
one-sided or unknown sharer, a sharer without a reason, an empty region, or a
constant that does not resolve.
"""
import ast
import csv
import operator
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TSV = os.path.join(ROOT, 'src', 'mods', 'base', 'asm', 'common', 'scratch_map.tsv')
SOURCES = [os.path.join(ROOT, 'src', 'mods', 'base', 'asm', 'common', 'addresses.inc'),
           os.path.join(ROOT, 'src', 'mods', 'latin-alphabet', 'asm', 'vwf', 'smallfont_defs.asm')]
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul}


def fail(msg):
    raise SystemExit(f'scratch_map: {msg}')


def constants():
    out = {}
    for path in SOURCES:
        for line in open(path, encoding='utf-8'):
            m = re.match(r'^(\w+)\s+equ\s+([^;]+?)\s*(?:;.*)?$', line)
            if m:
                out.setdefault(m[1], m[2])
    return out


def evaluate(expr, raw, seen=()):
    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.Name):
            if node.id in seen or node.id not in raw:
                fail(f'{node.id} does not resolve')
            return evaluate(raw[node.id], raw, seen + (node.id,))
        fail(f'unsupported expression {expr!r}')
    return walk(ast.parse(expr.strip(), mode='eval'))


def regions():
    raw = constants()
    rows = list(csv.DictReader(open(TSV, encoding='utf-8'), delimiter='\t'))
    out = {}
    for r in rows:
        name = r['name']
        if name in out:
            fail(f'{name} listed twice')
        start, end = evaluate(r['start'], raw), evaluate(r['end'], raw)
        if end <= start:
            fail(f'{name} is empty ({start:#x}..{end:#x})')
        shares = {s for s in (r['shares'] or '').split(',') if s}
        if shares and not (r['why'] or '').strip():
            fail(f'{name} shares {sorted(shares)} without saying why')
        out[name] = (start, end, shares)
    return out


def verify():
    reg = regions()
    for name, (_s, _e, shares) in reg.items():
        for other in shares:
            if other not in reg:
                fail(f'{name} shares with unknown region {other}')
            if name not in reg[other][2]:
                fail(f'{name} shares with {other}, but {other} does not name {name}')
    names = sorted(reg)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            (s1, e1, sh1), (s2, e2, _) = reg[a], reg[b]
            if s1 < e2 and s2 < e1 and b not in sh1:
                fail(f'{a} ({s1:#x}..{e1:#x}) overlaps {b} ({s2:#x}..{e2:#x}) '
                     f'and neither declares the other in scratch_map.tsv')
    print(f'scratch_map: {len(reg)} regions, every overlap declared')


if __name__ == '__main__':
    if sys.argv[1:] != ['verify']:
        raise SystemExit(__doc__)
    verify()
