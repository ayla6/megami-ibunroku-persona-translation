"""Port PSP-US negotiation answers into PSX answer slots (talktl-compatible rows).

Matching (see port_common doctrine): exact Japanese first, then the
canonical form (katakana folded to hiragana -- PSP restyled many answers;
same words, deterministic rule, tagged `psp-us-kata`); unanimous US wording
only, gated by talktl.check (1 line, one battle-box line wide). talk.py build prefers manual
rows and falls back to these.

Usage: python src/extraction_tools/matching/port_answers.py [--apply]
Report-only by default; --apply writes the generated file (translations
only -- rows without English never enter generated/) and refreshes the
manual worklist (unfilled ids) plus fuzzy candidate notes.

Slot pairing is positional (same demon, same tab slot k), accepting canonical
Japanese, small-kana/punctuation spelling variants, and contextual kana/kanji
equivalences learned between matching neighbouring slots. Other rewritten
answers are handled only by the anchored positional passes or remain manual
candidates; equal control codes alone never license a spelling match.
"""
import collections
import difflib
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'injection_tools'))
import strlib  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import etext  # noqa: E402
import talktl  # noqa: E402
import port_common  # noqa: E402
import answers_port_plan  # noqa: E402  (text-free correspondence snapshots)

PSX = os.path.join(ROOT, 'data', 'psx', 'TALK')
MANUAL = os.path.join(ROOT, 'translation', 'manual', 'talk', 'ANSWERS.tsv')
OUT = os.path.join(ROOT, 'translation', 'generated', 'TALK', 'ANSWERS.tsv')
NL = chr(10)


from text import decode_talk_box as decode_talk  # noqa: E402
from text import load_talk_slots  # noqa: E402  (connected path: BIN -> cache -> porter)

HOLES = re.compile(r'\[[0-9a-f]{4}\]')      # glyph-map hole markers ([05d8])
ENDCUT = re.compile(r'<FF(?:F5|EF)>')


def cut_end(t):
    """Text up to and including the end code - everything after it is dead
    stray data (the talktl convention; cache rows keep it visible)."""
    m = ENDCUT.search(t)
    return t[:m.end()] if m else t


def _no_punct(text):
    """Canonical Japanese with spaces and punctuation removed. Width, kana and
    comma/full-stop folds are the same deterministic rules as canonical_ja;
    small kana stay distinct (spelling_key owns that wider fold)."""
    text = port_common.canonical_ja(text)
    out = []
    for token in re.findall(r'<[^>]+>|.', text, re.S):
        if token.startswith('<'):
            out.append(token)
        elif not token.isspace() and not unicodedata.category(token).startswith(('P', 'S')):
            out.append(token)
    return ''.join(out)


def spelling_key(text):
    """Answer matching only: width/script folds, punctuation and small-kana
    spelling. Control tokens stay intact. This never rewrites source wording;
    equal keys only license a corresponding answer slot, not a corpus guess.
    """
    out = []
    for c in _no_punct(text):
        if c == 'ー':
            continue
        name = unicodedata.name(c, '')
        if name.startswith('HIRAGANA LETTER SMALL '):
            c = unicodedata.lookup(name.replace(' SMALL ', ' '))
        out.append(c)
    return ''.join(out)


def answer_punct_key(text):
    """English answer wording with its terminal punctuation removed. The PSP
    writes the same answer as 'It's a secret!' in one slot and 'It's a
    secret.' in another; that difference is typography, not a second wording."""
    return ENDCUT.sub('', text).strip().rstrip('.!')


def derive_boot_answer(source, japanese):
    """Derive an EBOOT answer using the destination answer terminator."""
    import port_derive
    en, why = port_derive.derive(source, japanese, 'TALK', '')
    if not why:
        en = re.sub(r'<FF01>\s*$', '<FFF5>', en)
    return en, why


class SlotSpellings:
    """Kana/kanji spelling equivalences learned from the game's own slots.

    Seeds must have matching slots immediately before AND after them, and
    at least three unchanged visible characters. Only a kana/kanji replacement
    is learned, with an adjacent character of context on each side; never a
    handwritten reading/name dictionary or an unconstrained fuzzy match.
    Conflicting spellings on either side are refused. Rules aren't chained.
    """
    def __init__(self, groups):
        proposals = collections.defaultdict(set)
        for pairs in groups:
            keys = {k: (spelling_key(a), spelling_key(b)) for k, (a, b) in pairs.items()}
            for k, (a, b) in keys.items():
                if a == b or not all(j in keys and keys[j][0] == keys[j][1]
                                     for j in (k - 1, k + 1)):
                    continue
                ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
                equal = sum(len(re.sub(r'<[^>]+>', '', a[i:j]))
                            for op, i, j, _, _ in ops if op == 'equal')
                if equal < 3:
                    continue
                for op, i, j, x, y in ops:
                    aa, bb = a[i:j], b[x:y]
                    if op != 'replace' or not re.fullmatch(r'[一-鿿ぁ-ゖー]+', aa + bb):
                        continue
                    is_kana = lambda s: bool(re.fullmatch(r'[ぁ-ゖー]+', s))
                    is_kanji = lambda s: bool(re.fullmatch(r'[一-鿿]', s))
                    # Kana/kanji readings are the common PSP restyling. A
                    # single-character kanji variant is the same option too
                    # (鎌遜する/謙遜する): both neighbours must already match,
                    # so it is a learned spelling, never a semantic guess.
                    if is_kana(aa) == is_kana(bb) and not (
                            len(aa) == 1 and len(bb) == 1
                            and is_kanji(aa) and is_kanji(bb)):
                        continue
                    # Include matching context, so a changed reading is not
                    # generalized to every occurrence of an isolated kanji.
                    left = 1 if i and x and a[i-1] == b[x-1] else 0
                    right = 1 if j < len(a) and y < len(b) and a[j] == b[y] else 0
                    aa, bb = a[i-left:j+right], b[x-left:y+right]
                    source, target = (bb, aa) if is_kana(a[i:j]) else (aa, bb)
                    proposals[source].add(target)
        reverse = collections.defaultdict(set)
        for a, bs in proposals.items():
            for b in bs:
                reverse[b].add(a)
        self.rules = {a: next(iter(bs)) for a, bs in proposals.items()
                      if len(bs) == 1 and len(reverse[next(iter(bs))]) == 1}
        self.pattern = (re.compile('|'.join(re.escape(a) for a in
                                           sorted(self.rules, key=lambda a: (-len(a), a))))
                        if self.rules else None)

    def key(self, text):
        key = spelling_key(text)
        return self.pattern.sub(lambda m: self.rules[m.group()], key) if self.pattern else key


def slot_spellings():
    """Learn from the paired Japanese answer slots, never English guesses."""
    import talk as talkt
    groups = []
    for fn in sorted(os.listdir(PSX)):
        if not fn.endswith('.BIN'):
            continue
        name = fn[:-4]
        t = talkt.load(name)
        if not t.ok or not t.s1_tab:
            continue
        slots = psp_answer_slots(name)
        ja = {a: etext.decode(sp[:t.s1_text_len(sp)]) for a, sp in t.s1}
        groups.append({k: (ja[a], slots[k][0]) for k, a in enumerate(t.s1_tab)
                       if a in ja and k in slots})
    return SlotSpellings(groups)


def psp_answer_slots(name):
    """{slot: (jp_text, us_text)} of a PSP TALK file's answer section, paired
    from the extraction caches (auto-refreshed when stale)."""
    jt = load_talk_slots(name, 'jp')
    ut = load_talk_slots(name, 'us')
    out = {}
    for k in jt:
        if k not in ut:
            continue
        if HOLES.search(jt[k]) or HOLES.search(ut[k]):
            continue  # unsolved glyphs on either side: not safe
        out[k] = (cut_end(jt[k]), cut_end(ut[k]))
    return out


def same_slot_pairs():
    """[(px, jt, ut, name, k, a, sim)] same-demon same-tab-slot pairs whose
    Japanese differs beyond canonicalization (PSP rewrites). Central helper:
    fuzzy notes and positional slot-fill both consume it."""
    import difflib
    import talk as talkt
    out = []
    for fn in sorted(os.listdir(os.path.join(ROOT, 'data', 'psx', 'TALK'))):
        if not fn.endswith('.BIN'):
            continue
        name = fn[:-4]
        try:
            t = talkt.load(name)
        except Exception:
            continue
        if not t.ok or not t.s1_tab:
            continue
        slots = psp_answer_slots(name)
        if not slots:
            continue
        by_off = {}
        for v, sp in t.s1:
            by_off[v] = etext.decode(sp[:t.s1_text_len(sp)])
        for k, a in enumerate(t.s1_tab):
            if a == 0xFFFFFFFF or k not in slots:
                continue
            px = by_off.get(a, '')
            jt, ut = slots[k]
            if etext.is_todo(ut) or not px or not jt:
                continue
            if HOLES.search(jt) or HOLES.search(ut):
                continue  # unsolved glyphs: no basis for comparison
            if port_common.canonical_ja(px) == port_common.canonical_ja(jt):
                continue
            pa = px.replace('<FFF5>', '').replace('<FFEF>', '')
            pb = jt.replace('<FFF5>', '').replace('<FFEF>', '')
            s = difflib.SequenceMatcher(None, pa, pb).ratio()
            out.append((px, jt, ut, name, k, a, s))
    return out



def _answer_ids():
    """(id -> Japanese, id -> (ja, en, note)) from the tracked tables."""
    prior = {}
    if os.path.exists(OUT):
        for r in strlib.tsv_rows(OUT, required=('id', 'ja')):
            if r['id'].isdigit():
                prior[r['id']] = r['ja']
    man = {}
    if os.path.exists(MANUAL):
        for r in strlib.tsv_rows(MANUAL, required=('id', 'ja', 'en', 'note')):
            if r['id'].isdigit():
                man[r['id']] = (r['ja'], r['en'], r['note'])
    # ID universe: canonical PSX enumeration (stable across runs, independent
    # of what files currently hold). Must agree with stored rows.
    universe = {}
    for i, (ja, _files) in enumerate(sorted(
            talktl.ans_strings().items(), key=lambda x: (-len(x[1]), x[0]))):
        universe[str(i)] = ja
    for idx, ja in list(prior.items()) + [(i, m[0]) for i, m in man.items()]:
        if idx in universe and universe[idx] != ja:
            raise SystemExit(f'port_answers: id {idx} drift: stored {ja[:30]!r} != PSX {universe[idx][:30]!r}')
    return universe, man


def _parse_source(source):
    """('psp-us', 'talk', 'NAME:k') from a row's source tag."""
    parts = source.split()
    if len(parts) < 2:
        raise answers_port_plan.PlanError(f'answers source has no locator: {source!r}')
    tag, token = parts[0], parts[1]
    if token.startswith('EBOOT/'):
        return tag, 'boot', token.split('/', 1)[1]
    return tag, 'talk', token.replace('/', ':', 1)


def _record_answer(idx, source):
    tag, us_kind, us_pos = _parse_source(source)
    answers_port_plan.record('answer', 'ANSWERS', idx, us_kind, us_pos, tag)


def _psx_answer_text(name, offset, talkt):
    """The PSX answer string at a talk file offset (offset-table value)."""
    t = talkt.load(name)
    if not t.ok or not t.s1:
        return ''
    for v, sp in t.s1:
        if v == offset:
            return etext.decode(sp[:t.s1_text_len(sp)])
    return ''


def fuzzy_candidates(pairs=None):
    """(rel, pos) -> [(sim, US wording, 'NAME/k')] for same-slot rewrites."""
    cands = collections.defaultdict(list)
    for _px, _jt, ut, name, k, a, s in (pairs if pairs is not None
                                       else same_slot_pairs()):
        if s >= 0.8:
            cands[(f'TALK/{name}', hex(a))].append((s, ut, f'{name}/{k}'))
    return cands


def _record_fuzzy(cands):
    """One decision per distinct US wording; the best score/locator wins."""
    if not answers_port_plan.capturing():
        return
    for (rel, pos), cands_for_row in cands.items():
        best = {}
        for s, ut, loc in cands_for_row:
            if ut not in best or (s, loc) > best[ut][:2]:
                best[ut] = (s, loc)
        for ut, (s, loc) in best.items():
            answers_port_plan.record('fuzzy', rel, pos, 'talk',
                                     loc.replace('/', ':', 1), f'{s:.2f}')


def write_fuzzy_notes(cands):
    """Record the top PSP candidates as notes on canonical manual rows for
    human decision. Only writes note cells of rows with empty en; filled en
    is never touched."""
    import toolbelt
    noted = 0
    for rel in sorted({r for r, _p in cands}):
        man = toolbelt.read_manual(rel, optional=True)
        changed = False
        for row in man:
            key = (rel, row['pos'])
            if key not in cands:
                continue
            if etext.has_text(row.get('en', '')):
                continue
            seen, parts = set(), []
            for s, ut, loc in sorted(cands[key], reverse=True):
                if ut in seen or len(parts) >= 3:
                    continue
                seen.add(ut)
                parts.append(f'{ut} (sim {s:.2f}, {loc}, UNREVIEWED)')
            n_more = len({u for _, u, _ in cands[key]}) - len(seen)
            if n_more > 0:
                parts.append(f'+{n_more} more')
            row['note'] = 'psp-candidates: ' + '; '.join(parts)
            changed = True
            noted += 1
        if changed:
            toolbelt.write_manual(rel, man)
    print(f'fuzzy notes: {noted} manual rows annotated')


def _apply_output(rows, slot_rows, over_rows, sim_rows, anchor_rows, slot_loc):
    import toolbelt
    import talk as _talkt
    # Canonical rows per answer-string position (rel TALK/<NAME>, pos =
    # the string's file offset, same locator the extract uses). The
    # slot-correct resolutions (exact/canonical, sim, anchor) win at
    # their position; the global per-string rows fill every remaining
    # position carrying that Japanese; unresolved positions stay manual
    # gaps (route_gaps). A human's filled en is never overwritten.
    per_pos = {}

    def put(name, v, en, psp):
        if en.strip():
            per_pos.setdefault((name, v), (en, psp))
    for name, v, _ja, en, _src in slot_rows:
        put(name, v, en, (slot_loc.get((name, v)) or '').replace('/', ':'))
    for name, a, _px, ut, src in sim_rows + anchor_rows:
        loc = src.rsplit(' ', 1)[-1]
        put(name, a, ut, loc.replace('/', ':') if '/' in loc else '')
    glob = {}
    for _idx, ja, en, source in rows:
        glob.setdefault(ja, (en, source))
    rel_pos, by_rel = {}, {}
    for fn in sorted(os.listdir(PSX)):
        if not fn.endswith('.BIN'):
            continue
        name = fn[:-4]
        try:
            t = _talkt.load(name)
        except Exception:
            continue
        if not t.ok or not t.s1:
            continue
        rel = f'TALK/{name}'
        for v, sp in t.s1:
            pos = hex(t.hdr[1] + v)
            rel_pos.setdefault(rel, []).append(pos)
            hit = per_pos.get((name, v))
            if hit:
                en, psp = hit
            else:
                got = glob.get(etext.decode(sp[:t.s1_text_len(sp)]))
                if not got or not got[1].startswith('psp-us'):
                    continue        # unresolved / manual-by-id: not mine
                en, source = got
                parts = source.split()
                psp = parts[1].replace('/', ':') if len(parts) > 1 else ''
            by_rel.setdefault(rel, []).append({'pos': pos, 'psp': psp, 'en': en})
    n_rows = 0
    for rel, nrows in by_rel.items():
        man = {r['pos'] for r in toolbelt.read_manual(rel, optional=True)
               if etext.has_text(r.get('en', ''))}
        keep = [r for r in nrows if r['pos'] not in man]
        n_rows += len(keep)
        toolbelt.upsert_generated(rel, keep)
    # THE SLOT'S OWN WORDING THAT DOES NOT FIT: the PSP-US line of the same
    # slot, too wide for the answer box, is a draft for a human to fit -
    # never shortened here, never dropped silently (toolbelt.route_over)
    hdr = {}
    for name, v, ut, errs, loc in over_rows:
        if name not in hdr:
            hdr[name] = _talkt.load(name).hdr[1]
        rel, pos = f'TALK/{name}', hex(hdr[name] + v)
        if pos in {r['pos'] for r in by_rel.get(rel, ())}:
            continue                  # another source already ships it
        widths = [re.match(r'(\d+) px:', e) for e in errs]
        if not all(widths):
            continue                  # not a size problem: stays a gap
        toolbelt.route_over(rel, pos, loc, ut, toolbelt.note_over(
            max(int(m.group(1)) for m in widths), talktl.ANS_W))
    for rel, poss in rel_pos.items():
        toolbelt.route_gaps(rel, poss)
    print(f'wrote canonical answer rows: {n_rows} rows in {len(by_rel)} '
          f'TALK files (unresolved positions stay manual gaps)')


def _collect_live(apply=False):
    import talk as talkt
    spellings = slot_spellings()
    by_ja = collections.defaultdict(collections.Counter)
    by_canon = collections.defaultdict(collections.Counter)
    by_punct = collections.defaultdict(collections.Counter)
    locs = collections.defaultdict(list)
    clocs = collections.defaultdict(list)
    plocs = collections.defaultdict(list)
    slot_votes = collections.defaultdict(collections.Counter)
    slot_loc = {}
    from text import TALK_DIR as _TALK_DIR
    for fn in sorted(os.listdir(_TALK_DIR['jp'])):
        if not fn.endswith('.BIN') or fn == 'ETC.BIN':
            continue
        name = fn[:-4]
        slots = psp_answer_slots(name)
        for k, (jt, ut) in slots.items():
            if etext.is_todo(jt) or etext.is_todo(ut):
                continue
            by_ja[jt][ut] += 1
            locs[jt].append(f'{name}/{k}')
            cj = port_common.canonical_ja(jt)
            by_canon[cj][ut] += 1
            clocs[cj].append(f'{name}/{k}')
            pj = _no_punct(jt)
            by_punct[pj][ut] += 1
            plocs[pj].append((ut, f'{name}/{k}'))
    slot_votes = collections.defaultdict(collections.Counter)
    slot_ja = {}
    slot_loc = {}
    # per-slot votes: PSX tab slot k carries offset v; when PSP-JP slot k
    # has the identical Japanese, its US wording is the context-correct one
    for fn in sorted(os.listdir(os.path.join(ROOT, 'data', 'psx', 'TALK'))):
        if not fn.endswith('.BIN'):
            continue
        name = fn[:-4]
        try:
            t = talkt.load(name)
        except Exception:
            continue
        if not t.ok or not t.s1_tab:
            continue
        slots = psp_answer_slots(name)
        if not slots:
            continue
        by_off = {}
        for v, sp in t.s1:
            by_off[v] = etext.decode(sp[:t.s1_text_len(sp)])
        for k, a in enumerate(t.s1_tab):
            if a == 0xFFFFFFFF or k not in slots:
                continue
            px = by_off.get(a, '')
            jt, ut = slots[k]
            if etext.is_todo(ut):
                continue
            if spellings.key(px) == spellings.key(jt):
                slot_votes[(name, a)][ut] += 1
                slot_ja[(name, a)] = px
                slot_loc[(name, a)] = f'{name}/{k}'
    universe, man = _answer_ids()
    ids = list(universe)
    rows, missed = [], []
    stats = collections.Counter()
    # stable ids: current generated file order (id -> ja); every PSX answer
    # string keeps its id across runs.
    for idx in ids:
        ja = universe[idx]
        en = man[idx][1] if idx in man else ''
        if etext.has_text(en):
            rows.append((idx, ja, en, 'manual'))
            stats['manual'] += 1
            continue
        cands = by_ja.get(ja)
        tag, proven = 'psp-us', locs[ja]
        if not cands or len(cands) != 1:
            cands = by_canon.get(port_common.canonical_ja(ja))
            tag, proven = 'psp-us-kata', clocs[port_common.canonical_ja(ja)]
        if not cands or len(cands) != 1:
            # Same answer, different punctuation: '内緒…' against the PSP's
            # '内緒'. Accept only when every PSP-US rendering says the same
            # thing apart from terminal punctuation; pick the most frequent
            # spelling of that one wording.
            pk = _no_punct(ja)
            raw = by_punct.get(pk)
            groups = collections.defaultdict(list)
            for ut, n in (raw or {}).items():
                groups[answer_punct_key(ut)].append((ut, n))
            if len(groups) == 1:
                ut = max(next(iter(groups.values())), key=lambda x: x[1])[0]
                cands = collections.Counter({ut: 1})
                # point at a source carrying the chosen spelling, not at a
                # punctuation variant of it
                proven = [loc for src, loc in plocs[pk] if src == ut]
                tag = 'psp-us-punct'
        if not cands or len(cands) != 1:
            missed.append((idx, ja))
            continue  # no PSP answer slot: the executable's lines below
        ut = next(iter(cands))
        errs = talktl.check(ja, ut, False, talktl.ANS_W, 1)
        if errs:
            stats['qa-fail'] += 1
            answers_port_plan.record('answer', 'ANSWERS', idx, 'talk',
                                     proven[0].replace('/', ':', 1), 'qa-fail')
            continue  # QA-failed: stays out of generated/, see manual
        rows.append((idx, ja, ut, tag + ' ' + proven[0]))
        answers_port_plan.record('answer', 'ANSWERS', idx, 'talk',
                                 proven[0].replace('/', ':', 1), tag)
        stats['auto'] += 1
    # THE SAME LINE IN THE EXECUTABLE: an answer no PSP answer slot carries
    # (the PSP moved it, e.g. the negotiation actions) whose Japanese is
    # exactly one PSP-JP EBOOT row (match_jp.exact_twins) takes that row's
    # PROVEN US twin (match_jp.us_twin) through the shared derivation and
    # the answer QA. No twin, no proof, or no fit: it stays a manual gap.
    import match_jp
    import port_derive
    twins = match_jp.exact_twins('EBOOT', missed)
    for idx, ja in missed:
        jp_row = twins.get(idx)
        us_row = match_jp.us_twin('EBOOT', jp_row) if jp_row else None
        en, why = (derive_boot_answer(us_row['text'], ja)
                   if us_row and (us_row.get('text') or '').strip()
                   else ('', 'no source'))
        if why or talktl.check(ja, en, False, talktl.ANS_W, 1):
            stats['miss'] += 1
            answers_port_plan.record('answer', 'ANSWERS', idx, split='miss')
            continue
        rows.append((idx, ja, en,
                     f"psp-us-boot EBOOT/{int(us_row['pos'], 16):x}"))
        answers_port_plan.record('answer', 'ANSWERS', idx, 'boot',
                                 f"{int(us_row['pos'], 16):x}", 'psp-us-boot')
        stats['auto'] += 1
    print(f'answers: {len(ids)} known ids, '
          f'{stats["manual"]} manual, '
          f'{stats["auto"]} PSP-unanimous, {stats["miss"]} unported, '
          f'{stats["qa-fail"]} QA-failed')
    # per-slot map (file, psx-offset -> en) for context-dependent answers
    slot_rows, over_rows = [], []
    for (name, v), cands in sorted(slot_votes.items()):
        if len(cands) != 1:
            continue
        ut = next(iter(cands))
        ja = slot_ja.get((name, v), '')
        errs = talktl.check(ja, ut, False, talktl.ANS_W, 1) if ja else ['no-ja']
        slot_rows.append((name, v, ja, '' if errs else ut,
                          ';'.join(errs) if errs else slot_loc.get((name, v), '')))
        answers_port_plan.record('slot', name, hex(v), 'talk',
                                 slot_loc[(name, v)].replace('/', ':', 1))
        if errs and ja:
            over_rows.append((name, v, ut, errs,
                              (slot_loc.get((name, v)) or '').replace('/', ':')))
    print(f'slot-mapped: {sum(1 for r in slot_rows if r[3])} clean, '
          f'{sum(1 for r in slot_rows if not r[3])} QA-failed')
    # positional slot-fill: same-slot PSP rewrites (sim>=0.8, QA-gated) cover
    # positions text votes never reach. Keyed by game position, tagged with
    # sim; exact/canonical slot rows win ties.
    sim_rows = []
    covered = {(name, v) for (name, v), c in slot_votes.items() if len(c) == 1}
    best = {}
    pairs = same_slot_pairs()
    for px, _jt, ut, name, k, a, s in pairs:
        if s >= 0.8 and (name, a) not in covered:
            if (name, a) not in best or s > best[(name, a)][0]:
                best[(name, a)] = (s, ut, px, f'{name}/{k}')
    for (name, a), (s, ut, px, loc) in sorted(best.items()):
        if talktl.check(px, ut, False, talktl.ANS_W, 1):
            continue
        sim_rows.append((name, a, px, ut, f'slot-sim{s:.2f} {loc}'))
        answers_port_plan.record('sim', name, hex(a), 'talk',
                                 loc.replace('/', ':', 1))
    print(f'slot-sim positional: {len(sim_rows)} QA-clean')
    # anchored hole-fill: PSP slot decodes with [xxxx] holes but sits at a
    # PSX-used position with exact/canonical neighbors on both sides, and its
    # known characters overlap the PSX text (guards rewrites like salt/heart).
    anchor_rows = []
    for fn in sorted(os.listdir(os.path.join(ROOT, 'data', 'psx', 'TALK'))):
        if not fn.endswith('.BIN'):
            continue
        name = fn[:-4]
        try:
            t = talkt.load(name)
        except Exception:
            continue
        if not t.ok or not t.s1_tab:
            continue
        slots = psp_answer_slots(name)
        if not slots:
            continue
        from text import load_talk_slots as _load
        _jt, _ut = _load(name, 'jp'), _load(name, 'us')
        full = {k: (_jt[k], _ut[k]) for k in _jt if k in _ut}
        by_off = {}
        for v, sp in t.s1:
            by_off[v] = etext.decode(sp[:t.s1_text_len(sp)])
        for k, a in enumerate(t.s1_tab):
            if a == 0xFFFFFFFF or k not in full:
                continue
            jt, ut = full[k]
            if not HOLES.search(jt) or HOLES.search(ut) or etext.is_todo(ut):
                continue
            px = by_off.get(a, '')
            if not px or port_common.canonical_ja(px) == port_common.canonical_ja(jt):
                continue
            known = re.sub(r'\[[0-9a-f]{4}\]', '', jt).replace('<FFF5>', '')
            bare_px = px.replace('<FFF5>', '')
            overlap = sum(1 for c in known if c in bare_px)
            if overlap < 3 and known not in bare_px and bare_px not in known:
                continue
            anchored = True
            for kk in (k - 1, k + 1):
                if kk not in full or kk not in slots:
                    anchored = False
                    break
                _njt, _nut = full[kk]
                _a2 = t.s1_tab[kk]
                _px2 = by_off.get(_a2, '')
                if port_common.canonical_ja(_px2) != port_common.canonical_ja(_njt):
                    anchored = False
                    break
            if not anchored:
                continue
            if talktl.check(px, ut, False, talktl.ANS_W, 1):
                continue
            anchor_rows.append((name, a, px, ut, f'slot-anchor {name}/{k}'))
            answers_port_plan.record('anchor', name, hex(a), 'talk',
                                     f'{name}:{k}')
    print(f'slot-anchor positional: {len(anchor_rows)} QA-clean')
    cands = fuzzy_candidates(pairs)
    _record_fuzzy(cands)
    if apply:
        _apply_output(rows, slot_rows, over_rows, sim_rows, anchor_rows, slot_loc)
        write_fuzzy_notes(cands)
    rows.sort(key=lambda r: int(r[0]))
    return rows


def _collect_replay(apply=False):
    import talk as talkt
    import port_derive
    universe, man = _answer_ids()
    ids = list(universe)
    rows, missed = [], []
    stats = collections.Counter()
    for idx in ids:
        ja = universe[idx]
        en = man[idx][1] if idx in man else ''
        if etext.has_text(en):
            rows.append((idx, ja, en, 'manual'))
            stats['manual'] += 1
            continue
        row = answers_port_plan.lookup('answer', 'ANSWERS', idx)
        kind = row['split']
        if kind == 'miss':
            missed.append((idx, ja))
            stats['miss'] += 1
            continue
        if kind == 'qa-fail':
            ut = answers_port_plan.us_text(row)
            if not talktl.check(ja, ut, False, talktl.ANS_W, 1):
                raise answers_port_plan.PlanError(
                    f'answers plan expected a QA failure for id {idx}; recapture')
            stats['qa-fail'] += 1
            continue
        ut = answers_port_plan.us_text(row)
        if kind == 'psp-us-boot':
            en, why = derive_boot_answer(ut, ja)
            if why or talktl.check(ja, en, False, talktl.ANS_W, 1):
                raise answers_port_plan.PlanError(
                    f'answers plan boot source no longer derives id {idx}; recapture')
        else:
            en = ut
            if talktl.check(ja, en, False, talktl.ANS_W, 1):
                raise answers_port_plan.PlanError(
                    f'answers plan source no longer fits id {idx}; recapture')
        rows.append((idx, ja, en, f'{kind} {answers_port_plan.locator(row)}'))
        stats['auto'] += 1
    print(f'answers: {len(ids)} known ids, '
          f'{stats["manual"]} manual, '
          f'{stats["auto"]} PSP-unanimous, {stats["miss"]} unported, '
          f'{stats["qa-fail"]} QA-failed')
    slot_rows, over_rows = [], []
    slot_loc = {}
    plan = answers_port_plan.load()
    for row in plan['index'].values():
        if row['mode'] != 'slot':
            continue
        name, v = row['rel'], int(row['pos'], 16)
        ut = answers_port_plan.us_text(row)
        ja = _psx_answer_text(name, v, talkt)
        errs = talktl.check(ja, ut, False, talktl.ANS_W, 1) if ja else ['no-ja']
        loc = answers_port_plan.locator(row)
        slot_loc[(name, v)] = loc
        slot_rows.append((name, v, ja, '' if errs else ut,
                          ';'.join(errs) if errs else loc))
        if errs and ja:
            over_rows.append((name, v, ut, errs, loc))
    print(f'slot-mapped: {sum(1 for r in slot_rows if r[3])} clean, '
          f'{sum(1 for r in slot_rows if not r[3])} QA-failed')
    sim_rows = []
    for row in plan['index'].values():
        if row['mode'] != 'sim':
            continue
        name, a = row['rel'], int(row['pos'], 16)
        px = _psx_answer_text(name, a, talkt)
        ut = answers_port_plan.us_text(row)
        if talktl.check(px, ut, False, talktl.ANS_W, 1):
            raise answers_port_plan.PlanError(
                f'answers plan sim source no longer fits {name}/{a:#x}; recapture')
        sim_rows.append((name, a, px, ut,
                         f'slot-sim {answers_port_plan.locator(row)}'))
    print(f'slot-sim positional: {len(sim_rows)} QA-clean')
    anchor_rows = []
    for row in plan['index'].values():
        if row['mode'] != 'anchor':
            continue
        name, a = row['rel'], int(row['pos'], 16)
        px = _psx_answer_text(name, a, talkt)
        ut = answers_port_plan.us_text(row)
        if talktl.check(px, ut, False, talktl.ANS_W, 1):
            raise answers_port_plan.PlanError(
                f'answers plan anchor source no longer fits {name}/{a:#x}; recapture')
        anchor_rows.append((name, a, px, ut,
                            f'slot-anchor {answers_port_plan.locator(row)}'))
    print(f'slot-anchor positional: {len(anchor_rows)} QA-clean')
    cands = collections.defaultdict(list)
    for row in plan['fuzzy']:
        cands[(row['rel'], row['pos'])].append(
            (float(row['split']), answers_port_plan.us_text(row),
             answers_port_plan.locator(row)))
    if apply:
        _apply_output(rows, slot_rows, over_rows, sim_rows, anchor_rows, slot_loc)
        write_fuzzy_notes(cands)
    rows.sort(key=lambda r: int(r[0]))
    return rows


def collect(apply=False):
    if answers_port_plan.replaying():
        return _collect_replay(apply)
    return _collect_live(apply)


if __name__ == '__main__':
    if '--without-psp-jp' in sys.argv:
        os.environ[answers_port_plan.REPLAY_ENV] = str(answers_port_plan.PLAN)
    collect('--apply' in sys.argv)
