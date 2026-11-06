"""The textbox derivation - what a wording BECOMES in its box.

One place decides it, every porter calls it on the first pass (nothing
waits for a sweep to fix it up later):

  fit_codes    the wording carries the Japanese line's control codes, in
               the DESTINATION family's spelling (the battle interpreter
               cannot read a dialogue code - persona-decomp btlp/
               windowtype.c BtlWindowType is the authority)
  lay_out      the box's own layout (port_story.layout_box: labels, the
               flow, the pagination) - a fixed one-line field is not
               re-broken
  codes_match  the codes the destination requires, exactly
  box_gate     what the box cannot SHOW (its builder's width/line check)
  renorm_generated  generated/ is DERIVED data: every shipped row
               re-derives from its `psp` source through this, every run

Wording is never typed here and never shortened: only the codes, the
break points and the shape change.
"""
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'matching'))
import toolbelt  # noqa: E402
import vwf_wrap      # noqa: E402
import port_caps     # noqa: E402
# the box model (widths, budgets, what is a textbox) is the DESTINATION's -
# port_caps owns it, and this module derives into it
from port_caps import (BUDGET_PX, PEN_MAX, BUDGET_LINES, ink_of, widest)  # noqa: E402,F401


def fits_budget(en):
    """The strictest budget any dialogue box shares: every line within
    the box width and no more than four to a page (three visible lines
    plus the fourth scroll line). A one-line name field is tighter than
    this and its porter routes the row over; nothing is ever written here
    that the rendered box could not show."""
    px, lines = widest(en)
    return px <= PEN_MAX and lines <= BUDGET_LINES


def reflow(en, ja='', width=BUDGET_PX, text_rel=''):
    """A textbox is laid out by THE textbox pipeline - port_story.layout_box,
    the single entry every producer calls. Nothing here decides a box's
    layout; the line-break code is the file's own (port_caps.line_break:
    read off the file's Japanese, not a family-name table) and the budget
    gate applies (a row that cannot lay out is a draft, never a wrong
    box)."""
    import port_story
    brk = port_caps.line_break(text_rel)
    return port_story.layout_box(en, brk=brk)


def lay_out(text, rel, ja='', pos=''):
    """Lay a wording out the way its DESTINATION shows it.

    A textbox is reflowed at the box width (the words are never shortened -
    only the break points are placed). A fixed one-line field - a name, a
    skill, an item, a card label, an ADV system message whose viewport is
    one row - is NOT re-broken: it has no second line, so a break would only
    make it wrong (and, in a one-row message, invisible). Its edges are
    cleaned, a line/page move is spelled as the word gap it was, and its
    capacity is its builder's (port_caps.dest_cap)."""
    if port_caps.is_fixed_field(rel, pos):
        return vwf_wrap.one_line(text)
    if port_caps.is_textbox(rel):
        return reflow(text, ja, text_rel=rel)
    return vwf_wrap.clean_edges(text)


def unlayable_note(text, placed=False):
    """The honest reason a wording cannot be laid out in its box: it is
    wider than a line or longer than a page. The numbers are the
    renderer's, never the Japanese line's byte length. `placed` measures a
    row that is already laid out, so its name inserts count as the pixels
    they draw (the same measure QA uses)."""
    px, lines = widest(text, ink=not placed)
    if px > PEN_MAX:
        return toolbelt.note_over(px, PEN_MAX, 'px')
    if lines > BUDGET_LINES:
        return toolbelt.note_over(lines, BUDGET_LINES, 'lines')
    return ''


# PSP glyph-map hole markers ('[05d8]') and Japanese left in the text: a
# box still carrying them is an untranslated remnant, not English (port_dng's
# rule - "never guessed"). Judge both hole markers and decoded Japanese.
# Shared punctuation (＞ ￥ ・ ...) is not a remnant.
JP_LETTERS = toolbelt.JP_LETTERS
HOLES = re.compile(r'\[[0-9a-f]{4}\]|' + JP_LETTERS)
# Tokens whose width the flow prices as a worst-case copy: a name insert
# (<FF07>/<FF0F>/<FF08> plus its parameter) and the battle window's seven
# <FFFx> slots. The flow is not idempotent around one of these, so the
# renorm re-derives such a row a second time and only takes the layout that
# reproduces itself (one shape, whichever pass wrote it).
INSERTS = re.compile(r'<FF(?:07|08|0F)>|<FFF[0-9A-F]>')
JAPANESE_REMNANT = 'untranslated Japanese remnant'
JP_GLYPH = re.compile(JP_LETTERS)


def still_japanese(text):
    """Is this SOURCE wording Japanese rather than a translation?

    The PSP-US pack was not localised everywhere (a dungeon pack can be
    byte-identical to the JP one: d06's billboards and its title logo), so
    a `psp` pointer can name a unit whose words are still Japanese. That is
    NOT a wording to derive into a box: a destination whose font is ASCII
    (the dungeon text) cannot spell kana, and pushing the line through its
    encoder yields glyph indices that read back as '[0ad7][0b5f]' - which is
    not a remnant of a translation but the source itself, re-spelled.

    The test is the one stray_jp already owns: an ISOLATED glyph run inside
    English is furniture (a name record's glitch head) and is not this; a
    line that is really Japanese keeps its glyphs. Whatever is left is
    judged by HOLES, the same measure a derived box gets."""
    return bool(HOLES.search(ink_of(stray_jp(text or ''))))


def stray_jp(text):
    """STRAY JP GLYPHS the US build left inside its own English (PSP-US
    shipped a few: '収益' alone between two breaks in TENSI, '終' heading
    a POLUTAR laugh). An isolated run inside English wording is furniture
    like the '>' mark and goes; a line that is REALLY Japanese stays a
    remnant - when there is no English around it (or the run dwarfs it)
    nothing is stripped and HOLES judges the result. <FFFD> parameters
    are code bytes, not wording, and ride through untouched."""
    if not JP_GLYPH.search(text):
        return text
    letters = len(re.sub(r'[^A-Za-z]', '', text))
    runs = JP_GLYPH.findall(re.sub(r'(<FFFD>.)', '', text))
    if not (letters and sum(map(len, runs)) * 4 <= letters):
        return text
    stash = []
    text = re.sub(r'(<FFFD>.)', lambda m: (stash.append(m.group(1)),
                                           f'\x00{len(stash) - 1}\x00')[1],
                  text)
    text = re.sub(r' *' + JP_GLYPH.pattern + r'+ *', ' ', text)
    return re.sub(r'\x00(\d+)\x00', lambda m: stash[int(m.group(1))], text)


# A fixed one-line FIELD's record can carry a HEAD before its words: the
# PSP draws a skill's icon as glyph cells, places it with a code, and both
# builds carry the cells ('儖β<FF0F>トラフーリ' / '儖β<FF0F>Trafuri',
# '畢 nビーク' / '畢 nBeak'). It is furniture, never wording.
HEAD_CAP = 12            # a record head is a few cells, not a sentence
CELL = re.compile(r'[^\x00-\x7f]')
CODE = re.compile(r'<[0-9A-Fa-f]{2,4}>')
# ... and a cell that lost its high byte leaves ONE lower-case letter
# against the word that follows ('nBeak', 'fMaeiha', 'wFist of Fury',
# '椴o緑Toxic Sting'). No wording in the PSP-US build starts that way: every
# row that does is a name record whose head is all that remains of the cell
# (59 in the whole EBOOT, 35 of them reached the PSX tables).
LEAD_CELLS = re.compile(r'(?:[^\x00-\x7f]|<[0-9A-Fa-f]{2,4}>|[^A-Za-z0-9])*')


def shared_head(jp_text, us_text):
    """How many leading characters of a US record are the pair's HEAD - the
    glitch cells both builds carry before their own words - or 0 where
    nothing proves one.

    Two shapes prove a head, and the JP twin is the proof in both:

      (a) the JP row carries cells BEFORE its words (its first kana or
          kanji is where they begin). Where the JP run is longer than what
          the US row carries - the extractor dropped the run's first cells -
          only its tail matches, and only when the dropped part holds no
          ASCII letter or digit (glitch cells, not a word the US row simply
          does not have).

      (b) the JP row's OWN first glyphs ARE the cells: an icon both builds
          carry, which the JP glyph map happens to read as a kanji
          ('瞭 <FF0D>噛み付き' / '瞭 <FF0D>Feral Bite',
          '儖β<FF0F>トラフーリ' / '儖β<FF0F>Trafuri'). The leading run the
          two records share is the head when it holds a cell and no ASCII
          letter or digit, and both records then start their own words - the
          JP a glyph, the US a letter. A run that ends the US record (or is
          followed by more of the same script) is wording, not decoration.

    A head made of codes alone ('<FF1B>', a nameplate) is structure both
    builds need, never decoration.

    FIXED FIELDS ONLY: a textbox's head is the box's own structure
    (portraits, nameplates). Callers gate on port_caps.is_fixed_field."""
    if not jp_text or not us_text:
        return 0
    cut = JP_GLYPH.search(jp_text)
    if cut is not None:
        head = jp_text[:cut.start()][-HEAD_CAP:]
        if CELL.search(CODE.sub('', head)):
            for k in range(min(len(head), len(us_text) - 1), 0, -1):
                if us_text.startswith(head[-k:]):
                    if k == len(head) or not re.search(r'[0-9A-Za-z]',
                                                       head[:-k]):
                        return k
                    break
    n = 0                              # (b) the shared leading run
    while n < min(len(jp_text), len(us_text), HEAD_CAP) \
            and jp_text[n] == us_text[n]:
        n += 1
    pre = jp_text[:n]
    if (n and not re.search(r'[0-9A-Za-z]', CODE.sub('', pre))
            and CELL.search(CODE.sub('', pre))
            and JP_GLYPH.match(jp_text[n:])
            and re.match(r'[A-Za-z]', us_text[n:])):
        return n
    return 0


def half_head(us_text):
    """How many leading characters of a US record are its head where only a
    HALF-DECODED cell is left of it ('nBeak' -> 1) - the same rule, for the
    records nobody paired: the cell's high byte fell out, its low byte is
    one lower-case letter, and an English wording never begins that way."""
    t = us_text or ''
    m = LEAD_CELLS.match(t)
    i = m.end()
    if i >= len(t) or not t[i].islower():
        return 0                       # the record starts with its own words
    if t[i] == 'i':
        return 0                       # 'iPod', 'iMessage': a word, not a cell
    # THE WORD MUST START RIGHT THERE: the leftover letter is glued to the
    # next word ('nBeak', '畢 nBonecrusher') or stands one space off it
    # ('d Lilim'). Searching on for ANY later capitalised word is how a real
    # sentence got misread ('happiness as a butterfly. Soon,' offered to cut
    # at 'Soon') - a cell is one character, so its words are adjacent.
    rest = t[i + 1:]
    cells = 0                          # more cells can follow the letter
    while cells < len(rest) and CELL.match(rest[cells]):
        cells += 1
    tail = rest[cells:]
    if tail[:1].isupper():
        j = i + 1 + cells
    elif tail[:1] == ' ' and tail[1:2].isupper():
        j = i + 2 + cells
    else:
        return 0
    if not re.match(r'[A-Z][A-Za-z]', t[j:]):
        return 0                       # not a word: nothing to keep after the cut
    if t[i] == 'a' and j > i + 1:
        return 0                       # 'a Thing': a word, not a cell
    return j


def wording_head(jp_text, us_text):
    """The head to cut from a US record of a FIXED field: what the JP twin
    proves, else the half-decoded cell the record still carries."""
    return shared_head(jp_text, us_text) or half_head(us_text)


PSP_HEAD_MARKS = ('＞', '＜', '＾')   # box head, dungeon narration head,
                                     # title mark

# THE PSP NAMEPLATE MARK. The PSP marks a speaker line with its own head
# decoration - '￥N' (units 004F + 00ED, which the extract may spell as the
# raw-unit form '[004f]N'; '￥N＜' in the JP, '￥N' in the US) - then the name
# and the break that ends the nameplate. It is UI decoration like the box-head
# '>', never wording, and NO build ever prints it: every destination has its
# own spelling of the same construct, and that is the only thing this rule
# emits.
#   'ff1b'  the dialogue families' nameplate ('<FF1B>name<FF03>'), which the
#           textbox pipeline turns into the label 'Name:'
#   'label'  the families whose PSX row prints the speaker inline
#           ('<name>：<text>' - the dng boxes), so the English carries
#           'Name: ' where the PSP carried the marker + name + break
# A LONE '￥' is text (a price) and is never touched - only the pair with N
# marks a name.
NAMEPLATE = re.compile(r'(^|<FF0[24]>)\s*(?:￥N|\[004f\]N|\[004f\]\[00ed\])[＞＜]?'
                       r'([^<]*?)<FF03>')


def nameplate(text, form='ff1b'):
    """Re-spell the PSP's speaker nameplate as the destination's own form."""
    def repl(m):
        head, name = m.group(1), m.group(2).strip()
        if form == 'label':
            return head + (name + ': ' if name else '')
        return head + '<FF1B>' + name + '<FF03>'
    return NAMEPLATE.sub(repl, text or '')


# THE NAMEPLATE AT A BOX HEAD, in every spelling the sources use: the code
# form both PSX and PSP-JP carry ('<FF1B>name<FF03>'), the PSP-US raw units
# ('￥Nname<FF03>', '[004f]N...'), and - for a view whose extract already
# dropped the code - the bare 'name<FF03>' head. Parsing a nameplate is
# STRUCTURE (TEXT_LAYOUT_SPEC §4): the name never becomes body text, and a
# porter that needs the speaker reads it here, never with its own regex.
NAMEPLATE_HEAD = re.compile(
    r'^\s*(?:<FF1B>([^<]*)<FF03>'
    r'|(?:￥N|\[004f\]N|\[004f\]\[00ed\])[＞＜]?([^<]*?)<FF03>)')

# A NAME-LIKE HEAD: short, no sentence punctuation. A wrapped sentence that
# happens to cross the break is body text, never a speaker.
NAME_LIKE = re.compile(r'^[^<]{1,24}$')


def label_head(text, bare=False):
    """(speaker, rest) when `text` opens with a nameplate, else ('', text).

    `bare` also accepts the code-less record view ('name<FF03>') when the
    head is name-like - the view port_btlevt/port_btlneg read. The name is
    returned without its marker, colon or break: the caller spells the
    destination's own label."""
    text = text or ''
    m = NAMEPLATE_HEAD.match(text)
    if m:
        return (m.group(1) or m.group(2) or '').strip(), text[m.end():]
    if bare and '<FF03>' in text:
        head, rest = text.split('<FF03>', 1)
        h = head.strip()
        if (h and NAME_LIKE.match(h)
                and not re.search(r'[,!?、。！？…]|\.\.', h)):
            return h, rest
    return '', text


# AN INLINE LABEL AT A LAID-OUT LINE HEAD ('Name: text') - the spelling the
# families whose PSX row writes the speaker inline use (dng, BTLP). The
# label is ONE typographic unit (TEXT_LAYOUT_SPEC §4.2): it never breaks
# apart and the colon never starts the next line.
INLINE_LABEL = re.compile(r'^([^<:]{1,32}?): (?=\S)')


def inline_label(text):
    """(name, rest) when a line opens 'Name: '; else ('', text)."""
    m = INLINE_LABEL.match(text or '')
    if not m:
        return '', text or ''
    return m.group(1), text[m.end():]

# '<FFEF>' and '<FFF5>' are two spellings of the battle families' END (the
# interpreter's own table: references/persona-decomp src/btlp/windowtype.c
# CODE_END2 = 0xEF, CODE_END3 = 0xF5), so a row holds one MESSAGE per
# terminator - they are not line breaks.
MESSAGES = re.compile(r'<FF(?:EF|F5)>')


def messages(text):
    """How many MESSAGES a row holds: one per battle-family terminator."""
    return len(MESSAGES.findall(text or ''))


# THE TABLES SPELL THE MARKS FULLWIDTH ('＞' '＜'), ALWAYS. The ASCII '>' '<'
# is the INJECTION's spelling of them - etext maps the glyph the English font
# carries - so no rule that reads a table may look at '>' or '<' at all: '<'
# opens a code bracket ('<FF04>') and '>' closes it, and both are the
# injection's own output, never the table's furniture.
# (Treating '> ' as a mark in the table text ate the closing bracket of every
# page code - '<FF02><FF04> Flush ...' became '<FF02><FF04 Flush ...' - which
# lost the code and made the rest of the page one over-wide line.)


def head_marks(text, ja):
    """The PSP's head marks ('＞' box head, '＜' dungeon narration head, '＾'
    title mark) - furniture, and the PSX row is the only judge.

    Spelling: a mark is FULLWIDTH in the tables ('＞' '＜' '＾') - a
    character, so no rule can read it as a <code> token - and the injection
    spells it ASCII ('>' and '<', etext), the glyphs the English font
    actually carries.

    The PSP builds open a line with a mark as head furniture ('＞' in the
    US, '＞'/'＾' in the JP, and the dungeon family's narration opens '＜'),
    and the PSX does not: a PSX row shows a mark only where its own bytes
    carry one. So the ONE question is what the PSX row has, asked PER MARK -
      PSX has it   -> keep (the box really draws it)
      PSX lacks it -> delete the PSP's
    A row's Japanese carrying '＞' says nothing about a '＜' it does not
    carry: the poker instruction captions carry both '＜…＞' and '＞…＞' and
    keep both, while a '＜' the Japanese never wrote is furniture.
    The PSP-JP line is deliberately not consulted: a PSP-only mark is
    furniture whether or not the JP build happened to spell the same mark,
    and the PSP-JP line is not resolvable for every family (a dng/ADV
    row's pointer is a box index), so letting it decide would make the
    same PSX row print differently depending on which porter filled it."""
    out = text or ''
    for mark in PSP_HEAD_MARKS:      # a character: never part of a <code>
        if mark in (ja or ''):
            continue                 # the row's own Japanese draws it
        # a mark at a line start takes the space it decorates with it
        out = re.sub(r'(^|<FF[0-9A-F]{2}>|<FFF[0-9A-F]>) ?'
                     + re.escape(mark) + ' ?', r'\1', out)
        out = out.replace(mark, '')
    return out


LAYOUT_CODES = (0xFF02, 0xFF03, 0xFFF6, 0xFFF7)   # page/line moves only
STRIPPABLE = LAYOUT_CODES + (0xFF01,)             # and the terminator
# the subset that BREAKS A SENTENCE across lines/pages: to the reader these
# are whitespace whether the box wraps there or not. 0xFFF6 is btlevt's
# line move - it is whitespace to the reader exactly like <FF03> is.
LAYOUT_BREAK = (0xFF02, 0xFF03, 0xFF04, 0xFFF6)
# Line breaks are REFLOW OUTPUT, not wording. The English wraps at whatever
# width its own words need, so its line count is not the Japanese's and
# never can be: the Japanese broke for a 16px-per-glyph box, the English
# breaks for a VWF one. So these are excluded from every code comparison
# and are the reflow engine's to place, not the porter's.
#
# PAGE AND BOX ADVANCE ARE PRESENTATION TOO. How a text is
# split into boxes is a reading decision, not wording: the Japanese page
# holds 3 lines of 16px glyphs, so a PSP box that read as one screen can
# need two of ours - and a box may scroll ONCE, never four times, so a page
# advance that the Japanese wrote as a bare <FF02> wait becomes a
# <FF02><FF04> new box. Comparing those counts against the Japanese would
# forbid that reflow. What stays structural: an END code
# (FF01/FFEF/FFF5) and every non-layout code.
REFLOW_CODES = (0xFF02, 0xFF03, 0xFF04, 0xFFF6)

_PARAM_TOK = re.compile(r'<([0-9A-Fa-f]{4})>')


def psx_params(text):
    """Spell each PSP control code's parameter units as the raw bytes the
    PSX encoding carries.

    codec renders a code's parameters as glyph words (`<FF05><3C00>`, one
    `<XXXX>` per 2-byte unit - E_PARAM_UNITS). Left as text, the PSX
    encoder writes the six characters '&lt;3C00&gt;' into the box. The
    same two bytes in the PSX form are two `<XX>` tokens (port_story does
    exactly this: `'<FF05><%s><%s>' % (av[4:6], av[6:8])`). A code with no
    parameters (`<FF1B>`'s speaker name) is untouched."""
    import codec
    out = []
    i, n = 0, len(text)
    while i < n:
        m = _PARAM_TOK.match(text, i)
        if not m:
            out.append(text[i])
            i += 1
            continue
        out.append(m.group(0))
        i = m.end()
        c = int(m.group(1), 16)
        if c >> 8 != 0xFF:
            continue
        for _ in range(codec.E_PARAM_UNITS.get(c & 0xFF, 0)):
            p = _PARAM_TOK.match(text, i)
            if not p:
                break
            v = int(p.group(1), 16)
            out.append(f'<{v >> 8:02X}><{v & 0xFF:02X}>')
            i = p.end()
    return ''.join(out)


def fit_codes(text, ja, strict=False):
    """Make the wording carry the Japanese line's control codes, no more.

    The wording comes from the PSP, the codes from the Japanese (descs.py:
    'control codes as in the Japanese'). Two things a PSP line carries that
    a PSX slot does not:

      * a page break the PSP added because its line runs longer - that is
        layout, not wording, and the slot has no such code;
      * the terminator. The PSX extract does not show one and the encoder
        appends its own (btlp's `ff f5`), so a second is a code the
        Japanese does not have.

    Codes the Japanese DOES have are kept, and so is every code that
    carries meaning (a name slot `<FFF8>`, a portrait `<FF1B>`, an EXP
    value) - only layout and terminator codes in EXCESS of the Japanese
    are dropped.

    `strict` is for a fixed one-line field (a name/skill table): the slot
    is not a textbox, so a PSP-only UI marker such as `<FF0C>` cannot be
    shown there. Keep exactly the code tokens the Japanese carries and
    drop every other one."""
    # PSP-ONLY NAMEPLATE HEAD (the two builds agree on the shape): the marker
    # is UI decoration like the box-head '>', never wording - one rule, the
    # function above, spells it as the dialogue family's nameplate.
    text = nameplate(text)
    from port_controls import adapt_buttons
    text = adapt_buttons(text, ja)
    # A '>' the Japanese does not carry is PSP box furniture (most were
    # added for the PSP head markers; the PSX does not draw them), so it
    # does not enter the English. Where the Japanese HAS one, the PSX
    # draws it too - spelled ASCII '>', a real glyph the injection can
    # encode and no rule can mistake for a <code>.
    text = head_marks(text, ja)
    text = stray_jp(text)
    # PSP-ONLY NAME SPANS (the three texts agree): the US build wraps an
    # inline name in <FF18>...<FF18> and gives the opener a 16-bit id
    # (PSP-JP: 「<FF18>院<FF0C><FF18>」 - no id; PSP-US: <FF18><0600>...;
    # PSX: the name spelled inline, no code at all). That is FORMATTING,
    # not wording: drop the span codes and their id params and keep the
    # name the span carries. Real inserts (<FFFA>, <FFF8>) are the same
    # code on all three sides and pass through untouched.
    text = re.sub(r'<FF(18|19|1A)>(?:<[0-9A-F]{2,4}>)*(.*?)(?:<[0-9A-F]{2,4}>)*<FF\1>',
                  r'\2', text)
    # A CONTROL CODE IS ONE CODE. Only parameterized codes
    # (codec.E_PARAM_UNITS) consume following units, and only that many.
    # A bare <FFFB> is a KEY HOLD (windowtype.c CODE_HOLD), not a pause.
    import codec
    CODE_TOK = re.compile(r'<FF([0-9A-F]{2})>')

    def code_toks(t):
        """(code, start, end) per control code, `end` past its own
        parameters. A unit is one <XXXX> or the two <XX> bytes psx_params
        spells it as."""
        out, i = [], 0
        while True:
            m = CODE_TOK.search(t, i)
            if not m:
                return out
            c = int(m.group(1), 16)
            j = m.end()
            for _ in range(codec.E_PARAM_UNITS.get(c, 0)):
                p = re.match(r'<[0-9A-Fa-f]{4}>', t[j:])
                if p:
                    j += p.end()
                    continue
                p = re.match(r'<[0-9A-Fa-f]{2}><[0-9A-Fa-f]{2}>', t[j:])
                if p:
                    j += p.end()
            out.append((m.group(1), m.start(), j))
            i = j

    # LINE BREAKS are reflow output (FF03 the dialogue engines, FF F6 the
    # battle one): they never take part in code pairing - the layout
    # re-places them at its own break points. Pairing them is how a newline
    # came back as the Japanese's insert code.
    REFLOW = ('03', 'F6')
    ja_codes = [c for c, _s, _e in code_toks(ja or '') if c not in REFLOW]
    want = collections.Counter(ja_codes)
    toks = code_toks(text)
    used, keep = collections.Counter(), set()
    for c, start, _end in toks:          # pass 1: codes the Japanese has
        if used[c] < want[c]:
            used[c] += 1
            keep.add(start)
    spare = list(ja_codes)               # pass 2: its unused codes, in order
    for c in list(used.elements()):
        spare.remove(c)
    # pair by KIND, never by raw position: the wording's END code takes the
    # Japanese's END code (FF01 -> FF EF), its pause takes the Japanese's
    # pause - otherwise a beat's insert lands where an ending was.
    # FF F7 is a 12-frame pause and FF FB is a KEY HOLD (windowtype.c:
    # CODE_PAUSE / CODE_HOLD) - the two halves of the page skeleton. They
    # are never a substitute for a dropped pause: a bare FF FB would stop
    # the box for a button mid-sentence.
    KIND = {'01': 'end', 'EF': 'end', 'F5': 'end',
            '02': 'wait', '05': 'wait', 'FC': 'wait',
            'F7': 'hold', 'FB': 'hold',
            '18': 'ins', '19': 'ins', '1A': 'ins', '07': 'ins', '08': 'ins',
            '0F': 'ins', 'F0': 'ins', 'F2': 'ins', 'F3': 'ins', 'F4': 'ins',
            'F8': 'ins', 'F9': 'ins', 'FA': 'ins',
            '0E': 'choice', 'F1': 'choice',
            '06': 'attr', 'FE': 'attr'}

    def take_spare(kind):
        for c in spare:
            if KIND.get(c, c) == kind:
                spare.remove(c)
                return '<FF%s>' % c
        return ''
    out, i = [], 0
    # The family translation only applies when the DESTINATION is the
    # battle family (the Japanese carries its codes): for a dialogue
    # destination the wording's codes are that family's own and pass
    # through untouched - no special treatment for any box.
    battle = bool(re.search(r'<FFF[0-9A-F]>', ja or ''))
    # A NAMEPLATE IS STRUCTURE BOTH BUILDS NEED (see fit_codes' head: the PSP
    # spells it ￥N+name, the PSX <FF1B>name<FF03>), so it is never paired
    # against the Japanese and never dropped: the PSX's box DOES draw a name
    # there while its Japanese line carries none. The textbox pipeline turns
    # the kept code into 'Name: ', separate from the body wording.
    STRUCT = ('1B',)
    for c, start, end in toks:
        out.append(text[i:start])
        if not battle or c in REFLOW or c in STRUCT or KIND.get(c) == 'ins':
            out.append(text[start:end])  # own family / structure / reflow
        elif start in keep:
            out.append(text[start:end])
        else:
            repl = take_spare(KIND.get(c, c))
            # a dropped code keeps its word gap: 'death<FF05>warmed' must
            # never run together into 'deathwarmed'
            out.append(repl or ' ')
        i = end
    out.append(text[i:])
    text = re.sub(r'  +', ' ', ''.join(out))
    # ... is not automatically an ellipsis - a dot run has its own uses and
    # those are ported as written. But a run that TRAILS OFF is one, and
    # the game prints an ellipsis for it: the Japanese has '…' exactly
    # there. So a run closing the line becomes the character that means
    # that; the English font carries its glyph.
    text = re.sub(r'\.\.\.(?=\s*(?:<FF0[1234]>|$))', '…', text)
    # '[00]' is the odd-length trailing byte the extractor could not map -
    # an artefact of the extraction, never wording. After an end code it
    # also breaks the family's 'exactly one end code' rule.
    text = re.sub(r'\[00\]\s*$', '', text)
    # ...and exactly ONE end code, ever. A doubled terminator is the same
    # bug the talk checker calls out ('must end with exactly one end code')
    # and it also breaks bpe: the unpacker stops at the first one and the
    # round trip then loses whatever follows.
    text = re.sub(r'(<FFF5>|<FFEF>)(?:\s*(?:<FFF5>|<FFEF>))+', r'\1', text)
    import boot_pairs
    want = collections.Counter(boot_pairs.skeleton(ja)[0])
    have = collections.Counter(boot_pairs.skeleton(text)[0])
    # REFLOW_CODES are reflow output and belong to NO comparison - the rule
    # codes_match already enforces. Counting them here made every pass drop
    # one break the layout had just placed and leave its space behind, so a
    # row grew a space per pass.
    over = {c: have[c] - want[c] for c in have
            if have[c] > want[c] and c not in REFLOW_CODES}
    tok = re.compile(r'<([0-9A-Fa-f]{4})>')

    def sub(m):
        c = int(m.group(1), 16)
        if c in STRIPPABLE and over.get(c, 0) > 0:
            # A SPEAKER's break is structural, not layout: `<FF1B>Name<FF03>`
            # is the nameplate and the break that ends it. Dropping that one
            # fuses the name onto the line. Keep it and drop a later one.
            head = m.string[:m.start()]
            if re.search(r'<FF1B>[^<]*$', head):
                return m.group(0)
            over[c] -= 1
            # A layout code that separates WORDS still separates them when
            # it is gone: dropping a newline must not produce 'seems to
            # beclosed'. A newline or page break is a space to the reader
            # whatever the box does, so that is what it becomes.
            if c in LAYOUT_BREAK:
                a = m.string[m.start() - 1:m.start()]
                b = m.string[m.end():m.end() + 1]
                if a and b and not a.isspace() and not b.isspace():
                    return ' '
            return ''
        return m.group(0)
    out = tok.sub(sub, text)
    if strict:
        allowed = {c.upper() for c in re.findall(r'<([0-9A-Fa-f]{4})>', ja)}

        def strict_sub(m):
            if m.group(1).upper() in allowed:
                return m.group(0)
            c = int(m.group(1), 16)
            if c in LAYOUT_BREAK:
                a = m.string[m.start() - 1:m.start()]
                b = m.string[m.end():m.end() + 1]
                if a and b and not a.isspace() and not b.isspace():
                    return ' '
            return ''
        out = tok.sub(strict_sub, out)
    return psx_params(out)


def codes_match(en, ja):
    """Does this wording carry the Japanese line's control codes - exactly?

    The rule every family builder enforces (btlp.py fails loud on 'control
    codes differ from the Japanese'). The multiset is what counts, not the
    order: btlp's own `codes()` sorts. Two things are excluded because
    they are not the wording's to carry: the TERMINATOR (the encoder
    appends its own) and LINE BREAKS (reflow output - see REFLOW_CODES).

    A difference the port is ALLOWED to make is not a mismatch: the QA's
    own deviation gate (tstatus.classify_deviations - name slots the PSP
    reorders or drops, a choice the PSP adds, the card close) is the one
    place that decides, and both the porter and the QA read it."""
    import boot_pairs

    # Dialogue name opcodes have no meaning in the battle interpreter. Keep
    # the source token for diagnosis, but do not let a deviation exemption
    # turn it into shippable battle text without a proven translation.
    if re.search(r'<FFF[0-9A-F]>', ja or '') and re.search(
            r'<FF(?:07|08|0F|10)>', en or ''):
        return False

    # The terminator is the encoder's, and END codes are STRUCTURE, never a
    # deviation: a string holds exactly one, because the unpacker stops at
    # the first and drops the rest of the box (a second end code is how a
    # mispaired source showed up as 'shipping'). So exactly one each, and
    # the codes that remain must be the Japanese line's.
    ENDS = (0xFF01, 0xFFEF, 0xFFF5)

    def tail(c):
        c = [x for x in c if x not in REFLOW_CODES]
        return [x for x in c if x in ENDS], c
    (_ea, a), (_eb, b) = tail(boot_pairs.skeleton(en)[0]), tail(boot_pairs.skeleton(ja)[0])
    # A string carries AT MOST one end code: a second one stops the
    # unpacker mid-string and drops the rest of the box. How many the
    # wording carries is the encoder's business, not the row's - the
    # encoder appends its own - so it takes no part in the comparison.
    if len(_ea) > 1:
        return False
    if sorted(x for x in a if x not in ENDS) == sorted(x for x in b if x not in ENDS):
        return True
    import tstatus
    return bool(tstatus.classify_deviations(ja, en)[1])


def enc_len(text):
    """How many bytes a line takes in the game's dialogue encoding - the
    size every family's buffer is counted in (btlp: 'msg 40 has no
    reference and must fit 20 bytes'). Falls back to character count for
    anything the encoder refuses, which is only ever stricter."""
    import etext
    try:
        return len(etext.encode(text, end=None)) + 1
    except Exception:
        return len(text)


def box_gate(rel, ja, en):
    """What the box cannot SHOW: the family's own display budget - the
    width/line errors its builder's check reports. Codes are NOT here;
    those are codes_match's business (and the port may legitimately
    reorder or drop name slots). Empty means the row displays."""
    if rel.startswith('TALK'):
        import talk
        return [e for e in talk._qa(ja, en)
                if re.match(r'^\d+ (px:|lines)', e)]
    import tstatus
    return [f'{k}: {m}' for k, m in tstatus.check(ja, en, want_label=None)
            if k == 'width']


def dest_check(rel, ja, en):
    """The DESTINATION's own refusal list for a row, where the builder that
    will inject it has a checker: talk.py's _qa for a TALK unit/answer is
    literally the function the build drops rows with, so asking it here is
    the only way 'clean in the table' can mean 'ships in the disc'.

    Families without their own checker return [] - their gates are
    codes_match (the skeleton) and port_caps.dest_note (the box)."""
    if rel.startswith('TALK/') and (ja or '').strip():
        import talk
        return talk._qa(ja, en)
    return []


def derive(text, ja, rel, pos=''):
    """THE derivation, one call for every porter on its first pass: the
    wording's codes in the destination's spelling, laid out at the box,
    and the honest reason when it cannot ship (or '' when it does)."""
    if not port_caps.has_label_row(rel, pos) and '<FF1B>' not in (ja or ''):
        # A destination with no label row (the ADV message viewport) never
        # draws the PSP's nameplate: drop it with its name and break, which
        # are UI structure, not wording.
        _label, text = label_head(text)
    raw = fit_codes(text, ja, strict=port_caps.is_fixed_field(rel, pos))
    laid = lay_out(raw, rel, ja, pos)
    if HOLES.search(ink_of(laid or raw)):   # ink: <FFFD> params are the
                                            # engine's own glyphs, not wording
        return laid or raw, JAPANESE_REMNANT
    if not laid:
        return raw, unlayable_note(raw) or 'does not fit the box'
    if not codes_match(laid, ja):
        return laid, 'codes differ from the Japanese'
    # ONE MESSAGE IN, ONE MESSAGE OUT. Both directions ship wrong text, and
    # both are the same mismatch, so it is checked here - where every porter,
    # the leftover net and the renorm all pass - and not in any one of them:
    #   too few  - the composition stops at the row's first terminator and
    #              drops the rest (map idx 34: "a card was stuck to the spell
    #              card" then "obtained Vishnu's Avatar", whose PSP units sit
    #              in the REVERSE order in the US build, so gluing them by
    #              address composes the second message only);
    #   too many - several PSP units are glued into one row, so a terminator
    #              sits mid-string: the engine ends the line there and the rest
    #              never draws, and the row is unbuildable (idx 279, a "………"
    #              row whose recorded source is a whole menu: 'No<FFF5> Yes…').
    if rel == 'BTLP' and messages(ja) != messages(laid):
        return laid, (f'source mismatch: the row holds {messages(ja)} '
                      f'message(s), the composition {messages(laid)}')
    # THE DESTINATION'S OWN CHECK COMES FIRST: a row its builder refuses is
    # a row that does not ship, whatever this side thinks of it. Its words are already
    # the gate's own (which code, which line), never a bare verdict.
    why = '; '.join(dest_check(rel, ja, laid)) or \
        port_caps.dest_note(laid, rel, pos, ja)
    if not why:
        # the gate's own words - which line, how many px, which budget -
        # never a bare verdict. A draft that says only 'does not fit' is
        # unauditable.
        gate = box_gate(rel, ja, laid)
        if gate:
            why = '; '.join(gate)
    return laid, why


def _renorm_rel(rel):
    """The renorm of ONE file - its own process, its own result count.
    Files are independent (each writes its own generated rows), so the
    derivation is CPU-bound and runs in parallel."""
    changed = 0
    ja_of = toolbelt.psx_text_of(rel)
    rows = toolbelt.read_generated(rel, optional=True)
    dirty = False
    drop = []
    # A POINTER SHARED BY SEVERAL ROWS DOES NOT NAME A LINE. The PSP keeps a
    # menu as ONE unit ('No<FFF5> Yes<FFF5>Ignore<FFF5> Answer<FFF5>...') and
    # the mapping names each row by unit + item; the stored `psp` is the unit,
    # so re-deriving from it glues the whole menu into every row that came from
    # it (measured: 8 negotiation rows, and the result is unbuildable - an
    # interior terminator ends the string). Those rows are the family porter's
    # business (it knows the item), and this net only repairs what a pointer
    # can prove.
    _shared = collections.Counter((r.get('psp') or '').strip() for r in rows
                                  if (r.get('en') or '').strip())
    for r in rows:
        cur = (r.get('en') or '')
        if not cur.strip():
            continue
        # A CARD (<FF06> frame) is built by port_story's card path, which knows
        # the nameplate from the description. Re-deriving it from the wording
        # through the dialogue pipeline turned the name into a speaker LABEL
        # and gave it a colon that exists in neither script (ADV/E0 #61).
        if cur.lstrip().startswith('<FF06>'):
            continue
        ja = ja_of.get(r['pos'], '')
        # THE PSP'S HEAD MARKS ARE FURNITURE and only the PSX row's own bytes
        # can justify one (head_marks), so a stored row can lose a mark with no
        # source at all. It happens here, in the pass that owns 'generated is
        # derived data', because a row whose pointer names a family box index
        # is never re-derived and would otherwise keep the mark for ever.
        mark = head_marks(cur, ja)
        if mark != cur:
            r['en'] = cur = mark
            dirty = True
            changed += 1
        psp = (r.get('psp') or '').strip()
        if psp and _shared[psp] > 1:
            continue                      # one unit, several rows (see above)
        draft = toolbelt.psp_wording(psp)
        if not draft and ',' in psp:
            draft = toolbelt.psp_wording(psp.split(',', 1)[0])
        if draft:
            # THE RECORD HEAD, the same one rule as place() (wording_head):
            # only the head the US record itself still proves is cut here.
            # The renorm runs from PSX + PSP-US data alone, so it cannot
            # consult the JP twin; a head only the twin proves was cut when
            # the row was written.
            if port_caps.is_fixed_field(rel, r['pos']):
                draft = draft[wording_head('', draft):]
                if ink_of(draft) != ink_of(cur):
                    # A head only the JP twin could prove is still on the
                    # source; re-deriving would put furniture back into a row
                    # that was written without it. Keep the row as written.
                    continue
        if not draft:
            # NO SOURCE, NOTHING TO RE-DERIVE (a textbox whose pointer names
            # the family porter's own box index, a merged row). Re-laying out
            # the CURRENT text is not the source's layout and is not even
            # stable: vwf_wrap re-places a break across a <FF0F> name
            # variable each time. The family porter
            # owns those rows and re-derives them from the PSP box every
            # run - this net only re-derives what a pointer can prove.
            continue
        if HOLES.search(ink_of(cur)):       # ink: FFFD params are not wording
            # Japanese left in an en cell is never a translation: the
            # row is withdrawn and stays untranslated
            drop.append(r)
            changed += 1
            continue
        import match_jp       # lazy: the pair map is the matching layer's
        laid, why = derive(draft, ja, rel, r['pos'])
        if why or laid == cur:
            continue
        # THE RENORM NEVER LOSES A WORD. A derivation that drops text is a
        # defect in the pipeline, not a new layout. Keep the row and report
        # the dropped words.
        _w_cur = set(re.sub(r'<[^>]+>', ' ', cur).split())
        _w_new = set(re.sub(r'<[^>]+>', ' ', laid).split())
        if _w_cur - _w_new:
            print(f'renorm: {rel} {r["pos"]}: derivation DROPS '
                  f'{sorted(_w_cur - _w_new)[:4]} - row kept')
            continue
        if ink_of(laid) == ink_of(cur):
            # SAME WORDING, ANOTHER LAYOUT: the LAYOUT is derived data too.
            # Both sides come
            # from derive(), so they cannot disagree; the check below only
            # refuses a layout that does not re-derive to itself (the flow
            # is not idempotent across a name insert).
            if INSERTS.search(laid):
                again, _w = derive(laid, ja, rel, r['pos'])
                if again != laid:
                    continue
            r['en'] = laid
            dirty = True
            changed += 1
            continue
        r['en'] = laid
        dirty = True
        changed += 1
    if drop:
        rows = [r for r in rows if r not in drop]
        dirty = True
    if drop:
        # a withdrawal REMOVES the row: upsert only merges, so the full
        # list is written directly
        toolbelt.write_generated(rel, rows)
    elif dirty:
        toolbelt.upsert_generated(rel, rows)
    return changed


# THE TABLES NO FAMILY PORTER CLAIMS. port.py's porter table is the authority
# for who writes what; these string banks are the leftovers this net
# exists for. Re-deriving a PORTER'S rows here is a contract violation (the
# charter in port.py: "This phase must never rewrite one of their rows"): a
# second derivation path may disagree with the porter's own.
LAST_RESORT_TABLES = ('ADV', 'DNG')   # CASINO has its own complete-prize porter


def renorm_generated(rels=None):
    """Re-derive the LEFTOVER rows (LAST_RESORT_TABLES) from their `psp`
    source through the shared pipeline. Generated is DERIVED data. The source
    is the truth; a merged row (no single source) keeps its wording and only re-lays it
    out. A derivation that fails a gate never replaces a shipped row - the
    row keeps its `en` and the sweeps re-park it. Nothing types wording.
    Files derive in PARALLEL (each is its own process, each writes only
    its own rows): the derivation is CPU-bound and the port is not."""
    rels = list(rels) if rels is not None else [r for r in toolbelt.psx_rels()
                                                if r in LAST_RESORT_TABLES]
    try:
        import concurrent.futures as futures
        with futures.ProcessPoolExecutor() as pool:
            return sum(pool.map(_renorm_rel, rels))
    except Exception:
        # a platform without fork still works, just slower
        return sum(map(_renorm_rel, rels))
