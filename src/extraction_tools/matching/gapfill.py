"""Gap hunter: for each PSX box with no US pair, search the decoded US corpus
for matching content (names/terms via glossary+psp_names, distinctive words
via JP anchor map). Prints top candidates for review.

Usage: python src/extraction_tools/matching/gapfill.py [file] [entry]
Writes nothing; review suggestions, then update a sparse `translation/manual/events/E?.tsv` row if needed.
"""
import csv
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext  # noqa: E402
import efile  # noqa: E402
from text import load_psp  # noqa: E402
from codec import decode_box  # noqa: E402

# JA term -> EN search words (names/places; glossary spellings)
TERMS = {
    'ベルベット・ルーム': ['Velvet Room'], 'イゴール': ['Igor'],
    '他にも': ['Anything else'], 'ご用': ['Anything else'],
    '医師': ['Doctor'], 'うむ': ['Hmm', 'Well'],
    'ただしくん': ['Tadashi'], 'たまきちゃん': ['Tamaki'],
    '大石校長': ['Oishi', 'Principal'], '生徒会長': ['president', 'council'],
    '反谷教頭': ['Hanya', 'Vice Principal', 'vice principal'],
    'ハンニャ教頭': ['Hanya'], '姫野': ['Himeno', 'Yuko'],
    '武多': ['Takeshi'], '神取': ['Kandori'], '梨本みのり': ['Minori'],
    '横内': ['Toro'], 'トロ': ['Toro'], '吉野': ['Yoshino'],
    '夏美': ['Natsumi'], '高見': ['Takami'], '冴子': ['Saeko'],
    '桐島': ['Kirishima'], '綾瀬': ['Ayase'], '上杉': ['Uesugi'],
    '南条': ['Nanjo'], '黛': ['Mayuzumi', 'Yukino'], '稲葉': ['Inaba', 'Mark'],
    '城戸': ['Kido', 'Reiji'], '玲司': ['Reiji'], '園村': ['Sonomura', 'Maki'],
    '麻希': ['Maki'], 'ゆきの': ['Yukino'], 'マーク': ['Mark'],
    'ブラウン': ['Brown'], 'アヤセ': ['Ayase'], 'エリー': ['Elly'],
    '汝の記録': ['inscribe', 'story'], 'アガスティア': ['Agastya'],
    'マヌカン': ['Mannequin', 'Welcome'], '久美': ['Kumi'],
    'ヒホ子': ['Hiho'], '皆殺し': ['die', 'kill'],
    'マキ': ['Maki'],
}


def us_corpus():
    """(file, entry, box, text) for every US box."""
    out = []
    for f in ('E0', 'E1', 'E2', 'E3', 'E4'):
        c = load_psp(f, 'us')
        for ei, e in enumerate(c.entries):
            for k in range(len(e.boxes)):
                t = decode_box(e.box_bytes(k))
                txt = re.sub(r'<FF[0-9A-F]{2}>|\[[0-9a-f]{4}\]', ' ', t)
                out.append((f, ei, k, txt))
    return out


def main():
    only = (sys.argv[1], int(sys.argv[2])) if len(sys.argv) > 2 else None
    corpus = us_corpus()
    from port_story import convert_entry
    by_text = {}
    files = [only[0]] if only else ('E0', 'E1', 'E2', 'E3')
    for f in files:
        import efile as _efile
        n = len(_efile.load(os.path.join(ROOT, 'data', 'psx', 'ADV', f + '.BIN')).entries)
        for ei in range(n):
            if only and ei != only[1]:
                continue
            for k, ja, en, errs in convert_entry(f, ei):
                if en is None:
                    jat = re.sub(r'<FF[0-9A-F]{2}>|<G[0-9A-F]{3}>|<[0-9A-F]{2}>', '', ja)
                    by_text.setdefault(jat, []).append((f, ei, k))
    for jat, locs in sorted(by_text.items(), key=lambda kv: -len(kv[1])):
        if only and (locs[0][0], locs[0][1]) != only:
            continue
        keys = [t for t in TERMS if t in jat]
        if not keys:
            print(f'--- NO-TERMS x{len(locs)} {locs[0]}: {jat[:80]}')
            continue
        want = set(w.lower() for t in keys for w in TERMS[t])
        hits = []
        for f, ei, k, txt in corpus:
            low = txt.lower()
            score = sum(1 for w in want if w.lower() in low)
            if score:
                hits.append((score, f, ei, k, txt[:150]))
        hits.sort(reverse=True)
        print(f'--- x{len(locs)} {locs[0]} terms={keys}: {jat[:70]}')
        for s, f, ei, k, txt in hits[:3]:
            print(f'    [{s}] {f}/{ei} box{k}: {txt[:130]}')


if __name__ == '__main__':
    main()
