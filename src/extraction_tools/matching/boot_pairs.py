"""PSP-US <-> PSP-JP unit pairs for the BOOT tables - the Japanese twin of
a `psp` pointer.

A translation row's `psp` pointer names its PSP-US source row. The same
unit lives in the PSP-JP build at an unrelated offset (the two BOOTs are
different compiles: personas stride 0x4C vs 0x38, affinity 0x100 vs
0x40), so a viewer holding the US pointer cannot show the Japanese twin
without a pair map. This derives one - mechanically, with the PSX
record index (slot, holes and all) as the shared coordinate:

* the US side of a slot is never recomputed: it is the `psp` pointer the
  porters already wrote;
* the JP side of a slot is the JP record's text position - located by
  exact-text anchors against the PSX record's Japanese (the two are the
  same string; nothing is typed, the anchors are what the discs carry),
  fitted onto one arithmetic grid (base + slot*stride) and verified
  across the whole family before use.

Anything that does not verify stays unmapped - a wrong pair would show
one unit's Japanese next to another unit's English.

Output: translation/generated_mappings/psp_pairs.tsv

    file  us_pos  jp_pos

Usage: python src/extraction_tools/matching/boot_pairs.py [--apply]
"""
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
import toolbelt  # noqa: E402
import toolbelt   # noqa: E402
import slps       # noqa: E402

OUT = os.path.join(toolbelt.MAPPINGS, 'psp_pairs.tsv')
HEAD = 'file\tus_pos\tjp_pos\thow'
FILE = 'EBOOT'
REL = 'SLPS_005.00'
MIN_ANCHORS = 3
MIN_RATE = 0.5          # of the family's slots, exact JP == PSX Japanese


def family_slots():
    """{family: [(slot, psx_pos, ja)]} in slot order - the slot is the
    record index of the PSX table (affinity/personas/demons skip their
    unused records, so list order is NOT the slot)."""
    import personas, demons, affinity   # noqa: E402
    out = collections.OrderedDict()
    for fam, recs in (('affinity', affinity.records()),
                      ('personas', personas.records()),
                      ('demons', demons.records())):
        out[fam] = [(k, hex(a - slps.BASE), ja) for k, a, ja in recs]
    seeded = set(out)
    seen = collections.Counter()
    for off, ja, _psp, fam in slps.families(slps.data()):
        if fam in seeded:
            continue
        out.setdefault(fam, []).append((seen[fam], hex(off), ja))
        seen[fam] += 1
    return out


def _proven(rel):
    """Positions whose `psp` this repo did NOT derive from itself.

    `anchor_pairs` treats a pointer as evidence that a porter proved the
    match. A pointer `port_lastresort` wrote is the OUTPUT of that
    reasoning, not an input: feeding it back in would confirm its own
    mistakes (and has). A row whose note is one of port_lastresort's
    `psp ...` notes is therefore never evidence."""
    derived = {r['pos'] for r in toolbelt.read_manual(rel, optional=True)
               if (r.get('note') or '').strip().startswith('psp ')}

    def keep(rows):
        return [r for r in rows if r['pos'].split(',')[0] not in derived]
    return keep


def us_pointer():
    """{psx pos -> PSP-US source offset} straight from the porters'
    `psp` pointers (the US side of the match, never recomputed)."""
    out = {}
    keep = _proven(REL)
    for src in (keep(toolbelt.read_generated(REL, optional=True)),
                keep(toolbelt.read_manual(REL, optional=True))):
        for r in src:
            psp = (r.get('psp') or '').strip()
            if psp.startswith('EBOOT:'):
                out[r['pos'].split(',')[0]] = int(psp.split(':', 1)[1], 16)
    return out


def all_pointers():
    """[(japanese, us offset)] from EVERY PSX row that carries an EBOOT
    `psp` pointer - not just the table families. A pointer is the US side
    of a match a porter already proved, so the row's own Japanese is a
    free anchor onto the JP build wherever it lands. Pointers may name
    several sources ('EBOOT:2a563e,EBOOT:2a5678'); each is a claim.

    Only rows that carry WORDING are trusted. `psp` names the unit the
    wording came from (docs/TEXT_ARCHITECTURE.md), so a row whose `en` is
    empty has no wording to attribute and its pointer is not evidence of
    anything - a note's JP row especially, which would otherwise anchor
    the JP build to itself and pair one build's row with its own number."""
    out = []
    base = os.path.join(toolbelt.EXTRACTED, 'psx')
    for dirpath, _dirs, files in os.walk(base):
        for f in sorted(files):
            if not f.endswith('.tsv'):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), base)[:-4]
            rel = rel.replace(os.sep, '/')
            ja = {r['pos']: r['text']
                  for r in toolbelt.read_extracted('psx', rel, optional=True)}
            keep = _proven(rel)
            for src in (keep(toolbelt.read_generated(rel, optional=True)),
                        keep(toolbelt.read_manual(rel, optional=True))):
                for r in src:
                    if not (r.get('en') or '').strip():
                        continue
                    t = ja.get(r['pos'].split(',')[0])
                    if not t:
                        continue
                    for p in (r.get('psp') or '').split(','):
                        p = p.strip()
                        if not p.startswith('EBOOT:'):
                            continue
                        try:
                            out.append((t, int(p.split(':', 1)[1], 16)))
                        except ValueError:
                            continue
    return out


def anchor_pairs(jidx, jidx_norm):
    """{us offset -> jp offset} anchored on the PSX Japanese.

    A PSX row's Japanese is the same string its PSP-JP twin carries (the
    two are the same line), so where that string is UNIQUE in the JP
    build the row's `psp` pointer gives the US side and the anchor gives
    the JP side: one unit, both builds, nothing typed.

    Ambiguity is what makes a wrong pair, so it is refused twice: a
    Japanese shared by several JP rows cannot anchor anything, and a JP
    row claimed by two different US offsets is dropped from both."""
    import match_jp
    claims = collections.defaultdict(set)     # jp offset -> {us offsets}
    for t, us in all_pointers():
        for idx, keyf in ((jidx, plain), (jidx_norm, match_jp.norm)):
            v = idx.get(keyf(t))
            if v and len(v) == 1:
                claims[v[0]].add(us)
    out, dropped = {}, 0
    for jp, uss in claims.items():
        if len(uss) == 1:
            out[uss.pop()] = jp
        else:
            dropped += 1
    return out, dropped


def plain(s):
    """The row's decoded content: undecoded-code placeholders sit inside a
    box represented by one row, and they are not part of the name being
    matched (the anchor is still an exact string the discs carry)."""
    return re.sub(r'<[0-9A-Fa-f]{4}>', '', s).strip()


def jp_index():
    """{decoded text: [pos_int]} of the PSP-JP BOOT units (the anchors
    live here)."""
    out = collections.defaultdict(list)
    for r in toolbelt.read_extracted('psp_jp', 'EBOOT'):
        out[plain(r['text'])].append(int(r['pos'], 16))
    return out


def fit_grid(points):
    """(base, stride, {slot: pos}) of the arithmetic grid through the most
    anchors, or None. points = [(slot, pos)] - anchors only, so a name
    shared by several slots can never bend the grid. Stray anchors exist
    (a name that also occurs in another table), so the grid is the one
    that explains the MOST anchors - and a slot is only ever emitted from
    it when its own anchor sits on it exactly.

    The stride may be NEGATIVE: a table is built once and the two builds
    may lay it out in opposite directions (the JP skill descriptions run
    backwards through their slot indices), so only a zero stride is not a
    grid."""
    best = None
    for i, (k0, p0) in enumerate(points):
        for k1, p1 in points[i + 1:]:
            if k1 <= k0 or p1 == p0 or (p1 - p0) % (k1 - k0):
                continue
            stride = (p1 - p0) // (k1 - k0)
            base = p0 - k0 * stride
            if base < 0:
                continue
            on = [(k, p) for k, p in points if base + k * stride == p]
            if best is None or len(on) > best[3]:
                best = (base, stride, dict(on), len(on))
    return best[:3] if best else None


SLOT_FAMILIES = {'affinity': 120}   # record shape: N zero-padded FF01 slots


def ff01_runs(rows):
    """[(stride, [row pos])] maximal constant-stride runs of FF01-terminated
    rows - the shape of a stride table of text boxes."""
    pos = sorted(int(r['pos'], 16) for r in rows if r['text'].endswith('<FF01>'))
    runs, a = [], 0
    while a + 1 < len(pos):
        stride = pos[a + 1] - pos[a]
        b = a + 1
        while b + 1 < len(pos) and pos[b + 1] - pos[b] == stride:
            b += 1
        if b > a:
            runs.append((stride, pos[a:b + 1]))
        a = b
    return runs


def covering(rows_sorted, off):
    """The row whose unit holds `off` (a unit starts at its first decoded
    unit, so a pointer may name a byte inside it)."""
    import bisect
    starts = [int(r['pos'], 16) for r in rows_sorted]
    i = bisect.bisect_right(starts, off) - 1
    return rows_sorted[i] if i >= 0 else None


def jp_index_norm():
    """{canonical japanese: [pos_int]} - the same anchors after
    match_jp.norm, so a hiragana PSX label and a katakana PSP name still
    anchor (the script differs, the words do not)."""
    import match_jp
    out = collections.defaultdict(list)
    for r in toolbelt.read_extracted('psp_jp', 'EBOOT'):
        out[match_jp.norm(r['text'])].append(int(r['pos'], 16))
    return out


def skeleton(text):
    """(control-code sequence, visible length) of a decoded unit - the
    game's own layout of a line, and the one thing a Japanese and an
    English build of the same unit MUST agree on (align.py aligns whole
    archives on it). Portraits and voice codes are PSP-only and ignored."""
    import re
    tok = re.compile(r'<([0-9A-Fa-f]{4})>|\[([0-9A-Fa-f]{4})\]')
    codes = tuple(int(a or b, 16) for a, b in tok.findall(text))
    return (tuple(c for c in codes if c not in (0x1B, 0x18)),
            len(tok.sub('', text)))


def _align_seg(A, B, a, b, gap=-4):
    """Needleman-Wunsch of A[a] onto B[b] (align.py's `sim`, its gap), so
    a table that gained a row on one side still lines up."""
    import align
    if not a and not b:
        return {}
    if len(a) == len(b):
        return dict(zip(a, b))          # equal count: the order is the proof
    X, Y = [A[k] for k in a], [B[k] for k in b]
    n, m = len(X), len(Y)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + gap
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + gap
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = max(dp[i - 1][j - 1] + align.sim(X[i - 1], Y[j - 1]),
                           dp[i - 1][j] + gap, dp[i][j - 1] + gap)
    i, j, out = n, m, {}
    while i > 0 or j > 0:
        if (i > 0 and j > 0
                and dp[i][j] == dp[i - 1][j - 1] + align.sim(X[i - 1], Y[j - 1])):
            out[a[i - 1]] = b[j - 1]
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + gap:
            i -= 1
        else:
            j -= 1
    return out


def align_pairs(constraints):
    """{(us offset, jp offset)} of the message units, aligned between the
    proven pairs THIS RUN established.

    The JP and US BOOTs are two compiles of one program: their units are
    in the SAME ORDER (the verified pairs show 5 inversions in 770), so a
    unit's place between two proven pairs is its place on both sides. The
    anchored alignment is therefore bounded by verified pairs, and the
    method itself is measured: held back every second anchor and it
    reproduces 98% of the rest.

    The constraints come from this run's own votes, never from the output
    file: an alignment whose boundaries drift from run to run would make
    the file confirm itself.

    A pair is only emitted where the two units carry the SAME control-code
    skeleton - the game's own layout, and the one thing that cannot be a
    coincidence across two languages. That is what turns an order claim
    into a checked one."""
    jp = [(int(r['pos'], 16), r['text'])
          for r in toolbelt.read_extracted('psp_jp', 'EBOOT')
          if r['text'].endswith('<FF01>')]
    us = [(int(r['pos'], 16), r['text'])
          for r in toolbelt.read_extracted('psp_us', 'EBOOT')
          if r['text'].endswith('<FF01>')]
    jp.sort()
    us.sort()
    A = [skeleton(t) for _p, t in jp]
    B = [skeleton(t) for _p, t in us]
    jidx = {p: i for i, (p, _t) in enumerate(jp)}
    uidx = {p: i for i, (p, _t) in enumerate(us)}
    anchors = sorted((jidx[j], uidx[u]) for u, j in constraints
                     if j in jidx and u in uidx)
    cs = []
    for p in anchors:                 # a constraint must advance both sides
        if not cs or (p[0] > cs[-1][0] and p[1] > cs[-1][1]):
            cs.append(p)
    bounds = [(-1, -1)] + cs + [(len(A), len(B))]
    out = {}
    for (i1, j1), (i2, j2) in zip(bounds, bounds[1:]):
        out.update(_align_seg(A, B, list(range(i1 + 1, i2)),
                              list(range(j1 + 1, j2))))
    return {(us[j][0], jp[i][0]) for i, j in out.items()
            if A[i][0] == B[j][0]}
    """us -> jp from every method's votes, keeping only what is unanimous.

    Several methods may speak about one unit (a text anchor and a slot
    grid); where they agree that is confirmation, where they disagree at
    least one of them is wrong and the pair is refused. The same unit
    also cannot be two rows: a jp row claimed by two us rows is dropped
    from both."""
    out, ambiguous, collided = {}, 0, 0
    for u, js in votes.items():
        if len(js) == 1:
            out[u] = next(iter(js))
        else:
            ambiguous += 1
    rev = collections.defaultdict(set)
    for u, j in out.items():
        rev[j].add(u)
    for j, us in rev.items():
        if len(us) > 1:
            collided += 1
            for u in us:
                del out[u]
    return out, ambiguous, collided


def resolve(votes):
    """us -> jp from every method's votes, keeping only what is unanimous.

    Several methods may speak about one unit (a text anchor and a slot
    grid); where they agree that is confirmation, where they disagree at
    least one of them is wrong and the pair is refused. The same unit
    also cannot be two rows: a jp row claimed by two us rows is dropped
    from both."""
    out, ambiguous, collided = {}, 0, 0
    for u, js in votes.items():
        if len(js) == 1:
            out[u] = next(iter(js))
        else:
            ambiguous += 1
    rev = collections.defaultdict(set)
    for u, j in out.items():
        rev[j].add(u)
    for j, us in rev.items():
        if len(us) > 1:
            collided += 1
            for u in us:
                del out[u]
    return out, ambiguous, collided


def main():
    apply = '--apply' in sys.argv
    us = us_pointer()
    jidx = jp_index()
    jp_all = toolbelt.read_extracted('psp_jp', 'EBOOT')
    votes = collections.defaultdict(set)
    src = collections.defaultdict(set)

    def vote(u, j, tag):
        votes[u].add(j)
        src[(u, j)].add(tag)

    report = []

    anchored, refused = anchor_pairs(jidx, jp_index_norm())
    for u, j in anchored.items():
        vote(u, j, 'anchor')
    report.append(f'anchors: {len(anchored)} verified pairs from the PSX '
                  f'Japanese ({refused} JP rows claimed by two US rows '
                  f'- dropped)')

    for fam, slots in family_slots().items():
        rows = [(k, us[pos], plain(ja)) for k, pos, ja in slots
                if us.get(pos) is not None and plain(ja)]
        if fam in SLOT_FAMILIES:
            # no shared wording (the PSP reworded the line) - the pairing
            # is the record shape: a stride table of N FF01 boxes, slot k
            # of one table to slot k of the other. The table must be the
            # only ~N-slot run in the JP image, every slot must own exactly
            # one box, and the boxes must break alike - anything less is no
            # pairing at all.
            count = SLOT_FAMILIES[fam]
            cand = [(s, run) for s, run in ff01_runs(jp_all)
                    if count * 0.9 <= len(run) <= count]
            if len(cand) != 1:
                report.append(f'{fam}: {len(cand)} JP box runs of ~{count} '
                              f'slots - unmapped')
                continue
            stride, run = cand[0]
            jp_sorted = sorted(jp_all, key=lambda r: int(r['pos'], 16))
            ffpos = sorted(int(r['pos'], 16) for r in jp_sorted
                           if r['text'].endswith('<FF01>'))
            us_sorted = sorted(toolbelt.read_extracted('psp_us', 'EBOOT'),
                               key=lambda r: int(r['pos'], 16))
            import bisect

            def box_at(sorted_rows, slot):
                """the row that owns the slot (its first box at/after the
                slot start, inside the slot window)"""
                p0 = int(sorted_rows[0]['pos'], 16)
                for r in sorted_rows:
                    p = int(r['pos'], 16)
                    if p < slot:
                        continue
                    if p >= slot + stride:
                        return None
                    return r if r['text'].endswith('<FF01>') else None
                return None

            def cls(texts):
                """short/long class per slot, relative to the side's own
                lengths (the table ends in a run of short Reserve slots on
                both sides - the shape that pins the slot origin)."""
                med = sorted(len(t) for t in texts)[len(texts) // 2]
                return [1 if len(t) * 2 <= med else 0 for t in texts]

            best = None
            for t in range(0, 33):
                base = run[0] - t * stride
                jp_txt, ks = [], []
                for k, up, _ja in rows:
                    if k >= count:
                        continue
                    r = box_at(jp_sorted, base + k * stride)
                    u = covering(us_sorted, up)
                    if r is not None and u is not None:
                        ks.append(k)
                        jp_txt.append(r['text'])
                if len(jp_txt) < count // 2:
                    continue
                us_txt = [covering(us_sorted, dict((kk, pp) for kk, pp, _j
                                                  in rows)[k])['text']
                          for k in ks]
                a = cls(us_txt)
                b = cls(jp_txt)
                agree = sum(x == y for x, y in zip(a, b))
                if best is None or agree > best[0]:
                    best = (agree, base, len(ks))
            if best is None or best[0] < best[2] * 0.85:
                report.append(f'{fam}: slot origin unverified '
                              f'({best[0] if best else 0} shape matches) '
                              f'- unmapped')
                continue
            _agree, jbase, _nslots = best
            n = agree = 0
            hit = []
            for k, up, _ja in rows:
                if k >= count:
                    continue
                jp_row = box_at(jp_sorted, jbase + k * stride)
                us_row = covering(us_sorted, up)
                if jp_row is None or us_row is None:
                    continue
                hit.append((up, jp_row['pos']))
                n += 1
                agree += us_row['text'].count('<FF03>') == \
                    jp_row['text'].count('<FF03>')
            if n < count // 2 or agree / max(n, 1) < 0.8:
                report.append(f'{fam}: slot tables do not break alike '
                              f'({agree}/{n} boxes agree) - unmapped')
                continue
            for up, jp_pos in hit:
                vote(up, int(jp_pos, 16), 'box')
            report.append(f'{fam}: {n} pairs from the {count}-slot box tables '
                          f'(jp {jbase:#x}/{stride:#x}, origin pinned by the '
                          f'short-slot tail, {agree}/{n} boxes break alike)')
            continue
        if len({p for _k, p, _j in rows}) < MIN_ANCHORS:
            report.append(f'{fam}: {len(rows)} US-pointed slots - unmapped')
            continue
        anchors = [(k, jidx[ja][0]) for k, _up, ja in rows
                   if len(jidx.get(ja, ())) == 1]
        fit = fit_grid(anchors)
        if not fit:
            report.append(f'{fam}: no JP anchor grid '
                          f'({len(anchors)} unique anchors) - unmapped')
            continue
        base, stride, _jslots = fit
        # emit only verified landings: the grid position must be a real
        # JP row and that row must carry this slot's Japanese. A landing
        # we cannot verify is not a pair - the slot stays unmapped.
        landed = [(k, up, jidx[ja][0]) for k, up, ja in rows
                  if len(jidx.get(ja, ())) == 1
                  and jidx[ja][0] == base + k * stride]
        if len(landed) < MIN_ANCHORS:
            report.append(f'{fam}: only {len(landed)} slots land on the '
                          f'grid as verified JP rows - unmapped')
            continue
        for _k, up, jp in landed:
            vote(up, jp, 'grid')
        report.append(f'{fam}: {len(landed)} verified pairs on the anchor '
                      f'grid (jp {base:#x}/{stride:#x}, '
                      f'{len(anchors)} anchors)')

    import dngnames
    us_pos = {int(r['pos'], 16) for r in toolbelt.read_extracted('psp_us', 'EBOOT')}
    jp_pos = {int(r['pos'], 16) for r in toolbelt.read_extracted('psp_jp', 'EBOOT')}
    floors = [(u, j) for u, j in dngnames.floor_pairs()
              if u in us_pos and j in jp_pos]
    for up, jp in floors:
        vote(up, jp, 'floor')
    report.append(f'floors: {len(floors)} verified pairs (PSX name -> JP '
                  f'row, JP -> US by floor-skeleton alignment)')

    # pairs a reader confirmed by hand against both builds. Kept in their
    # own file so boot_pairs regenerating the map cannot lose them, and
    # voted on like everything else - if a method disagrees, resolve drops
    # the row rather than shipping a wrong pair.
    extra = os.path.join(toolbelt.SOURCE_MAPPINGS, 'psp_pairs_extra.tsv')
    n_extra = 0
    if os.path.exists(extra):
        for line in open(extra, encoding='utf-8').read().splitlines()[1:]:
            f = line.split('\t')
            if len(f) >= 2:
                vote(int(f[1], 16), int(f[0], 16), 'read')
                n_extra += 1
    report.append(f'read: {n_extra} pairs a reader confirmed against both '
                  f'builds')

    # the message tables align LAST, bounded by every pair this run proved
    aligned = align_pairs([(u, j) for u, js in votes.items() for j in js])
    for u, j in aligned:
        vote(u, j, 'align')
    report.append(f'aligned: {len(aligned)} pairs from the message tables '
                  f'(order between proven pairs, matching control skeleton)')

    pairs, ambiguous, collided = resolve(votes)
    if ambiguous or collided:
        report.append(f'refused: {ambiguous} units the methods disagreed '
                      f'on, {collided} JP rows two US rows both claimed')

    if apply:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, 'w', encoding='utf-8', newline='\n') as o:
            o.write(HEAD + '\n')
            for up in sorted(pairs):
                how = ','.join(sorted(src.get((up, pairs[up]), {'?'})))
                o.write(f'{FILE}\t{hex(up)}\t{hex(pairs[up])}\t{how}\n')
        print(f'boot_pairs: {len(pairs)} pairs -> '
              f'{os.path.relpath(OUT, ROOT)}')
    else:
        print(f'boot_pairs: {len(pairs)} pairs (report only - --apply to '
              f'write {os.path.relpath(OUT, ROOT)})')
    for line in report:
        print('boot_pairs:', line)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
