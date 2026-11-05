"""Fact-check PSP wording against the PSX game before any of it may be auto-added.

The PSP remake rebalanced the game, so a PSP line that states a game fact
(a damage share, a heal amount, a count) may describe the PSP's own rules
rather than the PSX's. The affinity family is the proven case: the PSP
lines there state the PSP's affinity rules and contradict the PSX table
(port_affinity.py refuses that family outright). This tool asks the same
question of every other paired row it can resolve, and it asks it
mechanically: it compares the NUMBERS in the PSX Japanese against the
numbers in the PSP-US wording. Numbers are language-independent, so the
check crosses JP->EN without any typed vocabulary.

Verdicts (the whole output; no wording is stored here):
  numbers-match       both sides state the same numeric facts
  numbers-differ      both sides state numbers and they disagree -> the PSP
                      line describes different rules; it must not be ported
  psp-only-numbers    the PSP carries every number the PSX states, plus
                      extras (the PSX text may have dropped them under its
                      length cap, or the PSP added a duration/percentage)
  psx-only-numbers    only the PSX side carries numbers (the PSP text
                      reworded away a fact)
  no-numbers          no numeric fact on either side; not mechanically
                      verifiable here

Sections:
  descs  skill/item descriptions, paired by src/extraction_tools/matching/descs_bank.tsv
         (psx string index -> PSP-US boot description bank offset)
  rows   every translation row carrying an EBOOT: pointer (the family
         tables: names, affinity, ...), joined through the extracted text
         on both sides (extracted_text/psx vs extracted_text/psp_us)

Usage: python src/extraction_tools/matching/factcheck.py
Output: data/derived/factcheck.tsv (one row per compared pair) + a summary.
The porters read the verdicts through verdicts() and refuse to auto-add
anything whose numbers differ - see port_descs.py / port_affinity.py.
"""
import collections
import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
import toolbelt  # noqa: E402
import strlib  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'derived', 'factcheck.tsv')
NL = chr(10)

_DIGITS = re.compile(r'[0-9０-９]+')
TOKEN = re.compile(r'<[^>]*>')          # control codes (<FF01>, <FF03>, ...) carry hex digits that are not facts


def numbers(s):
    """Multiset of integers stated in s. Full-width digits normalize; every
    other character is ignored, so this works for Japanese and English.
    Control-code tokens are stripped first: <FF01>'s "01" is not a fact."""
    out = collections.Counter()
    for m in _DIGITS.finditer(TOKEN.sub('', s or '')):
        out[int(unicodedata.normalize('NFKC', m.group(0)))] += 1
    return out


def verdict(ja, en):
    a, b = numbers(ja), numbers(en)
    if not a and not b:
        return 'no-numbers'
    if a == b:
        return 'numbers-match'
    if not a:
        return 'psp-only-numbers'
    if not b:
        return 'psx-only-numbers'
    # Extras are PSP additions, not contradictions: a line that keeps every
    # PSX fact and adds a duration/percentage is still accurate to the PSX
    # text. Only a PSX number that is missing or changed is a contradiction.
    if all(b[k] >= v for k, v in a.items()):
        return 'psp-only-numbers'
    return 'numbers-differ'


def _fmt(c):
    return ','.join(f'{k}x{v}' if v > 1 else str(k) for k, v in sorted(c.items())) or '-'


# ---------------------------------------------------------------------------
# section descs: PSX description strings vs the PSP-US boot description bank
# ---------------------------------------------------------------------------

def section_descs():
    import descs
    import etext
    import port_descs
    d = descs.data()
    bank, slots = port_descs.bank_map(), port_descs.slot_map()
    out = []
    for i, (a, e) in enumerate(descs.strings(d)):
        if i not in slots:
            continue
        ja = etext.decode(d[a - descs.B:e - descs.B])
        en = port_descs.bank_text(bank, slots[i])
        if not en:
            continue
        out.append({'family': 'descs', 'key': f'string {i}',
                    'pos': hex(a - descs.B), 'psp': f'EBOOT:{slots[i]:x}',
                    'psx': ja, 'us': en, 'verdict': verdict(ja, en)})
    return out


# ---------------------------------------------------------------------------
# section rows: every translation row with an EBOOT: pointer
# ---------------------------------------------------------------------------

def _extract(region, rel):
    path = os.path.join(ROOT, 'data', 'extracted_text', region, *rel.split('/')) + '.tsv'
    if not os.path.exists(path):
        return {}
    out = {}
    for r in strlib.tsv_rows(path, required=('pos', 'text')):
        out[int(r['pos'], 16)] = r['text']
    return out


# ---------------------------------------------------------------------------
# name preservation: a fact the numbers cannot see
#
# "宝石：ターコイズ" (Gem: Turquoise) ports as "A beautiful gem" - the PSP
# wording drops WHICH gem it is. A name is a fact, so a PSP line that loses
# one is not accurate to the PSX line. The names come from the established
# pairings themselves (translation rows whose en a human or the verified
# name porters already carry), restricted to the name-table families by
# their own record ranges - nothing is typed here.
# ---------------------------------------------------------------------------

def name_pairs():
    """[(ja_name, us_name)] from the name-table rows of the row store."""
    import demons
    import items
    import personas
    import skills
    psx = _extract('psx', 'SLPS_005.00')
    base = 0x80010000 - 0x800
    spans = []
    for mod in (skills, items, personas, demons):
        first = getattr(mod, 'FIRST', None) or getattr(mod, 'REC0', None)
        span = mod.COUNT * mod.STRIDE
        if first:
            spans.append((first - base, first - base + span))
    out = []
    for r in strlib.tsv_rows(os.path.join(ROOT, 'translation', 'generated', 'SLPS_005.00.tsv'),
                             required=('pos', 'en')):
        en = r['en'].strip()
        if not en:
            continue
        off = int(r['pos'], 16)
        if not any(lo <= off < hi for lo, hi in spans):
            continue
        ja = psx.get(off, '').strip()
        if ja:
            out.append((ja, en))
    return out


def _norm(s):
    return ' '.join((s or '').split()).lower()


def names_verdict(ja, us, names):
    """'kept' / 'dropped' / 'na' - does the PSP line keep every name the
    PSX line states? 'na' when the PSX line names nothing."""
    u = _norm(us)
    mentioned = [(j, en) for j, en in names if len(j) >= 2 and j in ja]
    if not mentioned:
        return 'na'
    dropped = [en for j, en in mentioned if _norm(en) not in u]
    return 'dropped' if dropped else 'kept'


def section_rows():
    import toolbelt
    psx = _extract('psx', 'SLPS_005.00')
    us = _extract('psp_us', 'EBOOT')
    out = []
    for r in toolbelt.read_generated('SLPS_005.00', optional=True):
        psp = (r.get('psp') or '').strip()
        if not psp.startswith('EBOOT:'):
            continue
        off = int(psp.split(':', 1)[1], 16)
        # EBOOT.tsv rows anchor at the first glyph; the pointer is the box
        # start, so the text can sit a byte or two later (boot_pairs rule).
        ja, en = psx.get(int(r['pos'], 16)), us.get(off)
        if en is None:
            en = next((us[o] for o in (off + 1, off + 2, off + 3) if o in us), None)
        if ja is None or en is None:
            continue
        out.append({'family': 'rows', 'key': r['id'], 'pos': r['pos'],
                    'psp': psp, 'psx': ja, 'us': en, 'verdict': verdict(ja, en)})
    return out


def main():
    names = name_pairs()
    rows = section_descs() + section_rows()
    for r in rows:
        r['names'] = names_verdict(r['psx'], r['us'], names)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', newline=NL) as o:
        o.write('family\tkey\tpos\tpsp\tpsx_numbers\tus_numbers\tnames\tverdict\tpsx\tus' + NL)
        for r in rows:
            o.write('\t'.join([r['family'], r['key'], r['pos'], r['psp'],
                               _fmt(numbers(r['psx'])), _fmt(numbers(r['us'])),
                               r['names'], r['verdict'], r['psx'].replace('\t', ' '),
                               r['us'].replace('\t', ' ')]) + NL)
    for fam in sorted({r['family'] for r in rows}):
        c = collections.Counter(r['verdict'] for r in rows if r['family'] == fam)
        total = sum(c.values())
        print(f'{fam}: {total} pairs')
        for v, n in c.most_common():
            print(f'    {v:18} {n}')
    bad = [r for r in rows if r['verdict'] == 'numbers-differ']
    lost = [r for r in rows if r['names'] == 'dropped']
    print(f'\n{len(bad)} pairs state CONTRADICTING numbers:')
    for r in bad[:15]:
        print(f'  [{r["family"]}] {r["key"]} {r["pos"]}: '
              f'{_fmt(numbers(r["psx"]))} vs {_fmt(numbers(r["us"]))}')
    print(f'\n{len(lost)} pairs DROP a name the PSX line states:')
    for r in lost[:15]:
        print(f'  [{r["family"]}] {r["key"]} {r["pos"]}: JP {r["psx"]} | US {r["us"]}')
    print(f'\n-> {OUT}')


def portable():
    """{(family, pos): True/False} for the porters' auto-add gate. A PSP
    line may be auto-added unless its numbers CONTRADICT the PSX line; a
    dropped name is advisory (kept in the report), because where the PSX and
    PSP-JP lines agree on the fact the PSP-US's shorter form is intentional
    localization - and the name is on screen in the same menu."""
    out = {}
    for r in section_descs() + section_rows():
        out[(r['family'], r['pos'])] = r['verdict'] != 'numbers-differ'
    return out


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
