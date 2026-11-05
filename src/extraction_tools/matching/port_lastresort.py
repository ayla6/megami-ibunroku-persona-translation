"""LAST RESORT: the leftover net of the port. Not a porter, not an owner.

SCOPE, and it is the whole file: port_derive.LAST_RESORT_TABLES - the
string banks (ADV.tsv, DNG.tsv) that no family porter writes.
Every loop goes through tables() and every write goes through _guard(), so
this net cannot touch a porter's table at all.

Text comes from port_derive, destinations from port_caps, sources from
toolbelt, the JP<->US pairing from match_jp. A wording a family porter can
carry is that porter's job; this file only derives the rows nobody claimed.

  python src/extraction_tools/matching/port_lastresort.py              report
  python src/extraction_tools/matching/port_lastresort.py --apply     leftovers
"""
import os
import re
import sys

# Deterministic output: set/dict iteration order otherwise leaks the
# per-process hash seed into row content.
# Seed re-exec ONLY as a script: an import must never hijack the host
# process.
if __name__ == '__main__' and os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    os.execvpe(sys.executable, [sys.executable] + sys.argv, os.environ)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'matching'))
import toolbelt  # noqa: E402
import match_jp      # noqa: E402
import port_caps     # noqa: E402
from port_caps import ink_of   # noqa: E402  (the drawn characters of a row)
import port_derive   # noqa: E402

# the pieces this tool runs, by their one home (kept short here on purpose)
psx_text_of = toolbelt.psx_text_of
psp_wording = toolbelt.psp_wording
psp_name = toolbelt.psp_name
_psp_rel = toolbelt.psp_rel
_extract = toolbelt._extract
_psx_rels = toolbelt.psx_rels
is_textbox = port_caps.is_textbox
is_fixed_field = port_caps.is_fixed_field
family_row = port_caps.family_row
family_wording = port_caps.family_wording
family_at = port_caps.family_at
dest_note = port_caps.dest_note
dest_owned = port_caps.dest_owned
widest = port_caps.widest
fit_codes = port_derive.fit_codes
lay_out = port_derive.lay_out
codes_match = port_derive.codes_match
box_gate = port_derive.box_gate
unlayable_note = port_derive.unlayable_note
psx_params = port_derive.psx_params
HOLES = port_derive.HOLES
JAPANESE_REMNANT = port_derive.JAPANESE_REMNANT
renorm_generated = port_derive.renorm_generated
jp_row_at = match_jp.jp_row_at
twin_of = match_jp.twin_of
note_jp = match_jp.note_jp
same_psx_text = match_jp.same_psx_text


# The families whose field holds SENTENCES, not a name: a description, an
# affinity line. A skill's or demon's NAME is not such a row's wording,
# however well it names the row (that is how 'βTrafuri' reached a PSX
# description slot) - so the name-core licence does not reach them.
DESCRIPTION_FAMILIES = ('descs', 'affinity')


def tables():
    """THE ONLY TABLES THIS NET MAY TOUCH (port_derive.LAST_RESORT_TABLES).

    port.py runs the family porters first and each owns its own tables; this
    net exists for the string banks nobody claims. Scoping every loop here is
    what stops it from shipping a second, disagreeing derivation of a porter's
    rows - that is how 4,711 TALK rows lost the head of their wording.
    """
    return [r for r in _psx_rels() if r in port_derive.LAST_RESORT_TABLES]


def _guard(rel):
    """Refuse to write outside the net's tables. One owner per table."""
    if rel not in port_derive.LAST_RESORT_TABLES:
        raise SystemExit(f'port_lastresort: {rel} is a family porter\'s table '
                         f'(port.py) - the leftover net must not write it')


def name_field(rel, pos):
    """Is this slot a NAME field? A one-line slot in a family that names
    things - not a textbox, and not a family whose wording is a SENTENCE
    (DESCRIPTION_FAMILIES).

    Only such a field may take its wording from a name (the name-core
    licence, and the file's own memory by CONTAINMENT): a description that
    mentions a skill's name is not that skill's name, and shipping the name
    there is how 'Trafuri' reached a slot whose Japanese says 'you do not
    have Trafuri'. Same Japanese, though, is always the same wording."""
    return (not is_textbox(rel)
            and family_at(pos, rel) not in DESCRIPTION_FAMILIES)


def owns(rel):
    """Whether this tool may touch a row of this file at all.

    A textbox the FAMILY PORTERS claim is matched and ported AS a
    textbox - port_story for the event boxes (ADV/Ex), port_s2d,
    port_dng, port_talk, btlp - and those porters own the whole pipeline
    (labels, breaks, the reflow, the pagination). This tool is the
    leftover net: the name and description slots, and the ADV system
    prompts (sysmsg/scriptmsg/giftmsg) no family porter covers - which
    are TEXTBOXES too and go through the same derivation (port_derive),
    never a bespoke one."""
    if rel == 'ADV' or rel.startswith(('ADV/', 'D0', 'TALK/')) or rel in (
            'S2D', 'DNG', 'BTLP', 'CASINO'):
        return rel == 'ADV' or is_name_field(rel) or not is_textbox(rel)
    return not is_textbox(rel)


def is_name_field(rel):
    return port_caps.is_name_field(rel)


def unclaimed(rel):
    """[(pos, ja)] of this file's units nobody has translated or sourced -
    the only rows this tool exists for. The state of a row is its `en`
    and its `psp`: a note is a note (provenance for a human, rewritten
    fresh by whatever runs next) and never a claim on the row. The `psp `
    machine notes are re-derived through ready(), not here."""
    if not owns(rel):
        return []                      # a family porter owns every row
    ja = psx_text_of(rel)
    gen = {r['pos']: r for r in toolbelt.read_generated(rel, optional=True)}
    man = {r['pos']: r for r in toolbelt.read_manual(rel, optional=True)}
    out = []
    for pos, text in ja.items():
        g, m = gen.get(pos), man.get(pos)
        if (m or {}).get('en', '').strip() or (g or {}).get('en', '').strip():
            continue
        if (m or {}).get('psp') or (g or {}).get('psp'):
            continue
        out.append((pos, text))
    return out


def ready(rel):
    """[(pos, jp pointer)] leftover rows this tool has already sourced.

    A row whose note is a `psp ` note is THIS TOOL's to re-derive; if its
    source no longer holds, the wording goes back too. The note's own tier
    is not trusted: main() recomputes it from the two Japanese strings, so
    a lead can never reach `en` on the strength of a stale note.

    A row a family porter has since finished is NOT a leftover. Its filled
    `en` (in generated or manual) is owned by that porter, and re-deriving
    here would overwrite it. Those rows are skipped.

    Every queue row is re-derivable except one holding a draft another pass
    routed (over limit, Japanese remnant).
    The Japanese to match comes from the note when it names one, else from
    the row's own scanned text."""
    man = {r['pos']: r for r in toolbelt.read_manual(rel, optional=True)}
    gen = {r['pos']: r for r in toolbelt.read_generated(rel, optional=True)}
    ja_of = psx_text_of(rel)
    out = []
    # every SCANNED position of the table, not only the ones a queue already
    # lists: the queue is written later in the build, so a from-scratch run
    # would otherwise find nothing to derive
    for pos in ja_of:
        m = man.get(pos) or {}
        if (m.get('en') or '').strip():
            continue                      # a human owns this row
        if ((gen.get(pos) or {}).get('en') or '').strip():
            continue                      # a family porter already shipped it
        note = (m.get('note') or '').strip()
        if note.startswith(('over limit', 'untranslated Japanese remnant')):
            continue                      # a draft another pass owns
        jp = note_jp(note) or (ja_of.get(pos) or '')
        if jp:
            out.append((pos, jp))
    return out


_TM = {}


def _memory(rel):
    """{core: (psp, en)} of this file's own proven translations - the
    generated rows. A name this file already says in English, with a
    source, is the answer for every other slot that carries the same
    Japanese: same lookup, not a guess."""
    if rel not in _TM:
        ja_of = psx_text_of(rel)
        m = {}
        for r in toolbelt.read_generated(rel, optional=True) or []:
            en = (r.get('en') or '').strip()
            j = re.sub(r'<FF[0-9A-F]{2}>|\s|　', '', ja_of.get(r['pos'], ''))
            if en and j:
                m.setdefault(j, ((r.get('psp') or '').strip(), en))
        _TM[rel] = m
    return _TM[rel]


def place(crel, crow, tier, jp_ptr, ja='', pos='', rel=''):
    """(psp, en, note, draft) for one match - the three cases above. `psp`
    is always the US unit's locator or empty; `jp_ptr` only ever reaches
    the note. `draft` is the wording when the destination cannot hold it
    (route_over composes `<reason>; <draft>` from `note` and `draft` -
    `note` is the REASON alone); empty otherwise.

    `tier` is the licence and it is checked HERE: a lead is a suggestion,
    so it never sources a row - it leaves the ordinary gap marker."""

    def keep(ptr, text):
        """Ship or draft a derived wording, measured at its destination.
        A wording that still shows glyph holes is a Japanese remnant, not
        English: it is kept as a draft with that reason, never `en`."""
        if HOLES.search(ink_of(text)):      # ink: FFFD params are not wording
            return ptr, '', JAPANESE_REMNANT, text
        note = dest_note(text, rel, pos, ja)
        return (ptr, text, '', '') if not note else (ptr, '', note, text)

    # FIRST: is this PSX position a known family slot? That is identity, not
    # similarity - the record at that offset IS this unit - so it outranks
    # whatever the text matcher thought. A skill description is reworded
    # wholesale between builds and no text match will ever find it.
    fptr, ftext, _ffam = family_wording(ja, pos)
    if ftext.strip():
        raw = fit_codes(ftext, ja, strict=is_fixed_field(rel, pos))
        ftext = lay_out(raw, rel, ja)
        if not ftext.strip():
            return fptr, '', (unlayable_note(raw)
                              or 'does not fit the box'), raw
        if codes_match(ftext, ja):
            return keep(fptr, ftext)
    if not is_textbox(rel) and widest(ja)[1] <= 1:
        same = same_psx_text(ja)
        if same:
            raw = fit_codes(same, ja, strict=True)
            same = lay_out(raw, rel, ja)
            if same.strip() and codes_match(same, ja):
                return keep('', same)
    # THE FILE'S OWN MEMORY (name and note fields): a battle note is the
    # skill's own line - strip the target token and the string either IS a
    # Japanese this file already translated, or names it verbatim. Identity
    # by exact or UNIQUE containment - the same proof the primary row had -
    # and its source pointer rides along. Two candidates is a guess, and
    # guesses stay leads.
    if not is_textbox(rel):
        core = re.sub(r'<FF[0-9A-F]{2}>|\s|　', '', ja)
        core = re.sub(r'^[敵味][１全複]', '', core)
        mem = _memory(rel)
        hit = mem.get(core)
        if hit is None and len(core) >= 2 and name_field(rel, pos):
            picks = [(j, v) for j, v in mem.items()
                     if core in j or (j and j in core)]
            if len(picks) == 1:
                hit = picks[0][1]
        if hit:
            fptr, ftext = hit
            raw = fit_codes(ftext, ja, strict=is_fixed_field(rel, pos))
            ftext = lay_out(raw, rel, ja)
            if ftext.strip():
                return keep(fptr, ftext)
    if tier == 'lead':
        # text similarity can only SUGGEST that this JP row is the PSX
        # line's source - a stray あ, a reworded description, a speaker
        # tag. A reader who can read both sides settles it, and that is
        # recorded in psx_jp_extra.tsv.
        if crow is not None and match_jp.psx_jp_confirmed(
                rel, pos, jp_ptr):
            tier = 'read'
        else:
            # NAME-CORE LICENCE (name and note fields): the JP row's last
            # segment - the skill's name under its build's decoration
            # ('畢 n' glitches and all) - names the PSX row's skill when a
            # substantial suffix of it appears verbatim in the PSX line.
            # That is a read, not a lead. Anything fuzzier is no source at
            # all.
            segs = [s.strip() for s in
                    re.split(r'<FF[0-9A-F]{2}>', crow['text'] or '') if s.strip()]
            seg = segs[-1] if segs else ''
            ja_bare = re.sub(r'\s+|　', '', ja)
            core = max((seg[i:] for i in range(len(seg))
                        if len(seg) - i >= 3 and seg[i:] in ja_bare),
                       key=len, default='')
            if not (name_field(rel, pos) and core):
                # A lead is a suggestion, not a source: nothing can be
                # shipped from it, so the row is an ordinary work-queue
                # gap and says what it IS (its scanned Japanese). The
                # candidate's percentage said how similar the two lines
                # look, which nobody can type and which is not what the
                # row is waiting for - a human plus a reader's confirmation
                # (psx_jp_extra.tsv).
                return '', '', toolbelt.gap_marker(ja), ''
            tier = 'core'
    us = twin_of(crel, crow)
    if us is not None:
        ptr = f'{psp_name(crel)}:{us["pos"]}'
        text = us['text']
        # THE RECORD HEAD (port_derive.wording_head - one rule, also run by
        # the renorm): these name-table rows carry the same glitch head on
        # both sides ('畢 n押し潰し' / '畢 nBonecrusher'), the JP row proves
        # how much of it is furniture, and where nobody paired the row its
        # half-decoded cell ('nBonecrusher') is all that is left of it.
        if is_fixed_field(rel, pos):
            text = text[port_derive.wording_head(crow['text'] if crow is not None
                                                else '', text):]
    else:
        # no JP<->US pair, but a SLPS family record may name this unit and
        # carry the porter's US source for it
        ptr, text, _fam2 = family_wording(ja, pos)
    if not text.strip() or port_derive.still_japanese(text):
        # The Japanese was found and no PSP-US WORDING follows it - the pair
        # map holds no twin, or the twin is a box the US build never
        # translated. Nothing can ship, so the row says what it is. Deriving
        # a Japanese line into an ASCII destination only re-spells it as
        # glyph indices ('[0ad7][0b5f]'), which reads like a decode failure
        # and explains nothing to whoever has to translate the row.
        return '', '', toolbelt.gap_marker(ja), ''
    # THE derivation (port_derive), the same one every porter runs on its
    # first pass - codes, layout, and the destination's own reason. The
    # wording's Japanese twin rides along where the pair is proven (the
    # three-text rules read it).
    laid, why = port_derive.derive(text, ja, rel, pos)
    if why == 'codes differ from the Japanese':
        # the source is real and the WORDING is right - it just cannot ship
        # into a slot whose structure is another's. That is a draft like any
        # other: the reviewer sees the wording and rewrites it to fit.
        return ptr, '', why, laid
    if why:
        return ptr, '', why, laid or text
    return keep(ptr, laid)


def redraft():
    """Recompute every parked row from its `psp` source with today's
    rules. STATELESS: a row's state is its `en` and its `psp` - the note
    is not consulted, because a note is a note (what a human reads), not
    a decision. The source is the truth; if the destination now accepts
    the wording it SHIPS, and if not the note is rewritten fresh from
    today's measurement. Nothing is ever parsed out of a note."""
    n = 0
    withdrawn = 0
    # A PORTER'S TABLE IS NOT THE NET'S (port_derive.LAST_RESORT_TABLES). The
    # net drafts rows only for banks no family porter writes.
    for rel in tables():
        ja_of = psx_text_of(rel)
        shipped = []
        drop = set()
        gen = {r['pos']: r for r in toolbelt.read_generated(rel, optional=True)}
        for r in toolbelt.read_manual(rel, optional=True):
            if (r.get('en') or '').strip() or not (r.get('psp') or '').strip():
                continue            # a human's wording, or an unclaimed row
            ja = ja_of.get(r['pos'], '')
            draft = psp_wording(r['psp'])
            if not draft:
                continue
            if port_derive.still_japanese(draft):
                # the source is an untranslated box (port_derive.still_japanese):
                # there is no wording to place, and the row is a plain gap
                toolbelt.route_to_manual(rel, {'pos': r['pos'], 'psp': '',
                                               'en': '',
                                               'note': toolbelt.gap_marker(ja)})
                n += 1
                continue
            laid, why = port_derive.derive(draft, ja, rel, r['pos'])
            if not laid:
                # the wording cannot be laid out at all: the draft is the
                # whole wording, and the note says what the box could not
                # show (its own numbers, not the Japanese line's length)
                laid = draft
                why = why or 'does not fit the box'
            draft = laid
            if not why:
                shipped.append({'pos': r['pos'], 'psp': r.get('psp') or '',
                                'en': draft})
                continue
            g = gen.get(r['pos'])
            if g and (g.get('en') or '').strip() and (
                    HOLES.search(ink_of(g.get('en') or ''))
                    or dest_note(g.get('en') or '', rel, r['pos'], ja)):
                drop.add(r['pos'])
            toolbelt.route_over(rel, r['pos'], r.get('psp') or '',
                                draft, why)
            n += 1
        if drop:
            keep = [g for g in gen.values() if g['pos'] not in drop]
            toolbelt.write_generated(rel, keep)
            withdrawn += len(drop)
        if shipped:
            _guard(rel)
            toolbelt.upsert_generated(rel, shipped)
            _guard(rel)
            toolbelt.route_gaps(rel, [])     # drop the notes they supersede
            n += len(shipped)
    return n, withdrawn


def main():
    """THE LEFTOVER NET. Its whole job: rows in the string banks no family
    porter writes (port_derive.LAST_RESORT_TABLES), derived from their `psp`
    source through today's pipeline. It never writes a porter's table - the
    guard refuses it - and it has no repair/sweep mode to drift into."""
    args = set(sys.argv[1:])
    unknown = args - {'--apply'}
    if unknown:
        raise SystemExit(f'port_lastresort: unknown option {", ".join(sorted(unknown))}'
                         f'\n  usage: port_lastresort.py [--apply]')
    apply = '--apply' in args
    if apply:
        # GENERATED IS DERIVED DATA: the leftover rows re-derive from their
        # `psp` source through today's pipeline on every run.
        renorm_generated()
    stat = {'exact': 0, 'canonical': 0, 'lead': 0, 'ported': 0, 'over': 0,
            'ready': 0, 'no source': 0}
    for rel in tables():
        done, todo = [], []
        psx_ja = psx_text_of(rel)
        before = {r['pos']: (r.get('note') or '')
                  for r in toolbelt.read_manual(rel, optional=True)}
        for pos, jp_ptr in ready(rel):
            if ':' not in jp_ptr:
                # NO RECORDED POINTER: pair the Japanese named in the note
                # under the same licence as the unclaimed pass: only a PROVEN tier sources a
                # row, a lead stays a note.
                cs = match_jp.find(jp_ptr, want=6)
                if not cs or cs[0][2] not in ('exact', 'canonical'):
                    continue
                crel, crow, tier = cs[0][0], cs[0][1], cs[0][2]
                jp_ptr = f'{psp_name(crel)}:{crow["pos"]}'
            else:
                told = match_jp.psx_jp_target(rel, pos)
                if told and told != jp_ptr:
                    jp_ptr = told
                crel, crow = jp_row_at(jp_ptr)
                if crow is None:
                    continue
                tier = match_jp.tier(psx_ja.get(pos, ''), crow['text'])
            psp, en, note, draft = place(crel, crow, tier, jp_ptr,
                                         psx_ja.get(pos, ''), pos, rel)
            if en or draft:
                stat['ready'] += 1
            elif apply:
                # this row was ported once and its source no longer holds:
                # the wording goes back too, or it would keep building
                # something nobody can account for
                toolbelt.unport(rel, pos)
            # a note is a reason: never blank a row's note on the way past
            done.append((pos, psp, en, note or before.get(pos, ''), draft))
        for pos, ja in unclaimed(rel):
            cands = match_jp.find(ja, want=6)
            if not cands or cands[0][2] == 'lead':
                # the slot join outranks similarity: the PSP rewrote many
                # lines (nameplates, full stops, its own extra boxes), and
                # a rewrite is exactly the line whose text match is only a
                # lead. The shared (entry, box) - validated, +-2 drift, by
                # match_jp.psx_id_twin - is the same line's proof.
                itwin = match_jp.psx_id_twin(rel, pos)
                if itwin is not None:
                    cands = [(match_jp.psx_jp_rel(rel), itwin,
                              'coordinate', 0.0)] + cands
            if not cands:
                stat['no source'] += 1
                psp, en, note, draft = place(None, None, 'none', '', ja, pos, rel)
                if en or draft:
                    done.append((pos, psp, en, note, draft))
                continue
            crel, crow, tier, _ratio = cands[0]
            stat[tier] = stat.get(tier, 0) + 1
            jp_ptr = f'{psp_name(crel)}:{crow["pos"]}'
            told = match_jp.psx_jp_target(rel, pos)
            if told and told != jp_ptr:
                jp_ptr = told
                crel, crow = jp_row_at(jp_ptr)
                if crow is None:
                    continue
                tier = match_jp.tier(ja, crow['text'])
            psp, en, note, draft = place(crel, crow, tier, jp_ptr, ja,
                                         pos, rel)
            if not en and not draft:
                psp = ''            # no source ships: the pointer goes too
                note = note or toolbelt.gap_marker(ja)
            done.append((pos, psp, en, note, draft))
        for pos, psp, en, note, draft in done:
            if en:
                stat['ported'] += 1
            elif draft:
                stat['over'] += 1
        todo = done
        if not todo:
            continue
        if not apply:
            for pos, psp, en, note, over in todo:
                print(f'  {rel} {pos}  {note or "ported":28} {psp}'
                      + (f'  -> {en[:52]!r}' if en else ''))
            continue
        ported = [{'pos': pos, 'psp': psp, 'en': en}
                  for pos, psp, en, _n, _o in todo if en]
        if ported:
            _guard(rel)
            toolbelt.upsert_generated(rel, ported)
        for pos, psp, en, note, draft in todo:
            if en:
                continue
            if draft:
                toolbelt.route_over(rel, pos, psp, draft, note)
            else:
                toolbelt.route_to_manual(rel, {'pos': pos, 'psp': '',
                                               'en': '', 'note': note})
        print(f'{rel}: {len(ported)} ported, '
              f'{sum(1 for x in todo if x[4])} over budget, '
              f'{sum(1 for x in todo if not x[1] and not x[4])} sourced '
              f'for a human')
        _guard(rel)
        toolbelt.route_gaps(rel, [])
    print(f"\nport_lastresort: {stat['exact']} exact, {stat['canonical']} "
          f"canonical, {stat['lead']} leads, {stat['ported']} given wording "
          f"({stat['ready']} of them were rows already matched), "
          f"{stat['over']} over budget, {stat['no source']} without a source")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
