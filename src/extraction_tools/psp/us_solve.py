"""One-time bootstrap solver for PSP-US text units -> ASCII (NOT part of the build).

Attack: pattern (repeat structure) + length + frequency-rank matching of
cipher unit-words against a vocabulary snapshot, solved greedily with
bijection consistency, then verified by decoding.

The solved map is saved as codec.py US_MAP; every build-path
script (port_story, port_talk, choices, fmv) decodes discs with that
saved map and never reads the FAQ HTML. You only need this solver if you
want to re-derive the map from scratch, in which case supply your own
--vocab word list (one token per line). No FAQ HTML is required to build.

Usage:
  python src/extraction_tools/psp/us_solve.py vocab --vocab words.txt   vocabulary stats
  python src/extraction_tools/psp/us_solve.py solve     run the solver, write translation/generated_mappings/psp_us_glyphs.tsv
  python src/extraction_tools/psp/us_solve.py check     decode sample boxes with the solved map
"""
import html
import math
import os
import re
import struct
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import strlib  # noqa: E402
from cipher import iter_boxes, box_text_units, SPACE  # noqa: E402

OUT = os.path.join(toolbelt.MAPPINGS, 'psp_us_glyphs.tsv')


def vocab_tokens():
    """Word list for the solver. Preferred: --vocab <words.txt> (one token
    per line, plain text). Alternatively: --html <file> (archive copy of a web
    script transcription, HTML stripped). The build never calls this."""
    if '--vocab' in sys.argv:
        p = sys.argv[sys.argv.index('--vocab') + 1]
        return re.findall(r"[A-Za-z']+", open(p, encoding='utf-8', errors='replace').read())
    if '--html' in sys.argv:
        p = sys.argv[sys.argv.index('--html') + 1]
        d = open(p, encoding='utf-8', errors='replace').read()
        d = re.sub(r'<script.*?</script>', '', d, flags=re.S)
        d = re.sub(r'<style.*?</style>', '', d, flags=re.S)
        d = re.sub(r'<[^>]+>', ' ', d)
        d = html.unescape(d)
        return re.findall(r"[A-Za-z']+", re.sub(r'[ \t\xa0]+', ' ', d))
    raise SystemExit('us_solve: supply --vocab <words.txt> (or legacy --html <file>); '
                      'the saved map in codec.py means the build never needs this solver')


def faq_vocab():
    """word(lowercased, letters+apostrophe only) -> count, plus case variants."""
    words = vocab_tokens()
    c = Counter(w.lower() for w in words)
    return c, len(words)


def pattern_of(word):
    """Repeat-structure signature, e.g. 'hello' -> (0,1,2,2,3)."""
    seen = {}
    return tuple(seen.setdefault(ch, len(seen)) for ch in word)


def cipher_words():
    """unit-word tuple -> count over all US boxes (E0-E4)."""
    words = Counter()
    for _, _, _, raw in iter_boxes('us'):
        units, _ = box_text_units(raw)
        cur = []
        for u in units:
            if u == SPACE:
                if cur:
                    words[tuple(cur)] += 1
                    cur = []
            else:
                cur.append(u)
        if cur:
            words[tuple(cur)] += 1
    return words


def cmd_vocab():
    c, n = faq_vocab()
    print(f'FAQ tokens: {n}, distinct lowercase words: {len(c)}')
    for w, cnt in c.most_common(40):
        print(f'  {w:<12} {cnt}')


def cmd_solve():
    fvocab, _ = faq_vocab()
    cwords = cipher_words()
    # index FAQ words by (length, pattern)
    index = defaultdict(Counter)
    for w, cnt in fvocab.items():
        if len(w) <= 12:
            index[(len(w), pattern_of(w))][w] = cnt
    # greedy: most frequent cipher words first
    unit2ch = {}
    ch2unit = {}
    log = []
    for cw, ccnt in cwords.most_common(4000):
        key = (len(cw), pattern_of(cw))
        cands = index.get(key)
        if not cands:
            continue
        # candidates consistent with current partial map, ranked by freq proximity
        best = None
        for w, wcnt in cands.most_common(25):
            ok = True
            for u, ch in zip(cw, w):
                if u in unit2ch and unit2ch[u] != ch:
                    ok = False
                    break
                if ch in ch2unit and ch2unit[ch] != u:
                    ok = False
                    break
            if not ok:
                continue
            score = abs(math.log((ccnt + 1) / (wcnt + 1)))
            if best is None or score < best[0]:
                best = (score, w)
        if best is None:
            continue
        _, w = best
        # only accept if it adds information or strongly confirms
        new = sum(1 for u, ch in zip(cw, w) if u not in unit2ch)
        if new == 0:
            continue
        for u, ch in zip(cw, w):
            unit2ch[u] = ch
            ch2unit[ch] = u
        log.append((ccnt, ' '.join('%04x' % u for u in cw), w))
    print(f'solved {len(unit2ch)} units from {len(log)} anchor words')
    for ccnt, cwhex, w in log[:60]:
        print(f'  x{ccnt:<6} {cwhex:<40} {w}')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        for u in sorted(unit2ch):
            f.write(f'{u:04x}\t{unit2ch[u]}\n')
    print('wrote', OUT)
    # coverage: fraction of all text units explained
    tot = sum(cwords.values())
    covered_units = 0
    total_units = 0
    for cw, ccnt in cwords.items():
        for u in cw:
            total_units += ccnt
            if u in unit2ch:
                covered_units += ccnt
    print(f'unit coverage: {covered_units}/{total_units} '
          f'({100 * covered_units / total_units:.1f}%)')


def load_map():
    m = {}
    for u, ch in strlib.tsv_fields(OUT, 2):
        m[int(u, 16)] = ch
    return m


def cmd_check():
    from text import load_psp
    m = load_map()
    c = load_psp('E0', 'us')
    for i in (0, 1):
        e = c.entries[i]
        for k in range(min(3, len(e.boxes))):
            raw = e.box_bytes(k)
            units, _ = box_text_units(raw)
            print(f'-- E0/{i} box{k}: ' + ' '.join(m.get(u, f'[{u:04x}]') for u in units))
    print(f'map size: {len(m)}')


if __name__ == '__main__':
    if sys.argv[1] == 'vocab':
        cmd_vocab()
    elif sys.argv[1] == 'solve':
        cmd_solve()
    elif sys.argv[1] == 'check':
        cmd_check()
