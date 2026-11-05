"""Word-wrap English for VWF dialogue boxes (ADV/DNG/S2D).

THE RULES ARE THE SPEC: docs/TEXT_LAYOUT_SPEC.md (sections 2 and 3). This
file is their only implementation; a change here that the spec does not say
is a change to the game's reading, so the two move together.

Measures text with the same rules as vwf/vwf_dialog.asm:
  ASCII 0x20-0x7E -> font/vwf_width.bin advance
  any other char  -> 16 px (original FONT.BIN glyph)
  <...> tokens    -> 0 px (control codes such as <FF03>, <FF02>)
and inserts <FF03> line breaks so no line exceeds the box width.
Existing <FF03> breaks are kept; <FF02>/<FF04> (wait/next page) reset nothing
width-wise but are passed through.

Usage:
  python tools/vwf_wrap.py "text"            -> wrapped text on stdout
  python tools/vwf_wrap.py --check "text"    -> report line widths, exit 1 if any overflow
"""
import functools
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# The box is 240 px, but vwf_dialog.asm wraps as soon as the pen reaches 240 after a glyph; an explicit
# <FF03> after such a line would skip a second line. Max 239.
BOX_WIDTH = 239
# The battle text box (BTLP: negotiation lines and the player's answers) has
# 6 px horizontal padding where the dialogue box has 12: its frame leaves 12 px
# more per line. The VWF engine still draws the original 15-cell (240 px) grid
# there, so no text may use them until it draws a 16th cell per battle row.
BATTLE_BOX_WIDTH = BOX_WIDTH + 12
# A page carries three visible lines and one scroll of up to three more.
# Longer text needs a new page.
PAGE_LINES = 6
NEWLINE = "<FF03>"
TOKEN = re.compile(r"(<[^>]+>)")

with open(os.path.join(ROOT, "src", "asm", "font", "vwf_width.bin"), "rb") as f:
    _widths = f.read()


def char_width(c):
    # ONE SPELLING RULE with the encoder (etext.spell): a character the font
    # prints as an ASCII one is priced as that ASCII one, or the flow would
    # price '’' at the Japanese 16px fallback and wrap a line that fits.
    import etext
    c = etext.spell(c)
    if c in ('＞', '＜'):
        c = '>' if c == '＞' else '<'
                    # the table spelling of the head marks; the glyphs the
                    # engine draws are the ASCII ones (etext encodes them
                    # so), so the flow prices a mark at its real width
    o = ord(c)
    if 0x20 <= o <= 0x7E:
        return _widths[o - 0x20]
    # the extra character-map entries have real VWF glyphs of their own
    # (make_vwf_font.EXTRA) - they are NOT the 16px Japanese fallback
    import make_vwf_font
    k = make_vwf_font.EXTRA_CODE.get(c)
    return _widths[k - 0x20] if k is not None else 16


# Words that look sentence-final but aren't (abbreviations, initials).
SENT_ABBREVS = {'mr', 'mrs', 'ms', 'dr', 'st', 'jr', 'sr', 'vs', 'etc',
                'e.g', 'i.e', 'no', 'fig', 'sen'}
SENT_END_RE = re.compile(r'[.!?…]+["\'”)\]]?$')


@functools.lru_cache(maxsize=131072)
def sent_end(w):
    """True when a word ends a sentence (not an abbreviation/initial).
    Control codes are ignored: `today.<FF02>` closes the sentence."""
    t = re.sub(r'<[^>]+>', '', w).rstrip()
    if not SENT_END_RE.search(t):
        return False
    core = SENT_END_RE.sub('', t).lower()
    if re.fullmatch(r'[a-z]', core):
        return False  # initial ("A. Smith")
    return core not in SENT_ABBREVS


def ink_width(font, g):
    """The glyph's measured width (rightmost ink column + 1) from its bitmap."""
    cols = [b for r in range(16) for b in range(8)
            if font[g * 16 + r] & (0x80 >> b)]
    return max(cols) + 1 if cols else 1


def fit_advances(font, s, panel, max_gap=3, min_gap=1):
    """(advances, gap) for a fixed graphics panel: measured glyph widths plus
    a letter gap, tightened by whole pixels until the text fits. The text
    itself is never shortened (only the space it stands in is managed)."""
    base = [ink_width(font, ord(c) - 0x20) for c in s]
    for gap in range(max_gap, min_gap - 1, -1):
        adv = [w + gap for w in base]
        if sum(adv) - gap <= panel:
            return adv, gap
    raise SystemExit(f'{s!r} needs {sum(base) + len(s) - 1}px even at gap '
                     f'{min_gap}, panel {panel}px')


# Name insertion codes + parameter byte: <FF07> family name, <FF0F> given name
# (5 typed characters each, name entry limit), <FF08> nickname (up to 8).
# The parameter is written あ in Japanese source and <XX> in generated
# English; both forms count. Counted as a run of 'R' - the name the entry
# allows at its widest: the name entry is locked to its ABC page
# (name/latin_start.asm), typed names render through vwf_name_map as narrow
# English, and 'R' is the widest glyph that page can type (8 px ink +
# LETTER_GAP = 9 px advance; '?' ties). The full-width worst case is gone
# with the kana pages (2026-10-13: うx5 overflowed lines measured at 5x9
# Latin - that cannot happen any more, no kana is typable).
NAME_CODES = ('<FF07>', '<FF08>', '<FF0F>', '<FF10>')   # the hero-name insert codes
FULL_NAME_CODES = ('<FF07>', '<FF0F>')   # <FF10> spells given + family
NAME_TOKEN_RE = re.compile(r'<FF(07|0F|08)>(?:あ|<[^>]*>)')
NAME_LENS = {'07': 5, '0F': 5, '08': 8}   # entry cells used (5/5 typed, 8 nickname)
NAME_WIDTHS = {k: sum(char_width(c) for c in 'R' * n) for k, n in NAME_LENS.items()}
NAME_TOKENS = {'<FF07>あ': NAME_WIDTHS['07'], '<FF0F>あ': NAME_WIDTHS['0F'], '<FF08>あ': NAME_WIDTHS['08']}
NAME_TOKEN = '<FF0F>あ'
NAME_WIDTH = NAME_WIDTHS['0F']

# --- the battle window's insert tokens (<FFFx>) -------------------------
# The same rule as the name tokens above, for BTLP's seven insert slots
# (persona-decomp btlp/insert.c "Seven slots ... filled with a name, a
# number, whose turn it is"). A slot holds the game's own copy CAP - a
# name at INSERT_SHORT/INSERT_LONG glyphs, or the decimal value
# BtlFormatDecimal can print - and the window draws that copy. So the
# width of an insert token is what that copy can occupy, and NOTHING
# else: the caps and the code-to-slot map are READ from the decomp here,
# never typed, and the glyph advance is the font's own.
#
# This is the ONE pricing. The flow breaks lines with it and btlp's width
# check measures with it, so a row is never refused for an insert the box
# holds and never shipped for one it cannot.
DECOMP_BTLP = os.path.join(ROOT, 'references', 'persona-decomp', 'src', 'btlp')


def _cdef(src, name):
    m = re.search(r'#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)' % re.escape(name), src)
    return int(m.group(1), 0) if m else None


def btl_insert_caps():
    """{code byte: glyphs} the battle window's insert codes can occupy.

    windowtype.c maps a code to the slot it points at (CODE_INSERTn 0xXX);
    insert.c maps a slot to what fills it (case n: a decimal value, or a
    name copy capped at INSERT_SHORT/INSERT_LONG); number.c says how many
    digits a value prints (DECIMAL_TOP) and the value may carry a minus,
    so the slot holds that many glyphs. The slot's own cell array is the
    hard bound, and a copy can never exceed it."""
    with open(os.path.join(DECOMP_BTLP, 'windowtype.c'), encoding='utf-8') as f:
        win = f.read()
    with open(os.path.join(DECOMP_BTLP, 'insert.c'), encoding='utf-8') as f:
        ins = f.read()
    with open(os.path.join(DECOMP_BTLP, 'number.c'), encoding='utf-8') as f:
        num = f.read()
    short, long = _cdef(ins, 'INSERT_SHORT'), _cdef(ins, 'INSERT_LONG')
    # 0x18 bytes of (attribute, glyph) pairs, one end byte
    m = re.search(r'u_char\s+cell\[(0x[0-9A-Fa-f]+|\d+)\]', ins)
    cell = int(m.group(1), 0) if m else None
    digits = len(str(_cdef(num, 'DECIMAL_TOP')))   # 1000000000 -> 10 places
    slot = {int(m.group(1)): int(m.group(2), 0) for m in re.finditer(
        r'#define\s+CODE_INSERT(\d)\s+(0x[0-9A-Fa-f]+)', win)}
    caps = {}
    for m in re.finditer(r'case\s+(\d)\s*:(.*?)(?=\n\s*case\s|\n\s*default|\Z)',
                         ins, re.S):
        n, body = int(m.group(1)), m.group(2)
        if 'BtlFormatDecimal' in body:
            caps[n] = digits + 1                   # the digits plus a minus
        else:
            c = re.search(r'BtlStrCopy(?:Esc)?\([^,]+,[^,]+,\s*'
                          r'(INSERT_SHORT|INSERT_LONG)\)', body)
            if c:
                caps[n] = short if c.group(1) == 'INSERT_SHORT' else long
    if cell:
        caps = {n: min(c, (cell - 1) // 2) for n, c in caps.items()}
    return {slot[n]: c for n, c in caps.items() if n in slot}


def btl_name_insert_codes():
    """Battle opcodes whose actual destination slot receives a copied name."""
    with open(os.path.join(DECOMP_BTLP, 'windowtype.c'), encoding='utf-8') as f:
        win = f.read()
    with open(os.path.join(DECOMP_BTLP, 'insert.c'), encoding='utf-8') as f:
        ins = f.read()
    opcodes = {int(m.group(1)): int(m.group(2), 0) for m in re.finditer(
        r'#define\s+CODE_INSERT(\d)\s+(0x[0-9A-Fa-f]+)', win)}
    named_slots = set()
    for m in re.finditer(r'case\s+\d+\s*:(.*?)(?=\n\s*case\s|\n\s*default|\Z)', ins, re.S):
        if 'BtlStrCopy' in m.group(1):
            named_slots.update(int(n) for n in re.findall(r'slot\[(\d+)\]\.cell', m.group(1)))
    if not named_slots or not named_slots <= opcodes.keys():
        raise ValueError('cannot derive battle name insert slots from reference decompilation')
    return frozenset(opcodes[n] for n in named_slots)


# A name insert holds glyphs of the name charset; the widest of those is
# the widest advance the font gives an ASCII letter ('N'/'R'/'U'/'?').
# Measured against the ported name tables it is exactly this - no name
# glyph is wider - so the worst-case copy is `cap` of them.
_NAME_GLYPH = max(char_width(chr(c)) for c in range(0x20, 0x7F))
BTL_INSERT_WIDTHS = {'<FF%02X>' % code: cap * _NAME_GLYPH
                     for code, cap in btl_insert_caps().items()}
BTL_NAME_INSERT_CODES = btl_name_insert_codes()


@functools.lru_cache(maxsize=131072)
def text_width(s):
    w = 0
    def _name(m):
        nonlocal w
        w += NAME_WIDTHS[m.group(1)]
        return ''
    s = NAME_TOKEN_RE.sub(_name, s)
    return (w
            + sum(char_width(c) for part in TOKEN.split(s)
                  if not TOKEN.fullmatch(part) for c in part)
            # an insert token is not zero: the window draws the name (or
            # value) the game fills it with, and the flow must leave the
            # room that copy takes (BTL_INSERT_WIDTHS)
            + sum(BTL_INSERT_WIDTHS[t] for t in TOKEN.findall(s)
                  if t in BTL_INSERT_WIDTHS))


CLOSERS = set('.,!?;:…’”)]]')
# Closing punctuation, apostrophes and multi-dot ellipses attach to the
# preceding word. Answers retain their own spacing outside this flow.
CLOSERS_RE = r'^[.,!?;:\'…»)\]]'


def hyphen_heads(word):
    """(head, tail) splits of a hyphenated word, longest head first, hyphen
    kept on the head ("well-informed" -> [("well-", "informed")]). Only
    proper internal splits; a trailing hyphen ("part-") never splits, and
    neither does a split that strands punctuation ("with--" stays whole)."""
    outs = []
    start = 1
    while True:
        k = word.find('-', start)
        if k < 1 or k >= len(word) - 1:
            break
        tail = word[k + 1:]
        if not re.search(r'[A-Za-z0-9’]', tail):
            break
        outs.append((word[:k + 1], tail))
        start = k + 1
    return outs[::-1]


# --- what a line break may not separate ---
# ARTICLES bind to the word AFTER them: "the hospital" is one atom, so a
# line never begins with the and never ends on it either (the noun keeps its
# article - the user's rule: "articles in the same line as the noun").
ARTICLES = {'a', 'an', 'the', 'this', 'these', 'those', 'its', 'their',
            'his', 'her', 'our', 'your', 'my'}
# CONNECTORS bind to the word BEFORE them: "go to | the station" - the line
# ends on the connector instead of starting with it.
CONNECTORS = {'to', 'of', 'in', 'on', 'at', 'with', 'from', 'for', 'by',
              'as', 'and', 'or', 'but', 'nor', 'than', 'that', 'into',
              'onto', 'about', 'over', 'under', 'off', 'upon', 'without',
              'through', 'toward', 'towards', 'between', 'among', 'against',
              'because', 'while', 'when', 'where', 'if', 'so', 'yet'}
_PROCL_STRIP = '"“‘([{'
_PROCL_END = '.!?…'


def _core_word(w):
    """The word without its leading quotes/brackets, for the tests below."""
    return w.lstrip(_PROCL_STRIP)


def _caps_word(w):
    """A word that can be part of a proper name: it begins with a capital,
    is real text (not a lone "I" or a speaker label), and does not end a
    sentence (a sentence end closes the unit - "Ms." is an abbreviation, so
    it stays open)."""
    t = _core_word(w).rstrip('"”’)]}')
    if len(t.rstrip(',;:')) < 2 or not t[0].isupper():
        return False
    if t.endswith((',', ';', ':')):
        return False
    return not sent_end(w)


def _glue_items(items):
    """Glue the units a line break may not separate (see ARTICLES /
    CONNECTORS / proper names above). One pass, then the flow sees only
    words: a break inside a unit is then not an opportunity at all."""
    out = list(items)
    # 1. articles: right to left into maximal runs ("such a thing" stays
    # whole; left to right would glue "such a" and strand "the" again).
    i = len(out) - 2
    while i >= 0:
        kind, word = out[i][0], out[i][1]
        nxt = out[i + 1]
        test = _core_word(word)
        if (kind == 'w' and nxt[0] == 'w'
                and test.rstrip(',;:').lower() in ARTICLES
                and test[-1:] not in _PROCL_END
                and not re.match(CLOSERS_RE, nxt[1])):
            out[i:i + 2] = [('w', word + ' ' + nxt[1])]
        i -= 1
    # 2. connectors: left to right, glued onto the word they follow
    glue = []
    for it in out:
        if (it[0] == 'w' and glue and glue[-1][0] == 'w'
                and _core_word(it[1]).rstrip(',;:').lower() in CONNECTORS
                and not sent_end(glue[-1][1])
                and not re.match(CLOSERS_RE, it[1])):
            glue[-1] = ('w', glue[-1][1] + ' ' + it[1])
        else:
            glue.append(it)
    out = glue
    # 3. proper names: NOT glued - a line MAY break inside one, it just pays
    # for it (the user's call: "not unbreakable, just very hard to break").
    # The break that would split a name is marked, and flow_layout ranks it
    # below every other cost but an overflow or an extra line. Last, so the
    # glue passes cannot drop a mark with a merge.
    return _mark_names(out)


def _mark_names(items):
    """Mark each word whose line break would split a PROPER NAME.

    A run of capitalised words is a name ("St. Hermelin High", "Ms. Saeko",
    "Mikage Hospital") but it is NOT one atom: the flow may break inside it
    when that is the only way to fit the box or to avoid a line. It pays,
    that is all - the user's rule (2026-10-25): "not unbreakable, just very
    hard to break". Derived from capitalisation and sentence shape only; no
    list of names exists anywhere.
    """
    out, prev, run = [], None, 0
    for it in items:
        if it[0] != 'w':
            out.append(it)
            prev, run = None, 0
            continue
        w = it[1]
        if prev is not None and run < 9 and _caps_word(prev) and _caps_word(w) \
                and not sent_end(prev):
            run += 1
            out.append((it[0], it[1], run))
        else:
            run = 0
            out.append(it)
        prev = w
    # Short double-quoted terms are reading units too. This is a soft break
    # cost, never an extra line/scroll, and derives solely from source quotes.
    start = None
    for i, it in enumerate(out):
        if it[0] != 'w':
            start = None
            continue
        for ch in re.sub(r'<[^>]+>', '', it[1]):
            if ch in '"“' and start is None:
                start = i
            elif ch in '"”' and start is not None:
                phrase = ' '.join(v[1] for v in out[start:i + 1])
                if len(phrase.split()) <= 4 and text_width(phrase) <= BOX_WIDTH:
                    for j in range(start + 1, i + 1):
                        out[j] = (out[j][0], out[j][1], 1)
                start = None
    return out


class Atom:
    """One unbreakable piece of line text plus how it joins its neighbours.
    join: what stands between it and the previous atom mid-line (dropped at a
    line start); brk: a line break is allowed before it; pen: what using that
    break costs (0 = an ordinary word gap, >0 = an internal split); word: it
    is real text (the pen-240 rule only counts words); last: the final piece
    of its item."""
    __slots__ = ('text', 'join', 'brk', 'pen', 'word', 'last', 'fin', 'nbrk')

    def __init__(self, text, join, brk, pen, word, last):
        self.text, self.join, self.brk, self.pen = text, join, brk, pen
        self.word, self.last, self.fin = word, last, False
        # a line break here would split a PROPER NAME ("Ms. | Saeko"):
        # allowed, but ranked below everything else (see flow_layout)
        self.nbrk = False


# A control code with its parameter bytes (a name insert's <01>, a pause's
# two bytes, <FFFD>'s parameter character): never split across a line break.
CODE_RUN = re.compile(r'<FFFD>.|<FF[0-9A-F]{2}>(?:<[0-9A-F]{2}>)*(?:あ)?|<[^>]+>')


def word_pieces(w):
    """[(text, brk, pen)] the pieces of one flow word: breaks after hyphens
    and around code runs are opportunities a line may use, but each costs a
    split, so a word stays whole unless breaking it saves a line or an
    overflow (the engine never splits for looks)."""
    cuts = set()
    for m in CODE_RUN.finditer(w):
        if 0 < m.start() < len(w):
            cuts.add(m.start())
        if 0 < m.end() < len(w):
            cuts.add(m.end())
    cuts.update(len(h) for h, _t in hyphen_heads(w))
    out, prev = [], 0
    for c in sorted(c for c in cuts if 0 < c < len(w)) + [len(w)]:
        out.append((w[prev:c], prev > 0, 1))
        prev = c
    return out or [(w, False, 1)]


def _is_article(w):
    """The article test the glue pass uses, for a word that stands alone
    (its follower was a code, not a word): such a word still may not leave
    the line it is on."""
    test = _core_word(w)
    return (test.rstrip(',;:').lower() in ARTICLES
            and test[-1:] not in _PROCL_END)


def flow_model(items):
    """items -> the flat flow stream: ('a', Atom) text pieces, ('b', code)
    deliberate breaks, ('v', code) voice codes. Deliberate breaks are region
    walls: the flow never merges, moves, or balances across them."""
    seq = []
    prev = None
    hold = False          # a lone proclitic: the next piece may not leave it
    for it in items:
        kind = it[0]
        if kind == 'b':
            seq.append(('b', it[1]))
            prev, hold = None, False
            continue
        if kind == 'G':
            seq.append(('v', it[1]))
            continue
        if kind == 'g':
            seq.append(('a', Atom(it[1], '', False, 0, False, True)))
            hold = False
            prev = seq[-1][1]
            continue
        if kind == 's':
            join = ('' if prev is None or prev.text.endswith('>')
                    or prev.text[-1:].isspace() else ' ')
            seq.append(('a', Atom(it[1], join, not hold, 0, False, True)))
            hold = False
            prev = seq[-1][1]
            continue
        w = it[1]
        closer = (w and re.match(CLOSERS_RE, w) and prev is not None
                  and not (w[0] in "'’" and len(w) > 1 and w[1].isalnum()))
        if closer and prev.text.endswith((':', '：')):
            # A speaker's label is followed by its speech, even when that
            # speech is punctuation alone. Keep the authored word gap and
            # keep the punctuation on the same line as the label.
            join, brk = ' ', False
        elif closer:
            # A closer word attaches spaceless to the line it closes: a
            # stranded "?" or "," never starts a line (the whole tail moves
            # down together). Multi-dot ellipses may start one ("..." is a
            # fine dramatic pause), so their attach point stays a break.
            join, brk = '', w.startswith('..')
        else:
            join = ' ' if prev is not None else ''
            brk = True
        if hold:
            brk = False
        pieces = word_pieces(w)
        hold = _is_article(w)
        marked = it[2] if len(it) > 2 else 0
        for k, (text, inner, pen) in enumerate(pieces):
            a = Atom(text, join if k == 0 else '',
                     brk if k == 0 else inner, pen if k else 0,
                     True, k == len(pieces) - 1)
            if k == 0 and marked:
                a.nbrk = True
            seq.append(('a', a))
            prev = a
    # A RUN OF ELLIPSES IS ONE WORD (spec 2.2): '... ... ...' with spaces is a
    # single dramatic beat, never a place to break, and it was shipping as a
    # two-line ellipsis (playtest ADV/E0 #22). Merge the run into one atom.
    # The run may be split by PAUSE codes ('...<FF05><10><00>...'), which are
    # atoms of their own, so it is a run of DOT atoms in the stream: mark every
    # dot after a dot as costly to break before. The codes stay exactly where
    # the source put them - only the break inside the run is discouraged.
    merged = []
    last_dot = False
    for kind, val in seq:
        if kind == 'a' and re.fullmatch(r'[.…]+', val.text):
            if last_dot:
                val.brk = True
                val.pen = 2          # 0 = an ordinary word gap
            last_dot = True
        elif kind == 'b':
            last_dot = False
        elif kind == 'a' and val.word:
            last_dot = False
        merged.append((kind, val))
    return merged


def line_text(text, atom):
    """Grow a line with one atom. Its join only stands where the line already
    has text: a line takes its first piece bare (a run of empty pieces still
    opens the next one bare, exactly as the flow has always spaced it)."""
    return text + ((atom.join or '') if text else '') + atom.text


def stop_cost(text):
    """How badly a line ends (spec 2.4).

    0 = a full stop (the line closes a sentence), 1 = a comma/semicolon/colon,
    (the sentence breathes there), 2 = anywhere else. It is an element of the
    cost tuple BEFORE the look terms, so a layout that ends its lines where
    the sentence breathes wins over one that merely fills the box harder.
    """
    t = re.sub(r'<[^>]+>', '', text).rstrip()
    if not t:
        return 0
    last = t.split(' ')[-1]
    if sent_end(last):
        return 0
    if t[-1:] in ',;:':
        return 1
    return 2


def fullness(w, remaining=1):
    """Positive squared widths favour balance, with a taper toward the tail.
    Earlier lines have more room to carry text; unlike a negative width cost,
    this never rewards making a wide line wider merely for its own sake.
    """
    return w * w // remaining


def flow_layout(atoms, width, measure, tail=1, want=None):
    """Where one run of words breaks - THE line-breaking decision, for both
    jobs: free flow (want=None: the LEAST lines that fit, overflow only where
    no break avoids it) and a fixed skeleton (want=n: exactly n lines, the
    count the Japanese box has and the codes must match). Either way the
    prettiest block wins last, in this order: lines close on a full sentence
    ("Instead of doing this." / "Like a normal person, you know?"), then
    lines as even as the words allow (square), then no dip and nothing
    falling downward (smooth, top-heavy). A hyphen or code split ranks ABOVE
    all of that: a word only ever breaks where it saves a line or an
    overflow - never for a squarer rag ("All-you- | can-eat!" loses to a
    short tail that keeps the compound whole). None of it may buy an extra
    line or an overflow - those come first.
    Returns [(first_atom, last_atom)] spans."""
    n = len(atoms)
    if not n:
        return []
    # cost = (overflow, internal splits, protected phrase breaks, clipped
    # speech fragments after a label, rhythm, shape, first line width).
    # Line count precedes every aesthetic / reading cost at the root.
    # Shape discounts earlier squared widths by remaining line count, plus
    # squared adjacent changes (doubled for growth). This gently tapers the
    # block. Word count by itself never penalises a short utterance.
    # A colon-ended opening atom is the speaker label, supplied as one unit
    # by label_words (or several hyphen pieces for an over-wide label).
    label_end = None
    prefix = ''
    for i, a in enumerate(atoms):
        prefix = line_text(prefix, a)
        if re.fullmatch(r'[^():!?"“”]+:', re.sub(r'<[^>]+>', '', prefix)):
            label_end = i
            break
        if re.search(r'[():!?"“”]', re.sub(r'<[^>]+>', '', prefix)):
            break
    label_width = None
    body_fits = False
    if label_end is not None:
        label = body = ''
        for a in atoms[:label_end + 1]:
            label = line_text(label, a)
        for a in atoms[label_end + 1:]:
            body = line_text(body, a)
        label_width = measure(label)
        body_fits = bool(body) and measure(body) <= width + tail
    # The preceding line's transition cost depends on the FIRST width of its
    # suffix. Keep one optimum per (line count, first width), not just per line
    # count: discarding the other widths makes a locally square suffix create
    # a globally hollow / narrow-middle block.
    best = [{} for _ in range(n)] + [{(0, -1): ((0, 0, 0, 0, 0, 0, -1), -1, None)}]
    for i in range(n - 1, -1, -1):
        text = atoms[i].text
        w = measure(text)
        j = i
        while True:
            lim = width + tail if atoms[j].fin else width
            over = w - lim
            if j + 1 == n or atoms[j + 1].brk:
                base = max(over, 0)
                for subkey, (sub, _end, _next) in best[j + 1].items():
                    k = subkey[0]
                    label_only = i == 0 and j == label_end
                    fragment = (i == 0 and label_end is not None
                                and j > label_end and j + 1 < n
                                and ((body_fits and (stop_cost(text) == 2
                                                     or (stop_cost(text) == 1
                                                         and k == 1 and sub[6] * 2 < w)))
                                     or w - label_width <= width // 5))
                    step = sub[6] - w
                    trans = (step * step + (step * step if step > 0 else 0)
                             if sub[6] >= 0 and not label_only else 0)
                    end = 0 if j + 1 == n else stop_cost(text)
                    # A minor punctuation boundary is not worth stranding a
                    # severely short final fragment. Full sentence boundaries
                    # and standalone speaker labels retain their own rules.
                    if not label_only and k == 1 and sub[6] * 3 < w and end == 1:
                        end += 2
                    # Tail/rise tests are shape costs, not sentence-boundary
                    # vetoes. Otherwise a modest short tail could force a
                    # narrow middle line or a growing triangle regardless of
                    # how much worse its overall shape is.
                    shape = fullness(w, k + 1) + trans
                    if not label_only and k == 1 and sub[6] * 2 < w:
                        shape += (w - 2 * sub[6]) ** 2
                    elif not label_only and k >= 1 and sub[6] * 10 > w * 14:
                        shape += (sub[6] - w) ** 2
                    total = (base + sub[0],
                             (atoms[i].pen if i else 0) + sub[1],
                             (1 if atoms[i].nbrk else 0) + sub[2],
                             sub[3] + int(fragment),
                             sub[4] + end,
                             sub[5] + shape,
                             w)
                    key = (k + 1, w)
                    cur = best[i].get(key)
                    if cur is None or total < cur[0]:
                        best[i][key] = (total, j, subkey)
                if over > 0 and want is None:
                    break
            if j + 1 >= n:
                break
            j += 1
            text = line_text(text, atoms[j])
            w = measure(text)
    if want is None:
        # Least lines, then internal splits, protected phrases, clipped
        # speech fragments, sentence boundaries and the whole block's shape.
        key = min(best[0], key=lambda key: (best[0][key][0][0], key[0])
                  + best[0][key][0][1:6])
    else:
        key = min(best[0], key=lambda key: (abs(key[0] - want),)
                  + best[0][key][0][:6])
    out, i = [], 0
    while i < n:
        _cost, j, next_key = best[i][key]
        out.append((i, j))
        i, key = j + 1, next_key
    return out


def flow_lines(items, width=BOX_WIDTH, measure=text_width, newline=NEWLINE,
               tail=1):
    """The textbox flow every porter and builder reflows through: the single
    place that decides where text breaks, so the rules and the look apply by
    default. items: ('w', word) words (speaker labels ride as words with the
    colon glued to the tail word, so long labels wrap at word gaps and the
    colon never strands alone); ('b', code) deliberate break (flush, emit
    code); ('s', code) spaced inline codes (names: spaces both sides);
    ('g', code) glued inline codes (pauses: join the line, next word spaced);
    ('G', code) voice codes: emitted before the line they sit in while the
    line keeps accumulating. Returns [('t', line) | ('c', code)] in stream
    order. tail = extra pixels the very last line may take (the VWF pen
    reaches 240 and wraps only before the next glyph; art that has no such
    room passes 0).
    Rules: deliberate breaks split the flow and stay where they are; within
    one run of words the LEAST lines that fit are used, then the squarest
    block (lines as equal as the words allow, never more lines to get it);
    closer-leading words attach spaceless so a stranded "?" or "," never
    starts a line (leading "..." may); hyphen/code splits exist but cost a
    split, so a word only breaks when that saves a line or an overflow;
    proclitics (a/an/the/to/of/in/on/at) never end a line (glued to what
    follows up front); width-made lines cap at 239 (pen 240 + explicit break
    skips a line), only the very last line before a wait, page, end, or
    nothing may use 240; anything still unbreakable is accepted for the
    width warning."""
    items = _glue_items(items)
    seq = flow_model(items)
    # the pen-240 allowance: only a line holding the last word of the whole
    # stream, and never one directly before an explicit break (that skips)
    more = False
    for k in range(len(seq) - 1, -1, -1):
        if seq[k][0] == 'a':
            seq[k][1].fin = (seq[k][1].word and seq[k][1].last and not more
                             and (k + 1 == len(seq) or seq[k + 1][0] != 'b'
                                  or seq[k + 1][1] != newline))
            more = more or seq[k][1].word
    out, region = [], []

    def flush():
        if not region:
            return
        atoms = [a for k, a in region if k == 'a']
        spans = flow_layout(atoms, width, measure, tail)
        # voice codes print before the line their stream position sits in
        # (the line that was still accumulating when they fired)
        line_of = {}
        for li, (i, j) in enumerate(spans):
            line_of.update((a, li) for a in range(i, j + 1))
        voice = [[] for _ in range(len(spans) or 1)]
        ai = -1
        for k, v in region:
            if k == 'a':
                ai += 1
            else:
                voice[line_of.get(ai if ai >= 0 else 0, 0)].append(v)
        for li, (i, j) in enumerate(spans):
            if li:
                out.append(('c', newline))
            out.extend(('c', c) for c in voice[li])
            text = ''
            for a in atoms[i:j + 1]:
                text = line_text(text, a)
            if text:
                out.append(('t', text))
        if not spans:
            out.extend(('c', c) for c in voice[0])
        region.clear()

    for entry in seq:
        if entry[0] == 'b':
            flush()
            out.append(('c', entry[1]))
            continue
        region.append(entry)
    flush()
    return out



def fill_lines(words, n, width=BOX_WIDTH, measure=text_width, tail=1):
    """Lay words into exactly n lines: the flow's own rules and its squarest
    block, at a line count a SKELETON fixes (the Japanese box has n lines and
    its control codes must match, so the count is not ours to choose - only
    the break points are). Same engine as flow_lines: nothing else decides a
    break anywhere. Returns the lines (fewer when the words are fewer)."""
    atoms = [a for k, a in flow_model(_glue_items([('w', w) for w in words]))]
    if atoms:
        atoms[-1].fin = True
    spans = flow_layout(atoms, width, measure, tail, n)
    out = []
    for i, j in spans:
        text = ''
        for a in atoms[i:j + 1]:
            text = line_text(text, a)
        out.append(text)
    return out


def wrap_line(line, width=BOX_WIDTH, measure=text_width, newline=NEWLINE,
              tail=1):
    """Reflow one run of text (no deliberate break inside) into a list of
    lines - the shared flow engine with word-only input, so every reflow
    anywhere breaks the same way. Words stay whole unless a hyphen/code
    split saves a line; anything still unbreakable is left for the width
    warning."""
    return [v for k, v in flow_lines([('w', w) for w in line.split(" ")],
                                     width, measure, newline, tail)
            if k == 't']


def wrap(text, width=BOX_WIDTH):
    # split on explicit newlines (deliberate breaks: kept, never re-balanced)
    # but keep page/wait tokens attached to their line
    result = []
    for logical in text.split(NEWLINE):
        result.extend(wrap_line(logical, width))
    # choice options (<FF0E>) start on their own line, and where their
    # break goes is the pen's - decided on the WRAPPED layout, never on
    # the words (see choice_breaks)
    return choice_breaks(NEWLINE.join(result))


PARAM_LEN = {'05': 2, '06': 1, '07': 1, '08': 1, '0E': 1, '0F': 1,
             '10': 1, '11': 0, '12': 0}   # control codes and their parameter bytes


def atoms(en):
    """[(kind, text)]: a control code WITH its parameters is one atom, so
    a parameter can never be mistaken for text (a choice prompt's set byte
    may itself be a space)."""
    out, i = [], 0
    while i < len(en):
        m = re.match(r'<FF([0-9A-F]{2})>', en[i:])
        if not m:
            out.append(('t', en[i]))
            i += 1
            continue
        j = i + m.end()
        for _ in range(PARAM_LEN.get(m.group(1), 0)):
            tm = re.match(r'<[0-9A-F]{2}>', en[j:])
            if tm:
                j += tm.end()
            elif j < len(en):
                j += 1
            else:
                break
        out.append(('c', en[i:j]))
        i = j
    return out


def clean_edges(en):
    """Strip padding blanks around codes and box edges - the EN box must
    open on text, never on blanks or a wait.

    Japanese padding (ASCII + ideographic spaces) is not wording and a
    fixed slot counts every byte: 'You already have this Persona. ' costs
    one more byte than it can ever show. Two things are never padding:
    name inserts (FF07/08/0F), battle inserts and pauses (FF05) render as
    words and keep their neighbours' spacing ("Mark:<name>found", "Mark:<pause>Dammit!"),
    and a control code's PARAMETER travels with its code - <FF0E> is
    followed by its choice-set byte, which may itself be a space (0x88)."""
    toks = atoms(en)
    # Names, numeric inserts and pauses can occupy visible space. Battle
    # insertion tokens come from the same decomp-derived set used to price
    # their width, rather than a second hand-maintained list.
    keep = ('<FF05>',) + NAME_CODES
    battle_inserts = frozenset(BTL_INSERT_WIDTHS)
    out, i = [], 0
    while i < len(toks):
        kind, text = toks[i]
        if kind == 't' and text in ' \t　':
            j = i
            while j < len(toks) and toks[j][0] == 't' and toks[j][1] in ' \t　':
                j += 1
            run = ''.join(a[1] for a in toks[i:j])
            prev = toks[i - 1] if i else None
            nxt = toks[j] if j < len(toks) else None
            nbrs = [x for x in (prev, nxt) if x]
            if prev is None or nxt is None:
                pass                          # box edge: padding
            elif any(x[0] == 'c' and x[1].startswith(keep) for x in nbrs):
                out.append(run)               # spacing around a name/pause
            elif (any(x[0] == 'c' and x[1] in battle_inserts for x in nbrs)
                  and not any(x[0] == 'c' and x[1] not in battle_inserts for x in nbrs)):
                out.append(run)               # visible battle insert, not a break
            elif any(x[0] == 'c' for x in nbrs):
                pass                          # padding beside a code
            else:
                out.append(run)               # spacing between words: wording
            i = j
            continue
        out.append(text)
        i += 1
    return re.sub(r'^(<FF0[234]>)+', '', ''.join(out))


def prompt_label_line(head, brk=NEWLINE, width=BOX_WIDTH, measure=text_width):
    """The prompt's own box, its speaker label on a line of its own.

    The label is prose and shares line 1 (spec 4.2) - except in a CHOICE PROMPT
    whose question then fits ONE line: retail's own shape is
    "アガスティアの木：<FF03>汝の記録を　我に刻むのか？" (label, break, the whole
    question), and it is the question the player reads while picking. A label
    that eats half the line splits the question in two instead.

    Only the prompt's own box (the text after its last page move), only when the
    rest of that box is ONE plain sentence that fits, and only when the box
    carries no other code (a name insert or a pause keeps the box's own
    spacing - those boxes are left exactly as the flow laid them out). Returns
    `head` unchanged whenever the test fails.
    """
    parts = re.split(r'(<FF02><FF04>|<FFFB><FFF7>)', head)
    box = parts[-1]
    plain = box.replace(brk, ' ')
    if '<' in plain or brk in plain:
        return head
    words = plain.split()
    label = []
    for w in words:
        label.append(w)
        if w.endswith(':'):
            break
    else:
        return head                      # no label in this box
    rest = ' '.join(words[len(label):])
    if not rest or not sent_end(rest) or measure(rest) > width:
        return head
    return (''.join(parts[:-1]) + ' '.join(label) + brk + rest)


def choice_breaks(en, brk=NEWLINE):
    """Choice options start on their own line - and the PEN decides where
    their break goes, never a blanket rule.

    A bare <FF0E> is right iff the pen is already at a line start when the
    prompt fires: the line in front of it is blank, or full enough that the
    engine wrapped it. A break in that spot skips a line. Any
    other pen position needs the break, or the first option draws mid-line
    ("me?Yes"). So this normalizes BOTH directions, and only ever the one
    break that is layout: nothing is added, dropped, or reworded.

    `brk` is the family's own line move: <FF03> in a textbox, <FFF6> in a
    btlevt box. THE rule - the porters lay wording out with it and the QA
    gate tests against it, so layout and verification use the same rule.

    ... AND A PROMPT THAT ALREADY REACHES THE BOX'S LAST VISIBLE ROW PAYS A
    SCROLL FOR THE OPTION BLOCK, so its line is GATED: '<FF02><FF03>' (press,
    then the line) is the PSX corpus' own spelling for that prompt (463 rows,
    against 47 bare ones, and every bare one is a ONE-line prompt). A bare
    line on a full box would autoscroll without a player press. The block needs the
    arming line plus one row per option, so the gate is due from the box's
    second-to-last row: prompt lines >= per - 1."""
    wait = '<FFFB><FFF7>' if brk == '<FFF6>' else '<FF02>'
    per = 4 if brk == '<FFF6>' else 3
    out, i = [], 0
    while True:
        j = en.find('<FF0E>', i)
        if j < 0:
            return ''.join(out) + en[i:]
        head = en[i:j]
        # the wait/break a previous layout put in front of the prompt is what
        # this function decides again below - clear it so the label test sees
        # the prompt's own text
        head = re.sub(r'(?:' + re.escape(wait) + r'|' + re.escape(brk) + r')+$', '', head)
        head = prompt_label_line(head, brk)
        # only the break right in front of the prompt is the prompt's own -
        # it goes FIRST, or it is what makes the pen look like a line start
        head = re.sub(r'(?:' + re.escape(brk) + r')+$', '', head)
        # the pen at the prompt: the ink since the last line/page move.
        # Codes are no ink of their own (a pause, a name slot) and move no
        # pen; a wait (<FF02>) neither - the line runs on behind it.
        line = re.sub(r'<[^>]*>', '', re.split(r'<FF0[34]>|<FFF6>|<FFF7>', head)[-1])
        bare = not line.strip() or text_width(line) > BOX_WIDTH
        # the box the prompt sits in: everything since its last page move
        box = re.split(r'<FF02><FF04>|<FFFB><FFF7>', head)[-1]
        lines = box.count(brk) + 1
        # A SPEAKER LABEL ON ITS OWN LINE IS NOT A PROMPT LINE: it is a
        # nameplate (spec 4.2), not text the option block has to clear. Retail's
        # own shape is "Agastya Tree:" / the question / the options, and the
        # question - ONE line when the label steps aside (prompt_label_line) -
        # is what decides the gate. Counting the nameplate made every prompt
        # with a long name pay a press for nothing.
        plate = re.sub(r'<[^>]*>', '', re.split(brk, box)[0]).strip()
        if lines > 1 and plate.endswith(':'):
            lines -= 1
        full = lines >= per - 1
        if not bare:
            head = re.sub(r'(?:' + re.escape(wait) + r')+$', '', head)
        out.append(head)
        if bare:
            out.append('<FF0E>')
        else:
            out.append((wait if full else '') + brk + '<FF0E>')
        i = j + len('<FF0E>')


def check(text, width=BOX_WIDTH):
    ok = True
    for line in text.split(NEWLINE):
        w = text_width(line)
        flag = "" if w <= width else "  <-- overflow"
        ok &= w <= width
        print(f"{w:4} px  {line}{flag}")
    return ok


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if args and args[0] == "--check":
        sys.exit(0 if check(args[1]) else 1)
    print(wrap(args[0]))
