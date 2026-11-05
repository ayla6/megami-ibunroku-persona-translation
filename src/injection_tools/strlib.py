"""Shared manual/generated merge for strings tables.

Doctrine: auto-derived English lives in translation/generated/<BINARY>/;
manual tables list only rows still needing humans (gaps, over-limit rows
with the real wording in their note, human overrides). Manual wins.
Generated files sit next to their binary, like every other generated
table (ADV/E?.tsv, BTLP.BIN/BTLMSG.tsv, ...): SLPS_005.00 tables under
translation/generated/SLPS_005.00/, BTLP.BIN tables under
translation/generated/BTLP.BIN/.

Row shape is detected from the header (first column = id, plus ja/en/note
columns when present). Values are {id: (ja, en, note)}.
"""
import os
import toolbelt
import re

# Project root, computed locally (never import etext here: etext itself
# reads tables through this module at import time, so a top-level etext
# import would be circular depending on who imports first).
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# gen filename -> path under translation/generated/ (mirrors data/psx layout)
GEN_PATHS = {
    'PERSONAS.tsv': os.path.join('SLPS_005.00', 'PERSONAS.tsv'),
    'DEMONS.tsv': os.path.join('SLPS_005.00', 'DEMONS.tsv'),
    'ITEMS.tsv': os.path.join('SLPS_005.00', 'ITEMS.tsv'),
    'SKILLS.tsv': os.path.join('SLPS_005.00', 'SKILLS.tsv'),
    'NICKNAMES.tsv': os.path.join('SLPS_005.00', 'NICKNAMES.tsv'),
    'BANNER.tsv': os.path.join('BTLP.BIN', 'BANNER.tsv'),
    # Field-trial race names are shared by three overlays, so the generated
    # table lives in strings/ rather than next to one binary.
    'RACES.tsv': os.path.join('strings', 'RACES.tsv'),
    # Affinity blurbs are read by ADV/DNG/S2D/BTLP (shared), same reason.
    'AFFINITY.tsv': os.path.join('strings', 'AFFINITY.tsv'),
    # Descriptions are a SLPS zone but a shared strings worklist too.
    'DESCS.tsv': os.path.join('strings', 'DESCS.tsv'),
    'BTLEVT.tsv': os.path.join('BTLP.BIN', 'BTLEVT.tsv'),
    'BTLMSG.tsv': os.path.join('BTLP.BIN', 'BTLMSG.tsv'),
    'BTLNEG.tsv': os.path.join('BTLP.BIN', 'BTLNEG.tsv'),
    'DNGTEXT.tsv': os.path.join('strings', 'DNGTEXT.tsv'),
    'DNGMSG.tsv': os.path.join('strings', 'DNGMSG.tsv'),
    'S2DSCRIPT.tsv': os.path.join('strings', 'S2DSCRIPT.tsv'),
}


def tsv_cols(path):
    """Header row of a TSV as a list (column order). Pairs with tsv_rows
    when a caller must rebuild positional lists for positional consumers."""
    line = open(path, encoding='utf-8').readline().rstrip('\r\n')
    if not line.strip():
        raise ValueError(f'{path}: empty file (no header row)')
    return line.split('\t')


def tsv_rows(path, required=()):
    """Header-keyed TSV reader: returns a list of dicts keyed by the header
    row. THE rule for every headered table in this repo — never index a
    headered file positionally.

    Fails loudly instead of skipping:
    - missing file -> FileNotFoundError
    - a column in `required` absent from the header -> ValueError
    - a row with MORE fields than the header -> ValueError (path:line +
      content; that is header/row drift, the exact bug class above)
    Rows may be SHORTER than the header (hand edits drop trailing tabs);
      missing fields read as ''.
    Blank lines are skipped. Tabs may not appear inside fields."""
    lines = open(path, encoding='utf-8').read().split('\n')
    if not lines or not lines[0].strip():
        raise ValueError(f'{path}: empty file (no header row)')
    cols = lines[0].rstrip('\r').split('\t')
    missing = [c for c in required if c not in cols]
    if missing:
        raise ValueError(f'{path}: header lacks required column(s) '
                         f'{missing} (has {cols})')
    out = []
    for n, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        f = line.rstrip('\r').split('\t')
        if len(f) > len(cols):
            raise ValueError(f'{path}:{n}: row has {len(f)} fields, '
                             f'header has {len(cols)}: {line[:80]!r}')
        f += [''] * (len(cols) - len(f))
        out.append(dict(zip(cols, f)))
    return out


CODE_RE = re.compile(r'<FF([0-9A-F]{2})>')


def norm(t):
    """Noise-free Japanese for cross-version matching: control codes,
    whitespace and punctuation gone (the JP glyph map drops/misreads a few
    characters; difflib eats the rest)."""
    t = CODE_RE.sub('', t)
    return re.sub(r'[\s\u3000：:、。！？…♥「」\[\]＜＞<>（）()]', '', t)


def tsv_fields(path, arity):
    """Headerless TSV reader (glyph maps, offset pairs): yields the first
    `arity` fields of every non-blank line as a tuple. Fails loudly
    (path:line) when a line has fewer than `arity` fields."""
    with open(path, encoding='utf-8') as f:
        lines = f.read().split('\n')
    for n, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        f = line.rstrip('\r').split('\t')
        if len(f) < arity:
            raise ValueError(f'{path}:{n}: expected >= {arity} tab-separated '
                             f'fields, got {len(f)}: {line[:80]!r}')
        yield tuple(f[:arity])


def _parse(path):
    rows = {}
    if not os.path.exists(path):
        return rows, None
    lines = open(path, encoding='utf-8').read().split('\n')
    cols = lines[0].split('\t')
    idx = {name: i for i, name in enumerate(cols)}
    for line in lines[1:]:
        if not line.strip():
            continue
        f = line.rstrip('\r').split('\t')
        try:
            key = int(f[0])
        except (ValueError, IndexError):
            # loud, never silent: a row we can't key is corruption or a
            # hand-edit breaking the format, and silently dropping rows is
            # how features die without anyone noticing (see tsv_rows).
            print(f'WARNING {path}: unkeyable row skipped (first field '
                  f'{f[0]!r}): {line[:80]!r}')
            continue
        ja = f[idx['ja']] if 'ja' in idx and len(f) > idx['ja'] else ''
        en = f[idx['en']] if 'en' in idx and len(f) > idx['en'] else ''
        note = f[idx['note']] if 'note' in idx and len(f) > idx['note'] else ''
        rows[key] = (ja, en, note)
    return rows, cols


def generated(gen_name):
    """{id: (ja, en, note)} from translation/generated/<BINARY>/<name>."""
    rel = GEN_PATHS.get(gen_name, gen_name)
    rows, _ = _parse(os.path.join(ROOT, 'translation', 'generated', rel))
    if not rows:
        # pre-reorg fallback: translation/generated/strings/<name>
        rows, _ = _parse(os.path.join(ROOT, 'translation', 'generated', 'strings', gen_name))
    return rows


def en_map(gen_name):
    """{ja: en} for filled rows of a generated table (official wording)."""
    return {ja: en for ja, en, note in generated(gen_name).values() if en.strip()}


_GLOSS = None


def glossary(domain=None):
    """{domain: {key: en}} from translation/manual/terms.tsv (translation data
    lives in data files, never as Python literals). Pass a domain for a flat
    {key: en} of just that domain."""
    global _GLOSS
    if _GLOSS is None:
        _GLOSS = {}
        p = toolbelt.GLOSSARY
        if os.path.exists(p):
            for r in tsv_rows(p, required=('domain', 'key', 'en')):
                _GLOSS.setdefault(r['domain'], {})[r['key']] = r['en']
    return _GLOSS if domain is None else _GLOSS.get(domain, {})


def write_worklist(manual_path, header, rows):
    """Write a manual worklist (rows pre-joined without header); removes the
    file when empty (fully auto-covered). Returns the kept row count."""
    if rows:
        os.makedirs(os.path.dirname(manual_path), exist_ok=True)
        with open(manual_path, 'w', encoding='utf-8', newline='\n') as o:
            o.write(header + '\n')
            o.write('\n'.join(rows) + '\n')
        print(f'wrote {manual_path}: {len(rows)} manual rows')
    elif os.path.exists(manual_path):
        os.remove(manual_path)
        print(f'wrote {manual_path}: fully auto-covered, worklist removed')
    return len(rows)


def read(manual_path, gen_name, manual_only=False):
    """{id: (ja, en, note)} merging manual over generated fallback
    (gen_name None = manual only)."""
    rows, _ = _parse(manual_path)
    if manual_only or not gen_name:
        return rows
    gen = generated(gen_name)
    for key, (ja, en, note) in gen.items():
        if not en.strip():
            continue
        cur = rows.get(key)
        if cur is None or not cur[1].strip():
            rows[key] = (cur[0] if cur else ja, en, cur[2] if cur else note)
    return rows
