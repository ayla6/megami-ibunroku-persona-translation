"""Report generated rows whose stored source does not say the row's Japanese.

`translation/generated/**` is DERIVED data: every row's `psp` names the
PSP-US unit its wording came from, and `port_lastresort.renorm_generated`
re-reads that unit on every run. That makes a row's provenance stable but not
CERTIFIED: the pointer is only ever re-read, never re-JUSTIFIED, so a row
written by an older pairing (a bank whose two builds order it differently,
paired one slot off) keeps its wording forever - a re-derivation from the same
pointer reproduces the same wrong line, and the porter that would have got it
right no longer claims the position, so nothing overwrites it.

This asks the pair map the other way round: the pointer's Japanese twin must
say what the row's Japanese says. Where it does not, the row is carrying a
neighbouring line's English.

READ ONLY. It prints; it never writes a table. Withdrawing a row is a data
decision (`toolbelt.unport`) and belongs to whoever owns the wording.

usage: pair_audit.py [rel ...]        (default: every rel with a generated table)
"""
import difflib
import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'matching'))
import toolbelt  # noqa: E402
import match_jp  # noqa: E402

CODE = re.compile(r'<FF[0-9A-Fa-f]{2,4}>')
LABEL = re.compile(r'^\s*(?:<FF1B>[^<]{1,24}<FF03>|[^<>：:<]{1,14}[：:])')
PUNCT = re.compile(r'[\s\u3000、。，．,.!?！？:：;；…‥・「」『』\u201c\u201d\u2019\'"'
                   r'()（）＞＜\[\]〜~ー\-－÷×※☆★◆◇○●△□♥♠♣]')
SAME = 0.7                      # a reworded line still shares this much kana


def core(text):
    """The line as comparable Japanese: no label, no codes, no punctuation.

    The two builds spell the same line differently on purpose (the PSP adds
    its own punctuation, wraps a name in <FF1B>..<FF03>, keeps a glitch cell
    before the wording), so what is compared is the CELLS, folded to one
    width, with everything the layout adds removed."""
    t = LABEL.sub('', text or '')
    t = CODE.sub('', t)
    t = unicodedata.normalize('NFKC', PUNCT.sub('', t))
    return PUNCT.sub('', t)


def same_line(ja, jp):
    """Do these two Japanese lines say the same thing (see SAME)?"""
    a, b = core(ja), core(jp)
    if not a or not b:
        return True                 # nothing to judge by
    if a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= SAME


def audit(rel):
    """[(pos, psp, ja, twin, en)] - rows whose source says a different line."""
    ja_of = toolbelt.psx_text_of(rel)
    out = []
    for r in toolbelt.read_generated(rel, optional=True) or []:
        psp = (r.get('psp') or '').strip()
        ja = ja_of.get(r['pos'], '')
        if ':' not in psp or not ja.strip():
            continue
        name = psp.split(':', 1)[0]
        if not toolbelt.psp_rel(name):
            continue                # a family slot pointer, not a PSP unit
        twin = match_jp.jp_text_of_us(psp)
        if not twin.strip():
            continue                # no pair: nothing to judge by
        if same_line(ja, twin):
            continue
        out.append((r['pos'], psp, ja, twin, r.get('en') or ''))
    return out


def main():
    rels = sys.argv[1:]
    if not rels:
        rels = []
        for root, _dirs, files in os.walk(os.path.join(ROOT, 'translation', 'generated')):
            for fn in sorted(files):
                if fn.endswith('.tsv'):
                    rels.append(os.path.relpath(os.path.join(root, fn),
                                                os.path.join(ROOT, 'translation', 'generated'))[:-4])
    total = 0
    for rel in sorted(rels):
        try:
            rows = audit(rel)
        except SystemExit:
            continue
        if not rows:
            continue
        total += len(rows)
        print(f'pair_audit: {rel}: {len(rows)} row(s) whose source says another line')
        for pos, psp, ja, twin, en in rows:
            flat = lambda s: re.sub(r'\s+', ' ', s).strip()
            print(f'  {pos}  {psp}')
            print(f'    row says   {flat(ja)[:70]}')
            print(f'    source says {flat(twin)[:70]}')
            print(f'    shipping   {flat(en)[:70]}')
    print(f'pair_audit: {total} row(s) to review')


if __name__ == '__main__':
    main()
