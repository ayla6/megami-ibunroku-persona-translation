"""The part-of-speech lexicon the flow reads: src/porting/lexicon/en_pos.tsv.

  python tools/make_lexicon.py [kaikki-English-words.jsonl]

Cut from a kaikki.org Wiktionary extract (one JSON object per entry, with
"word", "pos" and inflected "forms") down to the words the English tables
actually use, so the build never needs the extract itself - it is large,
and kaikki is not a download the build may rely on. An entry's inflected
forms carry its part of speech ("cars" a noun, "easiest" an adjective).
Columns: word, pos (the word's parts of speech, comma-joined: adj, adv,
conj, det, noun, prep, pron, verb; and vt / vi when a verb sense takes an
object / takes none - Wiktionary's transitive and intransitive tags). A word
missing from the file has no part of speech the flow knows.
THE FILE IS HAND-EDITED after this first cut (Wiktionary's rare senses
corrected: "he" is no noun here, "you" no determiner) and is not meant to be
regenerated: a rerun would drop those edits. Add a new word by hand.

https://kaikki.org/simplewiktionary/English/words/index.html
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import toolbelt  # noqa: E402

OUT = os.path.join(ROOT, 'src', 'porting', 'lexicon', 'en_pos.tsv')
# local only (external_tools is not committed): kaikki is not a download
# the build may rely on
SOURCE = os.path.join(ROOT, 'external_tools', 'kaikki',
                      'kaikki.org-dictionary-English-words.jsonl')
KEEP = {'adj', 'adv', 'conj', 'det', 'noun', 'prep', 'pron', 'verb'}


def corpus_words():
    words = set()
    for rel in toolbelt.psx_rels():
        try:
            rows = toolbelt.merged_rows(rel)
        except (OSError, ValueError, SystemExit):
            continue
        for r in rows:
            text = re.sub(r'<[^>]+>', ' ', r.get('en') or '')
            words.update(w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]*", text))
    return words


def lexicon(path, words):
    """{word: {pos}} for the corpus words, read one entry at a time."""
    out = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            entry = json.loads(line)
            pos = entry.get('pos')
            if pos not in KEEP:
                continue
            forms = {entry.get('word', '')}
            forms.update(x.get('form', '') for x in entry.get('forms', []))
            tags = {pos}
            if pos == 'verb':
                for sense in entry.get('senses', []):
                    t = ' '.join(sense.get('tags', []) + sense.get('raw_tags', []))
                    if 'intransitive' in t:
                        tags.add('vi')
                    if re.search(r'(?<!in)transitive', t):
                        tags.add('vt')
            for form in forms:
                # lowercase single words only: names have their own rule,
                # and "more English" is a phrase
                if form and form.islower() and ' ' not in form and form in words:
                    out.setdefault(form, set()).update(tags)
    return out


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else SOURCE
    words = corpus_words()
    lex = lexicon(src, words)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write('word\tpos\n')
        for w in sorted(lex):
            f.write(f'{w}\t{",".join(sorted(lex[w]))}\n')
    print(f'lexicon: {len(lex)} of {len(words)} corpus words '
          f'({sum("adj" in p for p in lex.values())} adjectives, '
          f'{sum("noun" in p for p in lex.values())} nouns) -> {OUT}')


if __name__ == '__main__':
    main()
