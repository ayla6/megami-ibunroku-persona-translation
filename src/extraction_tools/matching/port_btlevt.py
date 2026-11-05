"""Port the story-battle dialogue of BTLP.BIN (btlevt zone) from the PSP-US
EBOOT battle cluster.

Matching is Japanese-to-Japanese (the doctrine: never names, always the
data): every PSX message is fuzzy-matched against the extracted PSP-JP
battle cluster (extracted_text/psp_jp/EBOOT.tsv), which pins the box
correspondence. The wording then comes from the parallel PSP-US units
(extracted_text/psp_us/EBOOT.tsv), bridged JP<->US by Needleman-Wunsch on
box skeletons (align.nw - the merge/split handler).

The en keeps the PSX skeleton (btlevt's QA: exactly the Japanese control
codes, newlines free): words from PSP-US, breaks at the PSP box
boundaries, lines re-wrapped to <= 239px / 4 lines per page (three
visible plus the fourth scroll line).

  python src/extraction_tools/matching/port_btlevt.py [--apply]
  python src/extraction_tools/matching/port_btlevt.py --apply --without-psp-jp
      (replay a text-free correspondence plan)
"""
import difflib
import math
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
sys.path.insert(0, HERE)
import etext       # noqa: E402
import toolbelt    # noqa: E402
import vwf_wrap    # noqa: E402
import btlevt      # noqa: E402
import btlp        # noqa: E402 (the evt family's own placement rule: evt_accept)
import port_derive  # noqa: E402 (the shared furniture: nameplate, label, flow)
import match_jp     # noqa: E402 (the code-parameter rule, one place)
from align import nw, sim   # noqa: E402

# the battle-dialogue clusters (EBOOT units; both sides hold the same
# boxes in the same story order - the PSX zone runs the order in reverse).
# The bound is EXCLUSIVE (read_be takes [lo, hi)): the last US record starts
# at 0x29ea02 and must be included to preserve message order.
JP_LO, JP_HI = 0x28b986, 0x28d348
US_LO, US_HI = 0x29ba6a, 0x29ea30

# A RECORD ENDS '<FF02><FF01>' (wait, end) or '<FF02><FF04>' (wait, page -
# the text continues in the next box). NOTHING ELSE ends it: '<FF05>' is a
# mid-box beat, not an end marker.
END_RE = re.compile(r'(<FF02><FF0[14]>).*?$')
CODE_RE = re.compile(r'<FF([0-9A-F]{2})>')
BOX_RE = re.compile(r'<FF02><FF0[14]>|<FF05>')


def norm(t, psx=False):
    """Noise-free Japanese for matching: codes and their parameters,
    whitespace and punctuation gone (the JP glyph map drops/misreads a few
    characters; difflib eats the rest). `psx` marks a PSX line, whose name
    inserts carry the member id as a parameter unit that the PSP's do not
    (match_jp.strip_params) - left in, it is one stray character in the
    middle of the line.

    FULLWIDTH LATIN FOLDS TO ASCII: the PSX spells an English word inside a
    Japanese line in its fullwidth cells ('結構　Ｌｏｖｅｌｙですわね！') while
    the PSP-JP spells the same word halfwidth ('結構,Lovelyですわね!'), and
    the two are the same line - without the fold they scored 0.62 and the
    row fell out as 'no mechanical source'."""
    t = CODE_RE.sub('', match_jp.strip_params(t, psx))
    return re.sub(r'[\s\u3000：:、。！？…♥「」\[\]]', '',
                  unicodedata.normalize('NFKC', t))


def nlab(lab):
    """Speaker label normalized ('条：' -> '条'): the JP side keeps the
    separator colon in the label, the US side does not."""
    return lab.rstrip('\uff1a: ').strip()


def label_of(body):
    """The box's speaker label - the nameplate read as structure, in the
    spelling the view carries (port_derive.label_head: '<FF1B>name<FF03>',
    the PSP-US '￥N' form, or the code-less 'name<FF03>' record view).
    Body-text first lines are not labels. A first line whose continuation
    starts lowercase is a WRAPPED SENTENCE, never a speaker ('I've had
    enough<FF03>with the fun and games already!')."""
    lab, rest = port_derive.label_head(body, bare=True)
    if not lab:
        return ''
    if CODE_RE.sub('', rest).lstrip()[:1].islower():
        return ''
    return nlab(lab)


def skel(t):
    """(control codes, text length, speaker label) of a decoded box."""
    body = END_RE.sub('', t)
    return (tuple(int(c, 16) for c in CODE_RE.findall(t)),
            len(CODE_RE.sub('', t)), label_of(body))


def sim_battle(a, b, amap=None):
    """Battle-box similarity. The two localizations paginate differently,
    so codes/length drift; the SPEAKER sequence is parallel (same script).
    amap = jp label -> us label (voted from a first alignment pass)."""
    (ca, la, pa), (cb, lb, pb) = a, b
    if pa and pb:
        if amap and amap.get(pa) == pb:
            s = 8
        elif amap and (pa in amap or pb in set(amap.values())):
            s = -3
        else:
            s = 2 if pa == pb else 0
    elif not pa and not pb:
        s = 4
    else:
        s = -1
    if ca and cb and ca[-2:] == cb[-2:]:
        s += 2
    if abs(len(ca) - len(cb)) <= 1:
        s += 1
    ratio = (la + 1) / (lb + 1)
    s += 2 if 0.25 <= ratio <= 4 else -2
    return s


def jp_units():
    return [(p, t) for p, t in toolbelt.read_eboot('jp') if JP_LO <= p <= JP_HI]


def us_units():
    # the be_runs record view (toolbelt.read_be): a record is the box the
    # porters address - the unit view keeps the label code and parameter
    # bytes inline, which the speaker/segment parsing then reads as text
    return [(p, t) for p, t in toolbelt.read_be(US_LO, US_HI)]


def match_psx_jp(psx, junits):
    """[(jp_lo, jp_hi) | None] per PSX message: best contiguous JP run,
    monotone (PSX ascends while the cluster descends)."""
    out = []
    cursor = len(junits) - 1
    for _off, ja in psx:
        target = norm(ja, psx=True)
        best, pick = 0.0, None
        if target:
            for k in (1, 2, 3, 4):
                for hi in range(cursor, max(cursor - 6, k - 2), -1):
                    lo = hi - k + 1
                    if lo < 0:
                        break
                    cand = ''.join(norm(junits[lo + j][1]) for j in range(k))
                    r = difflib.SequenceMatcher(None, target, cand).ratio()
                    if r > best:
                        best, pick = r, (lo, hi)
        if best >= 0.62 and pick:
            out.append(pick)
            cursor = pick[0] - 1
        else:
            out.append(None)               # gap row: no mechanical source
    return out


def proven_pairs(junits, uunits):
    """{JP unit index: US unit index} where the SOURCE pairing already says
    which US record a JP record is.

    port_btlevt's own bridge is a monotone needleman-wunsch: it can shift a
    line or drop one, and it cannot express a REVERSAL at all - and the
    localisation stored this bank's quote block in the opposite order on the
    two builds, which is how 14 rows came to ship a neighbour's English
    ('南条：許さんぞ！' with 'Yukino: Careful, guys!'). The pair map
    (psp_pairs.tsv) and match_jp's whole-gap order join are pairings the
    evidence settled, so they override whatever the alignment guessed: a
    pair the map proves is never a guess, and an override that duplicates
    another index simply wins - the drifts it removes are exactly the ones
    the alignment made.

    Positions are the same spelling on both sides (the extract's own
    offsets), so this is a lookup, not a search."""
    import match_jp
    jp_ix = {p: i for i, (p, _t) in enumerate(junits)}
    us_ix = {p: j for j, (p, _t) in enumerate(uunits)}
    order = match_jp._order_pairs('EBOOT')
    out = {}
    for p, i in jp_ix.items():
        loc = match_jp._pairs().get(p) or order.get(p)
        if not loc:
            continue
        j = us_ix.get(toolbelt.psp_loc(loc))
        if j is not None:
            out[i] = j
    return out


def bridge_jp_us(junits, uunits, amap0=None):
    """JP unit index -> US unit index. Two passes: align on structure, vote
    the speaker-label pairs from the alignment (the labels are extracted
    text - never typed), then re-align with the name map."""
    A = [skel(t) for _p, t in junits]
    B = [skel(t) for _p, t in uunits]

    def run(amap):
        pairs = nw(A, B, sim_fn=lambda x, y: sim_battle(x, y, amap))
        return {i: j for i, j in pairs if i is not None and j is not None}

    if amap0 is not None:
        amap = dict(amap0)
        out = run(amap)
        out.update(proven_pairs(junits, uunits))
        return out, {}
    # seed: occurrence counts pair the labels (a speaker's count is a
    # fingerprint - extracted text, never typed)
    def counts(skel_list):
        c = {}
        for a in skel_list:
            if a[2]:
                c[a[2]] = c.get(a[2], 0) + 1
        return c
    jc, uc = counts(A), counts(B)
    jby, uby = {}, {}
    for k, v in jc.items():
        jby.setdefault(v, []).append(k)
    for k, v in uc.items():
        uby.setdefault(v, []).append(k)
    amap = {}
    for c, jl in jby.items():
        if c >= 2 and len(jl) == 1 and len(uby.get(c, [])) == 1:
            amap[jl[0]] = uby[c][0]
    # refine: vote label pairs from the seeded alignment
    votes = {}
    for i, j in run(amap).items():
        pa, pb = A[i][2], B[j][2]
        if pa and pb:
            votes.setdefault(pa, {}).setdefault(pb, 0)
            votes[pa][pb] += 1
    for pa, tally in votes.items():
        if pa in amap:
            continue                     # the count-unique seed stays
        top, n = max(tally.items(), key=lambda kv: kv[1])
        if n >= 2 and n >= 0.6 * sum(tally.values()):
            amap[pa] = top
    out = run(amap)
    out.update(proven_pairs(junits, uunits))
    return out, amap


def label_map(junits, uunits):
    """jp label -> us label. The two localizations tell the same story in
    the same order, so the speakers' FIRST-OCCURRENCE sequences align; a
    Needleman-Wunsch over them (paired by occurrence counts) derives the
    whole name map from the data - no name is ever typed."""
    def collect(rows):
        order, counts = [], {}
        for _p, t in rows:
            lab = label_of(END_RE.sub('', t))
            if lab:
                counts[lab] = counts.get(lab, 0) + 1
                if lab not in order:
                    order.append(lab)
        return order, counts
    jo, jc = collect(junits)
    uo, uc = collect(uunits)

    def sim(a, b):
        d = abs(jc[a] - uc[b])
        return 3 if d == 0 else (0.5 if d == 1 else -1)

    gap = -1.2
    n, m = len(jo), len(uo)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + gap
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + gap
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = max(dp[i - 1][j] + gap, dp[i][j - 1] + gap,
                           dp[i - 1][j - 1] + sim(jo[i - 1], uo[j - 1]))
    amap, i, j = {}, n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + sim(jo[i - 1], uo[j - 1]):
            if sim(jo[i - 1], uo[j - 1]) > 0:
                amap[jo[i - 1]] = uo[j - 1]
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + gap:
            i -= 1
        else:
            j -= 1
    return amap


def assign_spans(runs, j2u, junits, uunits, psx, amap):
    """One US span per matched message. The two localizations re-paginate
    boxes differently, so neighbour-anchored hulls drift across merge and
    split points; this instead tiles the cluster monotonically by
    message-level evidence: whose core partners land in the span, which
    speaker opens it, how much text it holds.

    ONLY A PROVEN MESSAGE TILES. A message whose first JP record the source
    pairing does not name has no US box of its own: the localisation merged
    it into a neighbour's box (JP 19's scream and JP 20 share PSP-US box
    27). It is left out of the tiling and SHARES the next proven message's
    box instead: its wording is that box's leading part, before the box's
    own <FF05> section
    mark (the proven message then takes the rest, so neither box repeats
    the other).

    -> ({psx index: (lo, hi) inclusive}, {unproven index: owner index})"""
    order = sorted((k for k, run in enumerate(runs) if run is not None),
                   key=lambda k: runs[k][0])          # cluster order (JP asc)
    tiled = [k for k in order if j2u.get(runs[k][0]) is not None]
    unproven = [k for k in order if j2u.get(runs[k][0]) is None]
    U = len(uunits)
    heads, chars = [], []
    for _p, t in uunits:
        body = END_RE.sub('', t).strip()
        head = nlab(port_derive.label_head(body, bare=True)[0])
        heads.append(head)
        chars.append(len(CODE_RE.sub('', body)))
    us_boxes = [len(BOX_RE.findall(t)) for _p, t in uunits]
    run_boxes = [sum(len(BOX_RE.findall(junits[i][1]))
                     for i in range(runs[k][0], runs[k][1] + 1)) for k in tiled]
    owner = {}
    for m, k in enumerate(tiled):
        for i in range(runs[k][0], runs[k][1] + 1):
            j = j2u.get(i)
            if j is None:
                continue
            pa = skel(junits[i][1])[2]
            pb = skel(uunits[j][1])[2]
            owner[j] = (m, bool(pa and pb and amap.get(pa) == pb))
    known = set(amap.values())
    run_spk, ja_chars = [], []
    for k in tiled:
        lab = ''
        for i in range(runs[k][0], runs[k][1] + 1):
            lab = nlab(skel(junits[i][1])[2])
            if lab:
                break
        run_spk.append(amap.get(nlab(lab), '') if lab else '')
        ja_chars.append(len(CODE_RE.sub('', psx[k][1])))

    def score(m, a, b):
        sc = 0.0
        for u in range(a, b):
            o = owner.get(u)
            if o is None:
                sc += 0.8                   # unclaimed: belongs to someone
            elif o[0] == m:
                sc += 6 if o[1] else 2      # own confirmed / weak pair
            else:
                sc -= 8 if o[1] else 0.3    # confirmed foreign / weak foreign
        sc += 2 - 1.5 * abs(sum(us_boxes[a:b]) - run_boxes[m])
        sc += 0.1 * (b - a)                 # ties go to the fuller span
        have = [heads[u] for u in range(a, b)]
        if run_spk[m]:
            # a speaker's message opens with its speaker's box
            if heads[a] == run_spk[m]:
                sc += 6
            elif heads[a] in known:
                sc -= 4                     # proven speaker mismatch
            elif heads[a]:
                sc += 1
            else:
                sc -= 3
        elif not any(have):
            sc += 1
        # English runs at a fairly stable fraction of the Japanese text;
        # how CLOSE the span's size is to that is the span-size evidence
        uc = sum(chars[a:b])
        if uc:
            r = ja_chars[m] / uc
            sc += max(-4.0, 3.0 - 2.0 * abs(math.log2(r / 0.55)))
        else:
            sc -= 4
        return sc

    M = len(tiled)
    dp = [[0.0] * (U + 2) for _ in range(M + 1)]
    pick = [[None] * (U + 2) for _ in range(M + 1)]
    for m in range(M - 1, -1, -1):
        for pos in range(U, -1, -1):
            best = dp[m][pos + 1] if pos < U else float('-inf')
            choice = None
            for q in range(pos + 1, min(pos + 15, U) + 1):
                v = score(m, pos, q) + dp[m + 1][q]
                if v > best:
                    best, choice = v, q
            dp[m][pos] = best
            pick[m][pos] = choice
    out = {}
    m, pos = 0, 0
    while m < M:
        q = pick[m][pos]
        if q is None:
            if pos >= U:
                break                       # no span fits (should not happen)
            pos += 1
        else:
            out[tiled[m]] = (pos, q - 1)    # inclusive, like us_flow
            m += 1
            pos = q
    # THE MERGED MESSAGES SHARE A BOX (see the docstring): the next proven
    # message's box, or the previous one's when the merge sits at the
    # cluster's end. They keep the same span so the porter reads the same
    # source; main cuts each side at the box's <FF05> section mark.
    share = {}
    for k in unproven:
        later = [j for j in tiled if runs[j][0] > runs[k][0]]
        owner = later[0] if later else (tiled[-1] if tiled else None)
        if owner is None or owner not in out:
            continue
        out[k] = out[owner]
        share[k] = owner
    return out, share


def us_flow(uunits, lo, hi, expect):
    """(speaker, [segment texts]) of the US span - segments are boxes
    (trailing box-end codes stripped).

    The nameplate is STRUCTURE, exactly as in every dialogue family: the
    speaker opens the first box and is read in whatever spelling the view
    carries (port_derive.label_head - the raw '￥N' marker is a code, never
    text), and a repeat at a continuation box is the same nameplate echoed
    (TEXT_LAYOUT_SPEC §4.4) and is dropped there. The label never stays in
    the body; the label must retain its colon.

    Returns speaker=None when the box proves a DIFFERENT speaker than the
    Japanese run's: that is a mispaired span, and a neighbour's English
    must be a gap, never a row."""
    segs = [END_RE.sub('', t).strip() for _p, t in uunits[lo:hi + 1]]
    speaker = ''
    if segs:
        head, rest = port_derive.label_head(segs[0], bare=True)
        if head:
            if expect and head != expect:
                return None, segs
            speaker, segs[0] = head, rest
    for i in range(1, len(segs)):
        head, rest = port_derive.label_head(segs[i], bare=True)
        if head and speaker and head == speaker:
            segs[i] = rest
    return speaker, segs


def ja_shape(ja):
    """(speaker | '<FFF9>' | '', break slots, inline codes, other codes) of
    the PSX message: breaks = FFFC pauses and <FFFB><FFF7> pages in order,
    inline = FFF8/FFF9 content codes, other = anything else (kept verbatim
    so the build's code-multiset QA passes)."""
    codes = [int(c, 16) for c in CODE_RE.findall(ja)]
    breaks, inline, other = [], [], []
    i = 0
    while i < len(codes):
        c = codes[i]
        if c == 0xFB and i + 1 < len(codes) and codes[i + 1] == 0xF7:
            breaks.append('page')
            i += 2
        elif c == 0xFC:
            breaks.append('pause')
            i += 1
        elif c in (0xF8, 0xF9):
            inline.append(c)
            i += 1
        else:
            if c != 0xF6:
                other.append(c)
            i += 1
    speaker = ''
    if ja.startswith('<FFF9>'):
        speaker = '<FFF9>'
    elif '\uff1a' in ja:
        pre = ja.split('\uff1a', 1)[0]
        if not CODE_RE.search(pre) and len(pre) <= 14:
            speaker = pre
    return speaker, breaks, inline, other


def compose(ja, usegs, speaker_us):
    """-> en or None (cannot compose without inventing wording)."""
    sp_ja, breaks, inline, other = ja_shape(ja)
    if speaker_us and sp_ja != '<FFF9>':
        head = speaker_us + ': '
    elif sp_ja == '<FFF9>':
        head = '<FFF9>: '
    else:
        head = ''
    # body flow: a PSP box boundary is either the end or a PAGE, and the
    # PSX spells that same structure '<FFFB><FFF7>'. So a boundary takes the
    # Japanese's PAGE slot - with the pauses that precede it, which belong
    # to the text before the page.
    # When the Japanese has no page for a boundary, the PSP paginated where
    # the PSX only paused - the boundary is a beat then.
    flow = []
    for n, seg in enumerate(usegs):
        body = seg
        if n == 0 and sp_ja == '<FFF9>' and '<FF03>' in body:
            body = body.split('<FF03>', 1)[1]     # FFF9 renders the name
        body = body.replace('<FF03>', ' ')
        # A PSP <FF05> BEAT IS THE SAME PAUSE the Japanese spells <FFFC>
        # (windowtype.c CODE_WAIT: thirty frames). It takes the Japanese's
        # next pause slot AT ITS OWN POSITION, in order - the beats are
        # where this localisation chose to pause, so the English must pause
        # there, not collect the slots at the end of the line (0x6bb2c had
        # all six pauses after the last word, three seconds of silence).
        # A slot that is a PAGE is a box boundary, not a beat: the beat is
        # dropped and the page is placed at the boundary below.
        def beat(_m):
            if breaks and breaks[0] == 'pause':
                breaks.pop(0)
                return '<FFFC>'
            return ''
        body = re.sub(r'<FF05>(?:<[0-9A-Fa-f]{2,4}>|[^<])?', beat, body)
        flow.append(body)
        left = len(usegs) - 1 - n                 # boundaries still to come
        if not left:
            continue
        take = []
        if breaks.count('page') >= left:
            while breaks:                         # up to and including it
                take.append(breaks.pop(0))
                if take[-1] == 'page':
                    break
        elif breaks:
            take.append(breaks.pop(0))
        flow.extend('PAGEBREAK' if k == 'page' else 'PAUSE' for k in take)
    for kind in breaks:                            # leftover slots: end
        flow.append('PAGEBREAK' if kind == 'page' else 'PAUSE')
    # build the en with the slots at their flow positions
    out = head
    for item in flow:
        if item == 'PAGEBREAK':
            out = out.rstrip() + '<FFFB><FFF7>'
        elif item == 'PAUSE':
            out = out.rstrip() + '<FFFC>'
        else:
            out += ('' if not out or out.endswith((' ', '<FFFB><FFF7>', '<FFFC>')) else ' ') + item
    out = re.sub(r' +', ' ', out).strip()
    # inline FFF8/FFF9 (rare): the JA places them; park at a sentence end
    for c in inline:
        if c == 0xF9 and out.startswith('<FFF9>'):
            continue
        want = '<FF%02X>' % c
        if want in out:
            continue
        m = None
        for mm in re.finditer(r'[.!?](?= |<FFFB><FFF7>|<FFFC>|$)', out):
            m = mm
        out = out[:m.end()] + want + out[m.end():] if m else out + want
    for c in other:                                # unknown JA codes ride on
        out += '<FF%02X>' % c
    # THE FAMILY SPELLING, one function for every porter (fit_codes): the
    # PSP's own codes (its <FF05> pause with frame params) are the dialogue
    # family's spelling and the battle interpreter has no such code - they
    # take the Japanese's own spelling in their place.
    import port_derive
    return port_derive.fit_codes(out, ja)


def rewrap(en):
    """FFF6 lines <= 239px. -> (text, worst page line count): over the
    page budget (4 lines: three visible plus the fourth scroll line) when
    the skeleton has no page slot for it - the draft then goes to manual
    as an over-limit row (codes must match the Japanese, so pages cannot
    be added). Pages (<FFFB><FFF7>) are the skeleton and never move; the
    lines inside one are laid out by the shared flow engine
    (vwf_wrap.flow_lines), measured with the codes stripped like every
    BTLP width check."""
    def width(s):
        return vwf_wrap.text_width(re.sub(r'<[^>]*>', '', s))

    import port_story
    out_pages, worst = [], 0
    for page in en.split('<FFFB><FFF7>'):
        joined = ' '.join(page.split())
        items = []
        # A SPEAKER LABEL IS ONE TYPOGRAPHIC UNIT, the dialogue families'
        # own rule (port_story.label_words): 'Nyarlathotep's voice:' never
        # breaks across lines, and the colon never strands.
        lab, rest = port_derive.inline_label(joined)
        if lab:
            items.extend(port_story.label_words(lab))
            joined = rest
        items.extend(('w', w) for w in joined.split(' ') if w)
        lines = [v for k, v in vwf_wrap.flow_lines(
            items, vwf_wrap.BOX_WIDTH, width, '<FFF6>', tail=0) if k == 't']
        worst = max(worst, len(lines))
        out_pages.append('<FFF6>'.join(lines))
    return '<FFFB><FFF7>'.join(out_pages), worst


def plan_sources(psx, junits, uunits):
    """Per PSX message: its US span, resolved speaker and shared-box cut.

    This is the part of the port that needs PSP-JP (message matching, the
    JP<->US bridge and the span tiling). It returns a text-free decision
    record per message; wording is never stored."""
    amap = label_map(junits, uunits)
    j2u = bridge_jp_us(junits, uunits, amap)[0]
    runs = match_psx_jp(psx, junits)
    spans, share = assign_spans(runs, j2u, junits, uunits, psx, amap)
    # spans whose leading part a merged (unproven) message already prints
    heads_taken = set(share.values())
    out = []
    for k, (off, ja) in enumerate(psx):
        run = runs[k]
        if run is None or k not in spans:
            out.append({'kind': 'gap', 'off': off, 'ja': ja})
            continue
        lo, hi = run
        hull = spans[k]
        expect = ''
        for _p, t in junits[lo:hi + 1]:
            expect = nlab(skel(t)[2])
            if expect:
                break
        expect = amap.get(expect, '') if expect else ''
        speaker_us, segs = us_flow(uunits, hull[0], hull[1], expect)
        if speaker_us is None or (expect and speaker_us and expect != speaker_us):
            out.append({'kind': 'gap', 'off': off, 'ja': ja})
            continue
        # A SHARED BOX IS SPLIT AT ITS OWN <FF05> SECTION MARK: the merged
        # message owns the leading part (it has no box of its own), the
        # proven message owns the rest - so neither repeats the other and
        # no PSP wording is dropped, it just belongs to its own box.
        cut = ''
        if segs and k in share:
            cut = 'leading'
        elif segs and k in heads_taken and '<FF05>' in segs[0]:
            cut = 'tail'
        out.append({'kind': 'ok', 'off': off, 'ja': ja, 'lo': hull[0],
                    'hi': hull[1], 'speaker': speaker_us or expect, 'cut': cut})
    return out, amap


def main():
    apply = '--apply' in sys.argv
    d = btlevt.data()
    msgs = btlevt.messages(d)
    psx = [(a - btlevt.B, etext.decode(d[a - btlevt.B:e - btlevt.B - 2]))
           for a, e in msgs]
    import btlevt_port_plan
    if '--without-psp-jp' in sys.argv:
        os.environ[btlevt_port_plan.REPLAY_ENV] = str(btlevt_port_plan.PLAN)
    replay = bool(os.environ.get(btlevt_port_plan.REPLAY_ENV))
    junits, uunits = ([] if replay else jp_units()), us_units()
    sources, amap = btlevt_port_plan.sources(psx, junits, uunits)

    rows, over, gaps, cand = [], [], [], {}
    for src in sources:
        off, ja = src['off'], src['ja']
        if src['kind'] == 'gap':
            gaps.append((off, ja))
            continue
        hull = (src['lo'], src['hi'])
        speaker_us, segs = us_flow(uunits, hull[0], hull[1], src['speaker'])
        if speaker_us is None:
            gaps.append((off, ja))
            continue
        if segs and src['cut'] == 'leading':
            segs = [segs[0].split('<FF05>', 1)[0]]
        elif segs and src['cut'] == 'tail' and '<FF05>' in segs[0]:
            segs = [segs[0].split('<FF05>', 1)[1]] + segs[1:]
        # the nameplate is never dropped (TEXT_LAYOUT_SPEC §4.1): when the
        # span's boxes carry no label but the Japanese run names a speaker,
        # the English still prints it - the name comes from the data map.
        en = compose(ja, segs, speaker_us or src['speaker'])
        if not en:
            gaps.append((off, ja))
            continue
        en, worst = rewrap(en)
        if worst > 4:
            over.append((off, en, toolbelt.note_over(worst, 4, 'lines')))
            continue
        # THE FAMILY'S CODE RULE, the same gate every porter applies
        # (port_derive.codes_match): the wording carries the Japanese line's
        # control codes, exactly. A porter that skips it ships extra pauses
        # and half a page skeleton (a bare <FFFB> is a key hold).
        if not port_derive.codes_match(en, ja):
            over.append((off, en, 'codes differ from the Japanese'))
            continue
        cand[hex(off)] = (en, f'EBOOT:{uunits[hull[0]][0]:x}')

    # THE FAMILY'S OWN PLACEMENT DECIDES (btlp.evt_accept -> evt_plan). A slot
    # that nothing re-points only has to hold 'FF 00 hi lo': the unpacker
    # follows that pointer into the resident spill bank, so a wording longer
    # than its slot is not a draft any more, and the packed size (which no
    # porter can compute alone - the pair table is global) is the build's own
    # question. Only what that plan refuses is queued.
    view = {r['pos']: {'pos': r['pos'], 'en': r.get('en') or ''}
            for r in toolbelt.merged_rows(btlp.REL)}
    for pos, (en, _psp) in cand.items():
        view[pos] = {'pos': pos, 'en': en}
    accept = btlp.evt_accept(d, view)
    for pos, (en, psp) in sorted(cand.items(), key=lambda kv: int(kv[0], 16)):
        ok, reason = accept.get(pos, (False, 'not in the family plan'))
        if ok:
            rows.append({'pos': pos, 'psp': psp, 'en': en})
        else:
            over.append((int(pos, 16), en, reason))

    print('speaker map:', {k: v for k, v in sorted(amap.items())})
    print(f'port_btlevt: {len(rows)} ported, {len(over)} over budget, '
          f'{len(gaps)} gaps (no mechanical source)')
    for off, en, note in over:
        print('  over', hex(off), note, repr(en[:60]))
    for off, ja in gaps[:8]:
        print('  gap ', hex(off), repr(ja[:48]))

    if apply:
        toolbelt.upsert_generated('BTLP', rows)
        for off, en, note in over:
            toolbelt.route_over('BTLP', hex(off), '', en, note)
        toolbelt.route_gaps('BTLP', [hex(off) for off, _ja in psx])
        print(f'port_btlevt: rows -> {toolbelt.gen_path("BTLP")}')


if __name__ == '__main__':
    main()
