"""Port S2D.BIN text (script boxes + location names) from the PSP-US BOOT.

Fills translation/generated/S2D.BIN.tsv (schema: docs/TEXT_ARCHITECTURE.md,
id | pos | psp | en) - the scaffold comes from `s2d.py dump` (which owns
positions); this porter only writes `en` + `psp` on matching rows:

  script boxes  s2d_map.tsv (idx = box scan order, lo/hi = PSP BOOT range)
                -> build_en reflows the PSP words into the box; the JA read
                from the binary verifies structure (tstatus.check).
                Remaining script gaps use exact whole portrait dialogue keys
                from PSP-JP and proven complete PSP-US twins; decoded_en keeps
                their authored waits/pages and uses the shared width flow.
  location names boot_s2dnames.tsv (psx_idx -> us_boot_offset) -> the BOOT
                label verbatim, gated by the BANNER_LIMIT width check (the
                arrival banner is the wider of the slot's two consumers; a
                map label that does not fit its own strip becomes a manual
                draft, see s2d.route_label_drafts).

Never touches manual/. Run `python src/injection_tools/s2d.py dump` first.

Usage: python src/extraction_tools/matching/port_s2d.py [--apply] [--force]
       [--without-psp-jp] (requires the validated text-free source plan)
"""
import os
import re
import sys

# Deterministic output (same seed as build.py).
# Seed re-exec ONLY as a script: an import must never hijack the host
# process.
if __name__ == '__main__' and os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    os.execvpe(sys.executable, [sys.executable] + sys.argv, os.environ)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'injection_tools'))
import etext      # noqa: E402
import tstatus    # noqa: E402
import toolbelt   # noqa: E402
import strlib     # noqa: E402
import vwf_wrap   # noqa: E402
import s2d        # noqa: E402  (the binary scans: boxes, slots, decode bases)
import match_jp   # noqa: E402
import port_story # noqa: E402  (shared label atoms and parameter-aware words)
import port_derive # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'psp'))
import eboot      # noqa: E402  (the canonical extraction owner)

ROOT = toolbelt.ROOT
REL = 'S2D'
BOOT = os.path.join(ROOT, 'data', 'cache', 'boot_be.tsv')
MAP = os.path.join(toolbelt.SOURCE_MAPPINGS, 's2d_map.tsv')
NMAP = os.path.join(toolbelt.SOURCE_MAPPINGS, 'boot_s2dnames.tsv')
NAMES_TEXT = os.path.join(ROOT, 'data', 'extracted_text', 'psp_us',
                          'boot_strings.tsv')


def load_boot():
    """(offset, kind, text) of every EBOOT text unit (extracted_text/psp_us/
    EBOOT.tsv - the single per-file extract; the boot_be bucket is dead)."""
    eboot.ensure_us()
    return [(int(r['pos'], 16), '', r['text'])
            for r in toolbelt.read_extracted('psp_us', 'EBOOT')]


def boot_runs(boot, lo, hi):
    """(speaker, items): PSP text as words plus PSP waits/pages kept as
    ('b', code) markers in stream order. NOTHING structural is dropped:
    FF02 waits and FF04 pages ride through exactly as PSP authored them
    (dismissal timing is never rewritten); PSP FF03 line breaks merge into
    the width flow (different box width); FF01 ends the box. Bare
    FF07/08/0F gain the hero <01>."""
    speaker, chunks = '', []
    for a, kind, text in sorted(boot):
        if lo <= a <= hi:
            if text:
                m = re.match(r'^([A-Za-z]+)<FF03>', text)
                if m and not speaker:
                    speaker = m.group(1).strip()
                chunks.append(re.sub(r'^[A-Za-z]+<FF03>', '', text))
            elif kind.strip():
                chunks.append(kind.strip())
    text = ''.join(chunks)
    text = text.replace('<FF01>', '')           # terminal: the builder adds END
    text = re.sub(r'<FF0([78F])>(?!<[0-9A-F]{2}>)', r'<FF0\1><01>', text)
    items = []
    for part in re.split(r'(<FF02>|<FF04>)', text):
        if part in ('<FF02>', '<FF04>'):
            items.append(('b', part))           # breaks keep their brackets
        elif part.strip():
            # FF03 merges into the width flow (PSP line breaks are its box
            # geometry), so it is dropped from the word stream entirely. Every
            # other code stays glued to the text around it: an inline code
            # never opens a word gap ("...<FFFC>Wait" is one run), so the flow
            # measures it whole and the spaces are exactly PSP's own.
            words = [w for w in re.split(r'<FF03>|\s+', part) if w]
            items.extend(('w', w) for w in words)
    return speaker, items


def build_en(ja, speaker, items):
    """Assemble EN from the PSP item stream (words plus PSP waits/pages in
    order). PSP owns pagination: waits/pages ride verbatim at PSP word
    positions (never added, moved, or rewritten); lines wrap by width
    through the shared flow. JA contributes only the alignment (which box
    maps where); it does not supply English name inserts."""
    runs, cur = [], []
    for k, v in items:
        if k == 'b':
            runs.append((cur, v))
            cur = []
        else:
            cur.append(v)
    runs.append((cur, None))
    label = speaker + ': ' if speaker else ''
    out = []
    first = True
    for words, brk in runs:
        if first:
            first = False
            if words:
                words = [label + words[0]] + words[1:]
            elif label:
                words = [label]
        for k, v in vwf_wrap.flow_lines(
                [('w', w) for w in words], vwf_wrap.BOX_WIDTH,
                vwf_wrap.text_width, '<FF03>'):
            out.append(v)
        if brk is not None:
            out.append(brk)
    return ''.join(out)


def portrait_index(jp_rows):
    """Exact whole-dialogue keys only; never feed name-table fragments here."""
    out = {}
    for row in jp_rows:
        raw = row['text']
        if not re.match(r'^\s*<FF1B>[^<>]+<FF03>', raw):
            continue
        if not raw.rstrip().endswith('<FF01>'):
            continue
        key = match_jp.dialogue_key(raw)
        if key:
            out.setdefault(key, []).append(row)
    return out


def portrait_twin(ja, index):
    """One eligible, proven US wording for the COMPLETE PSX dialogue, or None.

    Several equivalent source locations are harmless; differing wordings are
    ambiguous and must remain a gap. No containment/similarity fallback.
    """
    speaker = tstatus.speaker(ja)
    if not speaker:
        return None
    candidates = {}
    # `ja` (and its speaker) is a PSX line: its name inserts carry the
    # member id unit; the PSP-JP index keys carry none (dialogue_key).
    for jp in index.get(match_jp.dialogue_key(ja, psx=True), ()):
        heads = [re.match(r'^\s*<FF1B>([^<>]+)<FF03>', page)
                 for page in jp['text'].split('<FF04>')]
        if any(head is None or match_jp.norm(head.group(1))
               != match_jp.norm(speaker, psx=True) for head in heads):
            continue
        us = match_jp.us_twin('EBOOT', jp)
        if us is None:
            continue
        raw = us['text'].strip()
        if (not re.match(r'^<FF1B>[^<>]+<FF03>', raw)
                or not raw.endswith('<FF01>')
                or port_derive.HOLES.search(port_derive.ink_of(raw))):
            continue
        candidates.setdefault(raw, us)
    return next(iter(candidates.values())) if len(candidates) == 1 else None


def decoded_en(raw, ja=''):
    """Full PSP portrait dialogue, with authored waits/pages kept in order.

    Unlike ADV pagination, S2D's generic interpreter waits IN PLACE on FF02
    and clears the whole 15x3 grid when full. Each wait-delimited prose run
    uses shared label/word/width rules, never ADV's wait-removing paginate.
    A continuation after a standalone wait is refused: independently flowing
    it would incorrectly reset the physical pen. No waits/pages are invented;
    an authored page that needs more than three lines is refused.

    """
    raw = raw.strip()
    if raw.count('<FF01>') != 1 or not raw.endswith('<FF02><FF01>'):
        raise ValueError('incomplete portrait dialogue')
    # Only understood S2D dialogue structures are eligible. In particular,
    # choices/card/portrait commands cannot be guessed into this interpreter.
    allowed = {'01', '02', '03', '04', '05', '07', '08', '0F', '10', '1B'}
    if any(c not in allowed for c in re.findall(r'<FF([0-9A-F]{2})>', raw)):
        raise ValueError('unsupported portrait structure')
    # Full PSP extracts spell pause parameters as 16-bit numeric units.
    # The shared converter owns their raw PSX byte spelling; convert BEFORE
    # format repair can mistake the unit's printed characters for parameters.
    for pause in re.finditer(r'<FF05>', raw):
        if not re.match(r'(?:<(?!FF)[0-9A-F]{4}>|(?:<[0-9A-F]{2}>){2})',
                        raw[pause.end():]):
            raise ValueError('unsupported pause parameter representation')
    raw = port_derive.psx_params(raw)
    for pause in re.finditer(r'<FF05>', raw):
        if not re.match(r'(?:<[0-9A-F]{2}>){2}', raw[pause.end():]):
            raise ValueError('unsupported pause parameter representation')
    raw = toolbelt.fix_textbox(raw)
    out, used, pending = [], 0, False
    last_speaker = None
    for part in re.split(r'(<FF02>|<FF04>|<FF01>)', raw):
        if part == '<FF04>':
            out.append(part)
            used, pending = 0, False
            continue
        if part in ('<FF02>', '<FF01>'):
            out.append(part)
            pending = part == '<FF02>'
            continue
        if not part.strip():
            continue
        m = re.match(r'^\s*<FF1B>([^<>]+)<FF03>', part)
        items = []
        if m:
            speaker = m.group(1).strip()
            if speaker != last_speaker:
                items.extend(port_story.label_words(speaker))
            last_speaker = speaker
            part = part[m.end():]
        if '<FF1B>' in part:
            raise ValueError('portrait head inside prose')
        # PSP wraps after a hyphen without a word gap (shared story/TALK
        # rule). Other prose breaks consumed a space; discard only the
        # whitespace furniture adjacent to the source line break.
        part = re.sub(r'(-?)[ \t\r\n]*<FF03>[ \t\r\n]*',
                      lambda m: '-' if m.group(1) else ' ', part)
        items.extend(('w', w) for w in port_story.code_words(part))
        laid = ''.join(v for _k, v in vwf_wrap.flow_lines(
            items, vwf_wrap.BOX_WIDTH, vwf_wrap.text_width, '<FF03>'))
        if not laid:
            raise ValueError('empty dialogue run')
        lines = laid.split('<FF03>')
        if any(vwf_wrap.text_width(line) > vwf_wrap.BOX_WIDTH for line in lines):
            raise ValueError('dialogue width overflow')
        if pending:
            raise ValueError('unsupported wait-in-place continuation')
        used += len(lines)
        if used > 3:
            raise ValueError('authored S2D page exceeds three lines')
        out.append(laid)
        pending = False
    en = ''.join(out)
    if re.findall(r'<FF0[24]>', en) != re.findall(r'<FF0[24]>', raw):
        raise ValueError('authored timing changed')
    return en


def script_text(ja, en):
    """One script row's English, through the shared text rules.

    PSP head marks ('＞' narration, '＜' dungeon head) are furniture: only
    this PSX row's own Japanese decides whether the box draws one, so the
    shared rule (port_derive.head_marks) runs on every script row before the
    ship gate. Without it a PSP-only mark reaches the disc as a glyph the
    PSX box never had.

    Name insert kinds remain those of the English wording."""
    return port_derive.head_marks(en, ja)


def name_over_limit(text):
    """The located name's gate is the arrival banner, the slot's wider
    consumer (BANNER_LIMIT). The 8x1 map labels read the same slot but their
    wording can be split off in s2d (a manual row keyed at a label
    reference), so a name that only fits the banner still ports."""
    return vwf_wrap.text_width(text) > s2d.BANNER_LIMIT


def port(apply, force=False, without_psp_jp=False, strict=False):
    boot = load_boot()
    table = [(int(r['idx']), int(r['lo'], 16), int(r['hi'], 16),
              [k for k in r['keys'].split(';') if k])
             for r in strlib.tsv_rows(MAP, required=('idx', 'lo', 'hi', 'keys'))]
    d = s2d.data()
    bx = s2d.script_boxes(d)

    # `--force` re-derives every row: a filled row is not a source of truth
    # (an older pass may have kept furniture the current rules drop), so it
    # must not mark its box done either.
    filled = {} if force else {
        r['pos']: r for r in toolbelt.read_generated(REL, optional=True)
        if r.get('en', '').strip()}
    rows, fail = [], []
    for idx, lo, hi, keys in table:
        pos = hex(bx[idx][0] - s2d.B)
        if pos in filled and not force:
            continue                              # filled rows are never rewritten
        ja = etext.decode(d[bx[idx][0] - s2d.B:bx[idx][1] - s2d.B - 2])
        if not all(k in ja for k in keys):
            fail.append((idx, 'ja-keys'))
            continue
        speaker, items = boot_runs(boot, lo, hi)
        if not any(k == 'w' for k, v in items):
            fail.append((idx, 'no boot lines'))
            continue
        en = script_text(ja, build_en(ja, speaker, items))
        bad = tstatus.check(ja, en)
        real = [(k, m) for k, m in bad if k != 'width']
        if real:
            fail.append((idx, 'tstatus:' + ';'.join(k for k, _ in real)))
            continue
        rows.append({'pos': pos, 'en': en, 'psp': f'EBOOT:{lo:x}'})

    if without_psp_jp:
        from s2d_port_plan import replay
        done = {r['pos'] for r in rows} | set(filled)
        rows.extend(replay(d, bx, done))
    else:
        # Whole portrait dialogues fill remaining script gaps mechanically. Keep
        # the authored legacy mapping path above (and every already-filled row).
        done = {r['pos'] for r in rows} | set(filled)
        index = portrait_index(toolbelt.read_extracted('psp_jp', 'EBOOT'))
        for idx, (a, e) in enumerate(bx):
            pos = hex(a - s2d.B)
            if pos in done:
                continue
            ja = etext.decode(d[a - s2d.B:e - s2d.B - 2])
            us = portrait_twin(ja, index)
            if us is None:
                continue
            try:
                en = script_text(ja, decoded_en(us['text'], ja))
            except ValueError as ex:
                fail.append((idx, str(ex)))
                continue
            bad = tstatus.ship_errors(ja, en)
            if bad:
                fail.append((idx, 'tstatus:' + ';'.join(k for k, _ in bad)))
                continue
            rows.append({'pos': pos, 'en': en, 'psp': f"EBOOT:{int(us['pos'], 16):x}"})

        # THE SAME LINE IN THE PSP, any box the passes above left: a box whose
        # Japanese is exactly one PSP-JP row (match_jp.exact_twins) takes that
        # row's PROVEN US twin (match_jp.us_twin) through the same S2D layout
        # and ship gate - narration (＞) boxes have no portrait to index by.
        done = {r['pos'] for r in rows} | set(filled)
        left = [(idx, etext.decode(d[a - s2d.B:e - s2d.B - 2]))
                for idx, (a, e) in enumerate(bx) if hex(a - s2d.B) not in done]
        twins = match_jp.exact_twins('EBOOT', left)
        for idx, ja in left:
            jp = twins.get(idx)
            us = match_jp.us_twin('EBOOT', jp) if jp else None
            if us is None:
                continue
            try:
                en = script_text(ja, decoded_en(us['text'], ja))
            except ValueError as ex:
                fail.append((idx, str(ex)))
                continue
            bad = tstatus.ship_errors(ja, en)
            if bad:
                fail.append((idx, 'tstatus:' + ';'.join(k for k, _ in bad)))
                continue
            rows.append({'pos': hex(bx[idx][0] - s2d.B), 'en': en,
                         'psp': f"EBOOT:{int(us['pos'], 16):x}"})

        # READER-CONFIRMED SOURCES: a box whose PSP rewrote the line (so it is
        # not an exact twin) still has a JP row a reader matched by hand, and
        # that row's proven US twin is the wording. psx_jp_extra.tsv overrides
        # the matcher; without this pass those boxes stay gaps.
        done = {r['pos'] for r in rows} | set(filled)
        for idx, (a, e) in enumerate(bx):
            pos = hex(a - s2d.B)
            if pos in done:
                continue
            target = match_jp.psx_jp_target(REL, pos)
            if not target:
                continue
            crel, jp = match_jp.jp_row_at(target)
            us = match_jp.twin_of(crel, jp)
            if us is None:
                # No proven US twin = no PSP-US wording for this box. That is a
                # gap the manual worklist owns, not a derivation failure: the
                # reader matched a JP row, not this box to an English line.
                continue
            ja = etext.decode(d[a - s2d.B:e - s2d.B - 2])
            try:
                en = script_text(ja, decoded_en(us['text'], ja))
            except ValueError as ex:
                fail.append((idx, str(ex)))
                continue
            bad = tstatus.ship_errors(ja, en)
            if bad:
                fail.append((idx, 'tstatus:' + ';'.join(k for k, _ in bad)))
                continue
            rows.append({'pos': pos, 'en': en,
                         'psp': f"EBOOT:{int(us['pos'], 16):x}"})

    # location names
    nmap = strlib.tsv_rows(NMAP, required=('psx_idx', 'us_boot_offset'))
    boot_labels = {int(r['pos'], 16): r['text']
                   for r in toolbelt.read_extracted('psp_us', 'EBOOT')}
    slots = s2d.name_slots(d)
    for row in nmap:
        i = int(row['psx_idx'])
        pos = hex(slots[i][0] - s2d.B)
        if pos in filled and not force:
            continue
        us = boot_labels[int(row['us_boot_offset'], 16)]
        if name_over_limit(us):
            px = vwf_wrap.text_width(us)
            fail.append((f'name{i}', f'{px}px > {s2d.BANNER_LIMIT}px'))
            continue
        rows.append({'pos': pos, 'en': us,
                     'psp': f"EBOOT:{int(row['us_boot_offset'], 16):x}"})

    if strict and fail:
        raise ValueError(f'S2D plan cannot be captured: {len(fail)} failed rows: {fail[:5]}')
    n = toolbelt.upsert_generated(REL, rows) if apply and rows else len(rows)
    print(f'port_s2d: {n} rows filled; failed {len(fail)}')
    for f in fail[:15]:
        print('  FAIL', f)
    if apply:
        print('wrote', toolbelt.gen_path(REL))
    return rows


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    port('--apply' in sys.argv[1:], '--force' in sys.argv[1:],
         '--without-psp-jp' in sys.argv[1:])
