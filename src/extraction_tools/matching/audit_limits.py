"""Every 'too long' constraint in the port pipeline - and which of them are
really WIDTH limits.

A rendered string is limited by pixels, not by characters: a length cap is
only a correct proxy where every glyph is the same width. The VWF engine
(src/asm/vwf/, advance widths in src/asm/font/vwf_width.bin) makes widths
vary, so a row can pass a char cap and still not fit its slot. The user's
rule is therefore "a width limit, not a length one" wherever VWF renders.

This tool inventories, mechanically:
  * every cap the builders enforce (the constant is READ from the builder
    module, so the inventory fails loudly if a cap moves) together with the
    renderer that decides whether the cap is really a width limit;
  * every row currently too long to auto-port - the 'over limit N unit/CAP
    unit' notes (toolbelt.note_over, the canonical record of what the
    porters refused) across the whole translation tree;
  * rows that fit their char cap but overflow the one pixel budget the repo
    pins today (the 239px VWF dialogue box, vwf_wrap.BOX_WIDTH).

Usage: python src/extraction_tools/matching/audit_limits.py
"""
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import strlib  # noqa: E402
import vwf_wrap  # noqa: E402

GEN = os.path.join(ROOT, 'translation', 'generated')
MAN = os.path.join(ROOT, 'translation', 'manual')

# family, builder module, constant, unit, renderer, px budget (None = the
# slot's pixel width is not pinned anywhere yet)
CAPS = [
    ('skill names',      'skills',      'NAME_PX',     'px',    'small-font VWF battle skill menu (two 144px-separated columns)',        120),
    ('persona names',    'personas',    'MAXLEN',      'chars', 'small font 8px cells (status, PRS-CHG)',                                None),
    ('demon names',      'demons',      'ROW_PX',      'px',    'small font 8px cells (battle message, fusion, cards)',                  80),
    ('demon races',      'demons',      'RACE_LEN',    'chars', 'small font 8px cells',                                                   None),
    ('item names',       'items',       'ROW_PX',      'px',    'small font 8px cells (menus, shops, status, fusion)',                   80),
    ('affinity line',    'smallfont_vwf', 'ROW_PX',     'px',    'small-font VWF affinity row (retail 25-cell footprint)',                 200),
    ('skill/item descs', 'port_descs',  'WIDTH',       'px',    'VWF dialogue font (tools/vwf_wrap.py)',                                  239),
    ('casino prizes',    'casinoprize', 'MAX_CELLS',   'cells', 'small font cells',                                                       None),
    ('save nicknames',   'fix_save_nicks', 'FIELD',    'chars', 'name entry (fixed cells)',                                               None),
    ('party names',      'partynames',  'SLOT',        'chars', 'name entry (fixed cells)',                                               None),
]
OVER = re.compile(r'^over limit (\d+)\s?(px|chars|cells|B|words)/(\d+)\s?(px|chars|cells|B|words)')
BREAK = re.compile(r'<FF03>|<FF04>|<FFFC>|<FFF6>')   # line ends: FF03 newline, FF04 next page, FFFC/FFF6 battle text (FF02 = wait, continues the line)


def caps():
    out = []
    for fam, mod, const, unit, renderer, px in CAPS:
        m = __import__(mod)
        if not hasattr(m, const):
            raise SystemExit(f'audit_limits: {mod}.{const} is gone - update the inventory')
        out.append((fam, f'{mod}.{const}={getattr(m, const)}', unit, renderer, px))
    return out


def over_rows():
    """[(rel, pos, en, note)] for every row whose note records an over-limit
    refusal, across generated and manual."""
    out = []
    for base in (GEN, MAN):
        for dirpath, _dirs, files in os.walk(base):
            for f in sorted(files):
                if not f.endswith('.tsv'):
                    continue
                path = os.path.join(dirpath, f)
                rel = os.path.relpath(path, base)[:-4]
                try:
                    rows = strlib.tsv_rows(path)
                except ValueError:
                    continue
                for r in rows:
                    note = (r.get('note') or '')
                    if note.startswith('over limit'):
                        out.append((rel, r.get('pos', ''), r.get('en', ''), note))
    return out


def px_overflow():
    """Rows whose lines exceed the pinned 239px VWF dialogue box. Only the
    stores drawn in THAT box are flagged (ADV/DNG/S2D per vwf_wrap); the
    battle negotiation box has no pinned budget yet, so its rows are
    measured and reported but not judged."""
    boxed, other = [], []
    for dirpath, _dirs, files in os.walk(GEN):
        for f in sorted(files):
            if not f.endswith('.tsv'):
                continue
            path = os.path.join(dirpath, f)
            rel = os.path.relpath(path, GEN)[:-4]
            for r in strlib.tsv_rows(path):
                en = (r.get('en') or '').strip()
                if not en:
                    continue
                w = max((vwf_wrap.text_width(p) for p in BREAK.split(en)), default=0)
                if rel.split('/')[0] in ('ADV', 'S2D') or rel.split('/')[0].startswith('D0'):
                    if w > vwf_wrap.BOX_WIDTH:
                        boxed.append((rel, r.get('pos', ''), w, en))
                else:
                    other.append((rel, w))
    return boxed, other


def main():
    print('caps enforced today (READ from the builders):')
    for fam, src, unit, renderer, px in caps():
        budget = f'  ~{px}px slot' if px else '  pixel budget NOT pinned'
        print(f'  {fam:18} {src:28} [{unit}] {renderer}{budget}')
    over = over_rows()
    print(f'\nrows too long to auto-port (over-limit notes): {len(over)}')
    by = collections.Counter(rel for rel, _p, _e, _n in over)
    for rel, n in by.most_common():
        print(f'  {n:4}  {rel}')
    units = collections.Counter(OVER.match(n).group(2) for _r, _p, _e, n in over if OVER.match(n))
    print('  measured in:', dict(units))
    over_px, other = px_overflow()
    print(f'\ndialogue box (ADV/DNG/S2D, {vwf_wrap.BOX_WIDTH}px): '
          f'{len(over_px)} row(s) with a line over budget')
    for rel, pos, w, en in over_px[:10]:
        print(f'  {rel} {pos}: {w}px {en!r}')
    if other:
        wide = sorted(other, key=lambda x: -x[1])[:5]
        print(f'other VWF stores (no pinned budget): {len(other)} rows, '
              f'widest lines: ' + ', '.join(f'{rel} {w}px' for rel, w in wide))
    print('\nwidth-not-length verdicts:')
    # The verdicts are read from the inventory, not retyped: a family whose
    # builder enforces px is already width-based; one enforcing a cell count
    # is length==width only while its renderer draws fixed 8px cells.
    px_caps = [fam for fam, _c, unit, _r, _px in caps() if unit == 'px']
    print('  already a width limit : ' + ', '.join(px_caps))
    print('  length==width today   : small-font families (fixed 8px cells) - until')
    print('                          their renderer goes VWF, then the cap must become px')
    print('  length!=width NOW     : everything drawn through the VWF engine (dialogue,')
    print('                          map titles, battle command windows, negotiation) -')
    print('                          the char caps there are proxies and must become px')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
