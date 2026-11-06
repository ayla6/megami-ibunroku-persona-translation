"""Port-side insert widths: the widest record each message-machine code prints.

  python src/extraction_tools/matching/port_widths.py

The message machine's record inserts (<FF09> item, <FF0A> skill, <FF0B> demon,
<FF0C> Persona in the ADV message machine / demon in the DNG field script,
<FF13> arcana) print a record the caller names at run time. A line that
carries one must therefore reserve the room of the WIDEST name that code can
print - that width is a fact about the PORTED wording, so the port derives it
here and writes translation/generated/insert_widths.tsv. The layout engine
(injection_tools/vwf_wrap.py) reads that table when it prices an insert
token; nothing on the build side scans the name records.

Runs inside port.py's phase 1: boot_tables has written the name rows, the
font advances are fresh, and no porter has laid text out yet. Arcana are
retail's own full-width Latin cells (game data, not ported wording), decoded
from the ADV table the insert reads.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
import items      # noqa: E402  (record scans + the small-font -> ASCII inverse)
import skills     # noqa: E402
import demons     # noqa: E402
import personas   # noqa: E402
import strlib     # noqa: E402  (the headered-TSV reader/writer rule)
import toolbelt   # noqa: E402
import vwf_wrap   # noqa: E402  (the dialogue advances an insert draws with)

OUT = os.path.join(toolbelt.GENERATED, 'insert_widths.tsv')
COLS = ('code', 'family', 'px', 'longest')
ARCANA_COUNT = 22                      # g_kind_labels: 22 arcana, 10 bytes each
ARCANA_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .'/-:"

# insert code -> the family whose widest name bounds it. <FF0C> names BOTH
# its readers (ADV message machine: Persona; DNG field script: demon), so
# its width is the larger of the two families.
CODE_FAMILY = {'FF09': 'item', 'FF0A': 'skill', 'FF0B': 'demon',
               'FF0C': 'persona+demon', 'FF13': 'arcana'}


def family_names():
    """{family: [English name, ...]}: every record an insert can print,
    from the canonical SLPS rows (manual wins - toolbelt.merged_rows)."""
    by_off = {}
    for r in toolbelt.merged_rows('SLPS_005.00'):
        en = (r.get('en') or '').strip()
        if en:
            for _entry, off in toolbelt.pos_offsets(r['pos']):
                by_off[off] = en
    return {
        'item': [by_off.get(off) for off, _ja, _psp in items.records()],
        'skill': [by_off.get(a - skills.BASE) for _i, a, _ja in skills.records()],
        'demon': [by_off.get(a - demons.SLPS_BASE) for _k, a, _ja in demons.records()],
        'persona': [by_off.get(a - personas.BASE) for _k, a, _ja in personas.records()],
    }


def arcana_names():
    """The 22 arcana cells the <FF13> insert reads (ADV g_kind_labels)."""
    inv = {items.glyph(c): c for c in ARCANA_CHARS}
    base = toolbelt.asm_equ('OVERLAY_SLOT_ADDR')
    labels = toolbelt.asm_equ('ADV_KIND_LABELS')
    raw = open(os.path.join(ROOT, 'data', 'psx', 'ADV.BIN'), 'rb').read()
    return [''.join(inv.get(b, '') for b in
                    raw[labels - base + i * 10:labels - base + (i + 1) * 10]
                    .split(b'\xff')[0])
            for i in range(ARCANA_COUNT)]


def widths():
    """{code: {family, px, longest}} - px measured with the dialogue VWF
    advances, exactly the way vwf_wrap prices the text around an insert."""
    names = family_names()
    names['arcana'] = arcana_names()
    widest = {}
    for family, texts in names.items():
        texts = [t for t in texts if t]
        if not texts:
            raise SystemExit(f'port_widths: family {family} has no names - '
                             'run port.py first (boot_tables writes them)')
        widest[family] = max((sum(vwf_wrap.char_width(c) for c in t), t)
                             for t in texts)
    widest['persona+demon'] = max(widest['persona'], widest['demon'])
    return {code: {'family': family, 'px': widest[family][0],
                   'longest': widest[family][1]}
            for code, family in CODE_FAMILY.items()}


def main():
    table = widths()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # Same shape as the repo's other headered tables (boot_tables
    # write_cache): strlib.tsv_rows reads it back, never a positional index.
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\t'.join(COLS) + '\n')
        for code in sorted(table):
            e = table[code]
            f.write('\t'.join((code, e['family'], str(e['px']), e['longest']))
                    + '\n')
    for code, e in sorted(table.items()):
        print(f'port_widths: <{code}> {e["family"]:14s} {e["px"]:3d} px '
              f'({e["longest"]})')
    print(f'port_widths: {len(table)} codes -> {os.path.relpath(OUT, ROOT)}')


if __name__ == '__main__':
    main()
