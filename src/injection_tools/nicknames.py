"""Party nicknames (battle status panels) in SLPS_005.00.

  python src/injection_tools/nicknames.py dump     refresh generated TSV (keeps en)
  python src/injection_tools/nicknames.py build    QA + build/nicknames.asm

9 character records of 0x28 bytes; the nickname is a 10-byte field after
the halfwords 4F01 0000 6F01 (first field 0x800442B2 = the hero's default
"ATLUS"), single-byte game-font glyphs (uppercase A-Z, 0-9, glyph 0 =
space, lowercase = codes 0xE0.. via smallfont_lc), FF-terminated. Drawn
with the 8x12 small font: at most 8 characters are visible and a longer
name overwrites the next panel .
The records are COPIED into the party data when a character joins: a save
from before this patch keeps the Japanese nicknames of joined members.

Schema: docs/TEXT_ARCHITECTURE.md (id | pos | psp | en). This file is a
config + record reader only; all TSV io, merging and emission is
toolbelt.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext      # noqa: E402
import toolbelt   # noqa: E402
from toolbelt import Patch, fit_field, glyph_bytes, smallfont_char  # noqa: E402

ROOT = toolbelt.ROOT
REL = 'SLPS_005.00'            # real disc file (mirrored by the TSV paths)
BASE = 0x80010000 - 0x800      # SLPS file offset = VA - BASE
FIRST = 0x800442B2             # first nickname field (VA)
STRIDE = 0x28
COUNT = 9
FIELD = 10
MAXLEN = 8
OUT = os.path.join(ROOT, 'build', 'nicknames.asm')
G2C = {v: k for k, v in etext.char2g.items()}


def records():
    """[(pos, ja, psp)] the file's nickname fields in source order."""
    d = open(os.path.join(ROOT, 'data', 'psx', REL), 'rb').read()
    out = []
    for i in range(COUNT):
        va = FIRST + STRIDE * i
        off = va - BASE
        if d[off - 2:off] != b'\x6f\x01':
            toolbelt.fail(f'{REL}:{off:#x}: record head mismatch (not 6F01)')
        f = d[off:off + FIELD]
        ja = ''.join(G2C.get(x, '?') for x in f.split(b'\xff')[0])
        out.append((off, ja, ''))
    return out


def dump():
    rows = [((off), '') for off, _ja, _psp in records()]
    scaffold, _man = toolbelt.dump_scaffold(
        REL, [(hex(off), psp) for off, _ja, psp in records()])
    print(f'nicknames: {len(scaffold)} rows -> {toolbelt.gen_path(REL)}')


def encode(t):
    if len(t) > MAXLEN:
        toolbelt.fail(f'{t!r} is longer than {MAXLEN} (the panel clips at 8)')
    return bytes(smallfont_char(c) for c in t) + b'\xff'


def build():
    p = Patch('nicknames', OUT)
    # One table per real file: patch only this scan's positions (other
    # surfaces' rows belong to their own builders - see items.py).
    own = {off for off, _ja, _psp in records()}
    for r in toolbelt.merged_rows(REL):
        if int(r['pos'], 16) not in own:
            continue
        t = r['en'].strip()
        if not t:
            continue
        b = fit_field(encode(t), FIELD, pad=b'\x00',
                      what=f'{REL} id {r["id"]} {t!r}')
        p.org(toolbelt.file_va(REL, int(r['pos'], 16)), b, f'{r["id"]} {t}')
    print(f'nicknames: {p.n}/{COUNT} -> {OUT}')
    p.write()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'dump': dump, 'build': build}[sys.argv[1] if sys.argv[1:] else 'build']()
