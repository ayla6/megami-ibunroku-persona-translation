"""Port PSP-US TALK text into PSX TALK skeletons (talktl-compatible TSV rows).

The English is the PSP-US unit (same unit index - counts are identical across
all three versions), its codes TRANSLATED to the PSX battle box: the shared
ones (name inserts, voices, the choice prompt, the answer prompt and its
param byte) stay where the US line has them; its line breaks are reflowed
and its new-box (FF02 FF04) becomes the box's page turn (FFFB FFF7). Only the
end code comes from the PSX unit. The Japanese contributes no other code.

  python src/extraction_tools/matching/port_talk.py [NAME [max_units]]

Writes translation/generated/TALK/<NAME>.tsv (PSX target, PSP-US port, errors).
"""
import glob
import os
import re
import struct
import sys

# Deterministic output: set/dict iteration order otherwise leaks the
# per-process hash seed into row content. Same seed as build.py.
# Seed re-exec ONLY as a script: an import must never hijack the host
# process.
if __name__ == '__main__' and os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    os.execvpe(sys.executable, [sys.executable] + sys.argv, os.environ)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
import toolbelt  # noqa: E402
import etext  # noqa: E402
import vwf_wrap  # noqa: E402
from talk import Talk  # noqa: E402
import talk as talkbuild  # noqa: E402  (the build's own acceptance gate)
import talktl  # noqa: E402
from codec import US_MAP  # noqa: E402

PSX = os.path.join(ROOT, 'data', 'psx', 'TALK')
PUS = os.path.join(ROOT, 'data', 'psp_us', 'PSP_GAME', 'USRDIR', 'pack', 'talk')
OUTDIR = os.path.join(ROOT, 'translation', 'generated', 'TALK')

TOKEN = re.compile(r'<FF[0-9A-F]{2,4}>')


def frag_join(a, b):
    """Glue two spaceless unit-boundary fragments, or None when they are
    separate sentences. Spaces at true word gaps always survive as space
    bytes (trailing/leading), so a spaceless abutment is a split word
    (staring, Karma, YOU, 741953852741) -- except terminal punct + an
    uppercase start, which is a sentence boundary the authoring left
    spaceless in 4/8504 cases (Ahahahahaha! I, ... Well,)."""
    if a and a[-1] in '.!?' and b and b[0].isupper():
        return None
    return a + b


def psp_unit_spans(path):
    """[(start, bytes)] of the PSP talk units (the extract's anchors)."""
    d = open(path, 'rb').read()
    hdr = list(struct.unpack('<5I', d[:20]))
    b0 = hdr[0]
    offs = []
    i = b0
    while True:
        v = struct.unpack('<I', d[i:i + 4])[0]
        if v == 0xFFFFFFFF:
            break
        offs.append(v)
        i += 4
    starts = [o + b0 for o in offs]
    ends = starts[1:] + [hdr[1]]
    return [(s, bytes(d[s:t])) for s, t in zip(starts, ends)]


def psp_units_raw(path):
    return [b for _s, b in psp_unit_spans(path)]


SKIPPED = []
# voices (windowtype.c CODE_VOICE_LO..HI) and the choice prompt: codes the
# PSP-US talk text uses exactly as the PSX battle box does
KEPT_CODES = (0xEB, 0xEC, 0xED, 0xEE, 0xF1)


def psp_split(seg, glyphs=None, mark_dropped=False):
    """Head/stray words plus whether a region ends mid-word (open fragment).
    Returns (head, stray, open_stray, head_start_space, breaks, open_head,
    stray_breaks): breaks are [(head-word index, code)] for PSP pagination
    (FF02 wait / FF04 page) in the live head region, stray_breaks the same
    for the stray tail (the next message's turns ride there: ETC dots +
    turns + text after the end code). open_head is true when the head ends
    mid-word with no end code (a long message sliced across units:
    DOPPEL yo|u, m|ust); the main loop glues it to the next head, mirroring
    the stray tail join. Line breaks (FF03) merge into the width flow, glued
    spaceless after '-' (PSP hyphen wraps); PSP lines target a wider box.
    Breaks past the end code with no text after them are dead data.
    Unknown codes (FFEB/FFEC/FFED/FFEE/...) are dropped, never invented.
    Unknown codes (FFEB/FFEC/FFED/FFEE/...) are dropped, never invented.
    glyphs maps BE words to chars (default US_MAP; JP passes its map).
    mark_dropped=True (display caches ONLY, never the porter): skipped
    params/unknowns render inline as [fffd:xxxx]/[xxxx] instead of
    vanishing, so extracts show every byte the box contains."""
    def words_of(units):
        words, cur = [], ''
        for u in units:
            if u == SPACE:
                if cur:
                    words.append(cur)
                    cur = ''
            else:
                cur += u
        if cur:
            words.append(cur)
        return words

    if glyphs is None:
        glyphs = US_MAP
    head, stray = [], []
    breaks = []
    sbreaks = []
    cur = ''
    i = 0
    n = len(seg)
    in_stray = False
    stray_end_count = None
    head_ended = False
    head_started = False
    head_start_space = False

    def emit():
        nonlocal cur
        if cur:
            (stray if in_stray else head).append(cur.replace('…', '...'))
            cur = ''

    while i + 1 < n:
        if seg[i] == 0xFF:
            op = seg[i + 1]
            i += 2
            if op in (0xF5, 0xEF):
                emit()
                if in_stray:
                    if stray:
                        stray_end_count = len(stray)
                    # an end with no text since the last end closes an EMPTY
                    # message (dead data: JA WORM has <FFF1><FFF5><FFF1><FFF5>):
                    # its codes start nothing, so they do not ride into the
                    # next message
                    while stray and not re.sub(r'<FFFD>.|<FF[0-9A-F]{2}>', '', stray[-1]):
                        stray.pop()
                else:
                    head_ended = True
                in_stray = True
                # Messages re-align even after the end code: a voice code
                # (FFFD + 1 param byte) flips parity, so the authoring pads
                # one 00 here (SYOUJO/115, BASKET/55). Without the skip the
                # next word's lead byte is eaten (You're -> ou're).
                if i % 2 == 1 and i < n and seg[i] == 0x00:
                    i += 1
                continue
            if op in (0x02, 0x04):
                emit()
                if in_stray:
                    sbreaks.append((len(stray), op))
                else:
                    breaks.append((len(head), op))
                continue
            if op == 0x03:
                # A PSP line break is layout for its wider box, not content.
                # After '-' it kept no space (super-star, look-at-my-...: all
                # 24 hyphen-FF03 sites in PSP-US TALK rejoin spaceless), while
                # a break at a word gap consumed the space (ballin' skills).
                if cur.endswith('-'):
                    continue
                emit()
                continue
            if op == 0x1B:
                while i + 1 < n and seg[i] != 0xFF:
                    i += 2
            elif op == 0x18:
                i += 2
            elif ('<FF%02X>' % op) in talktl.INSERTS or op in KEPT_CODES:
                # THE PSP LINE'S OWN CODES (the battle box runs the same set):
                # a name insert, a voice, the choice prompt - kept in the
                # word where the US line put it, never the Japanese's
                cur += '<FF%02X>' % op
                if not in_stray:
                    head_started = True
                continue
            elif op == 0xFD:
                # the answer prompt and its ONE param byte - the answer
                # list's index, the same byte in the PSX (ff fd PP ff f5;
                # i += 4 ate the FFF5 end code, leaking the next message's
                # words into head: SYOUJO stari|ng, who'|s). Kept, its byte
                # spelled the way the PSX text spells it (etext.decode).
                if i < n:
                    cur += ('[fffd:%02x]' % seg[i] if mark_dropped
                            else '<FFFD>' + etext.decode(bytes([seg[i]])))
                    if not in_stray:
                        head_started = True
                i += 1
                continue
            emit()
            continue
        u = struct.unpack_from('>H', seg, i)[0]
        i += 2
        ch = glyphs.get(u, '')
        if ch == ' ':
            if not in_stray and not head_started:
                head_start_space = True
            if cur:
                (stray if in_stray else head).append(cur.replace('…', '...'))
                cur = ''
        elif ch:
            cur += ch
            if not in_stray:
                head_started = True
        elif mark_dropped:
            cur += '[%04x]' % u
            if not in_stray:
                head_started = True
        else:
            SKIPPED.append(u)
    open_stray = bool(cur and in_stray)
    open_head = bool(cur and not in_stray)
    emit()
    return (head, stray, open_stray, head_start_space, breaks, open_head,
            sbreaks, stray_end_count is not None and stray_end_count == len(stray),
            head_ended)


def psx_slots(ja):
    """Split a PSX-JA unit into (kind, value) slots: text runs and codes.
    Returns (slots, endcode). FFFD keeps its param char. Text after the first
    end code is dead data (strays) and is dropped, like talktl.check."""
    cut = [ja.index(c) + len(c) for c in ('<FFF5>', '<FFEF>') if c in ja]
    if cut:
        ja = ja[:min(cut)]
    slots = []
    pos = 0
    for m in TOKEN.finditer(ja):
        if m.start() > pos:
            slots.append(('text', ja[pos:m.start()]))
        c = m.group(0)
        if c == '<FFFD>':
            p = ja[m.end():m.end() + 1]
            slots.append(('code', c + p))
        else:
            slots.append(('code', c))
        pos = m.end()
    if pos < len(ja):
        slots.append(('text', ja[pos:]))
    end = ''
    if slots and slots[-1][0] == 'code' and slots[-1][1] in ('<FFF5>', '<FFEF>'):
        end = slots.pop()[1]
    return slots, end


def reflow(words, slots, end, breaks=None):
    """Fill text slots with words; FFF6 = fresh wrap, FFFC kept in place,
    other codes pinned. breaks = {word index: [FF02/FF04]}: PSP page turns
    fire before that word (as FFFB FFF7); PSP owns pagination, JA page
    breaks never enter. Width via talktl. The wrapping policy lives in
    vwf_wrap.flow_lines; this only builds the item stream (all words flow
    in the first text run, JA codes pin after in slot order, PSP page
    turns fire at their word indices)."""
    # flatten text with explicit wrap points from FFF6 slots
    breaks = breaks or {}

    def width(s):
        # talktl widths: demon/race/member/item/card tokens count at their
        # inserted widths (vwf_wrap alone measures them as zero and the
        # line overflows in game once the name renders).
        return talktl.width(s)

    items = []
    wi = 0
    for kind, val in slots:
        if kind == 'code':
            # Structure (<FFF6> line, <FFFB><FFF7> page) breaks the line and
            # pins verbatim; every other code is INLINE - it renders at the
            # pen and its width counts, so it rides the flow glued to the text
            # around it (never a gap, never a line of its own). Codes pin
            # after the words in slot order either way.
            items.append(('b', val) if val in ('<FFF6>', '<FFFB>', '<FFF7>')
                         else ('g', val))
        else:
            # estimate how many words fit if this were one line: we just
            # append words while they fit, emitting FFF6 wraps as needed.
            # A PSP page turn fires before its word (flushing the line).
            while wi < len(words):
                if wi in breaks:
                    for _op in breaks[wi]:
                        items.append(('b', '<FFFB>'))
                        items.append(('b', '<FFF7>'))
                items.append(('w', words[wi]))
                wi += 1
            # leftover cur flushed at next code/end
    out = vwf_wrap.flow_lines(items, 239, width, '<FFF6>')
    # drop trailing empty wrappers, build string
    s = _ride_last_line(''.join(v for _, v in out))
    # FFFC handling: talktl needs same COUNT as ja (movable). Count ours:
    return s + end, wi


def _over_reason(errs):
    """The worklist reason for a draft the box cannot show, in the shared
    over-limit format where it is a size (toolbelt.note_over); any other QA
    refusal keeps talktl's own words."""
    import toolbelt
    widths = [int(m.group(1)) for m in re.finditer(r'(\d+) px:', errs)]
    lines = [int(m.group(1)) for m in re.finditer(r'(\d+) lines \(max', errs)]
    if widths:
        return toolbelt.note_over(max(widths), vwf_wrap.BOX_WIDTH)
    if lines:
        return toolbelt.note_over(max(lines), 3, 'lines')
    return errs


def _ride_last_line(s):
    """The Japanese codes pin after the words (reflow), so its line breaks
    land behind the last word with nothing to show: '…huh?<FFF6><FFFC>' is
    a fourth line holding a wait, and after three full lines the engine
    reads that <FFF6> as 'box full - wait for a key, clear' - an empty box.
    A line or page break after the last VISIBLE thing (text, or an insert
    that prints a name) makes no line: the codes after it ride on the last
    line, in order."""
    last = 0
    pos = 0
    for m in re.finditer(r'<FFFD>.|' + TOKEN.pattern, s):   # FFFD: one param char
        if s[pos:m.start()].strip() or m.group(0) in talktl.INSERTS:
            last = m.end() if m.group(0) in talktl.INSERTS else m.start()
        pos = m.end()
    if s[pos:].strip():
        return s
    tail = re.sub(r'<FFF6>|<FFFB><FFF7>|<FFFB>|<FFF7>', '', s[last:])
    return s[:last] + tail


def _repaginate_lines(lines):
    """DP-split one page's FFF6-lines (no page breaks inside) into <=3-line
    pages. Returns None when no split is needed/possible."""
    n = len(lines)
    if n <= 3:
        return None

    def cost(i):
        """cost of ending a page after lines[i] (i is not the last line)."""
        tail = re.sub(r'<[^>]+>', '', lines[i])[-12:]
        if re.search(r'[.!?~]"?$', tail):
            return 0
        if re.search(r'[,;:—-]$', tail):
            return 2
        return 5

    from functools import lru_cache

    @lru_cache(maxsize=None)
    def best(start):
        """(pages, cost, breaks) splitting lines[start:] into <=3-line pages.
        FEWEST PAGES FIRST (TEXT_LAYOUT_SPEC section 2, rule 1: a break is
        only ever placed to fit the box); among splits with as few pages,
        the lowest cost - sentence ends, then clause ends, no one-line
        final page."""
        if n - start <= 3:
            return (1, 0 if n - start > 1 or start == 0 else 3, ())
        res = None
        for end in range(start + 1, min(start + 3, n - 1)):
            sub = best(end + 1)
            c = (sub[0] + 1, cost(end) + sub[1], (end,) + sub[2])
            if res is None or c[:2] < res[:2]:
                res = c
        return res

    r = best(0)
    pages, prev = [], 0
    for b in r[2]:
        pages.append(lines[prev:b + 1])
        prev = b + 1
    pages.append(lines[prev:])
    return pages


def repaginate(en):
    """Split over-long pages into <=3-line pages (each <=239 px), operating
    per page so existing (JA-proportioned or PSP) page turns are respected;
    new breaks prefer sentence ends and avoid orphans. Only page breaks and
    FFF6 wraps are added."""
    out = []
    for pg in en.split('<FFFB><FFF7>'):
        lines = [ln for ln in pg.split('<FFF6>') if ln != '']
        if len(lines) <= 3:
            out.append('<FFF6>'.join(lines))
        else:
            sub = _repaginate_lines(lines) or [lines]
            out.append('<FFFB><FFF7>'.join('<FFF6>'.join(p) for p in sub))
    return '<FFFB><FFF7>'.join(out)


def main(name, max_units=None, verbose=True):
    name = name.upper()
    t = Talk(name, open(os.path.join(PSX, f'{name}.BIN'), 'rb').read())
    praw = psp_units_raw(os.path.join(PUS, f'{name}.BIN'))
    import toolbelt
    # THE PSP SOURCE of every unit, keyed by its own start: the pointer a
    # generated row carries is where its wording came from (docs/
    # TEXT_ARCHITECTURE.md) - a row without it is unprovenance, so every
    # row this porter writes names its unit, shipped or parked.
    uspans = psp_unit_spans(os.path.join(PUS, f'{name}.BIN'))
    usrows = {r['pos']: r for r in toolbelt.read_extracted(
        'psp_us', f'pack/talk/{name}', optional=True) or []}
    usptr = {}
    for k, (s, _b) in enumerate(uspans):
        if hex(s) in usrows:
            usptr[k] = f'pack/talk/{name}:{hex(s)}'
    if not t.ok or not t.units:
        print(f'{name}: PSX TALK file uses a special layout; skipped by the standard port')
        return
    if len(t.units) != len(praw):
        print(f'{name}: PSX/PSP unit-count mismatch ({len(t.units)} vs {len(praw)}); skipped')
        return
    # A DEAD PSX UNIT (its Japanese is the end code alone) shows nothing, so
    # the PSP bytes cut at its index are no line of their own: they are the
    # stream that runs on from the unit before - the tail of a speaker
    # nameplate (<FF1B>Pyro Ja|ck<FF03>), the middle of a word ('T|is w|ell).
    # The units are contiguous slices of one stream, so appending them to the
    # last live unit is byte-exact, and every split/join rule below joins
    # across the dead unit as if it were not there (`live[k]`: the unit the
    # stream reaches k from) instead of losing the piece with it.
    praw = list(praw)
    # The first pointer, like all the others, may point inside the first
    # message. Its prefix follows the FF-filled pointer-table padding.
    with open(os.path.join(PUS, f'{name}.BIN'), 'rb') as f:
        data = f.read()
    first = uspans[0][0]
    padding = list(re.finditer(b'\xff{16,}', data[:first]))
    start = padding[-1].end() if padding else first
    start &= ~1
    praw[0] = data[start:first] + praw[0]
    # A UNIT CUT INSIDE A CODE: the answer prompt (FFFD) takes one param byte,
    # and a unit can end on FF FD with its param starting the next (BASKET
    # 54|55). The bytes are one stream, so the code moves to the unit its
    # param is in - read apart, the param byte decodes as a glyph.
    for k in range(len(praw) - 1):
        if praw[k][-2:] == b'\xff\xfd':
            praw[k], praw[k + 1] = praw[k][:-2], praw[k][-2:] + praw[k + 1]
    live, last = [], None
    for k in range(len(t.units)):
        live.append(last)
        if talkbuild.dead_unit(t.units[k]):
            if last is not None:
                praw[last], praw[k] = praw[last] + praw[k], b''
        else:
            last = k
    n = len(t.units) if max_units is None else min(int(max_units), len(t.units))
    rows = []
    ok = 0
    heads, strays, open_strays, head_spaces, unit_breaks = [], [], [], [], []
    open_heads, stray_breaks, stray_ended, head_ended = [], [], [], []
    for k in range(n):
        h, s, open_tail, leading_space, br, open_head, sbr, ended, hend = psp_split(praw[k])
        heads.append(h)
        strays.append(s)
        open_strays.append(open_tail)
        head_spaces.append(leading_space)
        unit_breaks.append(br)
        open_heads.append(open_head)
        stray_breaks.append(sbr)
        stray_ended.append(ended)
        head_ended.append(hend)
    # A complete message can sit entirely in the previous slice's tail.
    # If this slice then starts the following, still-open message, carry that
    # head forward instead of appending it after the already-ended message.
    for k in range(1, n):
        j = live[k]
        if (j is not None and stray_ended[j] and not head_ended[k]
                and heads[k] and not strays[k]):
            strays[k], heads[k] = heads[k], []
            open_strays[k], open_heads[k] = open_heads[k], False
            stray_breaks[k], unit_breaks[k] = unit_breaks[k], []
    # A head ending mid-word (no end code: a long message sliced across
    # units) continues in the next unit's head (DOPPEL yo|u, m|ust): glue it
    # forward, mirroring the stray tail join below. The glued word keeps
    # index 0, so unit k's break indices still address the same words.
    for k in range(1, n):
        j = live[k]
        if j is None:
            continue
        if open_heads[j] and heads[j] and heads[k] and not head_spaces[k]:
            glued = frag_join(heads[j][-1], heads[k][0])
            if glued is not None:
                heads[j].pop()
                heads[k][0] = glued
    for k in range(n):
        ja = etext.decode(t.units[k])
        if not re.sub(TOKEN, '', ja).strip():
            # a dead unit: the end code alone is not a sentence. There is
            # nothing to place words into, so reflowing leaves them over
            # ('leftover words: ck; <FFEF>') and the row is noise either way.
            continue
        j = live[k]
        prior = list(strays[j]) if j is not None else []
        current = list(heads[k])
        # PSP TALK sometimes splits a word at a unit boundary. A stray fragment
        # that ends without a space joins the next unit's first word when that
        # unit also starts without a space (e.g. `c` + `harms`).
        joined = False
        if j is not None and open_strays[j] and prior and current and not head_spaces[k]:
            glued = frag_join(prior[-1], current[0])
            if glued is not None:
                prior[-1] = glued
                current.pop(0)
                joined = True
        words = prior + current
        # The PSX row alone decides PSP head furniture; the shared rule does
        # not consult PSP-JP wording.
        import port_derive
        words = [w for w in (port_derive.head_marks(w, ja)
                             for w in words) if w]
        # THE STRAY-JP RULE (port_derive.stray_jp's threshold, word
        # granularity): the US build left a few JP glyphs inside its own
        # English - a word that is only JP glyphs goes when the unit is
        # otherwise English, and a really-Japanese unit keeps them (its
        # own gate refuses it as a remnant).
        # (the shown text only: a code and the answer prompt's param byte -
        # written as the PSX glyph it is, often a kana - are not words)
        def shown(w):
            return re.sub(r'<FFFD>.|<FF[0-9A-F]{2}>', '', w)
        jp_words = [w for w in words if port_derive.JP_GLYPH.search(shown(w))]
        letters = sum(len(re.sub(r'[^A-Za-z]', '', w)) for w in words)
        if jp_words and letters and \
                sum(len(shown(w)) for w in jp_words) * 4 <= letters:
            words = [w for w in words
                     if not port_derive.JP_GLYPH.search(shown(w))]
        # this unit's PSP breaks shift past the carried-over prior words
        # (minus one when the boundary word fragment merged back together).
        # The previous stray's breaks (the next message's turns ride in the
        # tail: ETC dots + turns + text after the end code) address the
        # prior words directly. Leading/trailing breaks would make empty
        # pages: dropped.
        breaks = {}
        for hi, op in unit_breaks[k]:
            wi = hi + len(prior) - (1 if joined else 0)
            if 0 < wi < len(words):
                breaks.setdefault(wi, []).append(op)
        if j is not None:
            for si, op in stray_breaks[j]:
                if 0 < si < len(words):
                    breaks.setdefault(si, []).append(op)
        slots, end = psx_slots(ja)
        # JA page breaks never enter the English text: pages come only
        # from PSP page turns (or fresh sentence-aware splits on overflow).
        slots = [(k, v) for k, v in slots
                 if not (k == 'code' and v in ('<FFFB>', '<FFF7>'))]
        # THE CODES ARE THE PSP LINE'S, translated (psp_split keeps them in
        # the words where the US line has them; its line and page codes
        # become the flow's breaks): the Japanese skeleton contributes its
        # text runs only - none of its codes is pinned into the English
        slots = [(k, v) for k, v in slots if k == 'text']
        en, used = reflow(words, slots, end or '<FFF5>', breaks)
        # a US wait (FF02) plus page turn (FF04) on the same word emits two
        # adjacent page boundaries: collapse (an empty page is never intended;
        # leading/trailing breaks are already dropped for the same reason).
        while '<FFFB><FFF7><FFFB><FFF7>' in en:
            en = en.replace('<FFFB><FFF7><FFFB><FFF7>', '<FFFB><FFF7>')
        # THE GATE IS THE BUILDER'S OWN: talk._qa is the exact function
        # talk.py build refuses a row with, so 'clean' here means 'ships
        # there'. Porter acceptance must agree with the builder.
        errs = talkbuild._qa(ja, en)
        if any('lines (max' in e for e in errs):
            # PSP sentences overflow one 3-line page: paginate (the BTLP
            # box turns pages on FFFB FFF7) instead of failing the unit.
            en = repaginate(en)
            errs = talkbuild._qa(ja, en)
        # unused-words warning
        if used < len(words):
            errs = errs + [f'leftover words: {" ".join(words[used:])}'[:120]]
        if not errs:
            ok += 1
        rows.append((k, ja, en, '; '.join(errs)))
    import toolbelt
    auto, over = [], []
    for k, ja, en, errs in rows:
        if not (en or '').strip():
            continue
        pos = hex(t.starts[k])
        if errs:
            over.append((pos, en, errs))
        else:
            auto.append({'pos': pos, 'psp': usptr.get(k, ''), 'en': en})
    if auto:
        toolbelt.upsert_generated(f'TALK/{name}', auto)
    for pos, draft, errs in over:
        k = t.starts.index(int(pos, 16))
        toolbelt.route_over(f'TALK/{name}', pos, usptr.get(k, ''), draft,
                            _over_reason(errs))
    toolbelt.route_gaps(f'TALK/{name}', talkbuild.text_starts(t))
    print(f'{name}: {ok}/{n} units clean')
    if verbose:
        for k, ja, en, errs in rows:
            if errs:
                print(f'--- unit {k}: {errs}')
                print(f'  ja: {ja[:150]}')
                print(f'  en: {en[:150]}')
                if k > 8:
                    print('  ... (truncated)')
                    break
    return rows


def report_skipped():
    """One run-level line for units the converter did not consume.

    SKIPPED accumulates across files, so printing per file repeats the same
    set for every file after the first (it printed 24 identical lines).
    `f500` is the end/separator unit every message ends with: skipping it is
    the converter working as designed and the per-file clean count already
    says so, so it is not named here.
    """
    odd = [u for u in SKIPPED if u != 0xF500]
    if odd:
        import collections
        print('skipped units (whole run):', ' '.join('%04x(x%d)' % (u, c)
              for u, c in collections.Counter(odd).most_common(15)))


def bulk():
    """Port every TALK file. Per-file TSVs are unit/ja/en with no notes;
    rows that fail QA surface as manual worklist rows (with notes), never
    as generated annotations."""
    import glob as _glob
    for path in sorted(_glob.glob(os.path.join(PSX, '*.BIN'))):
        name = os.path.basename(path)[:-4]
        try:
            main(name, verbose=False)
        except Exception as ex:
            print(f'{name}: FAIL {ex}')
    report_skipped()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
        report_skipped()
    else:
        bulk()
