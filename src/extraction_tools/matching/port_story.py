"""Port PSP-US story text into PSX event boxes (etext-compatible en strings).

Golden rule: the PSP-US box owns the words and pagination; the PSX-JA box
is the alignment key (which box maps where), a layout heuristic (text-run
lengths apportion words). Name insert kinds belong to the PSP wording.
No JA wording enters en.
  - PSP FF1B first line -> 'Label: ' prefix (verbatim). Later identical FF1B
    lines are dropped; differing ones are flagged.
  - PSP FF18/FF19 (+1 param, +0044 after 0200/0300), FF1A (flag) are dropped;
    FF02 waits / FF04 pages ride verbatim; FF03 lines merge into width flow.
  - PSP FF05 pauses ride verbatim with US durations; PSP FF07/08/0F name
    markers retain their PSP kind and gain the protagonist parameter;
    PSP FF0E choices ride with PSP's own value
    byte; PSP FF18/FF06 card heads map to the PSX FF06 frame style. JA
    codes never render.
  - Pure-dot US words are dropped when PSP has FF05 pauses (the pauses ARE
    the beat); kept otherwise.
  - Intro cards (FF06 portrait boxes) take a custom path (PSP-mapped frame).

  python src/extraction_tools/matching/port_story.py E0 0        convert entry, print rows + QA
  python src/extraction_tools/matching/port_story.py E0 0 --apply
                                             write the generated PSX/ADV/E0.tsv port table
"""
import csv
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import etext  # noqa: E402
import strlib  # noqa: E402
import efile  # noqa: E402
import vwf_wrap  # noqa: E402
import tstatus  # noqa: E402 (classify_deviations: the audit shares QA's gate)
from text import load_psp  # noqa: E402
from codec import US_MAP  # noqa: E402
import story_port_plan  # noqa: E402

ALIGN = os.path.join(toolbelt.MAPPINGS, 'align.tsv')

# PSP param rules (empirical, JP/US agreement)
DROP1 = {0x05, 0x06, 0x18, 0x19, 0x1A}
DROP0 = {0x07, 0x08, 0x11}
# Brackets, caption marks and bullets are visible glyphs in US_MAP, not
# invisible icons. They pass through the same decoder as every other glyph.
# PSX param sizes in DECODED chars
PSX_PARAMS = {'FF05': 2, 'FF06': 1, 'FF0E': 1, 'FF0F': 1}
# Japanese poker headings are structural labels, not speaker names. PSP-US
# supplies their exact English text in the word stream, so don't synthesize
# a second label from the PSX caption.
HAND_LABELS = strlib.glossary('hand')
# glossary JA names verified to match PSP spellings (labels + cards)
GLOSS_OK = strlib.glossary('name')


def collect_labels():
    """PSP-US speaker labels derived from story boxes; no cache writes."""
    from text import load_psp
    from codec import decode_box
    labels = set()
    for file in ('E0', 'E1', 'E2', 'E3', 'E4'):
        for entry in load_psp(file, 'us').entries:
            for i in range(len(entry.boxes)):
                decoded = decode_box(entry.box_bytes(i), holes=[])
                for match in re.finditer(r'<FF1B>([^<]*)', decoded):
                    label = match.group(1).strip()
                    if label and '[' not in label:
                        labels.add(label)
    return labels


def psp_names():
    """JA label -> PSP EN, for glossary characters whose EN appears as a US
    label, plus verified extras. Cached."""
    if psp_names.cache is None:
        import tstatus
        tstatus.load_glossary()
        labs = set()
        p = os.path.join(toolbelt.MAPPINGS, 'labels.tsv')
        if os.path.exists(p):
            for row in strlib.tsv_rows(p, required=('label',)):
                labs.add(row['label'])
        else:
            labs = collect_labels()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w', encoding='utf-8', newline='\n') as out:
                out.write('label\n')
                out.writelines(label + '\n' for label in sorted(labs))
        m = dict(GLOSS_OK)
        for ja, (en, cat) in tstatus.GLOSS.items():
            if cat in ('character', 'speaker label') and en in labs:
                m.setdefault(ja, en)
        # verified extras (PSP uses given name / nickname form)
        m.update(strlib.glossary('name_extra'))
        psp_names.cache = m
    return psp_names.cache


psp_names.cache = None


def accepted_pairs():
    """{(file, entry, box)} reviewed-good reattributions (keep US label)."""
    if accepted_pairs.cache is None:
        accepted_pairs.cache = set()
        p = os.path.join(toolbelt.SOURCE_MAPPINGS, 'accept.tsv')
        if os.path.exists(p):
            for f in strlib.tsv_fields(p, 3):
                accepted_pairs.cache.add((f[0], int(f[1]), int(f[2])))
    return accepted_pairs.cache


accepted_pairs.cache = None


# Sentinel prefix marking PSP-US structure breaks inside the word stream
# (FF02 wait / FF03 line / FF04 page). PSP owns pagination: JA breaks are
# dropped, PSP breaks are kept. Private-use char, never collides with text.
US_BRK = ''


def us_parts(raw, ja=None):
    """Segments [(label_or_None, words)] split at differing FF1B lines.
    PSP structure breaks ride inside the word stream as US_BRK sentinels."""
    segments = []
    curlabel = None
    words = []
    flags = []
    cur = ''
    i = 0
    n = len(raw)

    def flush():
        nonlocal cur
        if cur:
            # no quote/apostrophe splitting: punctuation stays glued to its
            # word exactly as PSP authored it ("young master.", y'know).
            # The width flow wraps whole words; a quote
            # never strands alone unless PSP spaced it that way.
            words.append(cur.replace('…', '...'))
            cur = ''

    def boundary(label):
        nonlocal curlabel, words
        flush()
        if curlabel is None:
            curlabel = label
        elif label != curlabel:
            segments.append((curlabel, words))
            words = []
            curlabel = label
            # NOTE: no flag: mid-box speaker breaks are handled structurally
            # (FF03 + 'Name: '), labels come straight from PSP data.

    while i + 1 < n:
        if raw[i] == 0xFF:
            op = raw[i + 1]
            i += 2
            # Only an op that puts something in the word stream (break, pause,
            # name insert, choice prompt, label) splits a word. An invisible op
            # is dropped here (styling, parameter bytes, terminators): the text
            # either side of one is adjacent on screen and stays ONE word, so a
            # plate inside PSP's own quotes can never open a gap
            # ('"' + plate + 'Persona' + '"' + '?' -> '"Persona"?', never
            # '"Persona "?'). Real spaces still split below.
            if op in (0x02, 0x03, 0x04, 0x05, 0x07, 0x08, 0x0E, 0x0F, 0x1B):
                flush()
            if op in (0x02, 0x03, 0x04):
                # PSP pagination/lineation: kept verbatim (JA breaks are
                # dropped instead). Rides the word stream as a sentinel.
                structural = False
                if op == 0x03:
                    from port_controls import is_heading
                    start = next((j for j in range(len(words)-1, -1, -1)
                                  if words[j].startswith(US_BRK)), -1)
                    structural = is_heading(' '.join(words[start + 1:]))
                words.append(US_BRK + ('STRUCT03' if structural else 'FF%02X' % op))
            elif op == 0x1B:
                lab = []
                while i + 1 < n and raw[i] != 0xFF:
                    u = struct.unpack_from('>H', raw, i)[0]
                    i += 2
                    ch = US_MAP.get(u, '')
                    if ch:
                        lab.append(ch)
                    else:
                        flags.append('unmapped-label:%04x' % u)
                boundary(''.join(lab).strip().replace('…', '...') or None)
            elif op == 0x05:
                # PSP pause with US duration: kept verbatim, rides the word
                # stream as a sentinel (pauses are US-authoritative; JA
                # pauses never enter the English text).
                if i + 1 < n and raw[i] != 0xFF:
                    param = struct.unpack_from('>H', raw, i)[0]
                    i += 2
                    words.append('%sFF05%04X' % (US_BRK, param))
            elif op in (0x07, 0x08, 0x0F):
                # PSP name insertion: kept as a position marker. The name
                # code is synthesized here (not at its JA slot), so
                # surrounding words keep PSP order ("awake, <name>!", not
                # "<name>awake,!").
                words.append('%sNAME%02X' % (US_BRK, op))
            elif op == 0x0E:
                # PSP choice prompt: kept as a position marker with PSP's
                # own value byte (FF0E LO 00; LO matches JA in all but 3
                # rows where PSP deliberately differs, plus 2 rows where
                # JA has no prompt at all and dropping it lost the choice).
                if i + 1 < n:
                    words.append('%sFF0E%02X%02X' % (US_BRK, raw[i], raw[i + 1]))
                    i += 2
            elif op in DROP1:
                if i + 1 < n and raw[i] != 0xFF:
                    first = struct.unpack_from('>H', raw, i)[0]
                    i += 2
                    if first in (0x0200, 0x0300) and i + 1 < n and raw[i] != 0xFF:
                        second = struct.unpack_from('>H', raw, i)[0]
                        if second == 0x0044:
                            i += 2
            elif op == 0x1A:
                flags.append('FF1A-present')
            elif op in DROP0:
                pass
            continue
        u = struct.unpack_from('>H', raw, i)[0]
        i += 2
        ch = US_MAP.get(u, '')
        if ch == ' ':
            flush()
        elif ch:
            cur += ch
        else:
            flags.append('unmapped:%04x' % u)
    flush()
    segments.append((curlabel, words))
    if ja is not None:
        from port_controls import adapt_buttons
        # Adapt the whole reference sequence, not each page independently:
        # the same physical button can have different uses in one message.
        joined = ' \ue001 '.join(' '.join(ws) for _label, ws in segments)
        adapted = adapt_buttons(joined, ja).split(' \ue001 ')
        segments = [(label, text.split(' ') if text else [])
                    for (label, _ws), text in zip(segments, adapted)]
        import port_derive
        # Head furniture that the PSX does not draw must not consume wrapping
        # width. Structural caption breaks were identified above, before its
        # visible markers are removed.
        segments = [(label, [clean for word in ws
                             if (clean := port_derive.head_marks(word, ja))])
                    for label, ws in segments]
    return segments, flags


# PSX param sizes in RAW bytes (must match tstatus.PARAM_LEN!)
PSX_PBYTES = {0x05: 2, 0x06: 1, 0x07: 1, 0x08: 1, 0x0E: 1, 0x0F: 1,
              0x11: 0, 0x12: 0}


def psx_tok_raw(raw):
    """Param-aware token list over RAW box bytes: ('t', decoded text) /
    ('c', code token with params as <XX> raw-byte tokens)."""
    toks = []
    pos = 0
    i = 0
    n = len(raw)
    cur = bytearray()
    while i < n:
        c = raw[i]
        if c == 0xFF and i + 1 < n:
            op = raw[i + 1]
            if cur:
                toks.append(('t', etext.decode(bytes(cur))))
                cur = bytearray()
            if op < 0x20:
                nb = PSX_PBYTES.get(op, 0)
                params = raw[i + 2:i + 2 + nb]
                toks.append(('c', '<FF%02X>' % op + ''.join('<%02X>' % b for b in params)))
                i += 2 + nb
            else:
                # command byte (>=0x20): keep raw, attach as code
                toks.append(('c', '<FF%02X>' % op))
                i += 2
        elif 0x80 <= c <= 0x87 and i + 1 < n:
            cur += bytes(raw[i:i + 2])
            i += 2
        else:
            cur.append(c)
            i += 1
    if cur:
        toks.append(('t', etext.decode(bytes(cur))))
    return toks


def split_label(toks):
    """Pull a leading JA 'X：' label off the first text token. Returns (label_ja, toks)."""
    for i, (kind, val) in enumerate(toks):
        if kind == 't' and val:
            m = re.match(r'^([^<]{1,12}：)', val)
            if m:
                toks[i] = ('t', val[m.end():])
                return m.group(1), toks
            return None, toks
    return None, toks


def jp_mid_labels(toks):
    """Mid-box JA speaker labels, in box order (the leading one is already
    stripped by split_label). A label is a text token starting with 'X：'
    (1-12 chars, fullwidth colon: the same shape split_label accepts).
    EN mid-box restatements keep their name iff one of these exists."""
    out = []
    for kind, val in toks:
        if kind == 't' and val:
            m = re.match(r'^([^<]{1,12}：)', val)
            if m:
                out.append(m.group(1))
    return out


def label_words(label):
    """Speaker-label words with the colon glued to the tail word
    (College student with her boyfriend:). The label is ONE typographic
    unit: a name must never break across lines ("Glasses-wearing" hanging
    over "schoolgirl: Um... hello."). So it flows as a single atom whenever
    it fits the box - it then either shares line 1 or takes the line whole,
    exactly like any other word. Only a label wider than the box itself
    falls back to wrapping at word gaps, and even then the colon stays
    glued to its own word (it never strands alone: E0/19 in game).
    Never shorten: all words kept."""
    ws = [w for w in label.split(' ') if w]
    if not ws:
        return []
    ws[-1] += ':'
    if vwf_wrap.text_width(' '.join(ws)) <= vwf_wrap.BOX_WIDTH:
        return [('w', ' '.join(ws))]
    return [('w', w) for w in ws]


# Words that look sentence-final but aren't (abbreviations, initials):
# waits/pages snap to real sentence ends so fragments never strand
# ("that little | ghost girl!"). Defined in the shared engine - the same
# predicate decides where a line ends, where a page turns and where a wait
# is allowed to cut.
sent_end = vwf_wrap.sent_end


def _slot_bounds(toks, nwords):
    """Word-count cut points for the real JA text slots: the PSX text slots
    are the distribution anchors, so the words are shared out proportionally
    to the JA slot lengths. One source of truth - reflow places the words
    and _ja_turn_words places the page turns from the same cut points, so a
    page turn always lands where the JA's own slot edge falls."""
    slots = [len(val) for kind, val in toks
             if kind == 't' and val.strip('　 ')]
    total_ja = sum(slots) or 1
    bounds = []
    acc = 0.0
    for L in slots:
        acc += L / total_ja * nwords
        bounds.append(int(round(acc)))
    return bounds


def _ja_turn_words(toks, nwords):
    """Word indices where the JA turns to a fresh window (<FF04>). A turn
    fires before the word at its index, so the slots before it fill the
    earlier box: the words reflow into the JA's boxes."""
    bounds = _slot_bounds(toks, nwords)
    out = []
    ns = 0
    for kind, val in toks:
        if kind == 't' and val.strip('　 '):
            ns += 1
        elif kind == 'c' and val == '<FF04>':
            w = bounds[ns - 1] if ns else 0
            if 0 < w < nwords:      # never a box with no words of its own
                out.append(w)
    return out


def reflow(first_label, items, toks):
    """Distribute US words across the PSX text slots proportionally to the JA
    slot lengths. items = [('w', word)] words, [('b', label_or_None)] forced
    breaks (mid-box speaker changes) and [('u', code)] PSP structure breaks
    (FF02/FF03/FF04 ride the word stream as US_BRK sentinels). PSP owns
    pagination: PSP internal waits/pages fire verbatim at PSP positions;
    JA waits/pages never render; trailing PSP breaks set dismissal
    timing; over-wide lines re-split by width.
    Returns (en, used, flags)."""
    flags = []
    # normalize PSP break sentinels to ('u', code) items (they are not words)
    norm = []
    for it in items:
        if it[0] == 'w' and isinstance(it[1], str) and it[1].startswith(US_BRK):
            norm.append(('u', it[1][len(US_BRK):]))
        else:
            norm.append(it)
    items = norm
    slots = []
    for kind, val in toks:
        if kind == 't' and val.strip('　 '):
            slots.append([len(val), []])
    # whitespace-only slots (padding around headers) take no words
    real = [it[1] for it in items if it[0] == 'w']
    bounds = _slot_bounds(toks, len(real))
    # assign real words; breaks ride with the following word
    ri = 0
    for i, s in enumerate(slots):
        lo = bounds[i - 1] if i else 0
        s[1] = real[lo:bounds[i]]
        ri = bounds[i]
    used = bounds[-1] if bounds else 0
    # rebuild ordered stream with breaks attached
    # map real-word index -> [(kind, val)] breaks firing before that word
    after = {}
    nreal = 0
    for it in items:
        if it[0] == 'w':
            nreal += 1
        else:
            after.setdefault(nreal, []).append(it)
    si = 0
    parts = []
    flow_items = []
    tail = 'empty'
    dirty = False
    if first_label:
        # The label is one prose atom; shared flow can put it on its own
        # line when that avoids a clipped speech fragment without adding
        # lines. A prompt that does not fit
        # on one line is gated by vwf_wrap.choice_breaks instead: no options
        # until the player presses, then one scroll.
        flow_items.extend(label_words(first_label))
        tail = 'other'
        dirty = True
    # (wrapping policy lives in vwf_wrap.flow_lines; the item stream
    # below only positions words, breaks and inline codes.)
    deferred = []  # JA terminal codes (FF01): appended after trailing PSP
    # breaks so waits/pages keep PSP order (wait-then-end, not end-wait)
    # rebuild the word stream with positioned breaks attached: convert the
    # slot words plus the positioned fires (after-map) into one flow item
    # list, then run the shared flow.
    emitted = 0  # real words placed
    glue = False  # dropped PSP FF03 after a hyphen fragment: the next word
    # rejoins spaceless (PSP hyphen wraps, same rule as port_talk)
    # parts tail state for conditional header breaks (casino sections):
    # a header breaks unless the output is empty or already break-ended.
    # (flow_items/tail/dirty already carry the speaker atom above, if any.)
    def fire(ak, av):
        # One positioned fire -> flow items: flush, break/code, spacing.
        # Speaker labels flow as words with the colon glued to the tail word.
        nonlocal dirty, tail, glue
        glue = False
        if ak == 'b':
            flow_items.append(('b', '<FF03>'))
            tail = 'break'
            dirty = False
            if av:
                flow_items.extend(label_words(av))
                tail = 'other'
                dirty = True
        elif av == 'STRUCT03':
            flow_items.append(('b', '<FF03>'))
            tail = 'break'
            dirty = False
        elif av == 'FF03':
            # A PSP LINE BREAK IN PROSE IS NOT OURS (spec 2): it is where the
            # PSP's 16px glyphs ran out, so the English reflows and the flow
            # places every break. Structural instruction captions keep their
            # own break. After a hyphen fragment the
            # next word glues spaceless (bunny-<FF03>girls).
            from port_controls import is_heading
            last_break = next((i for i in range(len(flow_items) - 1, -1, -1)
                               if flow_items[i][0] == 'b'), -1)
            caption = ' '.join(v for k, v, *_ in flow_items[last_break + 1:]
                               if k == 'w')
            if is_heading(caption):
                flow_items.append(('b', '<FF03>'))
                tail = 'break'
                dirty = False
            elif (flow_items and flow_items[-1][0] == 'w'
                    and flow_items[-1][1].endswith('-')):
                glue = True
        elif av in ('FF02', 'FF04'):
            flow_items.append(('b', '<%s>' % av))
            tail = 'break'
            dirty = False
        elif av.startswith('NAME'):
            code = '<FF%s><01>' % av[4:6]
            flow_items.append(('s', code))
            dirty = True
        elif av.startswith('FF05'):
            flow_items.append(('g', '<FF05><%s><%s>' % (av[4:6], av[6:8])))
            dirty = True
        elif av.startswith('FF0E'):
            flow_items.append(('b', '<FF0E><%s>' % av[4:6]))
            dirty = False
        else:
            raise SystemExit('port_story: unexpected stream code %r' % av)
    si = 0
    for kind, val in toks:
        if kind == 'h':
            # fixed header rendering with forced break (casino sections)
            if dirty or tail == 'other':
                flow_items.append(('b', '<FF03>', 0))
                tail = 'break'
            flow_items.append(('h', val))
            dirty = False
            tail = 'other'
            glue = False
            continue
        if kind == 't' and val.strip('　 '):
            w = slots[si][1]
            import os as _os2
            if _os2.environ.get('PSP_DEBUG'):
                print('DEBUG slot', si, repr(val[:20]), 'words:', w)
            si += 1
            # wrap slot words at BOX_WIDTH (label shares the first line)
            for word in w:
                if emitted in after:
                    for ak, av in after[emitted]:
                        fire(ak, av)
                if glue and flow_items and flow_items[-1][0] == 'w':
                    # suspended compound ("higher- or lower-ranked"): a
                    # conjunction continues the branch, so keep the space.
                    if flow_items[-1][1].endswith('-') and word.strip(
                            ',.!?;:\'"').lower() in (
                                'or', 'and', 'nor', 'but', 'yet'):
                        glue = False
                        flow_items.append(('w', word))
                    else:
                        flow_items[-1] = ('w', flow_items[-1][1] + word)
                        glue = False
                else:
                    flow_items.append(('w', word))
                dirty = True
                emitted += 1
            # no per-slot flush: line carries across slots (pauses/inserts
            # don't break lines); explicit breaks and wraps handle ends
        else:
            # PSP owns pagination: PSP internal waits/pages ride the word
            # stream verbatim (fired by the caller through fire()); JA
            # waits/pages never render (a JA beat landing mid-sentence
            # reads as a hang in English). JA pauses are dropped too.
            # JA non-terminal codes ride through glued at their proportional
            # slots; JA padding text never emits.
            if kind == 't' or val == '<FF03>':
                pass
            elif val in ('<FF02>', '<FF04>'):
                pass
            elif val.startswith('<FF05>'):
                pass
            elif kind == 'c' and val[:5] in ('<FF07', '<FF08', '<FF0F'):
                # Only PSP markers supply English name inserts.
                pass
            else:
                if val == '<FF01>':
                    # terminal code: the line is flushed with the rest at
                    # the end and flows straight through (glued, as
                    # before); the code itself goes last.
                    deferred.append(val)
                elif val.startswith('<FF0E>'):
                    # JA choice prompt: dropped, PSP owns all choices (its
                    # FF0E rides the word stream with PSP's own value).
                    pass
                else:
                    flow_items.append(('G', val))
                    tail = 'other'
                    dirty = True
                    glue = False
    # trailing breaks (speaker change at the very end)
    if emitted in after:
        for ak, av in after[emitted]:
            fire(ak, av)
    for k, v in vwf_wrap.flow_lines(flow_items, vwf_wrap.BOX_WIDTH,
                                    vwf_wrap.text_width, '<FF03>'):
        parts.append(v)
    parts.extend(deferred)
    # THE choice rule (vwf_wrap.choice_breaks): the options start on their
    # own line - every assembly point goes through it, no copy of the rule
    en = vwf_wrap.choice_breaks(''.join(parts), brk='<FF03>')
    return en, used, flags


# Nickname-less PSP staff/NPC cards: PSX JA name slot -> US name.
# (The US text then continues with the desc; leading name words stripped.)
CARD_NAMES = strlib.glossary('card')


def parse_card(raw):
    """Structured parse of a PSP intro-card box. Returns (name, nick, desc_words).
    Layout: FF18 params, NAME [0029] 'Nickname' [0006] NICK [002a] DESC...
    Nickname-less cards (PSP staff/NPC cards): NAME DESC... with NAME from
    CARD_NAMES via the PSX side (handled by caller passing psx_name)."""
    ICONS = {0x0029, 0x0006, 0x002a}
    segs = []  # text segments split by icons
    cur = ''
    i = 0
    n = len(raw)

    def flush():
        nonlocal cur
        if cur.strip():
            segs.append(cur.strip())
            cur = ''

    while i + 1 < n:
        if raw[i] == 0xFF:
            op = raw[i + 1]
            i += 2
            flush()
            if op in (0x07, 0x08, 0x0F):
                # name marker: preserved so the JA name code lands here
                segs.append('%sNAME%02X' % (US_BRK, op))
                continue
            if op == 0x03:
                # PSP line break rides as a sentinel so card_en's reflow
                # can glue it spaceless after '-' (PSP hyphen wraps);
                # joining it away here baked "part- time".
                segs.append('%sFF03' % US_BRK)
                continue
            if op in DROP1:
                if i + 1 < n and raw[i] != 0xFF:
                    first = struct.unpack_from('>H', raw, i)[0]
                    i += 2
                    if first in (0x0200, 0x0300) and i + 1 < n and raw[i] != 0xFF:
                        second = struct.unpack_from('>H', raw, i)[0]
                        if second == 0x0044:
                            i += 2
            continue
        u = struct.unpack_from('>H', raw, i)[0]
        i += 2
        if u in ICONS:
            flush()
            segs.append('<ICON%04x>' % u)
            continue
        ch = US_MAP.get(u, '')
        if ch == ' ':
            flush()
            segs.append(' ')
        elif ch:
            cur += ch
    flush()
    # segs: [name, <ICON0029>, 'Nickname', <ICON0006>, nick, <ICON002a>, desc...]
    if '<ICON0029>' in segs and '<ICON002a>' in segs:
        i29 = segs.index('<ICON0029>')
        i2a = segs.index('<ICON002a>')
        name = ' '.join(s for s in segs[:i29]
                        if s != ' ' and not s.startswith(US_BRK + 'FF03')).strip()
        nick = ''
        if '<ICON0006>' in segs:
            i06 = segs.index('<ICON0006>')
            nick = ' '.join(s for s in segs[i06 + 1:i2a]
                            if s != ' ' and not s.startswith(US_BRK + 'FF03')).strip()
        desc = []
        for s in segs[i2a + 1:]:
            if s == ' ':
                desc.append('')
            elif s.startswith('<ICON'):
                continue
            elif s.startswith(US_BRK):
                desc.append(s)
            else:
                desc.append(s)
        words = []
        for d in ' '.join(desc).replace('…', '...').split(' '):
            if d:
                words.append(d)
        name = name.replace('…', '...')
        if not name:
            return None  # icon bytes without a title: not a decodable card
        return name, nick.replace('…', '...'), words
    return None


def parse_card_simple(raw, psx_name):
    """Nickname-less staff/NPC card: NAME DESC... Name from CARD_NAMES via the
    PSX JA name slot; desc = US text minus leading name words."""
    if psx_name not in CARD_NAMES:
        return None
    name = CARD_NAMES[psx_name]
    words, cur = [], ''
    i, n = 0, len(raw)

    def flush():
        nonlocal cur
        if cur.strip():
            words.append(cur.strip())
            cur = ''

    while i + 1 < n:
        if raw[i] == 0xFF:
            op = raw[i + 1]
            i += 2
            flush()
            if op in (0x07, 0x08, 0x0F):
                # name marker: preserved so the JA name code lands here
                words.append('%sNAME%02X' % (US_BRK, op))
                continue
            if op in DROP1:
                if i + 1 < n and raw[i] != 0xFF:
                    first = struct.unpack_from('>H', raw, i)[0]
                    i += 2
                    if first in (0x0200, 0x0300) and i + 1 < n and raw[i] != 0xFF:
                        second = struct.unpack_from('>H', raw, i)[0]
                        if second == 0x0044:
                            i += 2
            continue
        u = struct.unpack_from('>H', raw, i)[0]
        i += 2
        if u in (0x0029, 0x0006, 0x002a):
            flush()
            continue
        ch = US_MAP.get(u, '')
        if ch == ' ':
            flush()
        elif ch:
            cur += ch
        else:
            return None  # unknown unit: not safe to strip blindly
    flush()
    flat = ' '.join(words).replace('…', '...')
    want = name.split(' ')
    got = flat.split(' ')
    if [g.lower().rstrip(',:') for g in got[:len(want)]] != [w.lower() for w in want]:
        return None
    rest = got[len(want):]
    # An inline source description can follow the name's comma on the SAME
    # line. Keep that authored punctuation; it is not a synthesized dash.
    suffix = ',' if got[len(want) - 1].endswith(',') else ''
    return name + suffix, '', rest


def parse_card_text(raw, psx_name):
    """Plain-text style card (FF06-headed US box, no FF18 portrait/icons):
    title line + description lines. The title must resolve to a known card
    name (via CARD_NAMES from the PSX JA slot or its EN value); otherwise
    this is not a card pair and None is returned."""
    if raw[:2] != b'\xff\x06':
        return None
    segments, flags = us_parts(raw)
    if any('unmapped' in fl for fl in flags):
        return None  # title/desc use codes outside the solved map
    chunks, cur = [], []
    for _lab, words in segments:
        for x in words:
            if isinstance(x, str) and x.startswith(US_BRK):
                if cur:
                    chunks.append(' '.join(cur))
                    cur = []
            else:
                cur.append(x)
    if cur:
        chunks.append(' '.join(cur))
    chunks = [c.replace('…', '...').strip(' .') for c in chunks if c.strip(' .')]
    if not chunks:
        return None
    title = chunks[0].lstrip('. ').strip()
    names = dict(CARD_NAMES)
    if psx_name in names and title.lower().startswith(names[psx_name].lower()):
        name = names[psx_name]
    elif title in names.values():
        name = title
    else:
        return None
    # THE SOURCE'S BREAKS SURVIVE THE PARSE: chunks were split at every break,
    # so joining them with a space threw the author's lines away and the flow
    # then re-broke the card wherever it liked. Each chunk after the title is
    # one source line, and the sentinel between them keeps it that way.
    desc = []
    for c in chunks[1:]:
        if desc:
            desc.append(US_BRK + 'FF03')
        desc.extend(w for w in c.split(' ') if w)
    return name, '', desc


def card_en(psx_raw, us_raw, name, nick, words):
    """Build card en: PSX FF06 frame whose style comes from the PSP box
    head (FF18/FF06 + 0200/0300 -> <FF06><02>/<FF06><03>), PSP-owned tail
    waits/end, name/nick/desc flowed through the middle slots. Mid-box
    codes are PSP's own markers; JA codes never enter (JA text runs only
    apportion the PSP words, a layout heuristic).
    (The PSX-JA head agrees in every paired row, but the value is read
    from the PSP bytes here, not copied from the Japanese.)"""
    style = '03' if (len(us_raw) > 3 and us_raw[0] == 0xFF
                     and us_raw[1] in (0x18, 0x06) and us_raw[2] == 0x03) else '02'
    head = '<FF06><%s>' % style
    # tail: PSP's own frame close + waits/end. Both card kinds close with a
    # four-byte frame code: portrait cards FF18 0000, plain-text cards
    # FF06 0000. Either maps to the PSX frame close <FF06><00>; every card
    # ends FF02 FF01, same bytes both sides.
    tail = ''
    i = len(us_raw)
    while i - 2 >= 0 and us_raw[i - 2] == 0xFF and us_raw[i - 1] in (0x01, 0x02):
        tail = '<FF%02X>' % us_raw[i - 1] + tail
        i -= 2
    if i - 4 >= 0 and us_raw[i - 4:i] in (bytes((0xFF, 0x18, 0x00, 0x00)),
                                          bytes((0xFF, 0x06, 0x00, 0x00))):
        tail = '<FF06><00>' + tail
        i -= 4
    if '<FF01>' not in tail:
        tail += '<FF01>'
    toks = [t for t in psx_tok_raw(psx_raw) if t[0] == 't']
    # THE CARD'S HEAD IS A NAMEPLATE, NOT A SPEAKER LABEL: the PSP writes the
    # name alone on its line ("＞ Saeko Takami"), with NO colon - a colon here
    # is our invention and does not exist in either script.
    # the PSP spells the nickname slot with its own colon, and the label is
    # rebuilt from the card's parts (not copied), so the colon is spelled here:
    # 'Yukino Mayuzumi (Nickname: Yukino)' - it is part of the label.
    body = ('%s (Nickname: %s)' % (name, nick) if nick else name).rstrip(':')
    if nick and body.count(':') > 1:
        body = body.replace('::', ':')
    # ... and the description must not open with the label's colon: the PSP
    # head and the parsed title can each contribute one, and a line that
    # begins with ':' is never right.
    words = [w for w in (words or []) if w]
    for idx, w in enumerate(words):
        if w.startswith(US_BRK):
            continue                     # a break sentinel: keep, look further
        if w.startswith(':'):
            rest = w.lstrip(':')
            if rest:
                words[idx] = rest
            else:
                del words[idx]
        break
    # Prefer the separate source nameplate when it costs no additional press.
    # Otherwise try one flowing card: an authored comma stays a comma; the
    # parenthesized nickname needs only a space; a bare name needs the dash
    # separator. A long nickname header may wrap (including at a hyphen) when
    # that saves a scroll, never merely for shape. No wording is shortened.
    def desc_text():
        """The description as text with its codes spelled back: a US_BRK
        sentinel carries either a code ('FF03') or a name slot ('NAME07',
        which is <FF07> plus its parameter)."""
        out, buf = [], []
        for w in list(words):
            if not w:
                continue
            if w.startswith(US_BRK):
                if buf:
                    out.append(' '.join(buf))
                    buf = []
                code = w[len(US_BRK):]
                if code.startswith('NAME'):
                    out.append('<FF%s><01>' % code[4:6])
                elif code.startswith('FF'):
                    out.append('<' + code + '>')
            else:
                buf.append(w)
        if buf:
            out.append(' '.join(buf))
        return ' '.join(out)

    head_fits = vwf_wrap.text_width(body) + 3 <= vwf_wrap.BOX_WIDTH

    def build(inline):
        # ONE layout pass and ONE pagination for the whole card (head included):
        # separate pagination could produce two scrolls in one box.
        separator = ' ' if nick or body.endswith(',') else ' - '
        laid = (layout_box(body + separator + desc_text()) if inline
                 else layout_box(desc_text(), head=body))
        return _clean(paginate(head + laid + tail)[0])

    plain = build(False)
    presses = lambda s: s.count('<FF02>')
    out = plain
    if head_fits or nick:
        compact = build(True)
        if (presses(compact) < presses(plain)
                or (body.endswith(',') and presses(compact) == presses(plain))):
            out = compact
    # THE FIRST LINE OF A CARD NEVER ENDS WITH A COLON: the nameplate is a
    # name, and a colon there is our label machinery leaking into a card
    # ("Yukino Mayuzumi (Nickname: Yukino):").
    out = re.sub(r'^(<FF06><[0-9A-F]{2}>.*?):(?=<FF03>)', r'\1', out,
                 count=1, flags=re.S)
    out = out.replace(' -  ', ' - ')
    # ... and no colon on the nameplate line, whatever the flow appended: the
    # name is a name, not a speaker label (the PSP has no colon there at all).
    return re.sub(r'^(<FF06><[0-9A-F]{2}>[^<:]*):(?=<FF03>)', r'\1', out)


def code_words(part):
    """Words of `part`, keeping every control code glued to its PARAMETER
    bytes (vwf_wrap.PARAM_LEN is the authority: FF05 x2, FF06/07/08/0E/0F x1).
    A param may be a whole character - <FF0E>'s choice param is a SPACE -
    so plain word splitting would eat it and the next code would be misread
    as the param (sysmsg: '[charset] non-ASCII bytes in text: 01')."""
    import re as _re
    import vwf_wrap as _v
    toks, i, word = [], 0, ''
    while i < len(part):
        m = _re.match(r'<FF([0-9A-F]{2})>', part[i:])
        if m:
            code = part[i:i + m.end()]
            i += m.end()
            n = _v.PARAM_LEN.get(m.group(1), 0)
            for _ in range(n):
                mm = _re.match(r'<[0-9A-F]{2}>', part[i:])
                step = mm.end() if mm else 1
                code += part[i:i + step]
                i += step
            word += code
            continue
        if part[i] == ' ':
            if word:
                toks.append(word)
                word = ''
            i += 1
            continue
        word += part[i]
        i += 1
    if word:
        toks.append(word)
    return toks


def layout_box(en, brk=None, head=None):
    """THE textbox layout - the one entry every producer calls (boot_btlmsg,
    port_lastresort, any family that has a box in hand). Nothing about a box's
    layout is decided anywhere else: the label rule at EVERY box head
    (label_words), LINE BREAKS as reflow output (the source's breaks belong to
    its own box - they are stripped to spaces and vwf_wrap.flow_lines re-places
    them at the width), the structure codes kept as deliberate breaks, the
    edge-blank rule, choice breaks, and the pagination. `brk` is the family's
    line-break code (<FF03> the dialogue engines, <FFF6> the battle one - FFF6
    really is BTLP's line move, not FF03; FF06 is colour and never a break).
    Returns '' when no layout fits the box - a row that cannot lay out is a
    draft, never a wrong box."""
    import re as _re
    import vwf_wrap as _v
    if brk is None:
        brk = vwf_wrap.NEWLINE
    # A CARD'S HEAD IS ITS OWN LINE and it must be part of the SAME layout
    # pass: laying the description out separately and then paginating the
    # pair paginated twice, which put two scrolls in one box (E0 #46).
    head_items = ([('w', w) for w in code_words(head) if w] + [('b', brk)]
                  if head else [])
    # A NAMEPLATE is one construct in two spellings: the PSX writes
    # '<FF1B>name<FF03>', the PSP writes its own head decoration plus the
    # name and the same break ('￥N' - '￥N＜' in the JP - then the name).
    # Both become the same label here; the decoration is not wording.
    LAB = _re.compile(r'^\s*(?:<FF1B>([^<]*)|￥N[＞＜]?([^<]*?))(<FF03>)')
    # THE BOX'S TAIL IS ITS OWN: the dismissal wait and the end code
    # ('<FF02><FF01>') are what make the box WAIT for a press. The layout
    # splits the text into parts and only words become lines, so preserve
    # the tail after the last word separately.
    tail = ''
    m = _re.search(r'((?:<FF0?[124]>|<FFEF>|<FFF5>)+)\s*$', en)
    if m:
        tail = m.group(1).replace(' ', '')
        en = en[:m.start()]

    items = list(head_items)
    for part in _re.split(r'(<FF0[124]>|<FFF5>|<FFEF>|<FFFB><FFF7>)', en):
        if not part:
            continue
        if _re.fullmatch(r'<FF[0-9A-F]{2}>|<FFFB><FFF7>', part):
            items.append(('b', part))
            continue
        m = LAB.match(part)
        if m:
            label = (m.group(1) or m.group(2) or '').strip()
            if label:
                # THE SPEAKER LABEL IS PROSE, NOT A FORCED NAMEPLATE. The PSP
                # prints every name on a line of its own ('<FF1B>name<FF03>');
                # that is PSP furniture, not this box's structure. The
                # PSX writes the name inline (南条：俺のと交換でいいんだな？,
                # 6,200 rows against 453) and so do we: the label is ONE atom
                # (label_words) that shares line 1 and never splits.
                items.extend(label_words(label))
            part = part[m.end():]
        else:
            # THE SAME NAMEPLATE, INLINE. The families whose PSX row writes
            # the speaker inline (dng, BTLP) carry 'Name: ' where the coded
            # families carry '<FF1B>name<FF03>'; the label is the same
            # construct and takes the same one-atom rule (§4.2) - a
            # multi-word name never breaks apart and the colon never starts
            # the next line.
            import port_derive as _pd
            label, rest = _pd.inline_label(part)
            if label:
                items.extend(label_words(label))
                part = rest
        # PROSE LINE BREAKS ARE THE FLOW'S. The PSP's own breaks in a
        # sentence are where ITS 16px glyphs ran out, not a layout decision:
        # reflow them to this box's width. What IS
        # structural keeps its own line: a card's nameplate (port_story's
        # card path) or a paired instruction caption. Everything else reflows.
        from port_controls import is_heading
        chunks = _re.split(r'<FF03>|<FFF6>', part)
        for i, chunk in enumerate(chunks):
            items.extend(('w', w) for w in code_words(chunk) if w)
            if i < len(chunks) - 1 and is_heading(chunk):
                items.append(('b', brk))
    out = ''.join(v for _k, v in _v.flow_lines(items, _v.BOX_WIDTH, newline=brk))
    out = _v.clean_edges(out)
    out = _v.choice_breaks(out, brk=brk)
    if brk == '<FFF6>':
        # BTLP/BTLEVT: the interpreter's full-page wait IS the scroll, so
        # the family's page skeleton is all pagination inserts. A battle box
        # holds FOUR lines - three visible, the fourth scrolled in by its
        # own <FFF6> (windowtype.c: WIN_LAST 0x2C is the third 15-cell row)
        # - so a page is four lines, not three. Chunking at three wrote the
        # PSX corpus' never-used '<FFFB><FFF7><FFF6>' for a four-line box,
        # and that line code after the page moved the pen off the page's
        # first row.
        out = paginate(out, line=brk, page='<FFFB><FFF7>',
                       wait='<FFFB><FFF7>', per=4)[0]
    else:
        out = paginate(out)[0]
    # the box's own tail (dismissal wait + end code) rides after the layout
    if tail and not out.rstrip().endswith(tail):
        out = out.rstrip() + tail
    return out


def paginate(en, line='<FF03>', page='<FF04>', wait='<FF02>', per=3):
    """Keep the AUTHORED boxes; add only what the English needs.

    The PSP script draws a fresh box where the writer asked for one - often
    repeating the speaker name first - and that split is the author's
    pagination. The <FF04> boundaries come from the source and are never
    merged away.

    What is NOT the author's is the scroll count: a box shows 3 lines and may
    scroll ONCE to the next 3. The Japanese page marks cannot be
    trusted for that - they were placed for 3 lines of 16px glyphs, so after
    the English reflow they land mid-sentence - so the waits are re-placed by
    our own line count: chunk 1 visible, chunk 2 one <FF02> scroll, chunk 3+
    a new box (<FF02><FF04>).

    `per` is the lines one page holds: the dialogue box's 3 (+1 scroll row),
    and the battle box's 4 (its own <FFF6> scrolls the fourth row in, so the
    page marker needs no line code after it).

    Returns (text, invented, nonsent): invented = advances added, nonsent =
    of those, cuts not at a sentence end (the caller reports that loudly).
    """
    out = []
    invented = nonsent = 0
    first = True
    for box in en.split(page):
        # THE BOX TAIL IS NOT TEXT: '<FF02><FF01>' is the dismissal press and
        # must not be counted as a 4th chunk (that invented a scroll for a
        # 3-line box). It comes back at the end of the last box.
        body = re.sub(r'(?:' + re.escape(wait) + r')*(<FF01>|<FFEF>|<FFF5>)'
                      + r'\s*$', r'\1', box)
        body = body.replace(wait, line)
        body = re.sub('(' + re.escape(line) + ')+', line, body)
        chunks = [c.strip() for c in body.split(line) if c.strip()]
        for ci in range(0, len(chunks), per):
            if not first:
                invented += 1
                prev = re.sub(r'<[^>]+>', '', chunks[ci - 1]).rstrip()
                word = prev.split(' ')[-1] if prev else ''
                if not sent_end(word):
                    nonsent += 1
                # chunk 2 of a box is its one scroll; everything else starts
                # a new box - including the next AUTHORED box. THE ORDER IS THE
                # ENGINE'S: '<FF02><FF03>' scrolls and moves the pen to the new
                # last line, and the PSX corpus spells it that way 1,796 times
                # against 17 of the reverse. '<FF03><FF02>' leaves the pen at
                # the end of the line above, appending scrolled text to it.
                if per == 3:
                    out.append(wait + (line if ci == 3 else page))
                else:
                    # a page's lines already carry their own line moves (the
                    # battle box's <FFF6> scrolls the fourth row in), so the
                    # page marker is the whole separator - the PSX corpus
                    # never writes a line code after it
                    out.append(page)
            out.append(line.join(chunks[ci:ci + per]))
            first = False
    s = ''.join(out)
    s = re.sub('(' + re.escape(wait) + ')+', wait, s)
    s = re.sub('(' + re.escape(page) + ')+', page, s)

    # A CODE'S PARAMETER IS NOT TRIM-ABLE WHITESPACE. <FF0E>'s one parameter is
    # a SPACE in the PSP script ('...<FF0E> <FF01>'), and the edge-blank rule
    # ate it - the encoder then read the next byte as the parameter and the
    # build failed with '[charset] non-ASCII bytes in text: 01'.
    def _fix_params(txt):
        out, i2 = [], 0
        while i2 < len(txt):
            m2 = re.match(r'<FF([0-9A-Fa-f]{2})>', txt[i2:])
            if m2:
                code = m2.group(1).upper()
                out.append(m2.group(0))
                i2 += m2.end()
                need = vwf_wrap.PARAM_LEN.get(code, 0)
                if need:
                    rest = txt[i2:]
                    if not rest or rest.startswith('<FF'):
                        out.append(' ' * need)
                    else:
                        out.append(rest[:need])
                        i2 += need
                continue
            out.append(txt[i2])
            i2 += 1
        return ''.join(out)
    s = _fix_params(s)

    # A BOX ENDS WITH ITS DISMISSAL WAIT: '<FF02><FF01>' is what makes the box
    # WAIT for the press that closes it. Pagination must preserve the tail
    # wait when splitting and re-placing page waits.
    s = re.sub(r'(?:' + re.escape(line) + r')+\s*$', '', s)
    if '<FF0E>' in s:
        # A CHOICE ROW ENDS WITH ITS OPTION BLOCK: '<FF0E><param><FF01>' - the
        # JP writes exactly that, and a wait after the block stops the options
        # from arming. The prompt wait goes BEFORE the block, as
        # '<FF02><FF03>'.
        s = re.sub(r'(<FF0E>.?)' + r'(?:' + re.escape(wait) + r')+', r'\1', s)
        # the line before the block is not ours to invent either: keep the
        # wait only if the caller (the JP's own shape) put one there.
        head, _, rest = s.partition('<FF0E>')
        kept = bool(re.search(r'(?:' + re.escape(wait) + r')+\s*$', head))
        head = re.sub(r'(?:' + re.escape(line) + r')+\s*$', '', head)
        head = re.sub(r'(?:' + re.escape(wait) + r')+\s*$', '', head)
        s = head + (wait if kept else '') + line + '<FF0E>' + rest
    else:
        s = re.sub(r'(?:' + re.escape(wait) + r')*(<FF01>|<FFEF>|<FFF5>)\s*$',
                   lambda m: wait + m.group(1), s)
    # ... and no empty line in front of the DISMISSAL wait. It must be that
    # wait exactly: a line code before a SCROLL wait is what moves the pen to
    # the next line; without it, the scroll appends text to the line above
    # instead of redrawing.
    # (no line code belongs in front of a wait at all: the wait carries the
    # break, '<FF02><FF03>' - see the scroll note above)

    # A CHOICE OPTION STARTS ITS OWN LINE (the QA gate holds exactly this
    # rule): run it LAST, on the finished text, so the result is a fixed point.
    s = vwf_wrap.choice_breaks(s, brk=line)
    return s, invented, nonsent


def merge_boxes(s, line='<FF03>', page='<FF04>', wait='<FF02>', min_boxes=1):
    """JOIN TWO AUTHORED BOXES WHEN THE JOIN IS FREE.

    The PSP's boxes are the author's and are kept - but two of them often fit
    one box between them, and then the break buys the player a press for
    nothing. A join is free when
    neither box scrolls and the pair fits the box's three lines, AND the box
    count stays in [psx boxes, psp boxes]: never fewer boxes than the PSX
    draws for the same speech. Nothing is re-flowed and no scroll is invented.
    """
    ends = ('<FF01>', '<FFEF>', '<FFF5>')
    tail = ''
    for e in ends:                      # the row's end code stays at the very end
        if s.rstrip().endswith(e):
            tail = e
            s = s[:s.rstrip().rfind(e)]
            break
    # THE OPTION BLOCK IS NOT SCROLLED TEXT. '<FF0E>' arms on a line of its
    # own, and the wait in front of it is that line's gate, not a scroll of
    # the box - reading it as scroll content made every choice box look
    # unjoinable ('not scr'), so a prompt whose JP is ONE box stayed two
    # (Yuka: "Um, I hate to ask, but..." / question, two presses where the JP
    # scrolls once). Protect the block, join, then put it back.
    block = ''
    m = re.search(r'((?:' + re.escape(wait) + r'|' + re.escape(line) + r')*'
                  r'<FF0E>(?:<[0-9A-F]{2}>)?)', s)
    if m:
        block = m.group(1)
        s = s[:m.start()] + '\x01CHOICE\x01' + s[m.end():]
    boxes = []
    splitter = '(' + re.escape(line) + '|' + re.escape(wait) + ')'
    for b in s.split(page):
        vis, scr, after = [], [], False
        for seg in re.split(splitter, b):
            if seg == line:
                continue
            if seg == wait:
                after = True
                continue
            t = seg
            for e in ends:
                t = t.replace(e, '')
            if not t.strip():
                continue
            (scr if after else vis).append(t.strip())
        if vis or scr:
            boxes.append((vis, scr))
    merged = []
    for vis, scr in boxes:
        joined = (merged and len(merged) >= min_boxes     # never below the PSX
                  and not scr and not merged[-1][1]
                  and len(merged[-1][0]) + len(vis) <= 3)
        if joined:
            merged[-1] = (merged[-1][0] + vis, [])
            continue
        merged.append((list(vis), list(scr)))
    out = []
    for vis, scr in merged:
        body = line.join(vis)
        if scr:
            # '<FF02><FF03>' - the engine's order: scroll first, then the pen
            # moves to the new last line
            body += wait + line + line.join(scr)
        out.append(body)
    res = (wait + page).join(out)
    # A CHOICE ROW ENDS WITH ITS OPTION BLOCK: no dismissal wait after it (the
    # wait would stop the options arming). The box's own
    # wait belongs to a text box, not to the block.
    res += (tail if block else (wait + tail if tail else ''))
    return res.replace('\x01CHOICE\x01', block) if block else res


def _clean(en):
    # NO LINE BEGINS WITH PUNCTUATION. A colon (a label's, most of all) that
    # stranded at a line start belongs to the line above: "Saeko Takami:" then
    # the description, never "Saeko Takami" / ": Homeroom teacher".'
    en = re.sub(r'<FF03>: *', ':<FF03>', en)
    en = re.sub(r'<FF03>([,.;!?]) *', r'\1<FF03>', en)
    en = re.sub(r':{2,}', ':', en)

    """Strip JA padding blanks around codes and box edges; the box must
    open on text, never on blanks or a wait. Name inserts (FF07/08/0F)
    render as words, so spaces around them are real English spacing and
    must survive (stripping them glues the name to its neighbours:
    "Mark:<name>found"). Pauses (FF05) keep their neighbours' spacing for
    the same reason ("Mark: <pause> Dammit!", never "Mark:<pause>Dammit!").
    vwf_wrap owns the rule (the reflow uses it too)."""
    return vwf_wrap.clean_edges(en)


_PSXC = {}
_USPC = {}
_JSPC = {}
_ALIGN_IDX = None


def psx_entries(f):
    if f not in _PSXC:
        _PSXC[f] = efile.load(os.path.join(ROOT, 'data', 'psx', 'ADV', f + '.BIN')).entries
    return _PSXC[f]


def usp_entries(f):
    if f not in _USPC:
        _USPC[f] = load_psp(f, 'us').entries
    return _USPC[f]


def jsp_entries(f):
    if f not in _JSPC:
        _JSPC[f] = load_psp(f, 'jp').entries
    return _JSPC[f]


def align_idx():
    global _ALIGN_IDX
    if _ALIGN_IDX is None:
        _ALIGN_IDX = {}
        # header-keyed parse, list-shaped for the positional consumers
        # below (row lists keep header order, so r[i] semantics hold);
        # Reject header/row drift to prevent binding a row to the wrong fields.
        cols = strlib.tsv_cols(ALIGN)
        for row in strlib.tsv_rows(ALIGN, required=cols):
            r = [row[c] for c in cols]
            # generated rows carrying a duplicate-wording repair append the
            # donor as a tuple (same shape align_fix's extended rows use)
            src = None
            if (len(r) >= 9 and row['src_file']
                    and row['src_entry'].isdigit() and row['src_box'].isdigit()):
                src = (row['src_file'], int(row['src_entry']), int(row['src_box']))
            r = r[:6]
            if src is not None:
                r += ['', src]
            if row['entry'].isdigit() and row['psx_box'] not in ('', 'None'):
                _ALIGN_IDX.setdefault((row['file'], int(row['entry'])), {})[
                    int(row['psx_box'])] = r
        # manual alignment repairs win (repair_alignment.py): (file, entry, psx, jp, us)
        # extended rows append (sfile, sentry, sbox): US text comes from there
        fx = os.path.join(toolbelt.SOURCE_MAPPINGS, 'align_fix.tsv')
        if os.path.exists(fx):
            for n, line in enumerate(open(fx, encoding='utf-8').read().split('\n'), start=1):
                if not line.strip():
                    continue
                r = line.rstrip('\r').split('\t')
                if len(r) not in (5, 8):
                    raise ValueError(f'{fx}:{n}: expected 5 or 8 fields, '
                                     f'got {len(r)}: {line[:80]!r}')
                if not r[2].isdigit():
                    raise ValueError(f'{fx}:{n}: psx_box {r[2]!r} not a number')
                f, ei, k = r[0], int(r[1]), int(r[2])
                u = r[4] if len(r) > 4 and r[4] not in ('', 'None') else None
                src = None
                if len(r) >= 8 and r[5] and r[6].isdigit() and r[7].isdigit():
                    src = (r[5], int(r[6]), int(r[7]))
                jp = r[3] if len(r) > 3 and r[3] not in ('', 'None') else ''
                row = [f, str(ei), str(k), jp, u if u is not None else '',
                       'ok' if u is not None else 'gap-fixed', '']
                if src is not None:
                    row.append(src)
                _ALIGN_IDX.setdefault((f, ei), {})[k] = row
    return _ALIGN_IDX


# Who's who (PSP descriptive labels + JA/EN names -> character)
WHO = strlib.glossary('who')


_JPM = None


def jp_map():
    global _JPM
    if _JPM is None:
        _JPM = {}
        p = toolbelt.PSP_GLYPHS
        for u, ch in strlib.tsv_fields(p, 2):
            _JPM[int(u, 16)] = ch
    return _JPM


def jp_text(raw):
    import difflib as _d  # noqa
    from codec import decode_box
    t = decode_box(raw, jp_map(), holes=[])   # markers visible; stripped below
    t = re.sub(r'<FF[0-9A-F]{2}>|\[[0-9a-f]{4}\]', '', t)
    return re.sub(r'\s+', '', t)


def psx_text(raw):
    t = etext.decode(raw)
    t = re.sub(r'<FF[0-9A-F]{2}>|<G[0-9A-F]{3}>|<[0-9A-F]{2}>', '', t)
    return re.sub(r'\s+', '', t)


def textsim(a, b):
    import difflib
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _live_slot(f, ei, psx, k):
    import match_jp
    psx_rel = 'ADV/' + f
    t = match_jp.psx_id_twin(psx_rel, f'{ei}:{psx.boxes[k][0]:#x}')
    if t is None:
        return None
    ut = match_jp.us_twin(match_jp.psx_jp_rel(psx_rel), t)
    if ut is None:
        return None
    return f, int(ut['entry']), int(ut['box'])


def _slot_pair(f, ei, psx, k):
    """(us_raw, us_box) for a PSX box via the slot join, or None.

    align.tsv is derived and this box has no 'ok' row in it. The PSP kept
    the script's SLOTS, so this box's (entry, box) - +-2 for boxes the
    build inserted or cut, validated by text overlap - names the same
    line even where the PSP rewrote it (nameplates, full stops), and that
    line's US twin holds the English. match_jp.psx_id_twin is the one
    implementation; nothing here re-judges a pair. The PSP-JP lookup is
    frozen as a text-free pointer (story_port_plan) for replay."""
    found = story_port_plan.slot(
        f, ei, psx.boxes[k][0], lambda: _live_slot(f, ei, psx, k))
    if found is None:
        return None
    sfile, sei, sk = found
    try:
        return usp_entries(sfile)[sei].box_bytes(sk), sk
    except Exception:
        return None


def convert_entry(f, ei):
    psx = psx_entries(f)[ei]
    usp = usp_entries(f)[ei]
    by_psx = align_idx().get((f, ei), {})
    # (invented scroll waits, of them cuts not at a sentence end) - totals for
    # this entry; the waits themselves are in the emitted rows (<FF02>).
    counts = [0, 0]
    out = []
    prev_lab = None  # last box's emitted speaker label (repeats are dropped)
    prev_ja = None  # last box's JA speaker label (continuity corroboration)
    for k in range(len(psx.boxes)):
        ja = etext.decode(psx.box_bytes(k))
        r = by_psx.get(k)
        us_raw, u = None, None
        if r is not None and r[5] == 'ok':
            u = int(r[4]) if r[4] not in ('', 'None') else None
            if len(r) > 7 and isinstance(r[7], tuple):
                sfile, sei, sk = r[7]
                us_raw = usp_entries(sfile)[sei].box_bytes(sk)
                u = sk  # for messages below
            else:
                us_raw = usp.box_bytes(u)
        else:
            pair = _slot_pair(f, ei, psx, k)
            if pair is None:
                out.append((k, ja, None, 'no-pair:%s' % (r[5] if r else '?')))
                prev_lab = None
                prev_ja = None
                continue
            us_raw, u = pair
        # card-mismatch: exactly one side is a portrait/style card. US cards
        # are FF18 portraits or FF06-headed plain-text cards.
        us_card = us_raw[:2] == b'\xff\x18' and len(us_raw) > 6 and us_raw[2:4] in (
            b'\x02\x00', b'\x03\x00')
        us_text_card = us_raw[:2] == b'\xff\x06'
        if ja.startswith('<FF06>') != (us_card or us_text_card):
            ja0 = etext.decode(psx.box_bytes(k))
            out.append((k, ja0, None, 'card-mismatch'))
            prev_lab = None
            prev_ja = None
            continue
        # intro cards (FF06 portrait boxes) take the custom path
        if ja.startswith('<FF06>'):
            card = parse_card(us_raw)
            if card is None:
                # nickname-less staff card: resolve name via PSX JA slot
                # (card-type prefix い/う stripped: 'い反谷教頭' -> '反谷教頭')
                psx_name = None
                for kind, val in psx_tok_raw(psx.box_bytes(k)):
                    if kind == 't' and val.strip('　 '):
                        psx_name = val.strip('　 ').split('（')[0].strip()
                        if psx_name[:1] in ('い', 'う'):
                            psx_name = psx_name[1:]
                        break
                if psx_name is not None:
                    card = parse_card_simple(us_raw, psx_name)
                if card is None and psx_name is not None:
                    card = parse_card_text(us_raw, psx_name)
            if card is None:
                out.append((k, ja, None, 'card-parse-fail'))
                prev_lab = None
                prev_ja = None
                continue
            name, nick, words = card
            en = _clean(card_en(psx.box_bytes(k), us_raw, name, nick, words))
            # A CARD SOURCE THAT IS STILL JAPANESE IS NOT A TRANSLATION, the
            # same rule the dialogue path applies below: PSP-US left some
            # profile cards untranslated, and building one here ships kana in
            # an `en` cell (then trips the width check). The box stays a gap.
            import port_derive
            if port_derive.still_japanese(en):
                out.append((k, ja, None, ''))
                prev_lab = None
                prev_ja = None
                continue
            errs = []
            for ln in re.split(r'<FF0[234]>', en):
                plain = re.sub(r'<[^>]+>', '', ln)
                if plain and vwf_wrap.text_width(plain) > vwf_wrap.BOX_WIDTH + 1:
                    errs.append('wide:%dpx' % vwf_wrap.text_width(plain))
                    break
            out.append((k, ja, en, '; '.join(errs)))
            prev_lab = None  # cards are name plates, not textbox labels
            prev_ja = None
            continue
        segments, flags = us_parts(us_raw, ja=ja)
        toks = psx_tok_raw(psx.box_bytes(k))
        ja_label, toks = split_label(toks)
        # hero grunt: the US speaker is the hero name-variable ({surname
        # given} in braces: FF1B 002f..0030, inner glyphs unmapped) while
        # the PSX box is spoken by the name insert itself (FF07+param, no
        # literal label). Keep the PSX skeleton (name slot, colon, waits;
        # nothing invented) and take the PSP-US body. Only this shape
        # qualifies.
        if ja_label is None and segments:
            lab_codes = []
            i = 2
            if us_raw[:2] == b'\xff\x1b':
                while i + 1 < len(us_raw) and us_raw[i] != 0xFF:
                    lab_codes.append(struct.unpack_from('>H', us_raw, i)[0])
                    i += 2
            namevar = (len(lab_codes) > 2 and lab_codes[0] == 0x002f
                       and lab_codes[-1] == 0x0030
                       and all(US_MAP.get(u, '') == ''
                               for u in lab_codes[1:-1]))
            t0 = next((v for kd, v in toks if kd == 't' and v), '')
            m = re.match(r'^(：+)', t0)
            c0 = next((v for kd, v in toks if kd == 'c'), '')
            if (namevar and m
                    and re.fullmatch(r'<FF07><[0-9A-F]{2}>', c0)):
                # Synthesize the protagonist parameter for the name label.
                c0 = '<FF07><01>'
                words = [w for _lab, w in segments for w in w
                         if isinstance(w, str) and not w.startswith(US_BRK)]
                body = ' '.join(words).strip()
                codes = [t for kind, t in toks if kind == 'c']
                tail = ''.join(c for c in codes[1:]
                               if c.startswith(('<FF02>', '<FF01>')))
                if body:
                    en = _clean(c0 + m.group(1) + body
                                + (tail if '<FF01>' in tail else tail + '<FF01>'))
                    out.append((k, ja, en, ''))
                    prev_lab = None  # name insert, no literal label shown
                    prev_ja = None
                    continue
        # resolve first label: PSP > HAND/PSP-names fallback > none (PSP style)
        first_lab = segments[0][0] if segments else None
        if ja_label and not first_lab:
            bare = ja_label.rstrip('：')
            if bare in HAND_LABELS:
                pass  # PSP-US heading words are emitted from its own stream
            elif bare in psp_names():
                first_lab = psp_names()[bare]
            else:
                flags.append('label-manual:%s' % ja_label)
        # speaker-mismatch: both sides name different characters; arbitrate
        # by content (PSX-JA vs JP-partner): same scene = PSP refinement,
        # different scene = misalignment for manual review. accept.tsv holds
        # reviewed-good pairs that keep their (reattributed) labels.
        if ja_label and first_lab:
            jb = ja_label.rstrip('：')
            pn = psp_names()
            wc = WHO.get(first_lab, first_lab)
            wj = WHO.get(jb, pn.get(jb, jb))
            if wc != wj and 'Girl' not in first_lab and (
                    wc in pn.values() or wj in pn.values()
                    or (jb in WHO and first_lab in WHO)):
                if (f, ei, k) in accepted_pairs():
                    pass  # reviewed reattribution; US label stands
                else:
                    try:
                        jidx = int(r[3]) if len(r) > 3 and str(r[3]).isdigit() else None
                        if jidx is None:
                            flags.append('speaker-mismatch:%s>%s' % (jb, first_lab))
                        else:
                            def _same_scene():
                                jent = jsp_entries(f)[ei]
                                if jidx >= len(jent.boxes):
                                    raise IndexError('JP box missing')
                                jraw = jent.box_bytes(jidx)
                                ptxt = psx_text(psx.box_bytes(k))
                                return (textsim(ptxt, jp_text(jraw)) >= 0.45,
                                        jraw)
                            if story_port_plan.decide(
                                    f, ei, k, jidx, _same_scene):
                                pass  # same scene: PSP refinement, keep US label
                            else:
                                flags.append('speaker-mismatch:%s>%s' % (jb, first_lab))
                    except story_port_plan.PlanError:
                        raise
                    except Exception as ex:
                        flags.append('speaker-mismatch:%s>%s:arbitrate-err' % (jb, first_lab))
        # Retail label presence wins: a PSX box with no speaker label shows
        # none even when PSP labels every box of the run (continuations,
        # choice prompts). Nulling first_lab here keeps mid-box restatements
        # and lets width/pagination below reclaim the line.
        if not ja_label and first_lab:
            first_lab = None
        # Keep dot-words even when the skeleton has FF05 pauses: the PSP
        # draws both, and its wording is ported verbatim.
        # Keep PSX text slots as distribution anchors, but render all header
        # words from PSP-US; no fixed/hand-authored English labels.
        tracks = list(toks)
        # flatten segments into items with breaks
        items = []
        # EN mid-box restatements keep their speaker name iff the JA box
        # states one here too (positional, in box order): a PSP "Name:"
        # with no JP "X：" behind it degrades to a bare break. Same rule
        # as the box-leading presence check above, just per restatement.
        ja_mid = jp_mid_labels(toks)
        for si, (lab, w) in enumerate(segments):
            if si > 0:
                if lab is not None and ja_mid:
                    ja_mid.pop(0)
                elif lab is not None:
                    lab = None
                items.append(('b', lab))
            for x in w:
                if isinstance(x, str) and x.startswith(US_BRK):
                    items.append(('u', x[len(US_BRK):]))
                else:
                    items.append(('w', x))
        # header slots keep fixed rendering (handled in reflow's build loop)
        toks2 = list(tracks)

        def finish(items_in):
            e2, used2, rf2 = reflow(first_lab, items_in, toks2)
            flags.extend(rf2)
            if not e2.endswith('<FF01>'):
                e2 += '<FF01>' if '<FF01>' not in e2 else ''
            nwords = sum(1 for it in items_in if it[0] == 'w')
            if used2 < nwords:
                got = [it[1] for it in items_in if it[0] == 'w']
                flags.append('leftover:%s' % ' '.join(got[used2:])[:80])
            e2, inv1, nons1 = paginate(e2)
            # Choice options must start their own line (same rule as tstatus
            # QA): where their break goes is the pen's - vwf_wrap owns it
            # (a mid-line pen needs its break ("me?Yes"), a full pre-line is
            # already at line start and a break there skips a line: E0/1/1).
            if '<FF0E>' in e2:
                e2 = vwf_wrap.choice_breaks(e2)
            # strip edge whitespace (JA padding blanks must not leak into EN)
            e2 = _clean(e2)
            # enforce can push a page to 4 lines: paginate again so waits split it
            e2, inv2, nons2 = paginate(e2)
            inv1 += inv2
            nons1 += nons2
            if inv1:
                # The invented waits are IN the row (<FF02>), so the generated
                # table already says what the box does; no per-box console
                # line. cmd_bulk totals them per file and files the mid-
                # sentence cuts under scratch/translation_reports/.
                counts[0] += inv1
                counts[1] += nons1
            return e2

        en = finish(items)
        # A FREE JOIN, DOWN TO THE PSX'S OWN COUNT AND NO FURTHER: the PSX draws
        # this box as 1 + its own <FF04> pages, the PSP's boxes are kept unless
        # the pair fits three lines (the count stays in
        # [psx boxes, psp boxes], never smaller than either).
        en = merge_boxes(en, min_boxes=1 + ja.count('<FF04>'))
        # THE OPTION BLOCK'S ARMING LINE IS THE LAYOUT'S, NOT THE JP'S. The
        # JP's wait is a proxy for ITS prompt length; the English prompt is a
        # different length, so copying the JP's wait either invents a press on
        # a one-line prompt or leaves a two-line prompt to scroll by itself
        # under the player. vwf_wrap.choice_breaks owns it: no wait when the prompt
        # fits above the options, '<FF02>' when it does not (the corpus' own
        # 463 '<FF02><FF03><FF0E>' rows) - no options until the player
        # presses, then exactly one scroll.
        if '<FF0E>' in en:      # an option always starts its own line
            en = vwf_wrap.choice_breaks(en)
        # THE PSP'S BOXES ARE THE AUTHOR'S (spec 3.1). A run of PSP boxes is
        # KEPT, not re-flowed to the Japanese word positions or stripped of
        # their waits. The PSX holds as many boxes as the text needs -
        # the box count is free - so there is nothing to trade away. A PSP box
        # whose English needs more than 3 lines scrolls ONCE (paginate owns
        # that); nothing is stuffed or squeezed, and the line count the PSX
        # shows is kept whenever the words fit without it.
        # NOTE: line widths are QA's job (tstatus width warnings), never the
        # porter's gate: over-wide textbox lines build as-is and are never
        # shortened, skipped, or gapped. No width errors are recorded here.
        out.append((k, ja, en, '; '.join(flags)))
        prev_lab = first_lab
        prev_ja = ja_label
    return out, counts


def _one(arg):
    """Worker: convert one entry, return plain data."""
    f, ei = arg
    rows, counts = convert_entry(f, ei)
    return f, ei, rows, counts


def psp_lookup(f):
    """(entry, box) -> psp provenance pointer for one story file: the unit
    in extracted_text/psp_us/pack/<E?>.tsv that supplied the English.

    The pointer must name the same box the porter read, so it goes through
    the same `align_idx()` table (generated align.tsv plus reviewed
    align_fix overrides), including a cross-file source row. A box with no
    binding keeps its own coordinate: provenance is the raw PSP-US slot
    only when the porter fell back to the slot join."""
    import toolbelt
    idx = {(r['entry'], r['box']): r['id']
           for r in toolbelt.read_extracted('psp_us', f'pack/{f}', optional=True)}
    by_file = {}

    def us_id(file, entry, box):
        if file not in by_file:
            by_file[file] = {
                (r['entry'], r['box']): r['id']
                for r in toolbelt.read_extracted(
                    'psp_us', f'pack/{file}', optional=True)}
        return by_file[file].get((str(entry), str(box)))

    def get(entry, box):
        e, b = str(entry), str(box)
        r = align_idx().get((f, int(e)), {}).get(int(b)) if b.isdigit() else None
        if r is not None and r[5] == 'ok':
            if len(r) > 7 and isinstance(r[7], tuple):
                sf, se, sb = r[7]
                rid = us_id(sf, se, sb)
                return f'{sf}:{rid}' if rid is not None else f'{sf}:'
            rid = idx.get((e, r[4]))
            return f'{f}:{rid}' if rid is not None else ''
        rid = idx.get((e, b))
        return f'{f}:{rid}' if rid is not None else ''
    return get


def store_generated(ports, replace_entry=None):
    """Store PSP-derived English into the per-file tables (docs/
    TEXT_ARCHITECTURE.md): pos = 'entry:boxstart' (archive sub-structure),
    psp = the source unit's pointer, manual = the gap queue (auto-cleaned)."""
    import toolbelt
    import efile as _efile
    by_file = {}
    for f, e, b, ja, en in ports:
        by_file.setdefault(f, []).append((e, b, ja, en))
    n = 0
    gap_jp = []
    gap_width = []
    for f, rows in by_file.items():
        entries = _efile.load(os.path.join(ROOT, 'data', 'psx', 'ADV', f + '.BIN')).entries
        psp_of = psp_lookup(f)
        rel = f'ADV/{f}'
        auto = []
        for e, b, ja, en in rows:
            if not (en or '').strip():
                continue
            # A SOURCE THAT IS STILL JAPANESE IS NOT A TRANSLATION. The
            # PSP-US pack carries a few untranslated boxes (E1's Snow Queen
            # and Agastya Tree lines are kana in the US build too), and a
            # porter that stores one ships kana in an `en` cell - no charset
            # can encode it and QA calls it an error. The box stays a gap
            # (the PSX Japanese ships) until a real source fills it. Same
            # rule, same matcher as the re-derivation net (port_derive).
            import port_derive
            if port_derive.HOLES.search(port_derive.ink_of(en)):
                gap_jp.append((f, e, b))
                continue
            # THE PSP'S HEAD MARK IS FURNITURE and only THIS box's Japanese
            # can justify one (port_derive.head_marks): the PSP opens a line with
            # '＞', the PSX draws one only where its own bytes carry it. Doing
            # it here - where the PSX Japanese is in hand - is what keeps the
            # stored row right on the first pass instead of leaving it to the
            # re-derivation net (which cannot see a box-index pointer).
            en = port_derive.head_marks(en, ja)
            s, _e = entries[e].boxes[b]
            pos = f'{e}:{s:#x}'
            # A row that still cannot lay itself out is the source's wording,
            # so it becomes an over-limit draft (the Japanese ships) instead
            # of stopping the build.
            reason = port_derive.unlayable_note(en, placed=True)
            if reason:
                toolbelt.route_over(rel, pos, psp_of(e, b), en, reason)
                gap_width.append(f'{f}/{e}/{b}: {reason}')
                continue
            row = {'pos': pos, 'en': en}
            psp = psp_of(e, b)
            if psp:                        # missing key keeps any existing pointer on upsert
                row['psp'] = psp
            auto.append(row)
        n += toolbelt.upsert_generated(rel, auto)
        # the gap queue: every box of the file that has no translation yet
        spots = [f'{e}:{s:#x}'
                 for e, ent in enumerate(entries) for s, _x in ent.boxes]
        toolbelt.route_gaps(rel, spots)
    if gap_jp:
        # silence would look like a clean port: name what stayed Japanese
        print('kept as gaps (source is still Japanese, not a translation): '
              + ', '.join(f'{f}/{e}/{b}' for f, e, b in gap_jp))
    if gap_width:
        print('over-limit dialogue drafted to manual: '
              + '; '.join(gap_width))
    return n


def cmd_bulk(apply=False, jobs=None):
    import multiprocessing as mp
    import efile as _efile
    # The text caches must reflect the glyph map: regenerate when stale.
    from text import cmd_cache as _recache
    _map = toolbelt.PSP_GLYPHS
    if not os.environ.get(story_port_plan.REPLAY_ENV):
        _probe = os.path.join(ROOT, 'data', 'extracted_text', 'psp_jp', 'pack', 'E0.tsv')
        if os.path.exists(_map) and (not os.path.exists(_probe)
                                     or os.path.getmtime(_map) > os.path.getmtime(_probe)):
            print('glyph map newer than text cache: regenerating extracts')
            _recache('jp', strict=False)   # holes print loud; the port continues
            _recache('us', strict=False)   # (hole-carrying rows route to gaps)
    # preload shared read-only data before forking (CoW-shared with workers)
    for f in ('E0', 'E1', 'E2', 'E3'):
        psx_entries(f)
        usp_entries(f)
    align_idx()
    entry_ids = [(f, ei) for f in ('E0', 'E1', 'E2', 'E3')
                 for ei in range(len(psx_entries(f)))]
    if jobs is None:
        jobs = min(8, os.cpu_count() or 4)
    if jobs > 1:
        with mp.Pool(jobs) as pool:
            results = pool.map(_one, entry_ids)
    else:
        results = [_one(a) for a in entry_ids]
    by_file = {}
    waits = {}                      # f -> [invented scrolls, of them mid-sentence cuts]
    for f, ei, rows, counts in results:
        by_file.setdefault(f, []).append((ei, rows))
        tally = waits.setdefault(f, [0, 0])
        tally[0] += counts[0]
        tally[1] += counts[1]
    # identical-text reuse: a gap card byte-identical to clean port(s) adopts
    # their English when all donors agree. Cards only (FF06 name+description
    # units are context-free); dialogue lines can deictically differ between
    # scenes even with identical bytes, so those stay gaps. The gap's own
    # errors must be pairing failures (card-parse-fail, no-pair, unmapped
    # US words); text problems are never papered over. E.g. a profile card
    # duplicated across entries where only one US copy was translated.
    _PAIR_ERRS = ('no-pair', 'card-parse-fail', 'unmapped')
    donor_en = {}
    donor_ok = {}
    for f in ('E0', 'E1', 'E2', 'E3'):
        for ei, rows in sorted(by_file.get(f, [])):
            for k, ja, en, errs in rows:
                if en and not errs:
                    try:
                        raw = bytes(psx_entries(f)[ei].box_bytes(k))
                    except Exception:
                        continue
                    donor_en.setdefault(raw, set()).add(en)
    for raw, ens in donor_en.items():
        if len(ens) == 1 and raw[:2] == b'\xff\x06':
            donor_ok[raw] = next(iter(ens))
    n_borrowed = 0
    fixed_rows = []
    for f, ei, rows, counts in results:
        new_rows = []
        for k, ja, en, errs in rows:
            if en is None and (not errs or errs.startswith(_PAIR_ERRS)):
                try:
                    raw = bytes(psx_entries(f)[ei].box_bytes(k))
                except Exception:
                    raw = None
                if raw is not None and raw in donor_ok:
                    print(f'--- {f}/{ei} box {k}: identical-text borrow')
                    new_rows.append((k, ja, donor_ok[raw], ''))
                    n_borrowed += 1
                    continue
            new_rows.append((k, ja, en, errs))
        fixed_rows.append((f, ei, new_rows, counts))
    results = fixed_rows
    by_file = {}
    for f, ei, rows, counts in results:
        by_file.setdefault(f, []).append((ei, rows))
    print(f'identical-text borrows: {n_borrowed}')
    total_clean = total_gap = total_err = 0
    ported_all = []
    auto_dir = os.path.join(ROOT, 'scratch', 'translation_reports')  # diagnostics, not translation tables
    os.makedirs(auto_dir, exist_ok=True)
    errlog = open(os.path.join(auto_dir, 'story_errors.tsv'), 'w', encoding='utf-8')
    errlog.write('file\tentry\tbox\terrors\tja\n')
    for f in ('E0', 'E1', 'E2', 'E3'):
        for ei, rows in sorted(by_file.get(f, [])):
            for k, ja, en, errs in rows:
                if en is None:
                    total_gap += 1
                elif errs:
                    total_err += 1
                    if total_err <= 15:
                        print(f'--- {f}/{ei} box {k}: {errs[:100]}')
                    errlog.write(f'{f}\t{ei}\t{k}\t{errs}\t{ja[:120]}\n')
                if en is None or errs:
                    continue
                total_clean += 1
                if apply:
                    ported_all.append((f, ei, k, ja, en))
        print(f'{f}: found {sum(1 for r in ported_all if r[0] == f)} clean PSP ports')
    for f in ('E0', 'E1', 'E2', 'E3'):
        inv, nons = waits.get(f, (0, 0))
        if inv:
            print(f'{f}: {inv} scroll waits placed by paginate (<FF02> in the rows)'
                  + (f', {nons} cut mid-sentence' if nons else ''))
    print(f'BULK: {total_clean} clean, {total_gap} gaps, {total_err} errors')
    errlog.close()
    print('errors listed in scratch/translation_reports/story_errors.tsv')
    if apply:
        n = store_generated(ported_all)
        print(f'wrote {n} clean PSP-derived English rows under translation/generated/ADV/')
        # deviation audit: every EN/JA code difference must be a known
        # PSP-deliberate class (added/dropped names, PSP-valued choices);
        # anything else is porter corruption, reported loudly (the build QA
        # gate fails the build on it, so it can never slip through quiet).
        all_devs = {}
        n_unexplained = 0
        for f, ei, k, ja, en in ported_all:
            devs, ok = tstatus.classify_deviations(ja, en)
            if not ok:
                n_unexplained += 1
                print(f'DEVIATION-UNEXPLAINED {f}/{ei}/{k}: {en[:100]!r}')
            elif devs:
                all_devs[(f, ei, k)] = devs
        with open(os.path.join(auto_dir, 'psp_deviations.tsv'), 'w', encoding='utf-8', newline='\n') as o:
            o.write('file\tentry\tbox\tkind\tja\ten\n')
            for (f, ei, k), devs in sorted(all_devs.items()):
                for kind, jt, et in devs:
                    o.write(f'{f}\t{ei}\t{k}\t{kind}\t{jt}\t{et}\n')
        print(f'wrote {len(all_devs)} rows with PSP-deliberate deviations'
              + (f' [{n_unexplained} UNEXPLAINED]' if n_unexplained else ''))
        stale = os.path.join(auto_dir, 'name_inserts.tsv')
        if os.path.exists(stale):
            os.remove(stale)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--bulk':
        if '--without-psp-jp' in sys.argv:
            os.environ[story_port_plan.REPLAY_ENV] = str(story_port_plan.PLAN)
        cmd_bulk(apply='--apply' in sys.argv)
        return
    f, ei = sys.argv[1], int(sys.argv[2])
    apply = '--apply' in sys.argv
    verify = '--verify' in sys.argv
    rows, counts = convert_entry(f, ei)
    if counts[0]:
        print(f'{f}/{ei}: {counts[0]} scroll waits placed by paginate '
              f'(<FF02> in the rows), {counts[1]} cut mid-sentence')
    nok = sum(1 for _, _, en, e in rows if en and not e)
    print(f'{f}/{ei}: {nok}/{len(rows)} clean')
    if verify:
        tsv = os.path.join(ROOT, 'translation', 'generated', 'ADV', f'{f}.tsv')
        cur = {}
        if os.path.exists(tsv):
            for row in strlib.tsv_rows(tsv, required=('entry', 'box', 'en')):
                if row['entry'] == str(ei) and row['box'].isdigit():
                    cur[int(row['box'])] = row['en']
        ndiff = 0
        for k, ja, en, errs in rows:
            if en and not errs and k in cur and cur[k] != en:
                ndiff += 1
                print(f'--- box {k} DIFFERS from generated PSP text')
                print(f'  table: {cur[k][:160]}')
                print(f'  fresh: {en[:160]}')
        print(f'verify: {ndiff} generated rows differ')
        return
    for k, ja, en, errs in rows:
        if errs or en is None:
            print(f'--- box {k}: {errs}')
            print(f'  ja: {ja[:130]}')
            print(f'  en: {(en or "")[:220]}')
    if apply:
        ports = [(f, ei, k, ja, en) for k, ja, en, errs in rows if en and not errs]
        n = store_generated(ports, replace_entry=(f, ei))
        print(f'updated generated PSP text for {f}/{ei}: {len(ports)} boxes ({n} total)')


if __name__ == '__main__':
    main()
