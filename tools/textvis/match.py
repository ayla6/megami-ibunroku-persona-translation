"""Ranked PSP matches for a row's text - the "find psp" button behind the viewer.

A row's own `psp` pointer is provenance, already shown next to the draft. This
is the other direction: given the text in the editor (a human's draft, or the
PSP wording a generated row already carries, or the Japanese of a queued row),
which PSP-US or PSP-JP units could it be?

The needles are the row's MOST DISTINCTIVE parts, not its whole text: a code
with its parameter (`<FF05><10><00>`, `<FF06><02>`), a number, a proper noun, a
long word, a kanji run. Everyday codes (`<FF03>` line, `<FF02>` wait,
`<FF01>` end) carry little information and are weighted accordingly, and a
needle found in many units is worth less than one found in few.

A code is compared by MEANING, not spelling: the PSP writes waits as
`<FF05><1000>`, this project writes `<FF05><10><00>`, so both sides are reduced
to a canonical token (`ff05:1000`) before searching. That is what makes a
distinctive code usable across the two builds.

The score shown is the share of those weighted needles a unit contains, so
"82%" reads as "82% of this row's distinctive material is here". Structure
(same page/scroll shape) only breaks ties, so the number always sorts.

Import is a conversion, not a copy: a PSP-US unit is turned into the PSX
coding this project stores (label `Name: `, PSP's own line/page/wait breaks,
`<FF05><1000>` -> `<FF05><10><00>`, portrait/icon codes dropped, `[00]` tail
dropped). The wording is the PSP's, never retyped. The Japanese extracts are
already in the shape a PSX-JA row is read in, so they import as they are.
"""
import math
import re

CJK = '\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff01-\uff60'

# PSP control codes carry parameter units; PARAM_LEN is the shared authority
# (src/injection_tools/vwf_wrap.py) and is imported, never copied.
from vwf_wrap import PARAM_LEN as _PARAM_LEN          # noqa: E402

PARAM_LEN = {int(k, 16): v for k, v in _PARAM_LEN.items()}

CODE = re.compile(r'<FF([0-9A-Fa-f]{2})>')            # a control code
BYTE2 = re.compile(r'<([0-9A-Fa-f]{4})>')            # two parameter bytes
BYTE1 = re.compile(r'<([0-9A-Fa-f]{2})>')            # one parameter byte

# codes that only say "this is a textbox": they cost nothing to match
STRUCT = {0x01, 0x02, 0x03, 0x04, 0x11, 0x12, 0xF5, 0xEF}
SKIP_CODES = {0x18, 0x19, 0x1A}        # portrait / icon: no PSX counterpart

STOP = set("""a an the and or but if then than that this these those there here is are was
were be been being am do does did done have has had i you he she it we they me him her us
them my your his its our their mine yours which who whom what when where why how not no yes
so as at by for from in into of on onto out over to up with without about after again
against all any because before below between both down during each few further more most
other same some such only own just very can will would should could may might must shall
let s t re ve ll d m im ive youre thats dont doesnt didnt cant wont theyre weve ill""".split())


# ---------------------------------------------------------------------------
# reading a PSP text: codes, their parameters, and the words around them
# ---------------------------------------------------------------------------

class Glyphs:
    """unit -> character, for turning a parameter that decoded as a glyph
    back into the bytes the PSP wrote."""

    def __init__(self, table):
        self.by_unit = dict(table)
        self.by_char = {}
        for unit, ch in table.items():
            if len(ch) == 1:
                self.by_char.setdefault(ch, unit)

    def unit(self, ch):
        return self.by_char.get(ch)

    def char(self, unit):
        return self.by_unit.get(unit, '')


def units(text, glyphs):
    """[(kind, value, params)] over a decoded text.

    kind 'c' is a control code (value = the byte after FF), 'b' a stray raw
    byte, 't' text. A code eats its own parameters: a decoded parameter may
    be written as `<xx>`, `<xxxx>` or as the glyph it decodes to.
    """
    out, i, n = [], 0, len(text)
    while i < n:
        m = CODE.match(text, i)
        if m:
            code = int(m.group(1), 16)
            i = m.end()
            params = []
            for _ in range(PARAM_LEN.get(code, 0)):
                mm = BYTE2.match(text, i)
                if mm:
                    v = int(mm.group(1), 16)
                    params.extend((v >> 8, v & 0xFF))
                    i = mm.end()
                    continue
                mm = BYTE1.match(text, i)
                if mm:
                    params.append(int(mm.group(1), 16))
                    i = mm.end()
                    continue
                if i < n:
                    u = glyphs.unit(text[i]) if glyphs else None
                    if u is None:
                        params.append(0)
                    elif u > 0xFF:
                        params.extend((u >> 8, u & 0xFF))
                    else:
                        params.append(u & 0xFF)
                    i += 1
            out.append(('c', code, params))
            continue
        m = BYTE2.match(text, i)
        if m:
            v = int(m.group(1), 16)
            out.append(('b', v, (v >> 8, v & 0xFF)))
            i = m.end()
            continue
        m = BYTE1.match(text, i)
        if m:
            out.append(('b', int(m.group(1), 16), ()))
            i = m.end()
            continue
        j = i + 1
        while j < n and not CODE.match(text, j) and not BYTE1.match(text, j):
            j += 1
        out.append(('t', text[i:j], ()))
        i = j
    return out


CODE_RUN = re.compile(r'<FF([0-9A-Fa-f]{2})>((?:<[0-9A-Fa-f]{2,4}>)+)?')


def canon_codes(text, glyphs=None):
    """The text's codes as canonical tokens: `ff05:1000`, `ff1b`, `ff0e:03`.

    Two spellings of one code become one token, which is the only reason a
    PSP `<FF05><1000>` and a PSX `<FF05><10><00>` can be compared at all.
    Parameters are read as written (`<xx>` / `<xxxx>`); a parameter that
    decoded as a glyph character belongs to the text, not here.
    """
    out = []
    for m in CODE_RUN.finditer(text):
        val = int(m.group(1), 16)
        if val in SKIP_CODES:
            continue
        tok = 'ff%02x' % val
        raw = m.group(2)
        if raw:
            digits = re.sub(r'[<>]', '', raw)
            if len(digits) % 2:
                digits = '0' + digits
            tok += ':' + digits.lower()
        out.append(tok)
    return out


def convert_us(text, glyphs):
    """The PSP-US unit as this project stores a row's English, plus flags.

    Label runs (`<FF1B>Name<FF03>`) become a head `Name: ` - PSX has no such
    opcode, and a mid-box label (the next speaker on a shared page) is
    dropped with its break, as the porters store it. Icon/portrait codes are
    dropped, waits keep the PSP's own duration, and the PSP's own line and
    page breaks are kept: this is the source's shape, not a re-flow.
    """
    flags = []
    toks = units(text, glyphs)
    if any(k == 't' and re.search(r'\[[0-9A-Fa-f]{3,4}\]', v) for k, v, _p in toks):
        flags.append('glyph hole in source')
    out, i, seen = [], 0, False
    while i < len(toks):
        kind, val, _params = toks[i]
        if kind == 'c' and val == 0x1B:
            j, label = i + 1, ''
            while j < len(toks) and not (toks[j][0] == 'c'
                                         and toks[j][1] in (0x03, 0x02, 0x04, 0x01)):
                if toks[j][0] == 't':
                    label += toks[j][1]
                j += 1
            if j < len(toks) and toks[j][0] == 'c' and toks[j][1] == 0x03:
                if not seen:
                    out.append(('t', label.strip() + ': ', ()))
                i = j + 1
                continue
        if kind == 't' and val.strip():
            seen = True
        out.append(toks[i])
        i += 1
    res = []
    for kind, val, params in out:
        if kind == 't':
            res.append(val)
            continue
        if kind == 'b':
            flags.append('stray raw byte dropped')
            continue
        if val in SKIP_CODES:
            continue
        if val == 0x05:
            res.append('<FF05><%02X><%02X>' % (params[0], params[1]))
        elif val == 0x06:
            res.append('<FF06><%02X>' % params[0])
        elif val == 0x0E:
            res.append('<FF0E><%02X>' % (params[0] & 0xFF))
        elif val in (0x07, 0x08, 0x0F):
            ch = glyphs.char(params[0]) if params else ''
            res.append('<FF%02X>%s' % (val, ch or '<%02X>' % (params[0] if params else 0)))
        elif val == 0x01:
            res.append('<FF01>')
            break
        else:
            res.append('<FF%02X>' % val)
    text = ''.join(res)
    text = re.sub(r'\[[0-9A-Fa-f]{4}\]', '', text).replace('[00]', '')
    return text, sorted(set(flags))


def convert_jp(text):
    """The JP extract's unit as a PSX-JA row is read.

    The Japanese extracts are already decoded into the same code notation
    (the two builds share the VM), so this drops only what the extractor
    adds: a blank/padding word rendered as `[00]` / `[0000]`. A glyph hole
    (`[xxxx]` with a real word) is KEPT and flagged - never dropped silently.
    """
    flags = []
    if re.search(r'\[(?!0{2,4}\])[0-9A-Fa-f]{3,4}\]', text):
        flags.append('glyph hole in source')
    text = re.sub(r'\[0{2,4}\]', '', text)
    return text.strip(), flags


# ---------------------------------------------------------------------------
# needles: what in this row is worth looking for
# ---------------------------------------------------------------------------

def needles(text, glyphs, cap=10):
    """[(kind, needle, weight)] - the row's most distinctive pieces.

    `kind` is 'code' (canonical token, matched against the unit's code
    signature) or 'word' (a case-folded substring of the unit's text).
    Japanese is searched as BIGRAMS, not as whole runs: the two builds word
    the same line differently, so a whole phrase is a needle that only finds
    itself - `お金が足りません` finds nothing, `足り` finds the line.
    """
    found, seen = [], set()

    def add(kind, s, w):
        key = (kind, s.lower())
        if not s or key in seen:
            return
        seen.add(key)
        found.append((kind, s.lower() if kind == 'word' else s, w))

    toks = units(text, glyphs)
    i = 0
    while i < len(toks):
        if toks[i][0] != 'c':
            i += 1
            continue
        run = []
        while i < len(toks) and toks[i][0] == 'c':
            run.append(toks[i])
            i += 1
        # a code run is worth searching when it carries a parameter or is not
        # one of the everyday structural codes
        for _k, val, params in run:
            if val in SKIP_CODES:
                continue
            tok = 'ff%02x' % val + (':' + ''.join('%02x' % b for b in params)
                                    if params else '')
            if params:
                add('code', tok, 5.0)
            elif val not in STRUCT:
                add('code', tok, 2.0)

    plain = re.sub(r'<[^>]+>', ' ', text)
    for m in re.finditer(r'[A-Za-z]{3,}|\d+|[%s]+' % CJK, plain):
        s = m.group(0)
        if s[0].isdigit():
            add('word', s, 3.0 + min(len(s), 4) * .3)
            continue
        if re.match('[%s]' % CJK, s):
            if len(s) == 1:
                add('word', s, 2.0)
            else:
                for k in range(len(s) - 1):
                    add('word', s[k:k + 2], 2.5)
        elif s.lower() not in STOP:
            w = 2.0 + min(len(s), 12) * .35
            if s[0].isupper() and len(s) > 2:
                w += 1.5                   # a name, not a common word
            add('word', s, w)

    found.sort(key=lambda t: -t[2])
    return found[:cap]


def region_of(text):
    plain = re.sub(r'<[^>]+>', '', text)
    j = len(re.findall('[%s]' % CJK, plain))
    a = len(re.findall('[A-Za-z]', plain))
    return 'jp' if j > a else 'us'


def match(text, files, codes, glyphs, region=None, limit=12, prefer_rel=None):
    """{needles, region, hits} - ranked units, best first.

    `files` is {region: {rel: [unit rows]}} and `codes` the parallel
    {region: {rel: [canonical code string]}} the server caches next to the
    extracts, so no file is read here. Likelihood is the rarity-weighted
    share of the needles a unit contains; on an exact tie the row's own
    extract wins, then the unit whose page/scroll shape matches.
    """
    picks = needles(text, glyphs)
    if not picks:
        return {"region": region or region_of(text), "needles": [], "hits": []}
    regions = [region] if region in ('us', 'jp') else ['us', 'jp']
    code_picks = [(i, s, w) for i, (k, s, w) in enumerate(picks) if k == 'code']
    word_picks = [(i, s, w) for i, (k, s, w) in enumerate(picks) if k != 'code']

    raw = []
    for reg in regions:
        sig_of = codes[reg]
        for rel, units_ in files[reg].items():
            for j, r in enumerate(units_):
                low = r['text'].lower()
                sig = sig_of[rel][j]
                got = [i for i, s, _w in word_picks if s in low]
                got += [i for i, s, _w in code_picks if s in sig]
                if got:
                    raw.append([reg, rel, j, got])
    if not raw:
        return {"region": region or region_of(text),
                "needles": [p[1] for p in picks], "hits": []}

    df = [0] * len(picks)
    for _r, _rel, _j, got in raw:
        for i in got:
            df[i] += 1
    adj = [w / (1 + math.log2(1 + df[i])) for i, (_k, _s, w) in enumerate(picks)]
    total = sum(adj) or 1.0

    src_pages, src_waits = text.count('<FF04>'), text.count('<FF02>')
    hits = []
    for reg, rel, j, got in raw:
        r = files[reg][rel][j]
        body = r['text']
        lik = sum(adj[i] for i in got) / total
        shape = ((body.count('<FF04>') == src_pages)
                 + (body.count('<FF02>') == src_waits))
        home = 1 if (prefer_rel and rel == prefer_rel) else 0
        hits.append((round(lik, 4), home, shape, reg, rel, r, got))
    hits.sort(key=lambda h: (-h[0], -h[1], -h[2]))
    out = []
    for lik, home, shape, reg, rel, r, got in hits[:limit]:
        out.append({"region": reg, "rel": rel, "id": r['id'], "pos": r['pos'],
                    "text": r['text'], "lik": lik, "structure": shape,
                    "matched": [picks[i][1] for i in got]})
    return {"region": region or region_of(text),
            "needles": [p[1] for p in picks], "hits": out}
