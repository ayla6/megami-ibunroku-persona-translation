"""Casino "MAKE THE CODE" prize bar (CASINO.BIN): Shift-JIS prize strings -> English, in place.

  python src/injection_tools/casinoprize.py          patch build/CASINO.BIN (after armips)
  python src/injection_tools/casinoprize.py list     print prizes and glyph counts
  python src/injection_tools/casinoprize.py dump     derive complete prize TSV rows

The prize list is a table of ~95 records
(0x42 bytes: 4 header bytes, Shift-JIS text, 0x0A, zero fill; first at file 0x42A4C) inside CASINO.BIN. The text object
converter (RAM 0x8008CC48) turns every character into a glyph index (array of 20 halfwords per object) by lead byte:
0x82 digits (0x824F-0x8258) -> index second+0x53, 0x82 UPPERCASE letters (0x8260-0x8279) -> second+0x60, 0x81 space -> blank,
0x81 5B / 7C (the long-vowel mark / minus) -> 0xAC, katakana / hiragana via their own ranges. Lowercase letters have NO tile
(they map to blank), so the English is ALL CAPS. The bar shows 19 cells (the 20th is clipped by the bar edge) and the array holds
20: never write more than 19 glyphs (no bound check in the converter).
Record layout of one prize line: <name> [ 0x8258 ("9", drawn as "+") <tail> ] where the tail is `C 1000000` (coins; glyph C is the
coin), `C 5000` or the katakana metal card -> "MTL CARD". The English keeps the tail bytes except the metal card.
Names come from the item table or the mechanically paired PSP prize pool.
Each row stores the complete visible name+bonus, measured against the 19-cell
bar. The builder encodes that row as-is; it never appends hidden text.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
import etext  # noqa: E402
import strlib  # noqa: E402
import toolbelt  # noqa: E402


def item_names():
    """{ja: (en, psp)} for every name in the canonical SLPS table: the
    English is the extracted PSP-US wording, joined by position - no name
    is ever typed here."""
    ext = {r['pos']: r['text'] for r in toolbelt.read_extracted('psx', 'SLPS_005.00', optional=True)}
    out = {}
    for r in toolbelt.read_generated('SLPS_005.00', optional=True):
        ja = ext.get(r['pos'], '')
        if ja and (r['en'] or '').strip():
            out[ja] = (r['en'], r['psp'])
    return out


def tail_kind(tail):
    """What a prize's bonus IS, comparable across the builds: the metal
    card, a coin amount (its digits), or None for no bonus. The PSX spells
    it after the '９' separator, the PSP as its own '+…' line."""
    import unicodedata
    if tail is None:
        return None
    t = unicodedata.normalize('NFKC', tail).replace('<FF01>', '').strip()
    if 'メタルカード' in t or 'Metal Card' in t:
        return 'metal'
    return re.sub(r'\D', '', t) or t


def psp_prize_twins(records_ja):
    """{psx pos: (US name, US pos)} from the PSP's own prize table.

    The PSP keeps each prize as two strings - the bonus line ('+5,000
    Coins'), then the name - in a pool that runs in the REVERSE of the PSX
    record order. The pool is found by sequence, not by address: among the
    US executable's strings, the run that read backwards (a '+' line
    attaching to the name after it) reproduces the PSX's bonus kinds the
    furthest, and only a unique longest run counts. The names pair in that
    order; one whose digits differ from the PSX name ('88 枚' vs '99
    Metal Cards') is a different prize and stays unpaired."""
    import unicodedata
    rows = sorted(((int(r['pos'], 16), r['pos'], r['text'])
                   for r in toolbelt.read_extracted('psp_us', 'EBOOT', optional=True) or []
                   if r['text'].rstrip().endswith('<FF01>')))
    text = [t.replace('<FF01>', '').strip() for _o, _p, t in rows]
    want = [(pos, name, tail_kind(tail) if sep else None)
            for pos, name, sep, tail in records_ja]

    def walk(i):
        got = []
        while i >= 0 and len(got) < len(want) and not text[i].startswith('+'):
            kind = None
            if i > 0 and text[i - 1].startswith('+'):
                kind = tail_kind(text[i - 1])
            if kind != want[len(got)][2]:
                break
            got.append(i)
            i -= 2 if kind is not None else 1
        return got
    best, runs = [], 0
    for i in range(len(rows)):
        got = walk(i)
        if len(got) > len(best):
            best, runs = got, 1
        elif got and len(got) == len(best):
            runs += 1
    if runs != 1 or len(best) < 2:
        return {}
    out = {}
    for (pos, name, _kind), i in zip(want, best):
        digits = lambda s: re.sub(r'\D', '', unicodedata.normalize('NFKC', s))
        if digits(name) != digits(text[i]):
            continue
        out[pos] = (text[i], rows[i][1])
    return out


def port_prizes():
    """Compose each complete prize once from the source name and record bonus.
    Fitting lines land in generated; complete over-budget drafts go to manual.
    """
    src = open(toolbelt.bin_path('CASINO'), 'rb').read()
    names = item_names()
    recs = [(hex(off),) + ja.partition('\uff19') for off, _raw, ja in records(src)]
    twins = psp_prize_twins(recs)
    gen, over = [], 0
    for off, _raw, ja in records(src):
        name, sep, tail = ja.partition('\uff19')
        if not name:
            continue
        _, suffix = tail_bytes(tail, sep)
        hit = names.get(name)
        if hit is None and hex(off) in twins:
            # not an item (a set, a card bundle): the PSP prize table's own
            # name for this record
            en, upos = twins[hex(off)]
            hit = (en, f'EBOOT:{int(upos, 16):x}')
        if hit is None:
            continue                      # no source: gap, queued by the full scan
        en, psp = hit
        up = en.upper()
        if not re.fullmatch(r'[A-Z0-9 \-]+', up):
            continue                      # unprintable here: gap for a human name
        complete = up + suffix
        if len(complete) <= MAX_CELLS:
            gen.append({'pos': hex(off), 'psp': psp, 'en': complete})
        else:
            toolbelt.route_over('CASINO', hex(off), psp, complete,
                                toolbelt.note_over(len(complete), MAX_CELLS, 'cells'))
            over += 1
    toolbelt.upsert_generated('CASINO', gen)
    print(f'casinoprize: {len(gen)} prizes derived, {over} over the cell budget -> {toolbelt.man_path("CASINO")}')


def load_rows():
    """{off: [en, tail]} from the canonical CASINO table (manual wins)."""
    src = open(toolbelt.bin_path('CASINO'), 'rb').read()
    merged = {int(r['pos'], 16): r['en'] for r in toolbelt.merged_rows('CASINO')}
    rows = {}
    for off, _raw, ja in records(src):
        name, sep, tail = ja.partition('\uff19')
        en = (merged.get(off) or '').strip()
        rows[off] = [en if etext.has_text(en) else '', tail]
    return rows


MAX_CELLS = 19
PLUS = b'\x82\x58'                       # "9": drawn as "+"
METAL = 'メタルカード'
PAT = re.compile(rb'((?:[\x81-\x9f\xe0-\xef][\x40-\xfc]){2,})\x0a')
FIRST, LAST = 0x42A4C, 0x45200           # table range in the file (the first four matches are code, not text)


def fw(s):
    """A prize bar's text as the full-width cells the casino font draws.

    Every character is the FULL-WIDTH form of itself and the bytes are
    the game's own encoding (cp932): that is exactly the hand table this
    replaced - ' ' is 0x8140, '-' 0x817C, 'A' 0x8260, '0' 0x824F - and it
    covers whatever else the wording carries (lowercase, '÷', ...) instead
    of an alphabet typed out in advance. Only a character the encoding has
    no cell for at all fails, and it fails loud."""
    out = b''
    for c in s:
        c = '　' if c == ' ' else (
            chr(ord(c) + 0xFEE0) if 0x21 <= ord(c) <= 0x7E else c)
        try:
            out += c.encode('cp932')
        except UnicodeEncodeError:
            raise SystemExit(f'casinoprize: unsupported character {c!r} in {s!r}')
    return out


def records(d):
    for m in PAT.finditer(d):
        if not FIRST <= m.start() <= LAST:
            continue
        try:
            ja = m.group(1).decode('shift_jis')
        except UnicodeDecodeError:
            continue
        yield m.start(), m.group(1), ja


def tail_bytes(tail, sep):
    if not sep:
        return b'', ''
    if tail == METAL:
        _mc = strlib.glossary('casinoprize')['metal_card']
        return PLUS + fw(_mc), '+' + _mc
    import unicodedata
    return PLUS + tail.encode('shift_jis'), '+' + unicodedata.normalize('NFKC', tail)


def encode_prize(text):
    """Encode the COMPLETE visible row. '+' uses the retail prize separator
    tile (encoded as full-width 9); C is the coin icon. No suffix is appended
    here: the porter has already composed the name and bonus in the TSV."""
    parts = text.split('+')
    if len(parts) > 2:
        raise ValueError('a prize row may contain at most one bonus separator')
    return PLUS.join(fw(part) for part in parts)


def translate(off, ja):
    """-> (complete English text, encoded bytes) or None to keep Japanese."""
    row = rows().get(off)
    if row is None or not etext.has_text(row[0]):
        return None
    en = row[0]
    if len(en) > MAX_CELLS:
        raise SystemExit(f'casinoprize: {off:06X} {en!r} does not fit {MAX_CELLS} cells')
    return en, encode_prize(en)


_ROWS = None


def rows():
    global _ROWS
    if _ROWS is None:
        _ROWS = load_rows()
    return _ROWS



def main():
    if 'dump' in sys.argv:
        port_prizes()
        return
    src = open(os.path.join(ROOT, 'data', 'psx', 'CASINO.BIN'), 'rb').read()
    out = bytearray(open(os.path.join(ROOT, 'build', 'CASINO.BIN'), 'rb').read()) if 'list' not in sys.argv else None
    n = 0
    for off, raw, ja in records(src):
        t = translate(off, ja)
        if t is None:
            if out is None:
                print(f'{off:06X} {"":4s}  {ja}  ->  (Japanese kept)')
            continue
        en, b = t
        assert len(b) // 2 <= MAX_CELLS and len(b) + 1 <= 0x3E
        if out is not None:
            new = (b + bytes([0x0A])).ljust(len(raw) + 1, bytes([0]))   # never change the file size (a longer slice would shift the rest)
            assert not any(src[off + len(raw) + 1:off + len(new)]), f'{off:06X}: English overruns non-zero data'
            out[off:off + len(new)] = new
        else:
            sys.stdout.reconfigure(encoding='utf-8')
            print(f'{off:06X} {len(b) // 2:2d}  {ja}  ->  {en}')
        n += 1
    if out is not None:
        assert len(out) == len(src), 'casinoprize: size changed'
        open(os.path.join(ROOT, 'build', 'CASINO.BIN'), 'wb').write(out)
    print(f'casinoprize: {n} prize strings')


if __name__ == '__main__':
    main()
