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
import contextlib
import functools
import os
import toolpath  # noqa: E402  (src/ is on sys.path when this is imported)
import re
import strlib   # noqa: E402  (the headered-TSV reader; needs the toolbelt path)
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
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
BOX_LINES = 3      # the lines one box shows without a scroll
BOX_ENDS = ('<FF04>', '<FFF7>', '<FF01>', '<FFEF>', '<FFF5>')   # a fresh box
NEWLINE = "<FF03>"
PAUSE_CODE = re.compile(r'<FF05><[0-9A-F]{2}><[0-9A-F]{2}>')
VOICE_CODES = ('<FFEB>', '<FFEC>', '<FFED>', '<FFEE>')   # a speaker's voice
TOKEN = re.compile(r"(<[^>]+>)")

# Every edition's advances, and the one being measured: the build's
# (toolpath.FONT_EDITION) unless a caller measures another face's layout of
# a row (measured_as) - a porter checking both layouts in one process. The
# stack is per thread: textvis's server measures both editions at once.
_WIDTHS = {}
for _edition in toolpath.FONT_EDITIONS:
    with open(toolpath.font_path("width", _edition), "rb") as f:
        _WIDTHS[_edition] = f.read()


class _Measuring(threading.local):
    def __init__(self):
        self.stack = [toolpath.FONT_EDITION]


_MEASURING = _Measuring()


@contextlib.contextmanager
def measured_as(edition):
    """Measure (char_width, text_width, the flow) with `edition`'s face."""
    _MEASURING.stack.append(edition)
    try:
        yield
    finally:
        _MEASURING.stack.pop()


def edition_cache(maxsize):
    """functools.lru_cache keyed on the arguments AND the face being
    measured: a width-dependent result is one edition's, never handed to
    the other inside measured_as."""
    def wrap(fn):
        cached = functools.lru_cache(maxsize=maxsize)(lambda edition, *args: fn(*args))

        @functools.wraps(fn)
        def call(*args):
            return cached(_MEASURING.stack[-1], *args)
        call.cache_clear = cached.cache_clear
        return call
    return wrap


def measuring():
    """The font edition being measured (measured_as, else the build's)."""
    return _MEASURING.stack[-1]


def char_width(c):
    return _char_width(c, _MEASURING.stack[-1])


@functools.lru_cache(maxsize=None)
def _char_width(c, edition):
    _widths = _WIDTHS[edition]
    # ONE SPELLING RULE with the encoder (etext.spell): a character the font
    # prints as an ASCII one is priced as that ASCII one, or the flow would
    # price '’' at the Japanese 16px fallback and wrap a line that fits.
    import etext
    import make_vwf_font
    c = etext.spell(c)
    if c in ('＞', '＜') and c not in make_vwf_font.EXTRA_CODE and c not in make_vwf_font.ATLAS_CODE:
        c = '>' if c == '＞' else '<'
                    # the table spelling of the head marks; the glyphs the
                    # engine draws are the ASCII ones (etext encodes them
                    # so), so the flow prices a mark at its real width
    o = ord(c)
    if 0x20 <= o <= 0x7E:
        return _widths[o - 0x20]
    # the extra character-map entries have real VWF glyphs of their own
    # (make_vwf_font.EXTRA) - they are NOT the 16px Japanese fallback
    slot = make_vwf_font.ATLAS_CODE.get(c)
    if slot is not None:
        return make_vwf_font.atlas_glyphs(edition)[slot][-1]
    k = make_vwf_font.EXTRA_CODE.get(c)
    return _widths[k - 0x20] if k is not None else 16


# Words that look sentence-final but aren't (abbreviations, initials).
SENT_ABBREVS = {'mr', 'mrs', 'ms', 'dr', 'st', 'jr', 'sr', 'vs', 'etc',
                'e.g', 'i.e', 'no', 'fig', 'sen'}
SENT_END_RE = re.compile(r'[.!?…]+["\'”)\]]?$')
# THE SPEECH HEART (❤) is the speaker's flourish, not a word: it stands
# after the sentence's own mark with a space (`I'm your man. ❤`), never
# starts a line, and no grammar test sees it - the line ends where the mark
# before it does.
SPEECH_HEART = '\u2764'
_PLAIN_RE = re.compile(r'<[^>]+>|\s*' + SPEECH_HEART + '+')


def hanging_heart(text, measure):
    """The width of the speech hearts (and their space) that close text."""
    m = re.search(r'\s*' + SPEECH_HEART + r'+\s*$', text)
    return measure(text) - measure(text[:m.start()]) if m else 0


def _plain(text):
    """The words a grammar test reads: codes and speech hearts gone."""
    return _PLAIN_RE.sub('', text)


@edition_cache(131072)
def sent_end(w):
    """True when a word ends a sentence (not an abbreviation/initial).
    Control codes are ignored: `today.<FF02>` closes the sentence."""
    t = _plain(w).rstrip()
    if not SENT_END_RE.search(t):
        return False
    # Abbreviations and initials end in ONE plain period ("No.", "A.");
    # "no!", "no?" and "no..." close their sentence.
    if not re.search(r'(?<!\.)\.["\'”)\]]?$', t):
        return True
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
# (8 typed characters each, name entry limit), <FF08> nickname (up to 8).
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
NAME_LENS = {'07': 8, '0F': 8, '08': 8}   # entry cells used (8/8 typed + 8 nickname)
@functools.lru_cache(maxsize=None)
def name_widths(edition):
    """{name code: px} of the widest name a name insert can print, in an
    edition's face."""
    with measured_as(edition):
        return {k: sum(char_width(c) for c in 'R' * n) for k, n in NAME_LENS.items()}


NAME_WIDTHS = name_widths(toolpath.FONT_EDITION)
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


def btl_insert_slots():
    """{code byte: slot} from windowtype.c: the slot each <FFFx> points at.

    The code names are NOT the slot numbers: CODE_INSERT2 (0xF0) reads
    slot 2, but BtlSetInsert's case 6 is what fills slot 2. Read the
    `g_btl_insert[n].cell` the case body names, never the case number."""
    with open(os.path.join(DECOMP_BTLP, 'windowtype.c'), encoding='utf-8') as f:
        win = f.read()
    opcodes = {int(m.group(1)): int(m.group(2), 0) for m in re.finditer(
        r'#define\s+CODE_INSERT(\d)\s+(0x[0-9A-Fa-f]+)', win)}
    slots = {}
    for m in re.finditer(r'case\s+CODE_INSERT(\d)\s*:(.*?)(?=\n\s*case\s|\n\s*default|\Z)',
                         win, re.S):
        dest = re.search(r'g_btl_insert\[(\d+)\]\.cell', m.group(2))
        if dest and int(m.group(1)) in opcodes:
            slots[opcodes[int(m.group(1))]] = int(dest.group(1))
    return slots


def btl_insert_caps():
    """{code byte: glyphs} the battle window's insert codes can occupy.

    windowtype.c maps a code to the slot it points at; insert.c's case n
    is what fills a slot - and the case numbers are not the slot numbers
    (case 2 writes slot[3], case 3 slot[4], case 4 slot[6], case 6
    slot[2]), so the destination is read from each case body. A body holds
    a decimal value or a name copy capped at INSERT_SHORT/INSERT_LONG;
    number.c says how many digits a value prints (DECIMAL_TOP) and the
    value may carry a minus, so the slot holds that many glyphs. The
    slot's own cell array is the hard bound, and a copy can never exceed
    it."""
    with open(os.path.join(DECOMP_BTLP, 'insert.c'), encoding='utf-8') as f:
        ins = f.read()
    with open(os.path.join(DECOMP_BTLP, 'number.c'), encoding='utf-8') as f:
        num = f.read()
    short, long = _cdef(ins, 'INSERT_SHORT'), _cdef(ins, 'INSERT_LONG')
    # 0x18 bytes of (attribute, glyph) pairs, one end byte
    m = re.search(r'u_char\s+cell\[(0x[0-9A-Fa-f]+|\d+)\]', ins)
    cell = int(m.group(1), 0) if m else None
    digits = len(str(_cdef(num, 'DECIMAL_TOP')))   # 1000000000 -> 10 places
    code_of_slot = {slot: code for code, slot in btl_insert_slots().items()}
    caps = {}
    for m in re.finditer(r'case\s+(\d)\s*:(.*?)(?=\n\s*case\s|\n\s*default|\Z)',
                         ins, re.S):
        body = m.group(2)
        dest = re.search(r'slot\[(\d+)\]\.cell', body)
        code = code_of_slot.get(int(dest.group(1))) if dest else None
        if code is None:
            continue
        if 'BtlFormatDecimal' in body:
            caps[code] = digits + 1                # the digits plus a minus
        else:
            c = re.search(r'BtlStrCopy(?:Esc)?\([^,]+,[^,]+,\s*'
                          r'(INSERT_SHORT|INSERT_LONG)\)', body)
            if c:
                caps[code] = short if c.group(1) == 'INSERT_SHORT' else long
    if cell:
        caps = {code: min(c, (cell - 1) // 2) for code, c in caps.items()}
    return caps


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
def _btl_insert_widths(edition):
    """The decomp-capped battle insert prices in an edition's face: `cap`
    copies of its widest ASCII letter."""
    with measured_as(edition):
        glyph = max(char_width(chr(c)) for c in range(0x20, 0x7F))
    return {'<FF%02X>' % code: cap * glyph for code, cap in btl_insert_caps().items()}


BTL_INSERT_WIDTHS = _btl_insert_widths(toolpath.FONT_EDITION)
BTL_NAME_INSERT_CODES = btl_name_insert_codes()


def battle_insert_widths():
    return _battle_insert_widths(_MEASURING.stack[-1])


@functools.lru_cache(maxsize=None)
def _battle_insert_widths(edition):
    """{token: px} for the battle window's <FFFx> inserts - the ONE pricing.

    Two kinds of value reach a slot:

    * a FIXED FIELD or a decimal, exactly as retail's copy left it (the
      hero / a party member's 10-byte name slot,
      an arcana cell, BtlFormatDecimal's digits). The decomp's copy cap
      bounds those, and `btl_insert_caps` reads it.

    * a COMPLETE ported name: btlp/full_names.asm replaces the copy with
      `btl_name_copy`, which resolves an item record (head + item tail
      bank), a direct battle Persona record and an offer's demon name
      (head + OFFER_NAME_BANK tail)
      before encoding, so those codes print the whole name, not the retail
      cap. The bound is then the widest name of that family in the ported
      tables - a fact about the wording, so the PORT derives it
      (port_widths.py writes insert_widths.tsv) and this only reads the
      table.

    Overriding by token keeps both in one place: a code the port measures
    is priced from the table, every other code from the decomp."""
    widths = _btl_insert_widths(edition)
    table = insert_widths()
    for token in widths:
        if token in table:
            widths[token] = table[token]
    return widths


# --- message-machine name inserts ------------------------------------
# The dialogue engine's record insert prints the record the caller points
# at through the same VWF metrics as text: the small-font bytes go through
# vwf_small_map to ASCII and char_width prices them. So a line that
# carries an insert must leave room for the WIDEST name that code can
# print, not zero:
#   <FF09> item      <FF0A> skill     <FF0B> demon
#   <FF0C> Persona (ADV) / demon (DNG field script)
#   <FF13> arcana    (retail's own full-width Latin table)
# Which name is widest is a fact about the PORTED wording, so the port
# derives the widths (porting/port_widths.py, from the
# canonical name tables + the retail arcana cells) and this engine only
# reads its table - no name is typed or scanned here.
INSERT_CODES = ('<FF09>', '<FF0A>', '<FF0B>', '<FF0C>', '<FF13>')
INSERT_WIDTHS_PATH = os.path.join(toolpath.TRANSLATION, 'generated',
                                  'insert_widths.tsv')


@functools.lru_cache(maxsize=1)
def insert_widths():
    """{insert token: px} from the port's table (port_widths.py)."""
    try:
        rows = strlib.tsv_rows(INSERT_WIDTHS_PATH, required=('code', 'px'))
    except FileNotFoundError:
        raise SystemExit(
            'vwf_wrap: ' + os.path.relpath(INSERT_WIDTHS_PATH, ROOT) +
            ' is missing - the insert widths are port-derived data; run '
            'python src/porting/port.py')
    return {'<%s>' % r['code']: int(r['px']) for r in rows}


@edition_cache(131072)
def text_width(s):
    s = edition_text(s, _MEASURING.stack[-1])  # a row laid out for every edition: the measured one's
    w = 0
    def _name(m):
        nonlocal w
        w += name_widths(_MEASURING.stack[-1])[m.group(1)]
        return ''
    s = NAME_TOKEN_RE.sub(_name, s)
    battle = battle_insert_widths()
    return (w
            + sum(char_width(c) for part in TOKEN.split(s)
                  if not TOKEN.fullmatch(part) for c in part)
            # an insert token is not zero: the window draws the name (or
            # value) the game fills it with, and the flow must leave the
            # room that copy takes (battle_insert_widths, INSERT_WIDTHS)
            + sum(battle[t] for t in TOKEN.findall(s) if t in battle)
            + sum(insert_widths()[t] for t in TOKEN.findall(s)
                  if t in INSERT_CODES))


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
# CONNECTORS bind to the phrase AFTER them: "go | to the station" - a line
# starts on the connector, never ends on one (the subtitling standard, and
# what viewers pick: "the tech | to doctor a bit", "vinyl | in the burnt-out
# remains", "find me | but there is no point"). A connector that carries
# its own punctuation ("at?", "so,") ends its clause and stays free.
CONNECTORS = {'to', 'of', 'in', 'on', 'at', 'with', 'from', 'for', 'by',
              'as', 'and', 'or', 'but', 'nor', 'than', 'that', 'into',
              'onto', 'about', 'over', 'under', 'off', 'upon', 'without',
              'through', 'toward', 'towards', 'between', 'among', 'against',
              'so', 'yet'}
# QUESTION WORDS open a clause the way a subordinator does ("about what |
# happens", "don't know what | to do"): a line ending on a bare one pays
# the same.
QUESTION_WORDS = {'what', 'who', 'whom', 'whose', 'which', 'how', 'why'}
# Connectors that are also a verb's PARTICLE ("go on calling", "come in
# now"): one opens a phrase only when a noun phrase follows it (an article,
# possessive, pronoun, name or number - "in the burnt-out remains", "on
# Tuesday"); otherwise it belongs to its verb and binds BACK ("might as
# well / go on calling it").
# The adverb particles (out, up, down, ...) are no connectors but bind the
# same way: "go get yourselves checked out / at Mikage Hospital", never
# "checked / out at".
PARTICLES = {'on', 'off', 'over', 'in', 'about', 'through', 'under', 'by',
             'out', 'up', 'down', 'away', 'back', 'around'}
# SUBORDINATORS open the clause they introduce, so they bind FORWARD, but
# softly: "You should visit her | while you're there" - a line may begin
# with one, and ends on one only when that saves a line (a marked break,
# ranked like a name split).
SUBORDINATORS = {'because', 'while', 'when', 'where', 'if', 'until',
                 'unless', 'although', 'though', 'since', 'whether'}
# POSSESSIVES bind to their noun softly: a break between them ("at the end of
# her | journey") is allowed and costs a rhythm point, so a clearly better
# shape may take it. The other determiners (a, the, this, these, those) stay
# glued: "this is" is a pronoun phrase, not a determiner and its noun.
POSS = {'its', 'their', 'his', 'her', 'our', 'your', 'my'}
SOFT_POSS = True
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


# A pure article before a subordinator makes it a noun ("for a while").
PURE_ARTICLES = {'a', 'an', 'the'}
# Leads of compound subordinators ("as if", "even though", "only when"):
# they open the clause together with the subordinator after them.
SUB_LEADS = {'as', 'even', 'only', 'just', 'ever'}
# Fixed two-word phrases that read as one word: an adverbial idiom ("at
# least", "at once") or a degree word and its quantifier ("too much", "so
# many").
# The first glues onto the second; a line may begin on the pair.
FIXED_PAIRS = {('at', 'least'), ('at', 'most'), ('at', 'last'),
               ('at', 'first'), ('at', 'all'), ('at', 'once'),
               ('too', 'much'), ('too', 'many'), ('so', 'much'),
               ('so', 'many'), ('very', 'much'), ('how', 'much'),
               ('how', 'many'), ('as', 'much'), ('as', 'many'),
               ('that', 'much'), ('that', 'many')}


# Compound subordinators ("now that", "so that") open their clause together,
# softly: a break between the two pays SUB_PAIR_SPLIT, so a clearly better
# shape still takes it ("It's much easier now / that I've met you all...").
SUB_PAIRS = {('now', 'that'), ('so', 'that')}
SUB_PAIR_SPLIT = 1


def _first(w):
    return _core_word(w).split(' ', 1)[0].lower()


def _binds_forward(out, i):
    """Does word i glue onto the word after it (glue pass 1)?"""
    word, nxt = out[i][1], out[i + 1][1]
    test = _core_word(word)
    bare = test.rstrip(',;:').lower()
    follows_sub = _first(nxt) in SUBORDINATORS
    if bare in ARTICLES:
        # 'her while ...' is the pronoun ending its clause; 'a while' is
        # the article of a noun
        return bare in PURE_ARTICLES or not follows_sub
    if (test.lower(), _first(nxt).rstrip('.,;:!?…"”’)')) in FIXED_PAIRS:
        return True
    return test.lower() in SUB_LEADS and follows_sub


# Pronouns that are only ever a subject: a line ending on one cuts the
# subject from its verb ("..., but I / ended up getting caught"). "you" and
# "it" are objects as often as subjects ("I want you / to keep...").
SUBJECTS = {'i', 'he', 'she', 'we', 'they'}
# A pronoun or question word contracted with its verb ("what's", "I'll",
# "it's") is a subject AND its verb: a line ending on one cuts the verb from
# the rest of its clause ("what's / got me so pissed off?").
CONTRACTED = SUBJECTS | {'you', 'it', 'that', 'what', 'who', 'there',
                         'here', 'where', 'how'}
CONTRACTIONS = ("'s", "'re", "'ll", "'ve", "'d", "'m")
# Pronouns that are only ever an object: a line opening on one cuts it from
# the verb before it ("Don't blame / me when..."). "you" and "it" are
# subjects as often as objects; "her" is a possessive too.
OBJECTS = {'me', 'him', 'us', 'them'}


@edition_cache(1 << 16)   # pure in the line text; the layout asks per suffix
def ends_on_subject(text):
    return ends_on_contraction(text) or _last_plain(text) in SUBJECTS


def _last_plain(text):
    """The line's last word, lowercased; after a dash its last part ("run
    away--I" ends on "i")."""
    words = _plain(text).split()
    if not words:
        return ''
    return re.split(r'--|—', words[-1])[-1].lower().replace('\u2019', "'")


# What a line ending on a subordinator and the subject after it pays on top
# of a subject's end: the clause's opener and subject both left behind
# ("while I'm / gone" is worse than "while / I'm gone").
SUBORDINATE_SUBJECT_END = 1


@edition_cache(1 << 16)   # pure in the line text; the layout asks per suffix
def ends_on_subordinate_subject(text):
    words = _plain(text).split()
    return (len(words) > 1 and words[-2].lower() in SUBORDINATORS
            and ends_on_subject(text))


@edition_cache(1 << 16)   # pure in the line text; the layout asks per suffix
def ends_on_contraction(text):
    last = _last_plain(text)
    if not last:
        return False
    stem, _, tail = last.partition("'")
    return stem in CONTRACTED and "'" + tail in CONTRACTIONS


@edition_cache(1 << 16)   # pure in its two texts; the layout asks per candidate line
def opens_on_object(prev, nxt):
    """Does a line opening on nxt (its first piece) cut an object pronoun
    from the verb that ends the line before it? Not after a connector
    ("look at / me" breaks where a phrase starts) or punctuation."""
    first = _core_word(nxt).split(' ', 1)[0].lower()
    if first.rstrip('.,;:!?…"”’)') not in OBJECTS:
        return False
    words = _plain(prev).split()
    return bool(words) and words[-1].lower() not in CONNECTORS


@edition_cache(1 << 16)   # pure in the line text; the layout asks per suffix
def strands_opener(text):
    """Does the line end on the first word of a new sentence ("Anything is
    nonsense! Anything / nowadays...", "Let's go back! Yosuke's / hurt!")?
    The sentence end is the strongest break there is (Gerber-Moron &
    Szarkowska 2018: 85-95% of viewers): its next sentence starts the next
    line whole. An ellipsis ends a sentence only when a capital follows
    ("zombie... but / you're cool" goes on)."""
    words = _plain(text).split()
    if len(words) < 2 or not re.search(r'[.!?…]["”’)]*$', words[-2]):
        return False
    trails = bool(re.search(r'(?:\.\.|…)["”’)]*$', words[-2]))
    return not trails or words[-1].lstrip('"“‘(')[:1].isupper()


def starts_sentence_in(text):
    """Does a new sentence start inside the line, after a sentence end, and
    run on past its end ("The door is locked. Could that girl / have
    been...")? The caller knows the line ends mid-clause. Its lone first
    word is strands_opener; more of it strands only after a full stop
    (. ! ?): a beat that trails off runs on into the next sentence
    ("Masao... They tell me / you hate heights.")."""
    if strands_opener(text):
        return True
    words = _plain(text).split()
    for k in range(len(words) - 2):
        if (re.search(r'[.!?]["”’)]*$', words[k])
                and not re.search(r'(?:\.\.|…)["”’)]*$', words[k])
                and sent_end(words[k])):
            return True
    return False


# What a line pays for ending on a determiner whose "of" phrase opens the
# next line ("Do any / of these treasure boxes"): one rhythm point, as a
# connector pays. A quantifier and its partitive are one phrase.
PARTITIVE_END = 1


@edition_cache(1 << 16)   # pure in the two texts; the layout asks per candidate line
def splits_partitive(text, nxt):
    """Does the line cut a quantifier's "of" phrase: end on a determiner
    (lexicon `det`) with "of" opening the next line ("any / of these", "all
    / of us"), or end on the determiner's "of" itself ("any of / this food"
    - on top of the connector's own point: the "of" gains nothing up there)?"""
    words = _plain(text).split()
    following = _plain(nxt).split()
    det = lambda w: 'det' in lexicon().get(w.lower(), ())
    if len(words) > 1 and words[-1].lower() == 'of' and det(words[-2]):
        return True
    return (bool(words) and bool(following)
            and following[0].lower() == 'of' and det(words[-1]))


@edition_cache(1 << 16)   # pure in the line text; the layout asks per suffix
def ends_on_subordinator(text):
    """Does a line end on a subordinator that opens the next clause? Not
    when punctuation closes it ('while,') or an article makes it a noun
    ('for a while')."""
    words = _plain(text).split()
    if not words or words[-1].lower() not in SUBORDINATORS | QUESTION_WORDS:
        return False
    return len(words) < 2 or words[-2].lower() not in PURE_ARTICLES


# Closed-class words that open a phrase: question words, quantifiers and
# indefinite pronouns ("about | what happens", "over | something like this").
PHRASE_OPENERS = {'what', 'who', 'whom', 'which', 'where', 'when', 'why', 'how',
                  'whatever', 'whoever', 'all', 'each', 'every', 'some', 'any',
                  'no', 'both', 'such', 'many', 'much', 'few', 'several', 'one',
                  'something', 'anything', 'nothing', 'everything', 'someone',
                  'anyone', 'everyone', 'no-one', 'somebody', 'anybody',
                  'everybody', 'nobody'}


# What a line that ends on a connector pays (rhythm points, on top of its
# mid-clause end): the connector opens the phrase after it, and the reader
# should meet it there - but softly: a whole noun phrase on one line beats
# it ("I feel sorry for / the rest of the Tailors crew, / but I got places
# to be.").
CONNECTOR_END = 1
# What a break between a noun and its modifiers costs ("in your / class",
# "the easiest / way"): rhythm points on top of the mid-clause end.
NOUN_SPLIT = 2


@edition_cache(1 << 16)   # pure in the two texts; the layout asks per candidate line
def ends_on_connector(text, nxt):
    """Does the line end on a connector that opens the phrase starting with
    nxt? (A particle that opens none is its verb's: "go on / calling".)"""
    words = _plain(text).split()
    if not words:
        return False
    con = words[-1].lower()
    if con == 'like':
        return _like_preposition(words) and _opens_noun_phrase(con, nxt)
    if con not in CONNECTORS:
        return False
    return con not in PARTICLES or _opens_noun_phrase(con, nxt)


# What a line ending on the preposition "like" pays: half a connector's
# point - "like that" leans together, but a better shape still splits it.
LIKE_END = 0.5
# Words in front of "like" that make it the verb ("I like", "would like",
# "don't really like"), or a linking verb it completes ("sounds like / a big
# phony", "be like / this"): elsewhere it is the preposition ("stink like /
# humans", "stuff like / that") and binds forward as a connector does.
LIKE_VERB_ADVERBS = {'really', 'just', 'also', 'still', 'kinda', 'actually',
                     'even', 'not', 'no', 'never', 'always', 'totally', 'so',
                     'quite'}
LINKING_VERBS = {'seem', 'seems', 'seemed', 'sound', 'sounds', 'sounded',
                 'look', 'looks', 'looked', 'feel', 'feels', 'felt',
                 'act', 'acts', 'acted', 'acting',
                 'be', 'is', 'are', 'was', 'were', 'am', 'been'}


def _like_preposition(words):
    """Is the line-final "like" the preposition, not the verb?"""
    before = [w.lower().replace('\u2019', "'") for w in words[-3:-1]]
    while before and before[-1] in LIKE_VERB_ADVERBS:
        before.pop()
    if not before or before[-1][-1:] in ',;:.!?…':
        return False
    prev = before[-1]
    return not (prev in VERB_CUES or prev in LINKING_VERBS
                or prev.endswith(("'d", "n't", "'s", "'re", "'m")))


# What a line that ends on a verb that must take an object pays, when its
# object opens the next line ("we have to bring / the stone back"): half a
# rhythm point, ever so slightly - the verb and its object are one clause.
TRANSITIVE_END = 0.5
# Words in front that make an ambiguous noun/verb a verb ("I blame", "to
# bring", "would want").
VERB_CUES = SUBJECTS | {'you', 'it', 'to', 'will', 'would', 'can', 'could',
                        'should', 'must', 'might', 'may', 'shall', 'do',
                        'does', 'did', "don't", "doesn't", "didn't", "can't",
                        "won't", "wouldn't", "couldn't", "shouldn't", "i'll",
                        "you'll", "we'll", "they'll", "let's"}


@edition_cache(1 << 16)   # pure in the two texts; the layout asks per candidate line
def ends_on_transitive(text, nxt):
    """Does the line end on a verb that only ever takes an object, with the
    object opening the next line? A word that is a noun too counts as a verb
    only behind a subject, "to" or an auxiliary."""
    words = _plain(text).split()
    if not words:
        return False
    w = words[-1].lower()
    tags = lexicon().get(w, ())
    if 'vt' not in tags or 'vi' in tags:
        return False
    if ('noun' in tags or 'adj' in tags) and (
            len(words) < 2 or words[-2].lower() not in VERB_CUES):
        return False
    return _opens_noun_phrase('', nxt)


# AUXILIARIES carry the verb after them: a line ending on one cuts the verb
# phrase ("Only those who have been / called", "you will / witness"). One
# rhythm point - the weakest unit viewers keep whole (61-69%), but kept.
MODALS = {'will', 'would', 'can', 'could', 'shall', 'should', 'may', 'might',
          'must', 'do', 'does', 'did'}
AUX_BE_HAVE = {'is', 'are', 'was', 'were', 'am', 'be', 'been', 'being', 'have',
               'has', 'had'}
AUX_BE = {'is', 'are', 'was', 'were', 'am', 'be', 'been'}   # the copula: "The smiles you wear / are no longer false masks"
AUX_END = 1


@edition_cache(1 << 16)   # pure in the two texts; the layout asks per candidate line
def ends_on_auxiliary(text, nxt):
    """Does the line end on an auxiliary whose verb opens the next line?
    After a modal the next word is its verb, after a form of be its
    predicate ("The smiles you wear are / no longer..."); after have only a
    participle is ("have been / called"; never "I have / books")."""
    words = _plain(text).split()
    if not words:
        return False
    aux = words[-1].lower()
    head = _core_word(nxt).split(' ', 1)[0].rstrip('.,;:!?…"”’)').lower()
    if aux in MODALS:
        return bool(head) and head not in ('not', 'you', 'i', 'we', 'they', 'he', 'she', 'it')
    if aux in AUX_BE:
        return bool(head)       # a copula carries its predicate, whatever it is
    if aux in AUX_BE_HAVE:
        tags = lexicon().get(head, ())
        return (head in AUX_BE_HAVE
                or ('verb' in tags and re.search(r'(?:ed|en|ing)$', head) is not None))
    return False


# What a line pays for ending on an adverb between an auxiliary and its
# verb ("For some reason, The Snow Queen is usually / performed"): one
# rhythm point, as a connector pays.
ADVERB_END = 1


def ends_on_verb_adverb(text, nxt):
    """Does the line end on an adverb that sits inside a verb phrase - an
    auxiliary or modal before it, its verb opening the next line ("is
    usually / performed", "can always / tell", "have never / seen")?"""
    words = _plain(text).split()
    if len(words) < 2 or re.search(r'[,;:.!?…"”’)]$', words[-1]):
        return False
    adv, aux = words[-1].lower(), words[-2].lower()
    if aux not in MODALS | AUX_BE_HAVE or lexicon().get(adv) != frozenset({'adv'}):
        return False
    head = _core_word(nxt).split(' ', 1)[0].rstrip('.,;:!?…"”’)').lower()
    return 'verb' in lexicon().get(head, ())


@edition_cache(1 << 16)   # pure in the two texts; the layout asks per candidate line
def subject_before_auxiliary(text, nxt):
    """Does the line end on "you" or "it" with an auxiliary opening the next
    line? Then it is the subject, whatever it is elsewhere ("The time is soon
    when you / will need this power")."""
    words = _plain(text).split()
    head = _core_word(nxt).split(' ', 1)[0].lower()
    return (bool(words) and words[-1].lower() in ('you', 'it')
            and head in MODALS | AUX_BE_HAVE)


@edition_cache(1 << 16)   # pure in its two texts; the layout asks per candidate line
def subject_before_verb(text, nxt):
    """Does the line end on "you" or "it" with a word that is only ever a
    verb opening the next line (lexicon `verb`, no noun/adjective/adverb
    sense)? Then it is that verb's subject ("say that you / intend to"),
    never an object ("I want you / to keep", "make you / feel")."""
    words = _plain(text).split()
    head = _core_word(nxt).split(' ', 1)[0].rstrip('.,;:!?…"”’)').lower()
    tags = lexicon().get(head, frozenset())
    return (bool(words) and words[-1].lower() in ('you', 'it')
            and head not in MODALS | AUX_BE_HAVE      # (subject_before_auxiliary)
            and 'verb' in tags and not tags & {'noun', 'adj', 'adv', 'prep'})


def _opens_noun_phrase(con, word):
    """Does word open the phrase of the particle-capable connector con: an
    article/possessive, a pronoun, a name or number, a question word or
    quantifier, an adjective or noun ("in | black"), or a gerund after a
    preposition ("no point | in trying")? A gerund after on/off is the verb's
    particle ("go on calling")."""
    core = _core_word(word)
    head = core.split(' ', 1)[0].rstrip('.,;:!?…"”’)').lower()
    head = re.sub(r"in['\u2019]$", 'ing', head)   # the dropped g: "somethin'" is "something"
    tags = lexicon().get(head, frozenset())
    if ((head in CONNECTORS or 'prep' in tags)
            and not tags & {'pron', 'det', 'noun', 'adj'}):
        return False        # a preposition opens a phrase of its own ("freakin' out / over", "stop by / after")
    if head.endswith('ing') and len(head) > 4:
        return con not in ('on', 'off')
    return (head in ARTICLES or head in OBJECTS or head in ('you', 'it')
            or head in PHRASE_OPENERS or core[:1].isupper()
            or core[:1].isdigit()
            or bool(lexicon().get(head, frozenset()) & {'adj', 'noun', 'det', 'pron'}))


LEXICON_PATH = os.path.join(ROOT, 'src', 'porting', 'lexicon', 'en_pos.tsv')


@functools.lru_cache(maxsize=1)
def lexicon():
    """{word: {part of speech}} (adj, adv, conj, det, noun, prep, pron,
    verb), cut from a Wiktionary extract by tools/make_lexicon.py. A word
    not in it has no part of speech the flow knows."""
    try:
        with open(LEXICON_PATH, encoding='utf-8') as f:
            next(f)
            return {w: frozenset(p.split(',')) for w, p in
                    (line.rstrip('\n').split('\t') for line in f if line.strip())}
    except OSError:
        return {}


def _determiner(word):
    """An article, possessive or other determiner ("some", "no", "which"),
    or a possessive noun ("people's souls", "Kandori's ambitions")."""
    w = word.lower()
    return (w in ARTICLES or 'det' in lexicon().get(w, ())
            or (VERB_UNITS and _possessive_noun(w)))


def _possessive_noun(w):
    """A noun's possessive ("people's", "mankind's") - not a contraction
    ("let's", "who's", "something's" are a pronoun and its verb). Subtitle
    mode only: in a textbox "Maki's / mom" is a split the user keeps."""
    w = w.replace('\u2019', "'")
    if not re.search(r"\w(?:'s|s')$", w):
        return False
    stem = w[:-2] if w.endswith("'s") else w[:-1]
    tags = lexicon().get(stem, ())
    return 'noun' in tags and 'pron' not in tags and 'det' not in tags and stem != 'let'



def _modifier(word):
    """A word that qualifies the noun after it: an adjective, a determiner
    or possessive ("your car" is built like "red car"), or a SINGULAR noun -
    a noun in front of a noun works as an adjective ("the memory | stick").
    Not a plural: "the demons | attack" is a subject and its verb."""
    w = word.lower()
    tags = lexicon().get(w, ())
    return (_determiner(w) or 'adj' in tags
            or ('noun' in tags and not _plural(w)))


def _plural(word):
    """A plural noun form: the word minus -s/-es is a noun too."""
    lex = lexicon()
    return any(word.endswith(end) and 'noun' in lex.get(word[:-len(end)], ())
               for end in ('s', 'es') if len(word) > len(end) + 1)


def _listed_adjective(word):
    """A word a listing comma can follow inside a noun phrase: an adjective
    or a participle, or a hyphenated compound with one ("the suntanned,
    bleach-blonde"). Not a noun: "your journey, / young ones" ends its
    phrase at the comma."""
    w = word.lower().strip('"“”‘’\'')
    tags = lexicon().get(w, ())
    if 'adj' in tags:
        return True
    if re.search(r'(?:ed|en|ing)$', w) and 'verb' in tags:
        return True
    return '-' in w and any('adj' in lexicon().get(p, ()) for p in w.split('-') if p)


def _phrase_modifier(word):
    """A word that can stand among a noun's modifiers: _modifier's, a
    participle ("suntanned", "smiling"), or a hyphenated compound with one
    such part ("bleach-blonde")."""
    w = word.lower().strip('"“”‘’\'')
    if not w:
        return False
    if _modifier(w):
        return True
    if re.search(r'(?:ed|en|ing)$', w) and 'verb' in lexicon().get(w, ()):
        return True
    return '-' in w and any(p and _modifier(p) for p in w.split('-'))


@edition_cache(1 << 16)   # pure in the two texts; the layout asks per candidate line
def comma_inside_phrase(text, nxt):
    """Does the line end on a comma between two modifiers of one noun - a
    determiner, modifiers up to the comma, and another modifier opening the
    next line ("the suntanned, / bleach-blonde "kogal" set")? A comma there
    lists adjectives; the phrase has not reached its noun. The determiner
    is what makes it a phrase: "she's tall, / dark..." is a predicate."""
    words = _plain(text).split()
    if not words or not words[-1].endswith(',') or len(words) < 2:
        return False
    head = _core_word(nxt).split(' ', 1)[0].rstrip('.,;:!?…"”’)')
    # the flow hands a hyphenated word over in pieces ("bleach-"): a piece
    # that opens a compound is a modifier there
    # the next word is another adjective of the list ("bleach-blonde";
    # never "call", "even" - an adverb's line), and the chain before the
    # comma opens on an article or a possessive ("so", "little" are no
    # phrase's start)
    if (not head[:1].islower() or head.lower() in ARTICLES
            or head.lower() in CONNECTORS
            or not (head.endswith('-') or _listed_adjective(head))
            or 'adv' in lexicon().get(head.lower(), ())):
        return False
    if not _listed_adjective(_core_word(words[-1][:-1])):
        return False
    chain = [words[-1][:-1]] + words[-2::-1]
    for k, w in enumerate(chain):
        w = _core_word(w)
        if k and w.lower() in ARTICLES:
            return True
        if not w or w[-1:] in ',;:.!?' and k or not _phrase_modifier(w):
            return False
    return False


def _splits_noun_phrase(items, k):
    """Would a break before items[k] split a noun from the modifiers in
    front of it - a determiner or possessive, and the adjectives or nouns
    after it ("the easiest | way", "our whole | world", "in your | class",
    "the memory | stick")? The determiner is what makes the chain a phrase:
    "you look happy | today" is a predicate, not a phrase."""
    nxt = _core_word(items[k][1])
    if not nxt[:1].islower():
        return False
    noun = nxt.split(' ', 1)[0].rstrip('.,;:!?…"”’)')
    lex = lexicon()
    if 'noun' not in lex.get(noun.lower(), ()) or noun.lower() in CONNECTORS:
        return False
    # the words before the break, newest first, across the glued units
    before = []
    for it in items[k - 1::-1]:
        if it[0] != 'w':
            break
        before.extend(_plain(it[1]).split()[::-1])
        if len(before) > 4:
            break
    if not before or before[0][-1:] in _PROCL_END + ',;:"”’)':
        return False
    for k, w in enumerate(before):
        w = _core_word(w).lower()
        # a comma inside the chain lists its modifiers ("the suntanned,
        # bleach-blonde | "kogal" set"); the word right before the break
        # was tested above
        if k and w.endswith(','):
            w = w[:-1]
            if not _listed_adjective(w):
                return False
            continue
        if _determiner(w):
            return True
        if not _modifier(w):
            return False
    return False


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
        if (kind == 'w' and nxt[0] == 'w' and len(nxt) == 2
                and (_core_word(word).lower(), _first(nxt[1])) in SUB_PAIRS):
            out[i + 1] = ('w', nxt[1], -1)
        elif (kind == 'w' and nxt[0] == 'w' and _binds_forward(out, i)
                and test[-1:] not in _PROCL_END + ',;:'
                and not re.match(CLOSERS_RE, nxt[1])):
            if SOFT_POSS and test.lower() in POSS and len(nxt) == 2:
                out[i + 1] = ('w', nxt[1], -3)
            else:
                out[i:i + 2] = [('w', word + ' ' + nxt[1])]
        i -= 1
    # 2. verb particles: a particle-capable connector that opens no phrase
    # is its verb's ("might as well / go on calling it"): glued back onto the
    # verb. Every other connector stays free; a line that ends on one pays
    # (flow_layout, CONNECTOR_END).
    i = len(out) - 2
    while i > 0:
        kind, word = out[i][0], out[i][1]
        nxt = out[i + 1]
        con = _core_word(word).lower()
        if (kind == 'w' and nxt[0] == 'w' and con in PARTICLES
                and len(out[i]) == 2 and out[i - 1][0] == 'w'
                and not re.match(CLOSERS_RE, nxt[1])
                and not _opens_noun_phrase(con, nxt[1])
                and not sent_end(out[i - 1][1])
                and _plain(out[i - 1][1]).rstrip()[-1:] not in ',;:'):
            out[i - 1:i + 1] = [(out[i - 1][0], out[i - 1][1] + ' ' + word)
                                + tuple(out[i - 1][2:])]
        i -= 1
    # 2b. "not" binds back onto its auxiliary ("should not / get involved",
    # never "should / not get"): the negated auxiliary is one unit.
    i = len(out) - 1
    while i > 0:
        word, prev = out[i][1], out[i - 1]
        if (out[i][0] == 'w' and prev[0] == 'w' and len(out[i]) == 2
                and _core_word(word).lower().rstrip('.,;:!?…"”’)') == 'not'
                and _core_word(word)[:1] == 'n'
                and _plain(prev[1]).split()
                and _plain(prev[1]).split()[-1].lower() in MODALS | AUX_BE_HAVE):
            out[i - 1:i + 1] = [(prev[0], prev[1] + ' ' + word) + tuple(prev[2:])]
        i -= 1
    # 3. an adjective and its noun: soft, like a possessive and its noun
    for k in range(1, len(out)):
        if (out[k][0] == 'w' and len(out[k]) == 2 and out[k - 1][0] == 'w'
                and _splits_noun_phrase(out, k)):
            out[k] = ('w', out[k][1], -3)
    # 4. proper names: NOT glued - a line MAY break inside one, it just pays
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
        # A glued atom may hold several words ("the Peace", "Diner on").
        # The name test must use the words that actually touch the break,
        # not the atom's first letter: "the Peace | Diner on" splits
        # "Peace Diner" even though "the Peace" begins lowercase.
        prev_word = prev.rsplit(' ', 1)[-1] if prev is not None else ''
        first_word = w.split(' ', 1)[0]
        # Two all-caps words are shouting ("YOU GIVE"), not a name: a name
        # pair has a lowercase letter on one side ("SEBEC Hospital").
        lower = any(c.islower() for c in prev_word + first_word)
        # A comma ends a name AFTER its word: "Mikage Hospital," is still
        # the name, only the run stops there (prev_word keeps the test).
        if prev is not None and run < 9 and _caps_word(prev_word) \
                and _caps_word(first_word.rstrip(',;:')) \
                and not sent_end(prev_word) and lower:
            run += 1
            out.append((it[0], it[1], run))
        else:
            run = 0
            out.append(it)
        prev = w
    _mark_phrases(out)
    # Double-quoted phrases that fit a line are reading units too ("Truth is
    # stranger than fiction"). This is a soft break cost, never an extra
    # line/scroll, and derives solely from source quotes.
    start = None
    for i, it in enumerate(out):
        if it[0] != 'w':
            start = None
            continue
        for ch in _plain(it[1]):
            if ch in '"“' and start is None:
                start = i
            elif ch in '"”' and start is not None:
                phrase = ' '.join(v[1] for v in out[start:i + 1])
                if text_width(phrase) <= BOX_WIDTH:
                    for j in range(start + 1, i + 1):
                        out[j] = (out[j][0], out[j][1], 1)
                start = None
    return out


PHRASES_PATH = os.path.join(toolpath.TRANSLATION, 'phrases.tsv')
_PHRASE_STRIP = '.,;:!?…"“”‘’\'()[]'


def _phrase_word(w):
    """A word as phrases.tsv spells it: no codes, no punctuation around it,
    lowercase."""
    return _plain(w).strip(_PHRASE_STRIP).lower()


def phrases_stamp():
    """phrases.tsv's mtime (0 without one): a cache of layouts keys on it."""
    try:
        return os.stat(PHRASES_PATH).st_mtime_ns
    except OSError:
        return 0


def phrases():
    """The word sequences translation/phrases.tsv lists - several words read
    as one thing ("all-you-can-eat dinner"), longest first. Re-read when the
    file changes (textvis adds to it while it runs)."""
    return _phrases(PHRASES_PATH, phrases_stamp())


@functools.lru_cache(maxsize=4)
def _phrases(path, _stamp):
    try:
        rows = strlib.tsv_rows(path, required=('phrase',))
    except OSError:
        return ()
    seqs = {tuple(_phrase_word(w) for w in r['phrase'].split()) for r in rows}
    return tuple(sorted((q for q in seqs if len(q) > 1), key=len, reverse=True))


@functools.lru_cache(maxsize=4)
def _phrase_index(path, _stamp):
    """{first word: [phrase words, ...]} - the same list as phrases(), keyed
    so a text with no matching first word costs one lookup, not the whole
    list. phrases.tsv is the user's and grows, so the scan must not be
    linear in it for every box."""
    index = {}
    for seq in _phrases(path, _stamp):
        index.setdefault(seq[0], []).append(seq)
    return index


def _mark_phrases(items):
    """Mark, like a proper name, each break that would fall inside a phrase
    phrases.tsv lists: allowed, but ranked below everything else (rule 3).
    The words are matched across glued atoms ("the all-you-can-eat",
    "dinner at"); in place."""
    words = []                    # (item index, word, starts its item)
    for i, it in enumerate(items):
        if it[0] != 'w':
            words.append((i, None, True))       # a code or break ends a phrase
            continue
        for k, w in enumerate(it[1].split(' ')):
            words.append((i, _phrase_word(w), k == 0))
            if sent_end(w):
                words.append((i, None, True))   # a sentence end ends a phrase
    index = _phrase_index(PHRASES_PATH, phrases_stamp())
    for a in range(len(words)):
        seqs = index.get(words[a][1])
        if not seqs:
            continue
        for seq in seqs:
            n = len(seq)
            if a + n > len(words):
                continue
            if tuple(w for _i, w, _s in words[a:a + n]) != seq:
                continue
            for i, _w, starts in words[a + 1:a + n]:
                if starts:
                    items[i] = (items[i][0], items[i][1], 1)


class Atom:
    """One unbreakable piece of line text plus how it joins its neighbours.
    join: what stands between it and the previous atom mid-line (dropped at a
    line start); brk: a line break is allowed before it; pen: what using that
    break costs (0 = an ordinary word gap, >0 = an internal split); word: it
    is real text (the pen-240 rule only counts words); last: the final piece
    of its item."""
    __slots__ = ('text', 'join', 'brk', 'pen', 'word', 'last', 'fin', 'nbrk',
                 'lead', 'orig')

    def __init__(self, text, join, brk, pen, word, last):
        self.text, self.join, self.brk, self.pen = text, join, brk, pen
        self.word, self.last, self.fin = word, last, False
        # a line break here would split a PROPER NAME ("Ms. | Saeko"):
        # allowed, but ranked below everything else (see flow_layout)
        self.nbrk = False
        # a line may START here, but at a price: the noun after its
        # possessive or adjective ("where my | mouth", "the easiest | way")
        self.lead = False
        # the ORIGINAL breaks its line after this piece ('h' item): a line
        # ending here is the original's own line and costs no extra line
        self.orig = False


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
        piece = w[prev:c]
        # A closer never starts a line, not even a piece split off a code
        # run ("<FF07><00>?" must keep its "?"). Multi-dot ellipses are the
        # one exception ("..." is a fine dramatic pause).
        inner = prev > 0 and not (re.match(CLOSERS_RE, piece)
                                  and not piece.startswith('..'))
        out.append((piece, inner, 1))
        prev = c
    return out or [(w, False, 1)]


def _is_article(w):
    """The article test the glue pass uses, for a word that stands alone
    (its follower was a code, not a word): such a word still may not leave
    the line it is on."""
    test = _core_word(w)
    return (test.lower() in ARTICLES
            and not (SOFT_POSS and test.lower() in POSS)
            and test[-1:] not in _PROCL_END)


def flow_model(items, word_gaps=False):
    """items -> the flat flow stream: ('a', Atom) text pieces, ('b', code)
    deliberate breaks, ('v', code) voice codes. Deliberate breaks are region
    walls: the flow never merges, moves, or balances across them."""
    seq = []
    prev = None
    hold = False          # a lone proclitic: the next piece may not leave it
    pause_gap = False     # source gap after a timed pause
    bare = False          # the gap before a pause was just printed
    for it in items:
        kind = it[0]
        gap_here = bare
        if kind != 'h':          # an original line end is not a piece
            bare = False
        if kind == 'b':
            seq.append(('b', it[1]))
            prev, hold = None, False
            pause_gap = False
            continue
        if kind == 'G':
            seq.append(('v', it[1]))
            continue
        if kind == 'h':
            # the original's line ends after the piece before (ORIG_BREAK)
            if seq and seq[-1][0] == 'a':
                seq[-1][1].orig = 1 if it[1] == 'weak' else 2
            continue
        if kind == 'g' or (kind == 'w' and it[1] in VOICE_CODES):
            timed = bool(PAUSE_CODE.fullmatch(str(it[1])) or it[1] == '<FFFC>')
            # THE SOURCE OWNS WHICH SIDE OF A PAUSE ITS GAP SITS ON: 'a'
            # word gap is one gap, and a zero-width pause does not need two.
            # '<FF05> Silence!' carries it after; 'SHUT UP! <FF05>' before
            # (port_story's 'A' / 'B' flags). A gap before joins the pause
            # to the word it follows and the next piece starts bare, so the
            # produced text is the source's own shape.
            gap_after = timed and bool(len(it) > 2 and it[2])
            gap_before = timed and bool(len(it) > 3 and it[3])
            if gap_before:
                gap_after = False
            seq.append(('a', Atom(it[1], ' ' if gap_before else '',
                                  False, 0, False, True)))
            hold = False
            # A voice code or a timed pause opening a line prints nothing:
            # the words after it start the line bare, never behind a gap
            # ("<FFEB> Alright!", "<FF05><58><00> Wait a sec").
            prev = None if (prev is None and (it[1] in VOICE_CODES or timed)) \
                else seq[-1][1]
            pause_gap = gap_after
            # ...and the word after a pause carries its own gap only when
            # the source put one there: '...<FF05>Hmph' is the PSP's own
            # spelling, not a place to insert a blank.
            bare = timed and not gap_after
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
        if (closer and prev.text.endswith((':', '：'))
                and not re.search(r'\w', w)):
            # A speaker's label is followed by its speech, even when that
            # speech is punctuation alone. Keep the authored word gap and
            # keep the punctuation on the same line as the label. Speech
            # that opens on a beat ("...And that's") may start the next line.
            join, brk = ' ', False
        elif w.startswith(SPEECH_HEART) and prev is not None:
            # the speech heart keeps its gap and rides with the word before
            join, brk = ' ', False
        elif closer:
            # A closer word never starts a line: a stranded "?" or "," moves
            # down with the tail it closes. Multi-dot ellipses may start one
            # ("..." is a fine dramatic pause), so their attach point stays a
            # break. A spaced-off ellipsis is a pause and keeps the source's
            # gap ("whack! ...", "I ..."); a lone mark attaches ("Wait !" ->
            # "Wait!"). After an inline code the porter split it off
            # ('<FF08>...' trails the name): bare, and no pause opening a line.
            after_code = prev.text.endswith('>')
            # After a timed pause the source decides: '...<pause> ...' keeps
            # its gap, '...<pause>...' has none.
            separate = not after_code or pause_gap
            join = (' ' if w.startswith(('..', '…')) and separate
                    else '')
            brk = w.startswith(('..', '…')) and separate
        else:
            join = '' if gap_here else (' ' if prev is not None else '')
            brk = True
        if not word_gaps and hold and not (_first(w) in SUBORDINATORS
                         and prev is not None and prev.text.rsplit(' ', 1)[-1]
                         .lower() not in PURE_ARTICLES):  # 'her | while'
            brk = False
        pieces = [(w, False, 0)] if word_gaps else word_pieces(w)
        pause_gap = False
        hold = _is_article(w)
        marked = it[2] if len(it) > 2 else 0
        for k, (text, inner, pen) in enumerate(pieces):
            a = Atom(text, join if k == 0 else '',
                     brk if k == 0 else inner, pen if k else 0,
                     True, k == len(pieces) - 1)
            if k == 0 and marked == -3:
                a.lead = 3
            elif k == 0 and marked == -1:
                a.lead = 1
            elif k == 0 and marked:
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


@edition_cache(1 << 16)   # pure in the line text; the layout asks per suffix
def stop_cost(text):
    """How badly a line ends (spec 2.4).

    0 = a full stop (the line closes a sentence), 1 = a trailing ellipsis
    (the speech trails off but goes on), 2 = a comma/semicolon/colon (the
    sentence breathes there), 4 = anywhere else. It is an element of the
    cost tuple BEFORE the look terms, so a layout that ends its lines where
    the sentence breathes wins over one that merely fills the box harder.
    """
    t = _plain(text).rstrip()
    if not t:
        # A line of codes alone ("<FFF3>" - the demon's name) ends nowhere
        # in the sentence; an empty line ends nothing.
        return 4 if text.strip() else 0
    last = t.split(' ')[-1]
    # A SHORT ELLIPSIS BEAT LEANS FORWARD. One or two words trailing off
    # after a sentence that ended on the same line ("It's not good. But...",
    # "Yamaoka! You bastards...") open what follows, so ending the line on
    # them is weaker than a full stop (yet stronger than a comma). An
    # ellipsis that closes its own clause ("short, ho...") is a sentence end.
    if re.search(r'(?:\.\.|…)["\'”)\]]?$', last):
        words = t.split(' ')
        # a speaker's label opens the speech the way a stop does: a beat
        # right after it leans into what follows ("Brown: So, uh... / he
        # said there's...")
        ends = [k for k in range(len(words) - 1)
                if sent_end(words[k]) or words[k].endswith(':')]
        beat = words[ends[-1] + 1:] if ends else []
        # Only after a PLAIN stop: in a chain of trailing ellipses
        # ("Hmmm... Hmmmmmm...", "G-I-V-E... M-E...") no beat leans more
        # than another.
        plain = bool(ends) and not re.search(r'\.\.|…', words[ends[-1]])
        if (plain and 1 <= len(beat) <= 2
                and any(c.isalpha() for c in ''.join(beat))):
            return 1
        return 0
    if sent_end(last):
        return 0
    if t[-1:] in ',;:':
        return 2
    return 4


@edition_cache(1 << 16)   # pure in the line text; the layout asks per suffix
def full_stop(text):
    """Does the line end a sentence with . ! or ? - not a trailing ellipsis,
    which goes on?"""
    t = _plain(text).rstrip()
    return stop_cost(text) == 0 and not re.search(r'(?:\.\.|…)["\'”)\]]?$', t)


@edition_cache(1 << 16)   # pure in the line text; the layout asks per suffix
def opening_beat(text):
    """Is the line one word trailing off ("Unfortunately...", "Hmm...")? As
    the block's first line it is a beat of its own, like an opening
    sentence."""
    words = _plain(text).split()
    return ('<' not in text and len(words) == 1 and any(c.isalpha() for c in words[0])
            and re.search(r'(?:\.\.|…)["\'”)\]]?$', words[0]) is not None)


HOLLOW = 2   # rhythm points for a middle line under half its neighbours
# A step between two adjacent lines is worth more than the same pixels of
# width: a block whose lines jump 20, 40, 60 px reads as ragged however
# balanced its total is. Weighting the step makes the descent a smooth one
# (spec 2.6), not one big drop at the tail, without rewarding a wide line
# for being wide.
STEP_COST = 4
# Which way a block may lean. A textbox reads top-heavy: a growing step costs
# double, and a line far wider than the one before it pays (spec 2.6). A
# subtitle over a picture is the reverse - its upper line the shorter, so the
# text covers as little of the image as it can (the subtitling guidelines'
# pyramid): tools/fmv_retime.py sets this False for the movie subtitles.
TOP_HEAVY = True
# The verb-phrase units (an auxiliary and its verb, a copula and its
# predicate, "you"/"it" before an auxiliary) and a noun's possessive with its
# noun ("people's / souls"): a SUBTITLE keeps them whole - the subtitling
# standard, and what the movie subtitles read best with - but a textbox does
# not ("The library at home is / much better stocked.", "leave Maki's / mom"
# are the user's call). tools/fmv_retime.py sets this True for the movie
# subtitles.
VERB_UNITS = False
# What one rhythm point (cost[4]) is worth in shape: the root weighs a line
# end and the block's shape on one scale, so a single rhythm point (a short
# closing sentence, a trailing beat) never outweighs a far squarer block
# ("Mark: But that voice... / That's Maki's mom, I'm dead sure... /
# Isn't it?" loses to "Mark: / But that voice... That's Maki's mom, /
# I'm dead sure... Isn't it?").
SHAPE_POINT = 239 * 239 // 2
# What a mid-clause cut beside the speaker's name costs (cost[4]), on the same
# scale as any other line end: the label's line starts the speech, but it does
# not buy an extra line (spec 2.4). A label alone over speech that would fit
# beside it pays 2, so the cut's mid-clause end (4) plus these 2 clearly loses
# at an equal line count, while a block that saves a line still takes the
# speech beside the name.
LABEL_CUT = 2


def fullness(w, remaining=1):
    """Squared width: the classic raggedness term, so a block is as even as
    its words allow. `remaining` is kept for callers that want the old taper
    (the gentle descent now comes from the transition term, which charges a
    rise twice and a fall once) and never rewards making a wide line wider
    merely for its own sake.
    """
    return w * w


@edition_cache(1 << 16)   # pure in the line text; the layout asks per suffix
def stutter(text, nxt):
    """Does the line end on 'word...' that the next line repeats?"""
    words = _plain(text).split()
    following = _plain(nxt).split()
    if not words or not following:
        return False
    m = re.fullmatch(r"([\w'’-]+)(?:\.\.+|…)", words[-1])
    # exact repetition: "I... I am" stutters, "meat... Meat is" starts over;
    # a cut-off start stutters too ("H... How can this be", "Wh... Why")
    nxt0 = following[0].strip(',.!?')
    if bool(m) and (nxt0 == m.group(1) or (
            len(m.group(1)) < len(nxt0)
            and nxt0.lower().startswith(m.group(1).lower())
            and (m.group(1).lower() not in lexicon()      # not a word of its own
                 or (len(m.group(1)) == 1 and m.group(1).lower() not in 'ai')))):
        return True
    # a chain of trailing fragments is one stammer ("And this, uh... /
    # Exp... Expel...?"): no break between two of them
    return bool(m) and bool(re.fullmatch(r"[\w'’-]+(?:\.\.+|…)", following[0]))


@edition_cache(1 << 16)   # pure in the line text; the layout asks per suffix
def head_orphan(text):
    """Does the line end on the lone first word of a new sentence ("Is that
    so...? You're")? That word dangles away from the rest of its sentence:
    worse than an ordinary mid-clause break."""
    words = _plain(text).split()
    # a comma does not rescue it ("STUPID? HMM... WELL, / ME HAVE..."), and
    # one word and its comma alone on a line is the same orphan ("Masao,")
    # Returns how many mid-clause breaks it is worth: 2 for a lone sentence
    # head ("Is that so...? You're") or a line that is one word and its
    # comma ("Hahaha," / "Thus," alone). A comma after the head is a real
    # pause ("Huh? Dude, / that bandwagon...").
    if len(words) < 2:
        return 2 if len(words) == 1 and stop_cost(text) == 2 else 0
    if sent_end(words[-2]) and not sent_end(words[-1]) and stop_cost(text) == 4:
        return 2
    return 0


LABEL_RE = r'[^():!?"“”]+:'


def label_plain(text):
    """The text a label test reads: a name insert IS a name ("<FF08><01>:"
    is a speaker label like "Yukino:"), every other code is nothing."""
    text = NAME_TOKEN_RE.sub('Name', text)
    text = re.sub(r'<FF(?:07|08|0F|10)>(?:<[0-9A-F]{2}>)?', 'Name', text)
    return _plain(text)


def label_end(atoms):
    """The atom that closes a speaker label ('Name:'), or None.

    A label is the opening run of words whose text ends in ONE colon and
    carries no other bracket, colon or quote: a name, never a list. It is
    derived from sentence shape alone (never from a name table) and is the
    same test every reader of the flow uses, so the report and the layout
    can never disagree about what the label is.
    """
    prefix = ''
    for i, a in enumerate(atoms):
        prefix = line_text(prefix, a)
        plain = label_plain(prefix)
        if re.fullmatch(LABEL_RE, plain):
            return i
        if re.search(r'[():!?"“”]', plain):
            return None
    return None


@edition_cache(1 << 16)   # pure in the line text; the layout asks per suffix
def _closes_sentence_in(text):
    """Does the speech on a label's line open with a beat of its own - a
    hesitation that trails off or a one-word sentence ("Yuko: U-Um... I
    think Yukino", "Elly: Good! I was worried you")? A hesitation is a beat of its own,
    so the cut after it is not a clause cut in half."""
    plain = label_plain(text)
    m = re.match(r'\s*' + LABEL_RE + r'\s*(.*)$', plain)
    words = (m.group(1) if m else plain).split()
    # the hesitation OPENS the speech ("U-Um..."); an ellipsis later in the
    # line ("But that voice... That's Maki's") is a clause like any other
    return len(words) > 1 and (bool(re.search(r'(?:\.\.|…)\W*$', words[0]))
                               or sent_end(words[0]))


@edition_cache(1 << 16)   # pure in the line text; the layout asks per suffix
def _whole_tail(text):
    """Does the line finish the clause cut above it, and nothing more - one
    sentence end, at its very end ("would think it was weird!", never
    "there? When did they rebuild it!?")?"""
    words = _plain(text).split()
    return (bool(words) and stop_cost(text) == 0
            and not any(sent_end(w) for w in words[:-1]))


def label_only(text):
    """True when the whole line is a speaker label ('Name:') and nothing
    else - the one line spec 2.4 exempts from the speech block's shape."""
    return bool(re.fullmatch(LABEL_RE, label_plain(text).strip()))


def shape_report(lines, width=BOX_WIDTH):
    """Read one laid-out page back through the flow's own shape rules.

    `lines` are the page's line TEXTS, in order. Returns
    (widths, findings, cost, clauses): the widths that count, the shape
    findings in spec order (2.4, 2.5, 2.7), the block's shape cost and how
    many of its lines stop in the middle of a clause (spec 2.5 - the count a
    shape change trades against). A leading
    label-only line is never counted as the block's first width (spec 2.4:
    a standalone label is not a speech line), but a scrap of speech riding
    the label IS a finding. Every threshold here is the one the flow scores
    with, so a report row names a cost the optimizer actually paid.
    """
    widths = [text_width(line) for line in lines]
    findings = []
    first = 0
    if lines and label_only(lines[0]):
        first = 1
    elif len(lines) >= 2:
        plain = label_plain(lines[0])
        m = re.match(r'\s*(' + LABEL_RE + r')\s*(.*)$', plain)
        if m:
            label = text_width(m.group(1))
            rest = m.group(2).strip()
            speech = ' '.join([rest] + [_plain(x)
                                        for x in lines[1:]])
            rectangle = (abs(widths[0] - widths[1]) <= width // 10
                         and stop_cost(lines[0]) < 4)
            body_fits = text_width(speech) <= width
            # The flow's own two ways a label line clips the speech: the
            # whole speech would have fit under the name, or what rides the
            # name is a scrap - and a scrap is only a scrap when it does not
            # close its sentence (spec 2.4).
            beat_over_sentences = (len(lines) == 3 and not body_fits
                                   and bool(re.search(r'(?:\.\.|…)\W*$', lines[0]))
                                   and abs(widths[1] - widths[2]) <= width // 5
                                   and _whole_tail(lines[1]) and _whole_tail(lines[2]))
            if not rectangle and not beat_over_sentences and (
                    body_fits
                    or (widths[0] - label <= width // 5
                        and (stop_cost(lines[0]) != 0
                             or (bool(re.search(r'(?:\.\.|…)\W*$', lines[0]))
                                 and not re.search(r'\s', rest))))):
                findings.append('label-fragment')
    w = widths[first:]
    for i in range(len(w) - 1):
        last = i + 1 == len(w) - 1
        if last and w[i + 1] * 2 < w[i]:
            findings.append('tiny-tail')
        elif not last and w[i + 1] * 10 > w[i] * 14:
            findings.append('rise')
    for i in range(1, len(w) - 1):
        if w[i] * 2 < min(w[i - 1], w[i + 1]):
            findings.append('hollow')
    clauses = sum(1 for line in lines[first:-1]
                  if stop_cost(line) == 4 and not label_only(line))
    cost = sum(fullness(x, len(w) - i) for i, x in enumerate(w))
    for i in range(len(w) - 1):
        step = w[i + 1] - w[i]
        cost += STEP_COST * step * step * (2 if step > 0 else 1)
    if len(w) > 1:
        if w[-1] * 2 < w[-2]:
            cost += (w[-2] - 2 * w[-1]) ** 2
        elif w[-1] * 10 > w[-2] * 14:
            cost += (w[-1] - w[-2]) ** 2
    return w, findings, cost, clauses


# a line that trails off ("..." or "…" at its end)
TRAILS_RE = re.compile(r'(?:\.\.|…)\W*$')


def _rank(cost):
    """Rank a suffix on the same reading/shape scale as the root."""
    return cost[:3] + (cost[8],
                       2 * cost[7] + cost[4] + cost[5] / SHAPE_POINT,
                       cost[9])


def flow_layout(atoms, width, measure, tail=1, want=None, box=BOX_LINES,
                trace=None):
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
    Returns [(first_atom, last_atom)] spans. A `trace` list receives every
    layout the root weighed, as (rank key, spans), for the viewer's close
    calls."""
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
    label_end_i = label_end(atoms)
    label_width = None
    label_insert = False
    body_fits = False
    if label_end_i is not None:
        label = body = ''
        for a in atoms[:label_end_i + 1]:
            label = line_text(label, a)
        for a in atoms[label_end_i + 1:]:
            body = line_text(body, a)
        label_width = measure(label)
        # a label with a name insert in it has no width the reader sees: the
        # flow reserves the widest name, so any balance against it is only
        # the reservation's
        label_insert = bool(NAME_TOKEN_RE.search(label))
        body_fits = bool(body) and measure(body) <= width + tail
    # the same spans are asked for once per suffix: built once
    @functools.lru_cache(maxsize=None)
    def atoms_text(a, b):
        text = ''
        for atom in atoms[a:b + 1]:
            text = line_text(text, atom)
        return text

    # where the sentence an atom belongs to ends (its last atom), for the
    # comma strand below: a scrap stays a scrap over however many lines
    sentence_stop = [n - 1] * n
    for m in range(n - 1, -1, -1):
        sentence_stop[m] = (m if m == n - 1 or sent_end(atoms[m].text)
                            else sentence_stop[m + 1])

    # The preceding line's transition cost depends on the FIRST width of its
    # suffix. Keep one optimum per (line count, first width), not just per line
    # count: discarding the other widths makes a locally square suffix create
    # a globally hollow / narrow-middle block.
    # cost[7]: lines ending mid-clause (an extra line inside the box is
    # cheaper than one of these; past the box the line count comes first)
    # cost[10]: lines that end where the original ends its own (ORIG_BREAK):
    # those lines are the original's, not extra ones
    best = [{} for _ in range(n)] + [{(0, -1): ((0, 0, 0, 0, 0, 0, -1, 0, 0, 0, 0), -1, None)}]
    ranked = [{} for _ in range(n + 1)]   # best[i]'s ranks, kept beside it
    for i in range(n - 1, -1, -1):
        text = atoms[i].text
        w = measure(text)
        j = i
        while True:
            lim = width + tail if atoms[j].fin else width
            over = w - lim
            if j + 1 == n or atoms[j + 1].brk:
                base = max(over, 0)
                # a speech heart closing the line hangs off it: it must fit,
                # but the block's shape is the words' ("give me a smile,
                # okay Chi-Chi? ❤" is as long as its words)
                if SPEECH_HEART in text:
                    w -= hanging_heart(text, measure)
                # what this line alone decides, whatever follows it: worked
                # out once here, not once per remembered suffix below
                last = j + 1 == n
                nxt = None if last else atoms[j + 1]
                label_only = i == 0 and j == label_end_i
                sc = stop_cost(text)
                # a comma between two modifiers of one noun is no breath:
                # the line ends inside the phrase ("the suntanned, /
                # bleach-blonde "kogal" set")
                inside = (sc == 2 and not last
                          and comma_inside_phrase(text, nxt.text))
                if inside:
                    sc = 4
                trails = bool(TRAILS_RE.search(text))
                # (a standalone label ends on its colon, which says
                # nothing about where the speech breathes - but a label
                # alone over speech that would have fit beside it is a
                # wasted line, and pays the colon's rhythm point)
                end0 = (0 if last
                        else int(body_fits) * 2 if label_only
                        else sc)
                # A subordinator opens the clause after it: ending a
                # line on one is worse than another mid-clause end
                # ("visit her while / you're there").
                if end0 == 4 and (ends_on_subordinator(text)
                                  or ends_on_subject(text)
                                  or subject_before_verb(text, nxt.text)
                                  or (VERB_UNITS and
                                      subject_before_auxiliary(text, nxt.text))):
                    end0 += 2 + SUBORDINATE_SUBJECT_END * ends_on_subordinate_subject(text)
                # An object pronoun opening the next line is cut from
                # its verb ("Don't blame / me when..."): one rhythm
                # point, so a near-square block still keeps it ("what's
                # got / me so pissed off?").
                elif end0 == 4 and opens_on_object(text, nxt.text):
                    end0 += 1
                # A new sentence started at the end of the line and cut
                # mid-clause is a scrap: it ranks above the line count
                # inside the box ("Let's go back together! / Yosuke's hurt!
                # / He needs you...", never "together! Yosuke's / hurt!";
                # "The door is locked. / Could that girl...", never
                # "locked. Could that girl / have been...").
                opener = (not last and not label_only and sc == 4
                          and starts_sentence_in(text))
                if (not last and not label_only and sc == 4
                        and splits_partitive(text, nxt.text)):
                    end0 += PARTITIVE_END
                # A connector ends no line for free: it opens the phrase
                # after it ("the tech / to doctor a bit").
                if (not last and sc == 4 and not label_only
                        and ends_on_connector(text, nxt.text)):
                    end0 += (LIKE_END if _last_plain(text) == 'like'
                             else CONNECTOR_END)
                # An auxiliary carries its verb ("have been / called").
                if (VERB_UNITS and not last and sc == 4 and not label_only
                        and ends_on_auxiliary(text, nxt.text)):
                    end0 += AUX_END
                # An adverb inside a verb phrase carries its verb ("is
                # usually / performed"), in every box.
                if (not last and sc == 4 and not label_only
                        and ends_on_verb_adverb(text, nxt.text)):
                    end0 += ADVERB_END
                # A verb that must take an object ends no line for free
                # when the object opens the next one.
                if (not last and sc == 4 and not label_only
                        and ends_on_transitive(text, nxt.text)):
                    end0 += TRANSITIVE_END
                # A noun cut from its possessive or adjective ("where my /
                # mouth", "the easiest / way") is one rhythm point: a clearly
                # better shape still takes it. So is a phrase cut at the
                # comma between its modifiers ("the suntanned, / bleach-blonde
                # "kogal" set").
                if not last and (nxt.lead == 3 or inside):
                    end0 += NOUN_SPLIT
                elif not last and nxt.lead == 1:
                    end0 += SUB_PAIR_SPLIT
                # the next WORD (its pieces), for the comma tic below
                word_end = None
                if end0 == 2 and not last:
                    word_end = j + 1
                    while word_end < n - 1 and not atoms[word_end].last:
                        word_end += 1
                # (the label is not speech: on its line only the
                # speech's own width counts)
                speech_w = (w - label_width if i == 0 and label_width
                            else w)
                stut = not last and stutter(text, nxt.text)
                orphan = (0 if last or label_only
                          else head_orphan(text) or int(sc == 4))
                led = int(not last and bool(nxt.lead))
                pen = atoms[i].pen if i else 0
                nbrk = 1 if atoms[i].nbrk else 0
                first_full = (i == 0 and label_end_i is None and not last
                              and full_stop(text))
                beat_first = (i == 0 and label_end_i is None and not last
                              and opening_beat(text))
                beside = i == 0 and label_end_i is not None and j > label_end_i and not last
                bucket, ranks = best[i], ranked[i]
                for subkey, (sub, _end, after) in best[j + 1].items():
                    # _end: the last atom of the next line
                    k = subkey[0]
                    # A complete opening beat over two balanced, complete
                    # sentences is deliberate rhythm, not a clipped scrap.
                    # The beat may share the label's line or open the speech
                    # under a standalone label ("College student with her
                    # boyfriend: / Hoo boy... / Know where the police station
                    # is? / My boyfriend crashed his motorcycle.").
                    beat_over_sentences = (
                        label_end_i is not None
                        and ((i == 0 and j > label_end_i) or i == label_end_i + 1)
                        and k == 2 and not body_fits
                        and trails
                        and after is not None
                        and abs(sub[6] - after[1]) <= width // 5
                        and _whole_tail(atoms_text(j + 1, _end))
                        and _whole_tail(atoms_text(_end + 1, n - 1)))
                    fragment = (beside
                                and not beat_over_sentences
                                # the original's own beat beside the label
                                # ("Brown: Huh? / O-Ohhh...") is no scrap
                                and not atoms[j].orig
                                # the whole speech fits under the label:
                                # any split of it beside the label is a
                                # scrap the reader skims past with the name
                                # ("Elly: / Mm? Isn't he that transfer
                                # student?") - unless the split makes a
                                # rectangle ("Old man: Look, Akiko, /
                                # Hiroshi came to visit.")
                                and ((body_fits and not (
                                    k == 1 and abs(sub[6] - w) <= width // 10
                                    and sc < 4))
                                     # a complete sentence is no clipped
                                     # fragment ("Ayase: Awww!"); one word
                                     # trailing off is ("Takeda: Tch..."),
                                     # a phrase is not ("F-Fresh meat...")
                                     or (w - label_width <= width // 5
                                         and (sc != 0
                                              or (trails
                                                  and j == label_end_i + 1)))))
                    # Speech that stops mid-clause beside the name is a cut
                    # it pays for like any other mid-clause end ("Female
                    # student: Uh, isn't it / time you gave up on Yosuke?"):
                    # it never buys the extra line a label-only line takes
                    # (spec 2.4).
                    midlabel = (beside
                                 and sc == 4
                                 and not (k >= 2 and abs(sub[6] - w) <= width // 5
                                          and not label_insert)
                                 and not (_closes_sentence_in(text)
                                         and _whole_tail(
                                             atoms_text(j + 1, _end))))
                    step = sub[6] - w
                    # An opening sentence alone on the first line is a line of
                    # its own, not a scrap: the longer line after it is no
                    # rise when that line is a complete sentence too
                    # ("Eeeeeeee! / Areyoupicking a f-f-fight with Q!?"; never
                    # "Hey! / If I put you in a chained up box and / submerged
                    # it"). Not beside a label ("Mark: Idiot! / Even guys
                    # like him..."), and not further down the block ("I see...
                    # / I'm not surprised. / He does..."): there it only
                    # breaks up a rectangle.
                    full = ((first_full
                             and stop_cost(atoms_text(j + 1, _end)) == 0)
                            # the original's own beat ("Eep! ❤", "Ayase:
                            # Heheh!"): no rise after it - the lines under
                            # it are a block of their own
                            or (atoms[j].orig >= ORIG_FREE_RISE and not last))
                    grows = step > 0 if TOP_HEAVY else step < 0
                    trans = (STEP_COST * (step * step
                                          + (step * step if grows else 0))
                             if sub[6] >= 0 and not label_only
                             and not (full and step > 0) else 0)
                    end = end0
                    if midlabel:
                        end += LABEL_CUT
                    # A minor punctuation boundary is not worth stranding a
                    # severely short final fragment. Full sentence boundaries
                    # and standalone speaker labels retain their own rules.
                    # (a comma that strands a tiny last line is an orphan
                    # like a mid-clause cut: it counts in cost[7] too)
                    # (a short rest of the sentence cut across lines strands
                    # just the same: "mischief, / aren't / you!?" - only
                    # when the next line ends inside that sentence; one that
                    # goes on past it is no scrap: "mistake, / Takeda.
                    # Well... leave her be.")
                    strand = (not label_only and end == 2 and k >= 1
                              and (sub[6] * 3 < w if k == 1 else
                                   _end < sentence_stop[j + 1]
                                   and measure(atoms_text(j + 1, sentence_stop[j + 1])) * 3 < w))
                    if strand:
                        end += 4
                    # A comma before the one word that closes the sentence
                    # is no breath: the tail belongs to its sentence ("What
                    # adventures await me, / ho...? I'm excited!", "You're
                    # not being sincere, / hee-ho! If..."). Ending there is
                    # a mid-clause end.
                    tic = (end == 2 and word_end is not None
                           and _end > word_end
                           and sent_end(atoms_text(j + 1, word_end)))
                    if tic:
                        end = 4
                    # A line that ends a sentence (or trails off) and then
                    # strands a short final sentence under half its width
                    # ("Answer me... I'm begging you... / Yamaoka!", "Yes, I
                    # like it! / Keep it up!") orphans that scrap.
                    if (not label_only and k == 1 and sub[6] * 2 < speech_w
                            and sc <= 1):
                        end += 1
                    # A SEVERE RISE strands this line the way a mid-clause
                    # cut does: a line under half the width of the one after
                    # it reads as a scrap hanging off its neighbour
                    # ("Yuko: U-Um... / I think Yukino went inside the
                    # school."). The trailing-off "..." would otherwise buy
                    # the split a clean sentence boundary (stop_cost 0), so
                    # the rise itself is what must pay. It counts in cost[7]
                    # beside a mid-clause end, as spec rule 6 orders it.
                    # An opening beat over a complete sentence, with no
                    # label beside it, is a line of its own (rule 6:
                    # "Unfortunately... / that does not seem to be my
                    # role.").
                    severe = (not label_only and not beat_over_sentences
                              and not (beat_first and stop_cost(
                                  atoms_text(j + 1, _end)) == 0)
                              # the original's own beat: the lines under it
                              # are a block of their own, no rise ("Nanjo:
                              # Snow...? / Was he going to suggest The Snow
                              # Queen?")
                              and not (atoms[j].orig >= ORIG_FREE_RISE and not last)
                              and sub[6] > w * 2
                              and (sc == 4 or trails))
                    if severe:
                        end += 4
                    # A STUTTER IS ONE PHRASE: "No, I... / I am" breaks
                    # between a word and its own repetition.
                    if stut:
                        end = max(end, 4)
                    # A HOLLOW MIDDLE: the next line is under half of both
                    # its neighbours ("story, / but you know, / it'd be
                    # nice..."). Its punctuation does not pay for it. A
                    # complete short sentence is hollow only in a block of
                    # exactly three lines (one box, "here, / <name>! / It's
                    # too late..."); in a longer block it may end a page
                    # ("that... / inferior! | You are born...").
                    # `after` keys the line after next: (count, its width).
                    if (not label_only and k >= 2 and sub[6] >= 0
                            and sub[6] * 2 < min(w, after[1])
                            and (stop_cost(atoms_text(j + 1, _end)) > 0
                                 or (i == 0 and k == 2))):
                        end += HOLLOW
                    # Tail/rise tests are shape costs, not sentence-boundary
                    # vetoes. Otherwise a modest short tail could force a
                    # narrow middle line or a growing triangle regardless of
                    # how much worse its overall shape is. A standalone
                    # speaker label is not a speech line (spec 2.4): it takes
                    # no part in the block's balance, so the speech after it
                    # is scored as the block it would be on its own.
                    # Compare average speech shape, not a smaller sum merely
                    # because a standalone label excluded one line. Scale
                    # the suffix to this block's line count without pricing
                    # the label's own width or a transition to it.
                    shape = (sub[5] // k if label_only and k else
                             0 if label_only else fullness(w, k + 1) + trans)
                    if not label_only and k == 1 and sub[6] * 2 < w:
                        shape += (w - 2 * sub[6]) ** 2
                    elif (TOP_HEAVY and not label_only and k >= 1
                          and sub[6] * 10 > w * 14 and not full):
                        shape += (sub[6] - w) ** 2
                    elif (not TOP_HEAVY and not label_only and k >= 1
                          and w * 10 > sub[6] * 14):
                        shape += (w - sub[6]) ** 2
                    total = (base + sub[0],
                             pen + sub[1],
                             nbrk + sub[2],
                             sub[3] + int(fragment),
                             sub[4] + end,
                             sub[5] + shape,
                             w,
                             sub[7] + (0 if last or label_only
                                       else orphan or int(strand or severe
                                                          or tic)),
                             sub[8] + int(fragment or strand
                                          or severe or opener),
                             sub[9] + led,
                             sub[10] + int(not last and atoms[j].orig >= ORIG_FREE_LINE))
                    key = (k + 1, w)
                    r = _rank(total)
                    cur = ranks.get(key)
                    if cur is None or r < cur:
                        bucket[key] = (total, j, subkey)
                        ranks[key] = r
                if over > 0 and want is None:
                    break
            if j + 1 >= n:
                break
            j += 1
            text = line_text(text, atoms[j])
            w = measure(text)
        # A suffix already past the box loses to one with fewer lines and no
        # more overflow under ANY start: the root ranks overflow, then
        # max(lines, box), and the same start adds the same to both. Free
        # flow only (a fixed skeleton wants an exact count). A trace loses
        # nothing it reports: such a layout loses to the winner on overflow
        # or lines, so it is never a close call's runner-up.
        if want is None and len(best[i]) > 1:
            bucket = best[i]
            floor = {}
            for (k, _w), (c, _j, _s) in bucket.items():
                if floor.get(k, c[0] + 1) > c[0]:
                    floor[k] = c[0]
            low, run = [], None
            for k in sorted(floor):
                run = floor[k] if run is None else min(run, floor[k])
                low.append((k, run))
            for key in [key for key, (c, _j, _s) in bucket.items()
                        if key[0] > box and any(k < key[0] and o <= c[0]
                                                for k, o in low)]:
                del bucket[key]
                del ranked[i][key]
    if want is None:
        # Least lines, then internal splits, protected phrases, clipped
        # speech fragments, sentence boundaries and the whole block's shape.
        # A line inside the box is cheaper than a split word or name: line
        # counts up to what the box has left (`box`) tie, the splits decide,
        # then the count. Past the box, every line counts first.
        # Inside the box a mid-clause break is worse than an extra line too.
        def rank(key):
            c = best[0][key][0]
            return ((c[0], max(key[0], box)) + c[1:3]
                    + (c[8], key[0] - c[10], 2 * c[7] + c[4] + c[5] / SHAPE_POINT, c[9]))
    else:
        def rank(key):
            return (abs(key[0] - want),) + best[0][key][0][:6]

    def walk(key):
        out, i = [], 0
        while i < n:
            _cost, j, next_key = best[i][key]
            out.append((i, j))
            i, key = j + 1, next_key
        return out
    if trace is not None:
        trace.extend((rank(k), walk(k)) for k in best[0])
    return walk(min(best[0], key=rank))


# THE ORIGINAL'S OWN LINES AND PAUSES: where the Japanese ends a sentence or a beat
# (！？。…♥, a pause after it) and breaks its line right there, the English
# sentence with the same number ends a line the flow may use as the
# original's own: it costs no extra line (cost[10]), so "Eep! ❤ / I think
# your eyes are totally / gonna sweep me off my feet!" follows
# "どぎっ♥<FFF6>アンダの瞳に...". Its battle-box pauses after a sentence
# (<FFFC>) come along the same way ("Eeep...<FFFC> / You're one mean
# lady..." from "うひ……<FFFC><FFF6>お姉ちゃんて"). Only where both count the
# same sentences; otherwise only the opening sentence is matched (the n-th
# of one is not the n-th of the other).
JA_END = re.compile(r'(?:[！？。!?♥…]|‥|\.\.)+[」』）)]*')
_JA_CODES = re.compile(r'<FF05>(?:<[0-9A-F]{2}>){2}|<FFFD>.|<FF0[6-9A-F]>(?:<[0-9A-F]{2}>)?|<[^>]+>')


_PAUSE_MARK = '\x01'


ORIG_FREE_LINE = 2
JA_BEAT = 6          # characters: a Japanese sentence that short is a beat
ORIG_FREE_RISE = 1


def orig_beats(ja, words, pause=None):
    """({word index: pauses}, {word index}) - where the original pauses
    (`pause`, the battle box's <FFFC>) and where it breaks its line at the
    end of a sentence (see JA_END above), each put after the English word
    that ends the same-numbered sentence; never after the last."""
    t = re.sub(r'<FF03>|<FFF6>', '\n', ja or '')
    if pause:
        t = t.replace(pause, _PAUSE_MARK)
    t = _JA_CODES.sub('', t)
    ja_ends, breaks, pauses = 0, [], {}
    first = None             # the Japanese's opening sentence, label dropped
    for m in JA_END.finditer(t):
        ja_ends += 1
        if first is None:
            first = re.sub(r'^[^：\n]{1,12}：', '', t[:m.end()]).strip()
        after = re.match('[ \u3000\n' + _PAUSE_MARK + ']*', t[m.end():]).group(0)
        if '\n' in after:
            breaks.append(ja_ends)
        if after.count(_PAUSE_MARK):
            pauses[ja_ends] = after.count(_PAUSE_MARK)
    ends = []
    for i, w in enumerate(words):
        core = _plain(w)
        if core and sent_end(core):
            ends.append(i)
        elif not core and w.strip().startswith(SPEECH_HEART) and ends and ends[-1] == i - 1:
            ends[-1] = i              # the heart rides with its sentence
    if len(ends) != ja_ends:
        # the counts differ, but the OPENING sentence is still the opening
        # one ("へ？<FF03>あ…" / "Huh? O-Ohhh... you're right."): only it
        # ... when that sentence is a beat in the Japanese too ("へ？"; never
        # "おいッ誰がこぼして<FF03>いいと言ったザマすか？" for "Hey!")
        if len(ends) < 2 or not ja_ends or len(first) > JA_BEAT:
            return {}, {}
        breaks = [n for n in breaks if n == 1]
        pauses = {n: k for n, k in pauses.items() if n == 1}
        ends = ends[:1] + [len(words)]   # (no later sentence is matched)
    # a line of its own for a BEAT: a sentence of at most half the box
    # ("What!? / These guys were dead?"), or any sentence the original also
    # PAUSES after ("Did you just say that / you intend to defeat me?<FFFC> /
    # You are a wicked one..."); a longer bare one is the flow's to lay out
    # ("So there are angels and demons / within people's souls?")
    starts = [0] + [e + 1 for e in ends]
    # never inside a stammer ("H... / How can this be!?")
    breaks = [n for n in breaks if not (ends[n - 1] + 1 < len(words) and stutter(
        words[ends[n - 1]], words[ends[n - 1] + 1]))]
    beat = {n for n in breaks if n < len(ends)
            and (n in pauses or text_width(
                ' '.join(words[starts[n - 1]:ends[n - 1] + 1])) * 2 <= BOX_WIDTH)}
    # strong where the original pauses there too (or has no pause code to
    # tell): the beat is meant; a bare line break may be only the line
    # running out
    return ({ends[n - 1]: k for n, k in pauses.items() if n < len(ends)},
            {ends[n - 1]: not pause or n in pauses for n in beat})


def _timed(it):
    """A timed pause item: the flow's ('g', <FF05>..) or a porter's
    ('u', 'FF05..')."""
    return ((it[0] == 'g' and bool(PAUSE_CODE.fullmatch(str(it[1]))))
            or (it[0] == 'u' and str(it[1]).startswith('FF05')))


def with_orig_breaks(items, ja, pause=None):
    """items with the original's beats put in: `pause` (a 'g' code) after
    each word where the original pauses, and an ('h', '') where it breaks
    its line (orig_beats) - after the timed pauses that follow the word, so
    the line ends where the beat does ("Yamaoka!<FF05><3C><00>" / "You
    bastards..."). A word that already carries the pause keeps its own."""
    idx = {k: n for n, k in enumerate(k for k, it in enumerate(items) if it[0] == 'w')}
    pauses, at = orig_beats(ja, [items[k][1] for k in idx], pause)
    out, held = [], None
    for k, it in enumerate(items):
        if held is not None and not _timed(it):
            out.append(held)
            held = None
        out.append(it)
        if k not in idx:
            continue
        n = idx[k]
        nxt = items[k + 1] if k + 1 < len(items) else None
        if (n in pauses and pause not in it[1]
                and not (nxt and nxt[0] == 'g' and nxt[1] == pause)):
            # carried between two words, so the gap between them is theirs
            # ("lead?<FFFC> ...You", never "lead?<FFFC>...You")
            out.extend(('g', pause, True) for _ in range(pauses[n]))
        if n in at:
            held = ('h', '' if at[n] else 'weak')
    if held is not None:
        out.append(held)
    return out


def orig_sentence_lines(ja, words):
    """The English sentence ends the Japanese breaks its line after, or None
    when the two do not count the same sentences (then nothing says where
    the Japanese lines fall in the English). orig_beats' matching, without
    its beat-length test: {word index}."""
    t = _JA_CODES.sub('', re.sub(r'<FF03>|<FFF6>', '\n', ja or ''))
    breaks, n = set(), 0
    for m in JA_END.finditer(t):
        n += 1
        if '\n' in re.match('[ \u3000\n]*', t[m.end():]).group(0):
            breaks.add(n)
    ends = [i for i, w in enumerate(words) if _plain(w) and sent_end(_plain(w))]
    if len(ends) != n:
        return None
    return {ends[k - 1] for k in breaks if k <= len(ends)}


def flow_lines(items, width=BOX_WIDTH, measure=text_width, newline=NEWLINE,
               tail=1, joinable=None, word_gaps=False):
    # Pure in its arguments, and the corpus repeats itself (the talk
    # families share most of their lines): lay each stream out once.
    try:
        key = (tuple(tuple(it) for it in items), width, measure, newline,
               tail, joinable, word_gaps, _MEASURING.stack[-1])
        hash(key)
    except TypeError:
        return _flow_lines(items, width, measure, newline, tail, joinable, word_gaps)
    got = _FLOWN.get(key)
    if got is None:
        got = _FLOWN[key] = tuple(_flow_lines(items, width, measure, newline,
                                              tail, joinable, word_gaps))
    return list(got)


_FLOWN = {}


def _flow_lines(items, width=BOX_WIDTH, measure=text_width, newline=NEWLINE,
                tail=1, joinable=None, word_gaps=False):
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
    items = list(items) if word_gaps else _glue_items(items)
    seq = flow_model(items, word_gaps=word_gaps)
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
    used = [0]      # lines already shown in the current box
    pages = [0]     # <FF04> boundaries seen

    def fewest(entries):
        atoms = [a for k, a in entries if k == 'a']
        return len(flow_layout(atoms, width, measure, tail, box=0)) if atoms else 0

    def may_join(k):
        return (joinable is True
                or (joinable is not None and k < len(joinable) and joinable[k]))

    # Look ahead one box: a region followed by a <FF04> the merge may join
    # leaves the next box room for its fewest lines, when that join can fit
    # at all ("Don't worry, miss! Everything will be A-OK now that I'm here!"
    # keeps two lines so "Now go get 'em" joins instead of a new box).
    groups, cur = [], []
    for entry in seq:
        if entry[0] == 'b':
            groups.append((cur, entry))
            cur = []
        else:
            cur.append(entry)
    groups.append((cur, None))
    reserve_for = {}
    page_k = 0
    for gi, (entries, brk) in enumerate(groups):
        if brk is not None and brk[1] == '<FF04>':
            if may_join(page_k):
                nxt = next((e for e, _b in groups[gi + 1:] if e), None)
                if nxt is not None:
                    reserve_for[gi] = fewest(nxt)
            page_k += 1
    # the waits before a page (<FF02><FF04>) end the region early: carry a
    # reservation back to the last region before them
    for gi in sorted(reserve_for, reverse=True):
        g = gi
        while g > 0 and not groups[g][0]:
            g -= 1
        if g != gi:
            reserve_for[g] = reserve_for.pop(gi)
    gi_now = [0]

    def flush():
        if not region:
            return
        atoms = [a for k, a in region if k == 'a']
        box = max(BOX_LINES - used[0], 0)
        reserve = reserve_for.get(gi_now[0], 0)
        if reserve and used[0] + fewest(region) + reserve <= BOX_LINES:
            box = max(box - reserve, 0)
        spans = flow_layout(atoms, width, measure, tail, box=0 if word_gaps else box)
        used[0] += len(spans)
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
            gi_now[0] += 1
            out.append(('c', entry[1]))
            if entry[1] == '<FF04>' and joinable is not None:
                # joinable: True (any boundary may join) or one flag per
                # <FF04>; a box that may join keeps the earlier box's lines
                k = pages[0]
                pages[0] += 1
                may = (joinable if joinable is True
                       else k < len(joinable) and joinable[k])
                # nothing joins a full box, nor a box the next one cannot
                # share: its fewest lines would not fit beside the earlier
                # box's, so it is laid out as a box of its own
                nxt = groups[gi_now[0]][0] if gi_now[0] < len(groups) else []
                if (not may or used[0] >= BOX_LINES
                        or used[0] + fewest(nxt) > BOX_LINES):
                    used[0] = 0
            elif entry[1] in BOX_ENDS:
                used[0] = 0
            continue
        region.append(entry)
    flush()
    return out



RANK_NAMES = ('overflow', 'lines past the box', 'split words', 'split names',
              'scraps', 'lines', 'line ends and shape', 'noun phrase splits')


def weigh(words, width=BOX_WIDTH, measure=text_width, tail=1, box=BOX_LINES):
    """[(rank, lines)] every layout flow_layout weighs for one run of words
    (no deliberate break inside), best first: the same atoms, glue and
    ranking flow_lines uses, so the first is the flow's choice and the
    second is what it nearly chose. For the viewer's close calls."""
    seq = flow_model(_glue_items([('w', w) for w in words if w]))
    atoms = [v for k, v in seq if k == 'a']
    for a in atoms:
        a.fin = False
    for a in reversed(atoms):
        if a.word:
            a.fin = a.last
            break
    trace = []
    flow_layout(atoms, width, measure, tail, box=box, trace=trace)
    out = []
    for rank, spans in sorted(trace, key=lambda t: t[0]):
        lines = []
        for i, j in spans:
            text = ''
            for a in atoms[i:j + 1]:
                text = line_text(text, a)
            lines.append(text)
        out.append((rank, lines))
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
             '10': 1, '11': 0, '12': 0,
             'F1': 1, 'FD': 1, 'FE': 1, 'FF': 1}   # interpreter operand bytes


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
    name inserts (FF07/08/0F), battle inserts and pauses (FF05/FFFC) render as
    words and keep their neighbours' spacing ("Mark:<name>found", "Mark:<pause>Dammit!"),
    and a control code's PARAMETER travels with its code - <FF0E> is
    followed by its choice-set byte, which may itself be a space (0x88)."""
    toks = atoms(en)
    # Names, numeric inserts and pauses can occupy visible space. Battle
    # insertion tokens come from the same decomp-derived set used to price
    # their width, rather than a second hand-maintained list.
    # <FFFC> is the battle interpreter's pause (windowtype.c CODE_WAIT), the
    # sibling of <FF05>: the source's word gap beside it is wording.
    keep = ('<FF05>', '<FF11>', '<FF12>', '<FFFC>') + NAME_CODES + INSERT_CODES
    battle_inserts = frozenset(battle_insert_widths())
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


# The codes that MOVE the pen to another line/page. A one-row field has no
# second line to move to: where one of these sat, the reader sees the word
# gap it stood for, never an invisible line.
ONE_LINE_MOVES = re.compile(r'<FF(?:03|04)>|<FFF6>')


def one_line(text):
    """A destination that proves a single visible row (the message viewport
    is 16 px high) cannot show a line or page move: the move becomes the
    word gap it was, and the result must fit one 240 px line.

    This is a DESTINATION rule, not a wording edit: the same words are kept,
    only the break the destination has no room for is spelled as a space.
    (`<FF02>` waits stay: a wait pauses on the same line.)"""
    t = ONE_LINE_MOVES.sub(' ', text or '')
    t = re.sub(r' {2,}', ' ', t)
    return clean_edges(t)


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


# the words after which a new clause starts: a prompt's last line may begin
# there (prompt_tail_line)
CLAUSE_OPENERS = {'that', 'and', 'but', 'or', 'so', 'yet'} | SUBORDINATORS


def prompt_tail_line(head, brk=NEWLINE, width=BOX_WIDTH, measure=text_width):
    """The prompt's own box, BOTTOM-HEAVY: while the options are up the box
    has scrolled so only the question's LAST line shows above them, so that
    line carries as much of the question as fits ("<name>, / I could really
    use a hand!", never "<name>, I could / really use a hand!").

    The last line starts at the earliest CLAUSE boundary whose rest fits one
    line: after punctuation (a vocative's comma, a sentence end, a label's
    colon) or after the conjunction that opens the clause ("Are you certain
    that / you want to bring Hidehiko along?", "...ask this, but / could you
    make friends with Reiji?") - never between an auxiliary and its subject
    (no "Do / you have..."). A last line that already starts at a clause is
    left alone, and the tail never reaches back past the final sentence (the
    line holds the question, at most "Name: question"). Only when the final
    sentence is too long does it take the longest tail that does not cut
    after a subject, an article, a connector or an auxiliary before its
    subject ("You must / have stuff you're hiding too, right?"); the lines
    above are the flow's best layout in the lines the box has left, so the
    box never grows; a question that fits one line is one. Only line breaks
    move. Only the prompt's own box (after its
    last page move), and only a box whose codes are name inserts (a pause
    keeps the box's own spacing). Returns `head` unchanged whenever the test
    fails or the last line would not grow."""
    parts = re.split(r'(<FF02><FF04>|<FFFB><FFF7>)', head)
    box = parts[-1]
    lines = [x for x in box.split(brk) if x.strip()]
    if len(lines) < 2 or '<' in NAME_TOKEN_RE.sub('', box.replace(brk, ' ')):
        return head
    words = box.replace(brk, ' ').split()
    # a question that fits one line IS one line: wholly visible, and the
    # options follow it without a press
    if measure(' '.join(words)) <= width:
        return ''.join(parts[:-1]) + ' '.join(words)
    def fits_from(i):
        tail = ' '.join(words[i:])
        return measure(tail) <= width and measure(tail) > measure(lines[-1].strip())

    def ends_clause(w):
        return re.search(r'[,.!?:;…]["”’)]*$', w) is not None

    def clause(i):
        w = words[i - 1].lower()
        if w == 'that':
            # a complementizer opens a clause ("certain that / you want");
            # a determiner does not ("give back that / book")
            tags = lexicon().get(_core_word(words[i]).lower().strip('.,!?;:'), ())
            return not ('noun' in tags and not tags & {'pron', 'det'})
        return ends_clause(words[i - 1]) or w in CLAUSE_OPENERS

    def phrase(i):
        # the final sentence alone is too long: the longest tail, but never
        # cut after a word that leans on the next - a subject ("you / want"),
        # an article, a connector, an auxiliary before its subject ("Do /
        # you"); a modal before its verb may end the line ("You must / have
        # stuff you're hiding too, right?")
        w = _core_word(words[i - 1]).lower().rstrip(',;:')
        nxt = _core_word(words[i]).lower()
        if w in SUBJECTS | {'you', 'it'} | ARTICLES | CONNECTORS:
            return False
        if w in MODALS and nxt in SUBJECTS | {'you', 'it'}:
            return False
        return not (w in AUX_BE_HAVE and ends_on_auxiliary(w, words[i]))

    # a last line that already starts at a clause is the question's own:
    # left alone ("Do you know him?", "who cares about tomorrow?")
    if clause(len(words) - len(lines[-1].split())):
        return head
    # never past the final sentence: the line holds the question, at most
    # "Name: question" - not the end of the sentence before it
    start = max([k + 1 for k in range(len(words) - 1)
                 if re.search(r'[.!?…:]["”’)]*$', words[k])] or [1])
    for test in (clause, phrase):
        i = next((i for i in range(max(start, 1), len(words))
                  if test(i) and fits_from(i)), None)
        if i is None:
            continue
        above = _prompt_above(words[:i], lines, width, measure)
        if above is None:
            continue
        return ''.join(parts[:-1]) + brk.join(above) + brk + ' '.join(words[i:])
    return head


def _prompt_above(words, lines, width, measure):
    """The prompt's lines above its last one: the box's own lines, ending
    sooner ("Reiji's mother: It may be selfish / of me to ask this, but") -
    unless one would end on the first word of a new sentence ("but...
    Could"); then the flow's best layout of `words` in the lines the box has
    left ("Yuko: Um, I hate to ask, but... / Could you tell Maki I'll give
    back"), a label that stood on its own line keeping it. None when they
    do not fit."""
    kept, left = [], len(words)
    for line in lines:
        ws = line.split()
        if left <= 0:
            break
        kept.append(' '.join(ws[:left]))
        left -= len(ws)
    if not any(strands_opener(x) for x in kept):
        return kept
    room = BOX_LINES - 1
    head = []
    first = lines[0].split()
    if (len(first) < len(words) and words[:len(first)] == first
            and re.fullmatch(LABEL_RE, label_plain(lines[0]).strip())):
        head, words, room = [lines[0].strip()], words[len(first):], room - 1
    if not words:
        return head
    for _key, laid in weigh(words, width=width, measure=measure, box=room):
        if len(laid) <= room:
            return head + [' '.join(x.split()) for x in laid]
    return None


# FONT EDITIONS IN ONE ROW. A porter lays a row out once per face
# (toolpath.FONT_EDITIONS) and writes the two layouts as one row: a separator
# both agree on stays plain; where they differ, each face's codes carry its
# letter - <LFF03> breaks only in the large edition, <SFF03> only in the
# small one (pages and waits likewise). Wording only one edition has (an
# erratum marked for one face in psp_errata.tsv) is a span: <L{>...<}> or
# <S{>...<}>. edition_text reads one edition back: its own spans and codes
# and the plain ones, the other face's dropped, and a separator left with no
# code of its own is the space it replaced. The game never sees a letter:
# etext.encode and text_width resolve the edition first.
# A row with no letters (a family not laid out twice, or two layouts that
# agreed) is the same in both, except that its choice breaks are the large
# face's: another edition re-derives those (edition_layout).
ROW_EDITION = 'large'
EDITION_LETTER = {'large': 'L', 'small': 'S'}
_EDITION_CODE = re.compile(r'<([LS])([0-9A-F]{2,4})>')
# the codes a layout moves: line, page, wait, timed pause (with its two
# parameter bytes)
_LAYOUT_RUN = re.compile(r'(?:\s|<FF03>|<FF04>|<FF02>|<FF05><[0-9A-F]{2}><[0-9A-F]{2}>)+')


_EDITION_SPAN = re.compile(r'<([LS])\{>(.*?)<\}>', re.S)


def edition_text(en, edition=None):
    """One edition's wording of a row that may carry several (see above):
    its own spans and codes, the plain ones, nothing of another face."""
    if not en or '<L' not in en and '<S' not in en:
        return en
    letter = EDITION_LETTER[edition or toolpath.FONT_EDITION]
    en = _EDITION_SPAN.sub(lambda m: m.group(2) if m.group(1) == letter else '', en)
    out, pos = [], 0
    for m in re.finditer(r'(?:<[LS][0-9A-F]{2,4}>)+', en):
        own = ''.join(f'<{c}>' for l, c in _EDITION_CODE.findall(m.group(0)) if l == letter)
        before, after = en[:m.start()], en[m.end():]
        if not own and before[-1:] not in ('', ' ', '>') and after[:1] not in ('', ' ', '<'):
            own = ' '          # the other face broke here; this one keeps the space
        out.append(en[pos:m.start()] + own)
        pos = m.end()
    return ''.join(out) + en[pos:]


def merge_editions(texts):
    """{edition: laid-out row} -> one row carrying every edition's layout, or
    None when it cannot be written so that each edition reads back exactly
    its own (the caller then keeps ROW_EDITION's layout for all).

    Words both editions share anchor the row. Between two shared words, a
    separator that differs is lettered code by code (<LFF03>, <SFF02>...);
    where the words themselves differ (an erratum only one edition applies),
    each edition's own text between the anchors becomes a span,
    <L{>...<}> / <S{>...<}>."""
    import difflib
    base = texts[ROW_EDITION]
    others = {e: t for e, t in texts.items() if e != ROW_EDITION}
    if all(t == base for t in others.values()):
        return base
    if len(others) != 1:
        raise ValueError('merge_editions: two editions only')
    (other, text), = others.items()
    la, lb = EDITION_LETTER[ROW_EDITION], EDITION_LETTER[other]

    def split(t):
        """words, [(start, end)] of each word, the separators between them"""
        words, spans, cuts, pos = [], [], [], 0
        for m in _LAYOUT_RUN.finditer(t):
            words.append(t[pos:m.start()]); spans.append((pos, m.start()))
            cuts.append(m.group(0)); pos = m.end()
        words.append(t[pos:]); spans.append((pos, len(t)))
        return words, spans, cuts
    wa, pa, ca = split(base)
    wb, pb, cb = split(text)

    def separator(sa, sb):
        if sa == sb:
            return sa
        # a space in one face and codes in the other becomes the codes,
        # lettered; a space AND codes in one face is not one this can letter
        for sep in (sa, sb):
            if sep.strip() and ' ' in sep:
                return None
        # the codes both runs share stay plain, in their place; only the
        # difference is lettered (`?<LFF02><FF03><FF0E>`, never
        # `<LFF02><LFF03><SFF03>` for one break both faces make)
        ka = re.findall(r'<([0-9A-F]{2,4})>', sa)
        kb = re.findall(r'<([0-9A-F]{2,4})>', sb)
        parts = []
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ka, kb, autojunk=False).get_opcodes():
            if op == 'equal':
                parts.append(''.join(f'<{c}>' for c in ka[i1:i2]))
            else:
                parts.append(''.join(f'<{la}{c}>' for c in ka[i1:i2])
                             + ''.join(f'<{lb}{c}>' for c in kb[j1:j2]))
        return ''.join(parts)

    out = []
    blocks = difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes()
    for n, (op, i1, i2, j1, j2) in enumerate(blocks):
        if op == 'equal':
            for k in range(i1, i2):
                if k > i1:
                    sep = separator(ca[k - 1], cb[j1 + (k - i1) - 1])
                    if sep is None:
                        return None
                    out.append(sep)
                out.append(wa[k])
            continue
        # each edition's text between the shared words around this block
        a0 = pa[i1 - 1][1] if i1 else 0
        a1 = pa[i2][0] if i2 < len(wa) else len(base)
        b0 = pb[j1 - 1][1] if j1 else 0
        b1 = pb[j2][0] if j2 < len(wb) else len(text)
        if '<}>' in base[a0:a1] or '<}>' in text[b0:b1]:
            return None
        out.append(f'<{la}{{>{base[a0:a1]}<}}>' + f'<{lb}{{>{text[b0:b1]}<}}>')
    merged = ''.join(out)
    if edition_text(merged, ROW_EDITION) != base or edition_text(merged, other) != text:
        return None
    return merged


def lettered(en):
    """Does a row carry more than one edition's layout?"""
    return bool(en) and (_EDITION_CODE.search(en) is not None
                         or _EDITION_SPAN.search(en) is not None)


def per_edition(fn, en):
    """fn over a row, edition by edition when it carries several: each
    edition's text alone, the results merged again (ROW_EDITION's for all
    when they no longer merge). A row laid out once is fn(en)."""
    if not lettered(en):
        return fn(en)
    done = {}
    for e in toolpath.FONT_EDITIONS:
        with measured_as(e):
            done[e] = fn(edition_text(en, e))
    return merge_editions(done) or done[ROW_EDITION]


def edition_layout(en, brk=NEWLINE):
    """A row's wording laid out for the edition being built: its edition's
    text; a row laid out once (no letters) gets its choice breaks re-derived
    with this face's widths outside ROW_EDITION (the pen moves, so the break
    that is right moves too)."""
    one = edition_text(en)
    if one != en or toolpath.FONT_EDITION == ROW_EDITION or '<FF0E>' not in one:
        return one
    return choice_breaks(one, brk)


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
        head = prompt_tail_line(head, brk)
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
