"""Central doctrine + shared helpers for all PSP->PSX text porters.

DOCTRINE (how things are done and how they look):
- English lives in PSP data files and is read at runtime; Python files
  carry structure only (addresses, indices, Japanese keys). Mapping tables
  live beside the matching tools as source TSV (addresses + Japanese keys, no English).
- translation/generated/ holds TRANSLATIONS ONLY: every row has a non-empty
  `en` cell. A row without a translation MUST NOT be written to generated/
  (no miss markers, no empty cells, no TODO notes) -- generated/ is build
  input, not a worklist.
- translation/manual/ holds human work: gaps (empty `en`), notes, and
  drafts being fixed. Porters never delete human `en` cells or notes.
- Matching rules, in order of strength:
  1. exact: PSX Japanese == PSP Japanese byte-for-byte (unanimous US only);
  2. canonical: both sides pass canonical_ja() first (katakana->hiragana
     script folding + solved control units such as 0x0001 comma). This is a
     deterministic canonicalization, not a similarity judgment: same words,
     different script. Rows ported this way are tagged so the source stays
     auditable;
  3. positional: same slot/order in a known cluster (used only where the
     cluster alignment is proven; tagged as tone/positional matches).
  Similarity/fuzzy judgments NEVER enter generated output; they surface as
  manual notes for human decision.
- Every ported row is verified before writing (control-code skeleton and/or
  QA check, per the target builder). Over-cap rows go in as 'over limit
  N/M; <draft>' notes with empty en (toolbelt.route_over) which builders
  skip; humans shorten the draft into en.
- Porter CLI contract: no args = report only (print counts, write nothing);
  --apply = write. Re-running --apply must be idempotent and must never
  shrink or corrupt existing generated content.
- Connected extraction path: porters never parse game binaries directly.
  The extraction layer (src/extraction_tools/psp/text.py) owns ALL binary
  reads through one decoder per format; its refresh commands (talk-corpus,
  talk-slots, dng, cache) write data/extracted_text/ caches (untracked
  local artifacts) that keep EVERYTHING including undecodable holes, and
  porters consume those caches with automatic refresh when a binary or the
  glyph map is newer than the cache. If you need an original, look in
  extracted_text first -- if it is missing or stale, the refresh path is
  broken; fix that, never work around it with a one-off BIN read.
"""
import csv
import os
import unicodedata
import toolbelt  # noqa: E402


def canonical_ja(t):
    """Deterministic canonical form for text comparison: character WIDTH
    folds (NFKC - the PSX spells Latin, digits, punctuation and spaces
    full-width, the PSP half-width: 'Ｙｅｓ　Ｉ　ｓｅｅ' is 'Yes I see'), then
    katakana folds to hiragana (PSP restyled many answers into katakana;
    same words), and the Japanese comma/full stop fold to the ASCII the PSP
    writes. Control codes are ASCII and pass through untouched."""
    t = unicodedata.normalize('NFKC', t).translate(_PSP_PUNCT)
    return ''.join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ヶ' else c for c in t)


# the PSP spells the Japanese comma and full stop in ASCII ('だから,なんだ?'
# for 'だから、なんだ？'); NFKC leaves them, as they are not width forms
_PSP_PUNCT = str.maketrans({'、': ',', '。': '.'})


def write_generated(path, header, rows):
    """Write a generated translation table. Every row MUST have a non-empty
    `en` cell (column index 2 in [id, ja, en, ...] layout); raises otherwise.
    `rows` is [(id, ja, en, source)].
    """
    for i, ja, en, _src in rows:
        if not en or not en.strip():
            raise SystemExit(
                f'port_common: refusing to write {path}: row {i} '
                f'{ja[:40]!r} has no translation (generated/ holds '
                f'translations only; gaps belong in manual/)')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as o:
        w = csv.writer(o, delimiter='\t', lineterminator='\n')
        w.writerow(header)
        for i, ja, en, src in sorted(rows, key=lambda r: int(r[0])):
            w.writerow([i, ja, en, src])


def load_keyed(path, key=0):
    """{key-col: full row} of a TSV (header skipped)."""
    out = {}
    if not os.path.exists(path):
        return out
    for r in list(csv.reader(open(path, encoding='utf-8'), delimiter='\t'))[1:]:
        if r and len(r) > key:
            out[r[key]] = r
    return out


def ascii_fold(t):
    """Fullwidth ASCII -> ASCII (for diagnostics, not matching)."""
    return ''.join(chr(ord(c) - 0xFEE0) if '！' <= c <= '～' else c for c in t)
