"""Shared PSP BOOT readers and u16 text-table decoders.

Both PSP regions store menu/name text as u16 code units; the same helpers
serve the BOOT extractors (`boot.py`, `boot_tables.py`) and the pack survey
(`survey.py`) so table layouts are decoded in exactly one place:

* LE C-strings (0000-terminated, 0000/8140 = space): menus, race lists.
* BE FFFF-padded fixed records: persona/demon/skill/item name tables.
* BE FF03-separated option blob: dialogue-choice table.

Glyph codecs live in `codec.py` (US) and `src/extraction_tools/psp_glyphs.tsv`
(JP); this module only moves bytes.
"""
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import strlib  # noqa: E402
from codec import US_MAP, param_take  # noqa: E402

JP_BOOT = os.path.join(ROOT, 'data', 'psp_jp', 'PSP_GAME', 'SYSDIR', 'BOOT.BIN')
US_EBOOT = os.path.join(ROOT, 'data', 'psp_us', 'PSP_GAME', 'SYSDIR', 'EBOOT.BIN')
US_CACHE = os.path.join(ROOT, 'build', 'us_boot_decrypted.bin')

US_LE = {k: v for k, v in US_MAP.items() if k != 0x0000}
US_KNOWN = set(US_LE.keys())
US_SPACE = 0x8140

# Dialogue control codes (u16 units) used inside BE text runs; kept as
# <FFxx> tokens. FF01 ends a box, FF03 is a newline, FF02/FF04 wait/new
# page, FF0E a choice; the FFFx set are the talk-engine codes. FF00 is
# NOT a code (data noise only).
BE_CODE_LO, BE_CODE_HI = 0xFF01, 0xFF0F
BE_TALK_CODES = {0xFFEF, 0xFFF0, 0xFFF2, 0xFFF3, 0xFFF4,
                 0xFFF5, 0xFFF8, 0xFFF9, 0xFFFA, 0xFFFC}


def is_code(u):
    return BE_CODE_LO <= u <= BE_CODE_HI or u in BE_TALK_CODES


def is_ctrl(u):
    """A unit that is a control code (FF xx) - never a glyph, and the
    parameter units that follow one belong to it. `is_code` is the
    porters' narrower set; the box scan takes every FF unit, because a FF
    unit is a code even where the map has not named it, and reading its
    parameter as a glyph-map hole shreds a box at every '<FF18>' that
    carries one."""
    return 0xFF01 <= u <= 0xFF1F or 0xFFF0 <= u <= 0xFFFE


def is_text(s):
    """Text-shape filter for decoded runs. Rejects font/texture filler
    ('aaaa', 'QQQQ'), glyph-sheet rows ('A B C D', 'DEFGH IJ K') and other
    binary noise that strict glyph decoding alone still lets through."""
    s = s.strip()
    if len(s) < 3:
        return False
    if sum(c.isalpha() for c in s) < 2:
        return False
    if len(set(s)) < 3:
        return False
    if max(s.count(c) for c in set(s)) > len(s) * 0.5:
        return False
    letters = [c for c in s if c.isalpha()]
    if not any(c in 'aeiouAEIOU' for c in s) and not any(ord(c) > 127 for c in s):
        return False                       # 'Y Y', 'b.c': consonant noise rows
    if all(c.isupper() for c in letters) and len(set(letters)) >= 10:
        return False                       # font-sheet alphabet rows
    return True


def be_units(data, glyphs=None, max_gap=3):
    """[(offset, text, term)] every BE text unit of an image, in file
    order - the extraction's scanner (be_runs is the porters' reader).

    A unit is a text box: from the first unit after the padding to the
    FF01 that ends it, or a padded record (FFFF/0000). Unknown codes stay
    INLINE as '<%04X>' placeholders, so a box is never split at a code
    the glyph map has not solved yet and never dropped for not reading
    like prose.

    The line between text and data is structural: text carries unsolved
    codes sprinkled through it (a few units), code and pointer tables
    carry them in streaks. So a unit ends at a streak of >max_gap unknown
    units, and a run of data that never reaches a terminator is not a
    unit at all (more unknowns than decoded units). The dump records
    what the disc holds; readers decide what to use."""
    if glyphs is None:
        glyphs = US_MAP
    glyphs = dict(glyphs)
    glyphs.setdefault(US_SPACE, ' ')
    glyphs.setdefault(0x0000, ' ')       # single zero: the space glyph
    # (double zero is the inter-record padding the scan splits at)
    n = len(data) // 2
    w = struct.unpack('>%dH' % n, data[:n * 2])

    def tok(u):
        return glyphs[u] if u in glyphs else '<%04X>' % u

    out = []
    i = 0
    while i < n:
        if w[i] == 0xFFFF:
            i += 1
            continue
        if w[i] == 0 and i + 1 < n and w[i + 1] == 0:
            j = i
            while j < n and w[j] == 0:
                j += 1
            if j >= n or w[j] == 0xFFFF:
                i = j
                continue
            i = j - 1        # padding before text: the unit starts at the
            # fall through   # padding's last zero, the space glyph (the
                             # offsets the porters' pointers name)
        j, known, unk, term = i, 0, 0, ''
        while j < n:
            u = w[j]
            if u == 0xFFFF or (u == 0 and j + 1 < n and w[j + 1] == 0):
                term = 'FFFF' if u == 0xFFFF else '0000'
                break
            if u in glyphs or is_code(u):
                if is_code(u) or glyphs.get(u, ' ').strip():
                    known += 1        # spaces do not make text: data
                unk = 0               # decodes to spaces
            else:
                unk += 1
                if unk > max_gap:      # data, not text: stop before the
                    j -= max_gap       # streak and keep the decoded run
                    unk = max_gap
                    break
            j += 1
            if u == 0xFF01:
                term = 'FF01'
                break
        # a unit is its decoded text: codes the map has not solved are
        # noise, and a run with more noise than text is data (font sheets,
        # pointer tables). Every terminated unit is kept - it is a unit of
        # the disc whatever the map solves today; only un-terminated runs
        # of data are not units at all.
        if not term and not (known and known > unk):
            i = max(j, i + 1)
            continue
        # the text is decoded the same way as a box's (unit_tokens' param
        # rule): a control's parameter units belong to the code and are
        # never printed as the glyph their id happens to name
        toks, k = [], i
        while k < j:
            u = w[k]
            if is_ctrl(u):
                op = u & 0xFF
                toks.append('<FF%02X>' % op)
                k += 1
                take, is_id = param_take(op, w[k] if k < j else None,
                                         w[k + 1] if k + 1 < j else None)
                while take and k < j and (is_id or w[k] not in glyphs):
                    toks.append('<%04X>' % w[k])
                    k += 1
                    take -= 1
                continue
            toks.append(tok(u))
            k += 1
        out.append((i * 2, ''.join(toks), term))
        i = max(j, i + 1)
    return out


def be_boxes(data, glyphs=None, max_gap=3, min_units=2):
    """[(offset, text, term)] every TEXT BOX of an image - one row per box.

    `be_units` keeps a unit whole, which is right for the porters' pointer
    view but wrong as the extract: a name-table record merges the table
    header in front of its name into one row, and a run of data that never
    reaches a terminator becomes one row of megabytes. A BOX is what a
    reader wants: one unit of text, split at every FF01 and at the record
    padding, with the data around it left out.

    Two rules make the difference from a plain word scan:

    * spaces do not RESET the unknown streak. Data regions read as
      'word 0000 word 0000'; with a space counting as text the scan walks
      a whole pointer table and calls it one box.
    * a box carries language (letters, kana, kanji) and mostly reads as
      language - a few unsolved codes sprinkled through text are normal,
      a box that is mostly codes is the table around it.

    Unknown codes stay INLINE as '<%04X>' placeholders: a box is never
    split at a code the map has not solved and never dropped for one."""
    if glyphs is None:
        glyphs = US_MAP
    glyphs = dict(glyphs)
    glyphs.setdefault(US_SPACE, ' ')
    glyphs.setdefault(0x0000, ' ')
    n = len(data) // 2
    w = struct.unpack('>%dH' % n, data[:n * 2])

    def solid(u):
        """a unit that makes text: a glyph that is not a space, or a code"""
        return is_ctrl(u) or glyphs.get(u, ' ').strip() != ''

    out = []
    i = 0
    while i < n:
        if w[i] == 0xFFFF or (w[i] == 0 and i + 1 < n and w[i + 1] == 0):
            i += 1
            continue
        j, unk, term = i, 0, ''
        while j < n:
            u = w[j]
            if u == 0xFFFF or (u == 0 and j + 1 < n and w[j + 1] == 0):
                term = 'FFFF' if u == 0xFFFF else '0000'
                break
            if u in glyphs or is_ctrl(u):
                if solid(u):
                    unk = 0     # a space is padding as much as it is a
                # word gap: it never proves text and never ends a streak
                # of table around it
            else:
                unk += 1
                if unk > max_gap:
                    j -= max_gap
                    unk = max_gap
                    break
            j += 1
            if u == 0xFF01:
                term = 'FF01'
                break
        for ks, tm in _split_boxes(w, i, j, term):
            s = trim_box(unit_tokens(w, ks[0], ks[-1] + 1, glyphs))
            if len(s) >= min_units and is_box_text(s):
                out.append((ks[0] * 2, s, tm))
        i = max(j, i + 1)
    return out


def unit_tokens(w, lo, hi, glyphs):
    """[(text, kind)] one box's units as tokens: a glyph, a control code
    with its parameter units, or a hole - a unit the glyph map has not
    solved. A control's parameters are part of the CODE and are never
    text or holes (reading one shreds a box at every '<FF18>' that carries
    one). WHICH units a code takes is codec.param_take's one rule - an id
    is eaten whatever it reads as, a number parameter never eats a letter
    - and every decoder calls that; nothing re-derives it here."""
    out, k = [], lo
    while k < hi:
        u = w[k]
        if is_ctrl(u):
            op = u & 0xFF
            out.append(('<FF%02X>' % op, 'code'))
            k += 1
            take, is_id = param_take(op, w[k] if k < hi else None,
                                     w[k + 1] if k + 1 < hi else None)
            while take and k < hi and (is_id or w[k] not in glyphs):
                out.append(('<%04X>' % w[k], 'code'))
                k += 1
                take -= 1
            continue
        out.append((glyphs[u], 'glyph') if u in glyphs
                   else ('[%04x]' % u, 'hole'))
        k += 1
    return out


def _split_boxes(w, lo, hi, term):
    """[(unit range, term)] the FF01 boxes inside one decoded run - the
    terminator belongs to the box it ends."""
    parts, cur, tm = [], [], term
    for k in range(lo, hi):
        cur.append(k)
        if w[k] == 0xFF01:
            parts.append((cur, 'FF01'))
            cur, tm = [], term
    if cur:
        parts.append((cur, tm))
    return parts


def trim_box(toks):
    """A box's text with the record framing around it left out.

    A name table hands the scan its name WITH the table header in front of
    it ('<0200><0100><0070>p <B004> <2100><08A0>Rapier'), and a skill
    table hands its description behind a pointer table - both decode into
    stray letters and spaces that are not text. The signal is the holes:
    a text box carries a few unsolved codes sprinkled through it, a table
    carries them in streaks. So the box is cut at every streak of two or
    more holes, the piece that carries the text is kept, and it is trimmed
    to its words - extended over what of the box is not data (a floor
    suffix '  西' behind the name, the '＞' and the closing codes of a
    dialogue box)."""
    gaps, k = [], 0
    while k < len(toks):
        if toks[k][1] == 'hole':
            j = k
            while j < len(toks) and toks[j][1] == 'hole':
                j += 1
            if j - k >= 2:
                gaps.append((k, j))
            k = j
        else:
            k += 1
    parts, prev = [], 0
    for a, b in gaps + [(len(toks), len(toks))]:
        parts.append(toks[prev:a])
        prev = b
    best, best_spoken = '', -1
    for part in parts:
        s = _trim_span(part)
        if (_spoken(s), -len(s)) > (best_spoken, -len(best)):
            best, best_spoken = s, _spoken(s)
    return best


def _spoken(s):
    """How much text a piece carries - the letters, kana and kanji in it.
    Not its length: spaces and stat bytes do not count as language."""
    return sum(1 for c in _BOX_HOLE.sub('', _BOX_CODE.sub('', s))
               if not c.isspace())


def _trim_span(toks):
    """One piece of a box, cut back to the words it carries: the span from
    the first real word to the last, extended over the rest of the piece
    that is not data (a single unsolved code inside the text stays)."""
    runs, cur = [], []
    for k, (s, kind) in enumerate(toks):
        if kind == 'glyph' and s.strip():
            cur.append(k)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    # anchor on the runs that carry language: a data word that happens to
    # decode ('・' is a mapped glyph the pointer tables are full of) is
    # never where a box's text starts
    big = [r for r in runs
           if _BOX_LANG.search(''.join(toks[i][0] for i in r))]
    big = big or [r for r in runs if len(r) >= 2] or runs
    if not big:
        return ''
    lo, hi = big[0][0], big[-1][-1] + 1
    while lo > 0 and toks[lo - 1][1] != 'hole':
        lo -= 1
    while hi < len(toks) and toks[hi][1] != 'hole':
        hi += 1
    return ''.join(t[0] for t in toks[lo:hi])


# Language is letters and kana/kanji - NOT the punctuation the maps carry
# ('・', '＞', '。'): a data word that decodes to '・' is not a word, and a
# run of them is a pointer table, not prose.
_BOX_LANG = re.compile(
    r'[A-Za-z]{2}'
    r'|[\u3041-\u3096\u30a1-\u30fa\u30fc-\u30ff\u4e00-\u9fff]{2,}'
    r'|[\uff10-\uff19\uff21-\uff3a]{2,}')
# codec.decode_box's two bracket forms: '<...>' is a control code or a
# control's parameter (structure, never a hole), '[xxxx]' is a unit the
# glyph map has not solved (the hole that still needs a glyph).
_BOX_CODE = re.compile(r'<[^>]*>')
_BOX_HOLE = re.compile(r'\[[0-9a-fA-F]{4}\]')


def is_box_text(s):
    """A box is text when it carries language and mostly reads as language.
    The language test is the same shape test `is_text` makes, without its
    prose-only guards: a two-character floor name or a shop sign is a box
    just as much as a sentence."""
    plain = _BOX_HOLE.sub('', _BOX_CODE.sub('', s))
    if not _BOX_LANG.search(plain):
        return False
    holes = len(_BOX_HOLE.findall(_BOX_CODE.sub('', s)))
    spoken = _spoken(s)
    return bool(spoken) and holes <= spoken * 0.5


def be_runs(data, glyphs=None, min_units=3, with_spans=False):
    """[(offset, text, term)] BE text records over the whole image.

    A record is a maximal run of known glyph / control-code units, split at
    each FF01 (box end, kept in the text) and at 2+ consecutive 0x0000
    (inter-record padding; single 0x0000 is the space glyph, so word gaps
    stay inside the record). `term` is the record's terminator: 'FF01',
    'FFFF' (padded name slot), '0000' (C-string slot) or '' (run cut by
    unknown units). Records that fail is_text() on their code-stripped
    content are dropped. With `with_spans`, append the exclusive physical
    end offset, so callers can exclude opposite-endian scan collisions."""
    if glyphs is None:
        glyphs = US_MAP
    glyphs = dict(glyphs)
    glyphs.setdefault(US_SPACE, ' ')   # 0x8140: full-width space, used as word gap in some banks
    n = len(data) // 2
    words = struct.unpack('>%dH' % n, data[:n * 2])

    def ok(k):
        return words[k] in glyphs or is_code(words[k])

    def pad(k):
        return k + 1 < n and words[k] == 0 and words[k + 1] == 0

    out = []
    i = 0
    while i < n:
        if ok(i) and not pad(i):
            j = i
            while j < n and ok(j) and not pad(j):
                j += 1
            term = ''
            if j < n and words[j] == 0xFFFF:
                term = 'FFFF'
            elif j < n and words[j] == 0:
                term = '0000'
            # split into boxes at FF01
            parts, cur = [], []
            for k in range(i, j):
                cur.append(k)
                if words[k] == 0xFF01:
                    parts.append((cur, 'FF01'))
                    cur = []
            if cur:
                parts.append((cur, term))
            for ks, tm in parts:
                toks = []
                plain = []
                for k in ks:
                    u = words[k]
                    if is_code(u):
                        toks.append('<%04X>' % u)
                    else:
                        toks.append(glyphs[u])
                        plain.append(glyphs[u])
                s = ''.join(toks)
                if len(ks) >= min_units and is_text(''.join(plain)):
                    row = (ks[0] * 2, s, tm)
                    out.append(row + ((ks[-1] + 1) * 2,) if with_spans else row)
            i = j if j > i else i + 1
        else:
            i += 1
    return out

_jpm = None
_us = None


def jp_map():
    """{code: char} JP glyph map (cached)."""
    global _jpm
    if _jpm is None:
        _jpm = {}
        for u, ch in strlib.tsv_fields(toolbelt.PSP_GLYPHS, 2):
            _jpm[int(u, 16)] = ch
    return _jpm


def us_boot(path=None):
    """Decrypted US BOOT bytes (decrypts via pyeboot on first run)."""
    global _us
    if path:
        return open(path, 'rb').read()
    if _us is not None:
        return _us
    if os.path.exists(US_CACHE):
        _us = open(US_CACHE, 'rb').read()
        return _us
    try:
        import pyeboot
    except ImportError:
        raise SystemExit('boot: US BOOT is encrypted; install requirements.txt or pass --us-boot <decrypted>')
    os.makedirs(os.path.dirname(US_CACHE), exist_ok=True)
    ok = pyeboot.decrypt(US_EBOOT, US_CACHE)
    if not ok or not os.path.exists(US_CACHE):
        raise SystemExit('boot: pyeboot.decrypt failed on ' + US_EBOOT)
    _us = open(US_CACHE, 'rb').read()
    return _us


def jp_boot():
    return open(JP_BOOT, 'rb').read()


def le_string_at(data, off, glyphs, space=None, with_end=False):
    """Read one LE 0000-terminated string at a proven pointer, not a scan head.

    A preceding BE terminator can itself decode as an LE glyph. Scanning
    then absorbs that glyph into the next name; a pointer proves the true
    start without guessing from the wording. Unknown or unterminated input
    fails instead of returning a partial name. With `with_end`, also return
    the physical end offset including the terminator.
    """
    if off < 0 or off % 2 or off >= len(data):
        raise ValueError(f'invalid LE string pointer {off:#x}')
    chars = []
    for at in range(off, len(data) - 1, 2):
        u = struct.unpack_from('<H', data, at)[0]
        if u == 0:
            if not chars:
                raise ValueError(f'empty LE string at {off:#x}')
            text = ''.join(chars)
            return (text, at + 2) if with_end else text
        if space is not None and u == space:
            chars.append(' ')
        elif u in glyphs:
            chars.append(glyphs[u])
        else:
            raise ValueError(f'unknown LE unit {u:#x} at {at:#x}')
    raise ValueError(f'unterminated LE string at {off:#x}')


def le_strings(data, glyphs, space=None):
    """[(offset, text)] LE u16 C-strings: runs of known units, 0000-terminated."""
    n = len(data) // 2
    units = [struct.unpack_from('<H', data, j * 2)[0] for j in range(n)]
    out = []
    j = 0
    while j < n:
        u = units[j]
        if u in glyphs or (space is not None and u == space):
            k = j
            while k < n and (units[k] in glyphs or (space is not None and units[k] == space)):
                k += 1
            if k < n and units[k] == 0 and k - j >= 1:
                s = ''.join(glyphs.get(x, ' ') if x != space else ' ' for x in units[j:k])
                if sum(c.isalpha() for c in s) >= 3 or sum(ord(c) > 127 for c in s) >= 3:
                    out.append((j * 2, s.strip()))
            j = k + 1
        else:
            j += 1
    return out


def be_table(data, start, glyphs, strict):
    """Decode one BE option table from `start`: options until first unknown
    unit / FF01 / EOF. `strict` ends at unknowns (US: complete map); otherwise
    unknowns render as [xxxx] (JP: map has gaps). Returns (options, end)."""
    known = set(glyphs.keys()) - {0x0000}
    toks = []
    j = start
    while j + 1 < len(data):
        if data[j] == 0xFF:
            if data[j + 1] == 0x03:
                toks.append('<FF03>')
                j += 2
                continue
            break
        u = struct.unpack_from('>H', data, j)[0]
        if u == 0x0000 or u == 0x8140:
            toks.append(' ')
        elif u in known:
            toks.append(glyphs[u])
        elif strict:
            break
        else:
            toks.append('[%04x]' % u)
        j += 2
    opts = [o.strip() for o in ''.join(toks).split('<FF03>')]
    while opts and not opts[-1].strip(' .'):
        opts.pop()
    return opts, j


def be_padded_names(data, base, stride, count, off, length, glyphs, pad=0xFFFF):
    """[names] from a BE fixed-record table (name = `length` words at word
    offset `off`, `pad`-filled). Returns None unless every record decodes to
    >= 2 chars (positional-table guard: a wrong base must fail, not invent)."""
    n = len(data) // 2
    words = struct.unpack('>%dH' % n, data[:n * 2])
    out = []
    rec = base // 2
    for _ in range(count):
        ws = words[rec + off:rec + off + length]
        if not all(x == pad or x in glyphs for x in ws):
            return None
        s = ''.join('' if x == pad else glyphs[x] for x in ws).strip()
        if len(s) < 2:
            return None
        out.append(s)
        rec += stride // 2
    return out


def le_stride_names(data, base, stride, count, glyphs, space=None):
    """[names] from an LE 0000-terminated stride table (menus, race lists:
    each slot holds units then 0000 then zero fill to `stride`). Returns None
    unless every slot decodes to >= 2 chars (same positional guard)."""
    out = []
    for i in range(count):
        off = base + i * stride
        chunk = data[off:off + stride]
        if len(chunk) < stride:
            return None
        units = struct.unpack('<%dH' % (stride // 2), chunk)
        try:
            term = list(units).index(0)
        except ValueError:
            return None
        if term < 1:
            return None
        body = units[:term]
        if any(u != space and u not in glyphs for u in body):
            return None
        if any(u != 0 for u in units[term + 1:]):
            return None
        s = ''.join(glyphs.get(u, ' ') if u != space else ' ' for u in body).strip()
        if len(s) < 2:
            return None
        out.append(s)
    return out


def le_slot(data, off, stride, glyphs):
    """Decode one LE stride slot -> text or None (survey helper)."""
    chunk = data[off:off + stride]
    if len(chunk) < stride:
        return None
    units = struct.unpack('<%dH' % (stride // 2), chunk)
    try:
        term = list(units).index(0)
    except ValueError:
        return None
    if term < 1:
        return None
    body = units[:term]
    if any(u >= 0xFF00 or u == 0 for u in body):
        return None
    if any(u != 0 for u in units[term + 1:]):
        return None
    return ''.join(glyphs.get(u, '[%04x]' % u) for u in body)


def be_chain(data, lo, hi, glyphs, min_units=2):
    """[(offset, text)] back-to-back BE FFFF-terminated strings in [lo, hi):
    the shape of PSP description banks (no fixed stride: each record is
    text + FFFF, the next starts immediately)."""
    n = len(data) // 2
    words = struct.unpack('>%dH' % n, data[:n * 2])
    out = []
    j = lo // 2
    end = hi // 2
    while j < end - min_units:
        if words[j] in glyphs:
            k = j
            while k < end and words[k] in glyphs:
                k += 1
            if k - j >= min_units and k < end and words[k] == 0xFFFF:
                s = ''.join(glyphs[x] for x in words[j:k])
                if sum(c.isalpha() for c in s) >= 2:
                    out.append((j * 2, s))
                j = k + 1
            else:
                j += 1
        else:
            j += 1
    return out


def stride_runs(data, stride=0x10, min_run=6, endian='<', glyphs=None):
    """[(start, [texts])] runs of >= `min_run` consecutive decodable stride
    slots (survey helper: finds string tables without knowing their base)."""
    if glyphs is None:
        glyphs = US_MAP
    n = len(data) - stride
    texts = {}
    for off in range(0, n, 2):
        chunk = data[off:off + stride]
        fmt = '%s%dH' % (endian, stride // 2)
        units = struct.unpack(fmt, chunk)
        try:
            term = list(units).index(0)
        except ValueError:
            continue
        if term < 2 or term > stride // 2 - 1:
            continue
        body = units[:term]
        if any(u >= 0xFF00 or u == 0 for u in body):
            continue
        if any(u != 0 for u in units[term + 1:]):
            continue
        # Strict: every unit must be a known glyph. Bracket-fallbacks contain
        # alpha characters ([0c1a]) and turn binary noise into fake "runs".
        if any(u not in glyphs for u in body):
            continue
        s = ''.join(glyphs[u] for u in body)
        # Single-glyph filler (font/graphic padding like 'aaaa') is not text.
        if len(set(body)) < 2 and len(s) < 8:
            continue
        if sum(c.isalpha() for c in s) < 2 and sum(ord(c) > 127 for c in s) < 2:
            continue
        texts[off] = s
    runs, cur = [], []
    for off in sorted(texts):
        if cur and off == cur[-1][0] + stride:
            cur.append((off, texts[off]))
        else:
            if len(cur) >= min_run:
                runs.append((cur[0][0], [t for _, t in cur]))
            cur = [(off, texts[off])]
    if len(cur) >= min_run:
        runs.append((cur[0][0], [t for _, t in cur]))
    return runs
