"""Translation progress, QA and duplicate propagation for the event scripts.

  python src/injection_tools/tstatus.py status       print coverage + exactly where to continue
  python tools/tstatus.py qa           check every translated box against its Japanese original
  python tools/tstatus.py propagate    copy a translation to every box with identical Japanese
  python tools/tstatus.py next [N]     print the next N untranslated boxes (default 25) in work order

QA errors (build.py fails on these):
  codes     control codes with parameters differ from the Japanese (order, count or value)
  width     a line is wider than 239 px (the engine would wrap it mid-word:
            such a row is re-laid-out or never ships) or a page (between
            FF02/FF04) carries more than vwf_wrap.PAGE_LINES lines - the
            box is 3 visible lines plus the scroll, and the scroll carries
            the rest of the page (user call 2026-10-21: 5-6 lines, pending
            the in-game check). Nothing ships to wrap or scroll "as is"
  charset   anything the VWF font cannot print outside code parameters
            (Japanese left in the text; its own extras - e.g. '...' - are text)
  label     the speaker label does not match the glossary (e.g. ゆきの: must start "Yukino: ")
  encode    the text cannot be encoded
Warnings are listed but do not fail the build.
"""
import collections
import csv
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import etext      # noqa: E402
import strlib     # noqa: E402
import vwf_wrap   # noqa: E402

ROOT = etext.ROOT
EV = os.path.join(ROOT, 'translation', 'manual', 'events')
TAB, NL = chr(9), chr(10)
# parameter bytes that follow each control code (observed in all 7344 boxes)
PARAM_LEN = {0x05: 2, 0x06: 1, 0x07: 1, 0x08: 1, 0x0E: 1, 0x0F: 1, 0x11: 0, 0x12: 0}
STRUCT = {0x01, 0x02, 0x03, 0x04}
TOKEN = re.compile(r'<(?:FF[0-9A-F]{2}|G[0-9A-F]{3}|[0-9A-F]{2})>')


def rows(include_auto=True):
    """Yield all source boxes, merging sparse manual rows over PSP-generated ports."""
    auto = etext.auto_event_text() if include_auto else {}
    for n in etext.FILES:
        p = os.path.join(EV, f'{n}.tsv')
        manual = {}
        if not os.path.exists(p):
            pass  # no human work left for this file: fully auto-covered
        else:
            for line in open(p, encoding='utf-8').read().split(NL)[1:]:
                f = line.split(TAB)
                if len(f) >= 4 and f[0].isdigit():
                    manual[(int(f[0]), int(f[1]))] = (f[2], f[3])
        source = etext.efile.load(etext.path(n))
        for entry in source.entries:
            for box, (a, b) in enumerate(entry.boxes):
                key = (n, entry.index, box)
                ja = etext.decode(entry.body[a:b])
                local = manual.get((entry.index, box))
                if local and local[0] == ja and etext.has_text(local[1]):
                    en = local[1]
                else:
                    port = auto.get(key)
                    if port and port[0] == ja:
                        en = port[1]
                    elif local and local[0] == ja:
                        en = local[1]
                    else:
                        en = ''
                yield n, entry.index, box, ja, en


def code_seq(b):
    """[(code, params)] for the parameter-carrying control codes of an encoded box."""
    out, i = [], 0
    while i < len(b):
        c = b[i]
        if c == 0xFF and i + 1 < len(b):
            op = b[i + 1]
            i += 2
            if op in PARAM_LEN:
                out.append((op, bytes(b[i:i + PARAM_LEN[op]])))
            i += PARAM_LEN.get(op, 0)
        elif 0x80 <= c <= 0x87:
            i += 2
        else:
            i += 1
    return out


# Button/suit/marker glyphs the PSX font provably renders (used by the
# original JA text in these same boxes). Allowed in ported EN text.
SYMBOLS = ('○', '×', '△', '□', '・', '♥', '♠', '♣', '◆', '：',
           '＞', '＜', '￥', '【', '】')  # shared punctuation: the PSX lines
           # draw these too (the box-head arrows, currency, bracket callouts)


def symbol_bytes():
    if symbol_bytes.cache is None:
        out = []
        for s in SYMBOLS:
            try:
                out.append(etext.encode(s, end=b''))
            except ValueError:
                pass
        symbol_bytes.cache = out
    return symbol_bytes.cache


symbol_bytes.cache = None


def strip_symbols(b):
    for seq in symbol_bytes():
        b = b.replace(seq, b'')
    return b


def text_only(b):
    """encoded box -> bytes of displayed characters (codes and their parameters removed)."""
    out, i = bytearray(), 0
    while i < len(b):
        c = b[i]
        if c == 0xFF and i + 1 < len(b):
            op = b[i + 1]
            i += 2 + PARAM_LEN.get(op, 0)
        elif 0x80 <= c <= 0x87:
            out += b[i:i + 2]
            i += 2
        else:
            out.append(c)
            i += 1
    return bytes(out)


def segments(en):
    """pages for the width check: split on FF02/FF03-aware boundaries -> list of [lines].
    Empty strings are not lines: a wait-then-newline (FF02 FF03, the
    original style) leaves the cursor on a fresh line, it flashes no blank.
    Every family's codes count: a page turn is FF04 (ADV/DNG/S2D) or
    <FFFB><FFF7> (BTLP/TALK), a wait is FF02, and a line is FF03 or FFF6."""
    pages = []
    for page in re.split(r'<FF04>|<FF02>|<FFFB><FFF7>', en):
        pages.append([ln for ln in re.split(r'<FF03>|<FFF6>', page) if ln != ''])
    return pages


GLOSS = {}


def load_glossary():
    p = os.path.join(ROOT, 'translation', 'manual', 'glossary.tsv')
    if not os.path.exists(p):
        GLOSS.clear()
        return
    for line in open(p, encoding='utf-8').read().split(NL)[1:]:
        f = line.split(TAB)
        if len(f) >= 3 and f[0]:
            GLOSS[f[0]] = (f[1], f[2])


def speaker(ja):
    m = re.match(r'(?:<FF0[0-9A-F]>(?:<[0-9A-F]{2}>)?)*([^：<]{1,12})：', ja)
    return m.group(1) if m else None


def psp_labels():
    """(file, entry, box) -> PSP speaker label (or None) from the port
    alignment, with manual overrides (align_fix.tsv) applied. Loaded lazily;
    empty when no port data exists."""
    if psp_labels.cache is None:
        psp_labels.cache = {}
        rows = {}
        p = os.path.join(toolbelt.MAPPINGS, 'align.tsv')
        if os.path.exists(p):
            sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
            from text import load_psp as _load
            from codec import decode_box as _dec
            for r in csv.reader(open(p, encoding='utf-8'), delimiter='\t'):
                if not r or r[0] == 'file' or len(r) < 6 or not r[4].isdigit():
                    continue
                try:
                    key = (r[0], int(r[1]), int(r[2]))
                except ValueError:
                    continue
                # a duplicate-wording repair takes its label from the donor
                sf, se, sb = r[0], int(r[1]), int(r[4])
                if len(r) >= 9 and r[6] and r[7].isdigit() and r[8].isdigit():
                    sf, se, sb = r[6], int(r[7]), int(r[8])
                try:
                    rows[key] = _dec(_load(sf, 'us').entries[se].box_bytes(sb))
                except Exception:
                    continue
        fx = os.path.join(toolbelt.SOURCE_MAPPINGS, 'align_fix.tsv')
        if os.path.exists(fx):
            sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
            from text import load_psp as _load
            from codec import decode_box as _dec
            for r in csv.reader(open(fx, encoding='utf-8'), delimiter='\t'):
                if len(r) < 5 or not r[2].isdigit():
                    continue
                try:
                    key = (r[0], int(r[1]), int(r[2]))
                except ValueError:
                    continue
                if len(r) >= 8 and r[5] and r[6].isdigit() and r[7].isdigit():
                    sf, se, sk = r[5], int(r[6]), int(r[7])
                elif r[4] not in ('', 'None'):
                    sf, se, sk = r[0], int(r[1]), int(r[4])
                else:
                    rows.pop(key, None)
                    continue
                try:
                    rows[key] = _dec(_load(sf, 'us').entries[se].box_bytes(sk))
                except Exception:
                    rows.pop(key, None)
        for key, us in rows.items():
            m = re.search(r'<FF1B>([^<]*)', us)
            lab = m.group(1).strip() if m else None
            # ignore undecoded (bracketed) labels: fall back to glossary
            psp_labels.cache[key] = lab if lab and '[' not in lab else None
    return psp_labels.cache


psp_labels.cache = None


def ported_set():
    """{(file, entry, box)} already replaced with PSP-port text."""
    if ported_set.cache is None:
        ported_set.cache = set()
        p = os.path.join(ROOT, 'translation', 'generated', 'ADV', 'ported.tsv')
        if os.path.exists(p):
            for f in strlib.tsv_fields(p, 3):
                ported_set.cache.add((f[0], int(f[1]), int(f[2])))
    return ported_set.cache


ported_set.cache = None


def reviewed_set():
    """Source boxes with real manual English, where a human owns the label choice."""
    if reviewed_set.cache is None:
        reviewed_set.cache = set()
        for n, e, k, ja, en in rows(include_auto=False):
            if etext.has_text(en):
                reviewed_set.cache.add((n, e, k))
    return reviewed_set.cache


reviewed_set.cache = None


def check(ja, en, want_label='glossary', alt_label=None, line_px=None):
    """want_label: 'glossary' (default), a specific 'Label'
    string the en must start with, or None (no label required).
    alt_label: a second acceptable label (the PSP port label during the
    transition; ported boxes use it, unported ones keep the glossary).
    line_px: the width the DESTINATION proves (a viewport the code opens);
    None means the standard box, `vwf_wrap.BOX_WIDTH + 1`."""
    errs = []
    try:
        be = etext.encode(en)
    except ValueError as ex:
        return [('encode', str(ex))]
    bj = etext.encode(ja)
    # Pause codes (0x05) are US-authoritative: the English keeps the PSP-US
    # pauses verbatim and never imports JA pause positions, so they are
    # excluded from the code-sequence comparison (every other param code
    # must still match the Japanese skeleton exactly). The card frame close
    # <FF06><00> is likewise presentation-only (PSP portrait flow): the
    # frame head (02/03 layout select) still must match exactly.
    seq_j = [(o, p) for o, p in code_seq(bj)
             if o != 0x05 and not (o == 0x06 and p == bytes([0]))]
    seq_e = [(o, p) for o, p in code_seq(be)
             if o != 0x05 and not (o == 0x06 and p == bytes([0]))]
    # Name insert kinds and counts belong to the English wording, not the
    # Japanese sentence. Their parameters are validated independently below.
    seq_j = [x for x in seq_j if x[0] not in (0x07, 0x08, 0x0F)]
    seq_e = [x for x in seq_e if x[0] not in (0x07, 0x08, 0x0F)]
    if seq_e != seq_j:
        errs.append(('codes', f'ja {[(hex(o), p.hex()) for o, p in seq_j][:6]} en {[(hex(o), p.hex()) for o, p in seq_e][:6]}'))
    # A name insert takes a member id. The PSP spells some with none ("My last
    # name is <FF0F>.") and the PSX would read the next character as the id:
    # toolbelt.fix_textbox (the porters' and the repair tool's rule) gives those
    # the protagonist's id and spells <FF10> given / space / family, so anything
    # left bare here came from a hand edit or a writer that skipped the rule.
    bare = re.findall(r'<FF(?:07|08|0F|10)>(?!<[0-9A-Fa-f]{2}>)', en)
    if bare:
        errs.append(('name', f'name insert with no parameter: {bare[0]}'))
    for pg in segments(en):
        # A page carries 3 visible lines plus the scroll - and the scroll
        # is not one line (vwf_wrap.PAGE_LINES).
        # What a page cannot show is never shipped to wrap or scroll "as
        # is": it is re-laid-out or does not ship at all.
        if len(pg) > vwf_wrap.PAGE_LINES:
            errs.append(('width', f'{len(pg)} lines on a page (the page holds {vwf_wrap.PAGE_LINES})'))
            break
        # 239 px max (1 px shadows + uniform 1 px bearings: a 239 line's
        # shadow always fits); true overflow builds wrapped mid-word. A
        # destination that proves its own width (a message viewport the
        # code opens) is that much narrower and clips silently instead.
        limit = line_px or vwf_wrap.BOX_WIDTH + 1
        bad = [ln for ln in pg if vwf_wrap.text_width(ln) > limit]
        if bad:
            # the MEASUREMENT, not a verdict: which line, how many px, and
            # the budget - every overflow anywhere reports this shape
            errs.append(('width', f'{vwf_wrap.text_width(bad[0])} px over '
                                  f'{limit}: {bad[0][:40]}'))
            break
    if '<FF0E>' in en and vwf_wrap.choice_breaks(en) != en:
        # vwf_wrap.choice_breaks is THE rule (the porters lay the wording
        # out with it): the prompt's own break goes where the pen is -
        # <FF03> when the pen is mid-line ("me?Yes"), bare when it is
        # already at a line start (a break there skips a line: E0/1/1).
        errs.append(('choice', 'options must start on their own line '
                     '(<FF03> iff the pen is mid-line)'))
    bad = [c for c in strip_symbols(text_only(be)) if not etext.printable_byte(c)]
    if bad:
        errs.append(('charset', f'non-ASCII bytes in text: {bytes(bad[:6]).hex()}'))
    sp = speaker(ja)
    wants = []
    if want_label == 'glossary':
        if (sp and sp in GLOSS and GLOSS[sp][1] in ('character', 'speaker label')
                and etext.has_text(GLOSS[sp][0])):
            wants.append(GLOSS[sp][0])
    elif want_label:
        wants.append(want_label)
    # alt_label (the PSP port label) is only required when the PSX box shows
    # a speaker at all: a PSX continuation/choice box carries none, and the
    # port matches it (port_story "retail label presence wins").
    if alt_label and sp:
        wants.append(alt_label)
    if wants:
        # Pixel-width wrapping may split a long PSP speaker label across
        # FF03s; when checking its source label, join those wrapped pieces
        # with spaces before comparing.
        flat_en = re.sub(r'\s+', ' ',
                         en.lstrip().replace('<FF06><02>', '')
                         .replace('<FF03>', ' ')).strip()
        hit = False
        for want in wants:
            if flat_en.startswith(want + ':') or en.lstrip().replace('<FF06><02>', '').startswith(want + ':') or re.match(r'(?:<FF0[0-9A-F]>(?:<[0-9A-F]{2}>)?)*' + re.escape(want) + ':', en):
                hit = True
                break
        if not hit:
            errs.append(('label', f'{sp} should be "{wants[0]}:"'))
    return errs


def ship_errors(ja, en, want_label=None, line_px=None):
    """The errors that keep one box from shipping: exactly what cmd_qa
    counts, exemptions included. A code difference the deviation gate
    approves (a name slot the PSP reorders or drops, a choice the PSP
    adds) is not a broken box - every builder reads its rows through this
    so the gate can never drift from the QA. `line_px` is the width the
    destination proves when the code that opens it says so."""
    _devs, devs_ok = classify_deviations(ja, en)
    return [(k, m) for k, m in check(ja, en, want_label=want_label,
                                     line_px=line_px)
            if not (k == 'codes' and devs_ok)]


DEV_KINDS = ('add-name', 'drop-name', 'name-val',
               'choice-val', 'add-choice', 'drop-choice')
NAME_OPS = (0x07, 0x08, 0x0F)


def fmt_tok(op, p):
    """Text token for a (op, param-bytes) code: '<FF07><01>'."""
    return '<FF%02X>' % op + ''.join('<%02X>' % b for b in p)


def parse_tok(tok):
    """Inverse of fmt_tok (text token -> (op, param bytes)), None if malformed."""
    m = re.fullmatch(r'<FF([0-9A-F]{2})>((?:<[0-9A-F]{2}>)*)', tok or '')
    if not m:
        return None
    return (int(m.group(1), 16),
            bytes(int(x, 16) for x in re.findall(r'<([0-9A-F]{2})>', m.group(2))))


def seq_nopause(s):
    """[(op, param)] of an encoded box; pauses and card frame closes
    excluded (both US-authoritative presentation, never skeleton)."""
    return [(o, p) for o, p in code_seq(etext.encode(s))
            if o != 0x05 and not (o == 0x06 and p == bytes([0]))]


def match_with_deviations(ja, en, devs):
    """True when EN/JA code sequences reconcile after applying recorded
    PSP-deliberate deviations (add-*/drop-*: token one side only; *-val:
    same op, PSP value wins). check()'s own rules (pauses excluded, names
    as multiset) apply to the rest. Any malformed record fails closed."""
    try:
        sj = seq_nopause(ja)
        se = seq_nopause(en)
    except ValueError:
        return False
    rj = [x for x in sj if x[0] not in NAME_OPS]
    nj = sorted(x for x in sj if x[0] in NAME_OPS)
    re_ = [x for x in se if x[0] not in NAME_OPS]
    ne = sorted(x for x in se if x[0] in NAME_OPS)
    for kind, jt, et in devs:
        if kind == 'add-name':
            t = parse_tok(et)
            if t is None or t not in ne:
                return False
            ne.remove(t)
        elif kind == 'drop-name':
            t = parse_tok(jt)
            if t is None or t not in nj:
                return False
            nj.remove(t)
        elif kind == 'add-choice':
            t = parse_tok(et)
            if t is None or t not in re_:
                return False
            re_.remove(t)
        elif kind == 'drop-choice':
            t = parse_tok(jt)
            if t is None or t not in rj:
                return False
            rj.remove(t)
        elif kind in ('name-val', 'choice-val'):
            tj, te = parse_tok(jt), parse_tok(et)
            if tj is None or te is None or tj[0] != te[0]:
                return False
            if kind == 'name-val':
                if tj not in nj or te not in ne:
                    return False
                nj.remove(tj)
                ne.remove(te)
            else:
                if tj not in rj or te not in re_:
                    return False
                rj.remove(tj)
                re_.remove(te)
        else:
            return False
    return re_ == rj and ne == nj


def classify_deviations(ja, en):
    """(devs, explained): derive PSP-deliberate deviation records for one
    ported row: added/dropped hero-name inserts, name-param corrections,
    PSP-valued choices, added/dropped choice prompts. Anything else
    (porter corruption) returns explained=False for loud handling."""
    import collections as _c
    try:
        sj = seq_nopause(ja)
        se = seq_nopause(en)
    except ValueError:
        return [], False
    rj = [x for x in sj if x[0] not in NAME_OPS]
    nj = sorted(x for x in sj if x[0] in NAME_OPS)
    re_ = [x for x in se if x[0] not in NAME_OPS]
    ne = sorted(x for x in se if x[0] in NAME_OPS)
    devs = []
    # identical name tokens need no record; same-op leftovers pair up as
    # PSP-value corrections, single-sided leftovers as add/drop.
    cj, ce = _c.Counter(nj), _c.Counter(ne)
    for t in list(cj):
        m = min(cj[t], ce.get(t, 0))
        cj[t] -= m
        ce[t] -= m
        if cj[t] <= 0:
            del cj[t]
        if ce.get(t, 0) <= 0 and t in ce:
            del ce[t]
    lj, le = {}, {}
    for (o, p), n in cj.items():
        lj.setdefault(o, []).extend([p] * n)
    for (o, p), n in ce.items():
        le.setdefault(o, []).extend([p] * n)
    for op in NAME_OPS:
        aj, ae = sorted(lj.get(op, [])), sorted(le.get(op, []))
        while aj and ae:
            devs.append(('name-val', fmt_tok(op, aj.pop(0)), fmt_tok(op, ae.pop(0))))
        for p in ae:
            devs.append(('add-name', '', fmt_tok(op, p)))
        for p in aj:
            devs.append(('drop-name', fmt_tok(op, p), ''))
    # ordered walk over the rest: only choice prompts (0x0E) may differ.
    i = j = 0
    ok = True
    while i < len(rj) or j < len(re_):
        a = rj[i] if i < len(rj) else None
        b = re_[j] if j < len(re_) else None
        if a is not None and b is not None and a == b:
            i += 1
            j += 1
        elif (a is not None and b is not None and a[0] == 0x0E and b[0] == 0x0E):
            devs.append(('choice-val', fmt_tok(*a), fmt_tok(*b)))
            i += 1
            j += 1
        elif b is not None and b[0] == 0x0E and (a is None or a[0] != 0x0E):
            devs.append(('add-choice', '', fmt_tok(*b)))
            j += 1
        elif a is not None and a[0] == 0x0E and (b is None or b[0] != 0x0E):
            devs.append(('drop-choice', fmt_tok(*a), ''))
            i += 1
        else:
            ok = False
            break
    if not ok:
        return [], False
    # self-check through the same gate QA uses; never record silently wrong.
    if not match_with_deviations(ja, en, devs):
        return [], False
    return devs, True


def deviations():
    """{(file, entry, box): [(kind, ja_tok, en_tok)]} of PSP-deliberate
    deviations the porter placed (translation/generated/ADV/
    psp_deviations.tsv). The build QA exempts exactly these records."""
    if deviations.cache is None:
        deviations.cache = {}
        p = os.path.join(ROOT, 'translation', 'generated', 'ADV', 'psp_deviations.tsv')
        if os.path.exists(p):
            for row in strlib.tsv_rows(p, required=('file', 'entry', 'box', 'kind')):
                if row['kind'] in DEV_KINDS:
                    deviations.cache.setdefault(
                        (row['file'], int(row['entry']), int(row['box'])),
                        []).append((row['kind'], row['ja'], row['en']))
    return deviations.cache


deviations.cache = None


def cmd_qa(limit=40):
    load_glossary()
    pl = psp_labels()
    counts, shown, total = collections.Counter(), 0, 0
    for n, e, k, ja, en in rows():
        if etext.is_todo(en):
            continue
        total += 1
        key = (n, int(e), int(k))
        alt = pl.get(key) if key in ported_set() else None
        skip_label = key in reviewed_set()
        # deviations are classified live through the same gate the porter
        # uses (classify_deviations) - one code path, so the QA exemptions
        # can never drift from what the port actually placed
        devs, devs_ok = classify_deviations(ja, en)
        # question boxes never require a label (a same-speaker repeat shows
        # none even though its JA box carries one); anything else keeps the
        # exact label gate.
        if '<FF0E>' in ja or '<FF0E>' in en:
            want, alt = None, None
        else:
            want = 'glossary'
        for kind, msg in check(ja, en, want_label=want, alt_label=alt):
            if kind == 'label' and skip_label:
                continue
            if kind == 'codes' and devs_ok:
                continue
            counts[kind] += 1
            if shown < limit:
                print(f'{n}/{e}/{k} [{kind}] {msg}')
                shown += 1
    # Nothing ships wrapped or scrolled "as is": a row the box cannot show
    # is re-laid-out or does not ship (docs/TEXT_ARCHITECTURE.md's page
    # model), so every class here - width included - fails the build.
    fatal = sum(counts.values())
    print(f'QA: {total} translated boxes, errors: {dict(counts) or "none"}')
    return fatal


def cmd_propagate():
    by_ja = collections.defaultdict(collections.Counter)
    for n, e, k, ja, en in rows(include_auto=False):
        if etext.has_text(en):
            by_ja[ja][en] += 1
    conflicts = {ja: c for ja, c in by_ja.items() if len(c) > 1}
    filled = 0
    for n in etext.FILES:
        p = os.path.join(EV, f'{n}.tsv')
        lines = open(p, encoding='utf-8').read().split(NL)
        for i, line in enumerate(lines[1:], 1):
            f = line.split(TAB)
            if len(f) >= 4 and f[0].isdigit() and etext.is_todo(f[3]) and f[2] in by_ja:
                f[3] = by_ja[f[2]].most_common(1)[0][0]
                lines[i] = TAB.join(f)
                filled += 1
        open(p, 'w', encoding='utf-8', newline=NL).write(NL.join(lines))
    print(f'propagated {filled} boxes; {len(conflicts)} Japanese texts have conflicting translations')
    for ja, c in list(conflicts.items())[:5]:
        print('  conflict:', ja[:50])
    return filled


def stats():
    per = collections.OrderedDict()
    uniq, uniq_done = {}, set()
    for n, e, k, ja, en in rows():
        d = per.setdefault(n, collections.OrderedDict()).setdefault(e, [0, 0])
        d[0] += 1
        d[1] += 1 if etext.has_text(en) else 0
        uniq.setdefault(ja, False)
        if etext.has_text(en):
            uniq[ja] = True
    return per, uniq


def cmd_next(count=25, quiet=False):
    seen, out = set(), []
    done_ja = {ja for n, e, k, ja, en in rows() if etext.has_text(en)}
    for n, e, k, ja, en in rows():
        if etext.has_text(en) or ja in done_ja or ja in seen:
            continue
        seen.add(ja)
        out.append((n, e, k, ja))
        if len(out) >= count:
            break
    if not quiet:
        for n, e, k, ja in out:
            print(f'{n}/{e}/{k}: {ja}')
    return out


def talk_stats():
    d = os.path.join(ROOT, 'translation', 'manual', 'talk')
    tot = done = 0
    uniq = set()
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.endswith('.tsv'):
                for line in open(os.path.join(d, fn), encoding='utf-8').read().split(NL)[1:]:
                    f = line.split(TAB)
                    if len(f) >= 3 and f[0].isdigit():
                        tot += 1
                        uniq.add(f[1])
                        done += 1 if etext.has_text(f[2]) else 0
    return tot, done, len(uniq)


def cmd_status():
    load_glossary()
    per, uniq = stats()
    tot_boxes = sum(v[0] for f in per.values() for v in f.values())
    done_boxes = sum(v[1] for f in per.values() for v in f.values())
    tu, du = len(uniq), sum(1 for v in uniq.values() if v)
    review = 0
    rp = os.path.join(ROOT, 'translation', 'manual', 'review.tsv')
    if os.path.exists(rp):
        review = sum(1 for l in open(rp, encoding='utf-8').read().split(NL)[1:] if l.strip())
    talk = talk_stats()
    print(f'Event boxes: {done_boxes}/{tot_boxes} ({100 * done_boxes // max(tot_boxes, 1)}%)')
    print(f'Unique Japanese texts: {du}/{tu} ({100 * du // max(tu, 1)}%)')
    print(f'TALK units: {talk[1]}/{talk[0]} across {talk[2]} unique Japanese texts')
    print(f'Open review items: {review}')
    print('Coverage by file:')
    for n, ents in per.items():
        b = sum(v[0] for v in ents.values())
        d = sum(v[1] for v in ents.values())
        untouched = sum(1 for v in ents.values() if v[1] == 0)
        print(f'  {n}: {d}/{b} boxes, {len(ents)} entries, {untouched} untouched')
    part = [(n, e, v) for n, ents in per.items() for e, v in ents.items() if 0 < v[1] < v[0]]
    if part:
        print('Partially completed entries:')
        for n, e, v in part:
            print(f'  {n} entry {e}: {v[1]}/{v[0]}')
    nxt = cmd_next(1, quiet=True)
    if nxt:
        n, e, k, _ = nxt[0]
        print(f'Next untranslated box: {n}/{e}/{k} (run `python src/injection_tools/tstatus.py next 40` for a batch)')
    else:
        print('No untranslated event boxes.')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    a = sys.argv[1:] or ['status']
    if a[0] == 'status':
        cmd_status()
    elif a[0] == 'qa':
        sys.exit(1 if cmd_qa() else 0)
    elif a[0] == 'propagate':
        cmd_propagate()
    elif a[0] == 'next':
        cmd_next(int(a[1]) if len(a) > 1 else 25)
    else:
        raise SystemExit(__doc__)
