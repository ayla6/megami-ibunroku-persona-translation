"""Port DNGTEXT/DNGMSG gaps from PSP pack/dng boxes (offset-paired JP/US scan).

Mapping lives in src/extraction_tools/matching/dng_map.tsv (PSX JA key, dng subdir, nearby
US offset, fixup, note, US verification key); English is read at runtime
from the PSP dng .bins via the existing text.py orphan_runs + codec path.
This file is logic only.

  python src/extraction_tools/matching/port_dng.py        # report only
  python src/extraction_tools/matching/port_dng.py --apply  # write generated
  python src/extraction_tools/matching/port_dng.py --without-psp-jp --apply
      # use a validated text-free correspondence plan

Dungeon text is placed in the PSX slot when it fits, otherwise in spill
space; slot size does not require shortening the PSP wording.
Human-only (PSX-only / unsolved US glyphs / no PSP box): DNGTEXT milk ad,
iron-man poster, crossword (US glyphs unsolved), PERSONA poster (US partial),
扉は開かない; DNGMSG 待っててくれ.
"""
import csv
import difflib
import os
import re
import sys

# Deterministic output: set/dict iteration order otherwise leaks the
# per-process hash seed into row content. Same seed as build.py.
# Seed re-exec ONLY as a script: an import must never hijack the host
# process.
if __name__ == '__main__' and os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    os.execvpe(sys.executable, [sys.executable] + sys.argv, os.environ)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'psp'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'injection_tools'))
import etext  # noqa: E402
import port_derive  # noqa: E402  (the shared furniture rules: nameplate, head_marks)
import strlib  # noqa: E402
import toolbelt  # noqa: E402
import vwf_wrap  # noqa: E402

ROOT = etext.ROOT
END = b'\xff\xf5'
MAP = os.path.join(toolbelt.SOURCE_MAPPINGS, 'dng_map.tsv')
MAN_T = os.path.join(ROOT, 'translation', 'manual', 'strings', 'DNGTEXT.tsv')
GEN_T = os.path.join(ROOT, 'translation', 'generated', 'strings', 'DNGTEXT.tsv')
MAN_M = os.path.join(ROOT, 'translation', 'manual', 'strings', 'DNGMSG.tsv')
GEN_M = os.path.join(ROOT, 'translation', 'generated', 'strings', 'DNGMSG.tsv')

from text import load_dng_boxes as boxes  # noqa: E402  (connected path: BIN -> cache -> porter)

_us_all = None


def us_all():
    global _us_all
    if _us_all is None:
        _us_all = []
        base = os.path.join(ROOT, 'data', 'psp_us', 'PSP_GAME', 'USRDIR',
                            'pack', 'dng')
        for sub in sorted(os.listdir(base)):
            for s, t in boxes('us', sub):
                _us_all.append((sub, s, t))
    return _us_all


def us_near(sub, off, us_key=None):
    """Return the actual (subdirectory, offset, text) selected from PSP-US."""
    cands = boxes('us', sub)
    if us_key:
        keyed = [(s, t) for s, t in cands if us_key in t]
        if keyed:
            cands = keyed
    best, bd = None, None
    for s, t in cands:
        dd = abs(s - off)
        if bd is None or dd < bd:
            best, bd = (s, t), dd
    if best is not None and (bd < 0x300 or (us_key and us_key in best[1])):
        return sub, best[0], best[1]
    if us_key:
        for found_sub, found_pos, t in us_all():
            if us_key in t:
                return found_sub, found_pos, t
    assert False, (sub, hex(off), us_key)


HOLE = re.compile(r'\[[0-9a-f]{4}\]')


def clean_us(t):
    """US box -> PSX-format wording (general rules, names never typed in):
    - '[xxxx]' hole markers mean the US box is an untranslated JP remnant:
      NOT English - callers route it to manual as a gap, never guess.
    The box-head arrow and any name label are decided against the Japanese
    by the shared furniture rules (port_derive.nameplate / head_marks), applied
    in assemble() - the one place this family has both texts."""
    # FieldRunScript uses a zero-based member operand (0 is the hero), unlike
    # the one-based dialogue window. PSP name inserts are bare. Their opcode
    # meanings are unchanged: the original field interpreter selects the
    # given-name slot for 07 and the family-name slot for 0F. FF10 is the
    # western given + family spelling, with a space between the two parts.
    def field_name(m):
        op = m.group(1)
        if op == '10':
            return '<FF07><00> <FF0F><00>'
        return f'<FF{op}><00>'
    return re.sub(r'<FF(07|08|0F|10)>(?!<[0-9A-Fa-f]{2}>)', field_name, t)


def ja_codes(ja):
    return sorted(re.findall(r'<FF[0-9A-F]{2}>', ja))


def ja_pages(ja):
    """[[lines]]; each line keeps its own FF02/FF03 terminator."""
    pages = []
    for pg in re.split(r'<FF04>', ja):
        if pg in ('', '<FF01>'):
            continue
        lines = []
        for ln in re.split(r'(<FF03>|<FF02>)', pg):
            if ln in ('', '<FF01>'):
                continue
            if ln in ('<FF03>', '<FF02>'):
                if lines:
                    lines[-1][1] += ln
                else:
                    lines.append(['', ln])
            else:
                lines.append([ln, ''])
        pages.append(lines)
    return pages


def fit_lines(lines, n):
    """The US segments into the JA page's n lines. The count is the skeleton's
    (its control codes must match); the break points are the flow engine's
    (vwf_wrap.fill_lines - the same one every box uses). None when the words
    are too few to fill the skeleton."""
    out = vwf_wrap.fill_lines(' '.join(lines).split(' '), n,
                              vwf_wrap.BOX_WIDTH, vwf_wrap.text_width)
    return out if len(out) == n else None


def boxes_n(t):
    """Displayed textboxes of a layout = pages (a FF04 starts a new one)."""
    return t.count('<FF04>') + 1


def psx_furniture(ja, en):
    """The PSP's furniture in the PSX row's spelling - one rule per construct
    (port_derive): the nameplate marker ('￥Nname<FF03>') becomes the inline
    label its dng box prints ('Name: ', the dng rows spell the speaker
    '<name>：<text>'), and a box-head '>' survives only where the PSX row
    carries one. Both need BOTH texts, so every path that turns a PSP-US box
    into an `en` runs this - assemble() and the similarity fallback alike."""
    return port_derive.head_marks(port_derive.nameplate(en, 'label'), ja)


def assemble(ja, en):
    """Least-boxes layout (doctrine: a box layout follows whichever side
    uses the fewest textboxes). The TEXTBOX SEQUENCE - how many boxes the
    text plays in - follows the side with fewer of them: when the PSP side
    uses no more textboxes than the PSX-JA slot, the text is laid out in
    the PSP's boxes (the door text plays as ONE box, never split). The
    LINES inside those boxes are never taken from either side: the text is
    re-reflowed by the shared reflow engine at our box width (reflow_en
    owns every line break). Otherwise the US segments fill the JA box
    skeleton. FF01 is dropped in both cases (the builders append
    END themselves). Returns None when a page would go empty (JA-skeleton
    case only).

    The PSP's name insert kinds remain part of its wording.
    """
    en = psx_furniture(ja, en)
    if boxes_n(en) <= boxes_n(ja):
        # the PSP's box sequence (FF02 waits / FF04 pages), no source line
        # breaks: every FF03 becomes flow text and reflow_en re-breaks the
        # lines at our width
        t = re.sub(r'<FF01>', '', en).replace('<FF03>', ' ')
        return re.sub(r' {2,}', ' ', t)
    pages = ja_pages(ja)
    if not pages or any(not pg for pg in pages):
        return None
    segs = [s for s in re.split(r'<FF04>|<FF02>|<FF03>|<FF01>', en) if s]
    need = [len(p) for p in pages]
    per, rest = [], list(segs)
    for pi, n in enumerate(need):
        if pi == len(need) - 1:
            per.append(rest)
            rest = []
        else:
            take = min(n, max(len(rest) - (len(need) - pi - 1), 0 if not rest else 1))
            per.append(rest[:take])
            rest = rest[take:]
    if rest:
        per[-1].extend(rest)
    if any(not pg for pg in per):
        return None
    out = []
    for pg_ja, pg_en in zip(pages, per):
        fit = fit_lines(pg_en, len(pg_ja))
        if fit is None:
            return None
        out.append([(t, term) for t, (_, term) in zip(fit, pg_ja)])
    return '<FF04>'.join(''.join(t + (term or '<FF03>') for t, term in pg) for pg in out)


def WMAX():
    """Widest textbox line in px (engine wraps at 240; matches vwf_wrap)."""
    return vwf_wrap.BOX_WIDTH + 1


def reflow_en(en):
    """Re-flow each FF02/FF04 page of EN with the shared breaker
    (vwf_wrap.flow_lines: the same greedy fill + proclitic/closer rules
    as every other textbox). Carried PSP line breaks are PSP geometry
    (their font is narrower), so a page's lines are joined and re-broken
    at OUR width. FF02 waits and FF04 pages are untouched (no timing or
    pagination change, only line breaks within a page)."""
    parts = re.split(r'(<FF0[24]>)', en)
    out, page = [], []

    def flush():
        if page:
            joined = re.sub(r' {2,}', ' ', ' '.join(page))
            items = []
            # A SPEAKER LABEL IS ONE TYPOGRAPHIC UNIT (TEXT_LAYOUT_SPEC §4):
            # the dng boxes print it inline ('Name: text'), and the shared
            # rule reads it in every family (port_derive.inline_label).
            label, rest = port_derive.inline_label(joined)
            if label:
                items.append(('w', label + ':'))
                joined = rest
            items.extend(('w', w) for w in joined.split(' ') if w)
            toks = vwf_wrap.flow_lines(items, vwf_wrap.BOX_WIDTH,
                                       vwf_wrap.text_width, '<FF03>')
            out.append(''.join(v for _, v in toks))
            page.clear()

    for p in parts:
        if not p:
            continue
        if re.fullmatch(r'<FF[0-9A-F]{2}>', p or ''):
            flush()
            out.append(p)
        else:
            page.append(p.replace('<FF03>', ' '))
    flush()
    return ''.join(out)


def fit_report(ja, en, slot):
    """Assembled EN (None when US segments cannot fill the JA skeleton)."""
    if en is None:
        return 'cannot fill ja skeleton'
    try:
        eb = etext.encode(en, end=None) + END
    except ValueError as ex:
        return 'encode-fail:%s' % ex
    # Layout and English name inserts belong to the English wording, not the
    # Japanese slot. Other functional codes are still checked separately.
    LAYOUT = ('<FF01>', '<FF02>', '<FF03>', '<FF04>')
    names = set(vwf_wrap.NAME_CODES)
    codes = sorted(c for c in re.findall(r'<FF[0-9A-F]{2}>', en)
                   if c not in LAYOUT and c not in names)
    want = sorted(c for c in ja_codes(ja) if c not in LAYOUT and c not in names)
    if codes != want:
        return 'codes differ: ja %s en %s' % (want, codes)
    if slot is not None and len(eb) > slot:
        return 'over-slot %d > %d' % (len(eb), slot)
    lines = [l for l in re.split(r'<FF04>|<FF02>', en)
             for l in l.split('<FF03>') if l]
    wide = [l for l in lines
            if vwf_wrap.text_width(re.sub(r'<[^>]*>', '', l)) > WMAX()]
    if wide:
        return 'too wide'
    return ''


def paired_boxes():
    """JP wording and its US source, paired in fresh structural scan order.

    Byte offsets differ by region. A box-count mismatch cannot prove an
    index pairing and stays unpaired.
    """
    base = os.path.join(ROOT, 'data', 'psp_jp', 'PSP_GAME', 'USRDIR', 'pack', 'dng')
    out = []
    for sub in sorted(os.listdir(base)):
        jp_file = os.path.join(base, sub, sub + '.bin')
        us_file = os.path.join(ROOT, 'data', 'psp_us', 'PSP_GAME', 'USRDIR',
                               'pack', 'dng', sub, sub + '.bin')
        if not os.path.isfile(jp_file) or not os.path.isfile(us_file):
            continue
        jp_rows = boxes('jp', sub)
        us_rows = boxes('us', sub)
        if len(jp_rows) != len(us_rows):
            continue
        for (_jp_pos, jp_text), (us_pos, us_text) in zip(jp_rows, us_rows):
            out.append((sub, us_pos, strlib.norm(jp_text), us_text))
    return out


def finish(gen, surface, fail, apply, strict=False):
    """Report and write derived rows once, for either correspondence source."""
    print(f'dng port: {sum(len(v) for v in gen.values())} rows with full English, {len(fail)} gaps/failures')
    for f in fail:
        print('FAIL', f[0], repr(f[1])[:50], f[2][:100])
    if strict and fail:
        raise ValueError(f'DNG plan cannot be captured: {len(fail)} failed matches')
    if apply:
        for rel in sorted(gen):
            toolbelt.upsert_generated(rel, gen[rel])
        for rel in sorted(surface):
            toolbelt.route_gaps(rel, [p for p, _ja in surface[rel]])
        print('wrote canonical tables: generated %s; gaps routed to manual' % sorted(gen))
    return gen, surface


def port(apply, strict=False, without_psp_jp=False):
    table = list(csv.DictReader(open(MAP, encoding='utf-8'), delimiter='\t'))
    sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
    import dngtext as dt
    import dngpacks
    slots = {}
    for _name, fp, _bp in dt.files():
        for _off, ln, ja in dt.boxes(open(fp, 'rb').read()):
            slots.setdefault(ja, ln)
    # The canonical position surface (dngpacks owns it): rel -> [(pos, ja)].
    # D0?M name fields are dngnames' jurisdiction - this porter never writes
    # there (roles: one tool per surface, no overlap).
    surface, spots = {}, {}
    for rel, fp in dngpacks.pack_files():
        if len(os.path.basename(rel)) != 3:
            continue
        for off, _ln, ja in dngpacks.boxes(open(fp, 'rb').read()):
            surface.setdefault(rel, []).append((hex(off), ja))
            spots.setdefault(ja, []).append((rel, hex(off)))
    if without_psp_jp:
        from dng_port_plan import replay
        return finish(replay(surface), surface, [], apply, strict)
    # The porter re-derives what it can; the rest stays a manual gap.
    man_m = {}
    have_t, have_m = set(), set()
    gen, fail = {}, []

    def emit(ja, en, rep, psp):
        """One resolved ja -> rows at every position that ja lives at (the
        same wording can sit in several spots). Every resolved row carries
        its full English: fitting is the build's placement decision (in
        place or spill), never a reason to hold text back."""
        where = spots.get(ja, [])
        if not where:
            fail.append(('dng', repr(ja)[:50],
                         'resolved text has no position in the dngpacks scan'))
            return
        for rel, pos in where:
            gen.setdefault(rel, []).append({'pos': pos, 'psp': psp, 'en': en,
                                           '_source_mode': 'anchored'})
    for r in table:
        key, sub, off = r['key'], r['sub'], int(r['off'], 16)
        fix, note, us_key = r['fix'], r['note'], r['us_key']
        source_sub, source_pos, source_text = us_near(sub, off, us_key or None)
        psp = '%s:%x' % (source_sub, source_pos)
        en = clean_us(source_text)
        if HOLE.search(en):
            fail.append((r['file'], key, 'US box is an untranslated JP remnant '
                         '(hole markers) - gap routed to manual, never guessed'))
            continue
        if fix.startswith('split '):
            en = en.replace(fix[6:], '<FF03>' + fix[6:], 1)
        raw = en
        tag = 'psp-dng %s/0x%x' % (sub, off)
        if note:
            tag += ' ' + note
        if r['file'] == 'DNGTEXT':
            rows = [ja for ja in slots if key in ja]
            if not rows:
                fail.append(('dngtext', key, 'no PSX row'))
                continue
            for ja in rows:
                en = assemble(ja, raw)
                if en is not None:
                    en = reflow_en(en)
                rep = fit_report(ja, en if en is not None else raw, slots.get(ja))
                if en is None or 'encode-fail' in rep or 'codes differ' in rep:
                    if ja not in have_t:
                        fail.append(('dngtext', key, rep))
                    continue
                emit(ja, en, rep, psp)
        else:
            # Match pool: manual rows + existing generated rows + every PSX box
            # (a DNGMSG-mapped JA that is really a box is owned by dngtext:
            # dngmsg never writes inside boxes, so without rerouting its
            # English would build nowhere).
            pool = dict(man_m)
            for bja in slots:
                pool.setdefault(bja, bja)
            if key == 'NO_SUCH_KEY':
                matches = [j for j in pool
                           if '長い間使われていない' in j and 'もう' not in j]
            else:
                matches = [j for j in pool if key in j]
            if not matches:
                fail.append(('dngmsg', key, 'no manual row'))
                continue
            for ja in matches:
                box = ja if ja in slots else (ja + '<FF01>' if ja + '<FF01>' in slots else None)
                if box is not None:
                    en = assemble(box, raw)
                    if en is not None:
                        en = reflow_en(en)
                    rep = fit_report(box, en if en is not None else raw, slots.get(box))
                    if en is None or 'encode-fail' in rep or 'codes differ' in rep:
                        if box not in have_t:
                            fail.append(('dngmsg', key, rep))
                        continue
                    emit(box, en, rep, psp)
                    continue
                slot = len(etext.encode(ja, end=None) + END)
                en = assemble(ja, raw)
                if en is not None:
                    en = reflow_en(en)
                rep = fit_report(ja, en if en is not None else raw, slot)
                if en is None or 'encode-fail' in rep or 'codes differ' in rep:
                    if ja not in have_m and ja not in man_m:
                        fail.append(('dngmsg', key, rep))
                    continue
                emit(ja, en, rep, psp)
    # mechanical cross-version pairing: the PSP re-packed text per map, so
    # files do not correspond 1:1. Unfilled boxes pair to a PSP box by JP
    # similarity (both languages' wording is derived data; the US text at
    # the paired position is the source). Hole-marked US text routes to
    # gaps like every other family.
    # (jp box, us box) paired by BOX INDEX - the join the viewer shows.
    # The two regions' packs lay text out at different offsets, so a
    # position join finds nothing. Packs whose box counts differ between
    # the regions are re-paginated: without an align entry they never pair
    # (pairing across a merge/split would port the wrong text).
    psp = paired_boxes()
    for rel in sorted(surface):
        rows_now = {r['pos'] for r in gen.get(rel, [])}
        for pos, ja in surface[rel]:
            if pos in rows_now or pos in have_t or pos in have_m:
                continue
            n = strlib.norm(ja)
            if len(n) < 4:
                continue
            if not psp:
                continue
            best = max(psp, key=lambda p: difflib.SequenceMatcher(None, n, p[2]).ratio())  # noqa: E501
            if difflib.SequenceMatcher(None, n, best[2]).ratio() < 0.68:
                continue
            raw = clean_us(best[3])
            if HOLE.search(raw):
                continue            # unmapped US font: gap, never guessed
            en = psx_furniture(ja, raw)
            en = reflow_en(en)
            if etext.has_text(en):
                gen.setdefault(rel, []).append(
                    {'pos': pos, 'psp': f'{best[0]}:{best[1]:x}', 'en': en,
                     '_source_mode': 'similarity'})

    return finish(gen, surface, fail, apply, strict)


if __name__ == '__main__':
    port('--apply' in sys.argv[1:], without_psp_jp='--without-psp-jp' in sys.argv[1:])
