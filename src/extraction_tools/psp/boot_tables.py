"""English names from the PSP-US BOOT tables (positional, PSX order verified).

The decrypted PSP-US BOOT image holds data tables in the same order as the
PSX SLPS tables: personas (100 x 0x4C, name = 18 words at +40 bytes),
demons, skills, items (strides below). Names are u16BE glyph codes decoded
with the US map, FFFF-padded. RACES is the exception: an LE 0000-terminated
0x10-stride menu table (same order as the PSX field-race table, verified via
the demon records' race bytes); it lands in translation/generated/strings/
because the table is shared by three overlays, not one binary.

Output is translation/generated/<BINARY>/<TABLE>.tsv ONLY (rows with usable
auto English; gaps and over-cap rows live in manual only, with the real
wording noted): SLPS_005.00 tables under
translation/generated/SLPS_005.00/, BANNER under
translation/generated/BTLP.BIN/ (where BTLP.BIN/BTLMSG.tsv already
lives). Every run also refreshes the disc-text cache
data/cache/boot_tables.tsv (table, idx, file offset, en)
so the BOOT text exists in extracted_text too, independent of the PSX port.
Manual tables are never written
here: each domain tool's dump() trims them to human-needed rows. Each
domain tool's own build (charset/length rules) is the validator.

Usage: python src/extraction_tools/psp/boot_tables.py [domain ...]
       domains: personas | demons | skills | items | nicknames | banner | races | banks | be

The `be` domain is the complete BE-text dump of the image (every glyph run
over the whole BOOT, codes kept inline) -> data/extracted_text/psp_us/
data/cache/boot_be.tsv (offset, term, text): the authoritative "is there text left in
BOOT?" artifact consumed by boot_census.py.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
from codec import US_MAP  # noqa: E402
from tables import be_chain, be_padded_names, be_runs, le_stride_names  # noqa: E402
import boot as _boot  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
import strlib  # noqa: E402

BOOT = None  # resolved via boot.us_boot() (cached decrypted image)
NL = chr(10)
# Working caches of EBOOT ranges: extracted_text holds one canonical TSV
# per real disc file (EBOOT.tsv here), so the caches live in data/cache.
CACHE = os.path.join(ROOT, 'data', 'cache', 'boot_tables.tsv')

TABLES = {
    # domain: (base, stride, count, name_off_words, name_len_words)
    # BE FFFF-padded fixed records (LE stride tables live in LE_TABLES).
    'personas': (0x265838, 0x4C, 100, 20, 18),
    'demons': (0x271734 - 48, 0x58, 194, 24, 20),
    'items': (0x26a440, 0x40, 386, 0, 20),  # 382 PSX-mapped (slot 0 = Medicine) + 4 PSP-only tail extras
    'skills': (0x267638, 0x30, 242, 0, 20),
    'nicknames': (0x27144E, 0x48, 9, 0, 10),
}

LE_TABLES = {
    # domain: (base, stride, count) — LE 0000-terminated stride slots.
    # Demon races: 26 entries, verified positional against PSX order via the
    # demon records' race bytes (PSP 0-based +0x01 == PSX 1-based +0x0B,
    # 154/194 agree; the rest follow the same N->N-1 pattern).
    'races': (0x2879a0, 0x10, 26),
}

# Back-to-back BE description banks (no fixed stride; see tables.be_chain):
# enemy names then item/skill descriptions. Order-mapping to the PSX DESCS
# zone is follow-up work; this domain only fills the extracted_text cache.
BANKS = (0x275044, 0x27c000)


def _over_note(draft, cap, unit='chars', amount=None):
    """Canonical over-cap note (reason; draft) for _write_pair rows. `amount`
    is the measured size when the family measures something other than the
    character count (skills: rendered px); it defaults to len(draft)."""
    import toolbelt as t
    return t.over_note(t.note_over(len(draft) if amount is None else amount,
                                   cap, unit), draft)


def _injection(name):
    sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
    return __import__(name)


def gen_personas(names):
    personas = _injection('personas')
    rows = []
    for k, a, ja in personas.records():
        auto = names[k - 1] if 0 <= k - 1 < len(names) else ''
        if auto and len(auto) > 16:
            rows.append((k, [str(k), f'{a:08X}', ja, '', _over_note(auto, 16)]))
        else:
            rows.append((k, [str(k), f'{a:08X}', ja, auto,
                              'psp-boot' if auto else '']))
    return 'id\trecord\tja\ten\tnote', rows


def gen_demons(names):
    rows = []
    sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
    import demons
    for k, a, ja in demons.records():
        auto = names[k - 1] if 0 <= k - 1 < len(names) else ''
        tier, px = demons.name_fit(auto) if auto else (0, 0)
        if auto and tier is None:
            # the row is retail's ten 8-px cells and the condensed tier still
            # cannot hold the name: it goes to manual as a draft (the
            # Japanese stays on disc) like every other unsendable wording.
            rows.append((k, [str(k), f'{a:08X}', ja, '',
                             _over_note(auto, demons.ROW_PX, 'px', px)]))
        else:
            rows.append((k, [str(k), f'{a:08X}', ja, auto,
                             'psp-boot' if auto else '']))
    return 'id\trecord\tja\ten\tnote', rows



def _pos(a):
    """Record address -> canonical pos cell. File offsets pass through;
    RAM addresses convert to file offsets here."""
    import toolbelt as t
    return hex(a) if a < 0x80010000 else hex(t.va_file_offset(a))

def gen_items(names):
    sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
    import items
    rows = []
    for k, rec in enumerate(items.records()):
        a, nm = rec[0], rec[1]
        ja = nm if isinstance(nm, str) else items.ja(nm)
        auto = names[k] if 0 <= k < len(names) else ''
        tier, px = items.name_fit(auto) if auto else (0, 0)
        if auto and tier is None:
            # ten 8-px cells and the condensed tier still cannot hold it: the
            # name is drafted to manual (the Japanese ships) instead of
            # spilling into the row's count column
            rows.append((k, [str(k), _pos(a), ja, '',
                             _over_note(auto, items.ROW_PX, 'px', px)]))
        else:
            rows.append((k, [str(k), _pos(a), ja, auto, '']))
    return 'idx\taddr\tja\ten\tnote', rows


def gen_skills(names):
    sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
    import skills
    rows = []
    for rec in skills.records():
        i, a, ja = rec[0], rec[1], rec[2]
        auto = names[i] if 0 <= i < len(names) else ''
        px = skills.width_px(auto) if auto else 0
        if auto and px > skills.NAME_PX:
            rows.append((i, [str(i), f'{a:08X}', ja, '',
                             _over_note(auto, skills.NAME_PX, 'px', px)]))
        else:
            rows.append((i, [str(i), _pos(a), ja, auto, 'psp-boot' if auto else '']))
    return 'idx\tram\tja\ten\tnote', rows


def gen_nicknames(names):
    sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
    import nicknames
    rows = []
    for i, rec in enumerate(nicknames.records()):
        a, ja = rec[0], rec[1]
        auto = names[i] if 0 <= i < len(names) else ''
        rows.append((i, [str(i), _pos(a), ja, auto]))
    return 'idx\tram\tja\ten', rows


def gen_races(names):
    """Field-trial race names (ADV/DNG/S2D 6-cell fields): every PSP race
    fits, so usable rows carry auto English and the manual worklist keeps
    only human overrides."""
    sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
    import demons
    rows = []
    for i, ja in demons.races():
        auto = names[i] if 0 <= i < len(names) else ''
        if auto and len(auto) > demons.RACE_LEN:
            rows.append((i + 1, [str(i + 1), f'{i * demons.RACE_LEN:02X}', ja, '',
                                 _over_note(auto, demons.RACE_LEN)]))
        else:
            rows.append((i + 1, [str(i + 1), f'{i * demons.RACE_LEN:02X}', ja, auto,
                                 'psp-boot' if auto else '']))
    return 'id\tfield\tja\ten\tnote', rows


def gen_banner():
    """BANNER rows via positional mapping (verified: every text-filled row
    agrees with it, 234/234): BANNER 1-242 = PSP skill names[idx-1],
    243-346 = PSP item names[idx-243] (full PSP names: the 160px centered
    banner box fits them, unlike the 15-cell skill menu). Rows whose JA
    also text-matches keep the x-skills-items note; the rest get
    psp-boot-pos. 0/112/113 are RESERVE and stay blank."""
    sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
    import banner
    base, stride, count, off, length = TABLES['skills']
    names_s = table_names(base, stride, count, off, length) or []
    base, stride, count, off, length = TABLES['items']
    names_i = table_names(base, stride, count, off, length) or []
    src = {}
    src.update(strlib.en_map('SKILLS.tsv'))
    src.update(strlib.en_map('ITEMS.tsv'))
    rows = []
    for k, p, ja in banner.records():
        auto = src.get(ja, '')
        note = 'x-skills-items'
        if not auto and k not in (0, 112, 113):
            if 1 <= k <= 242 and k - 1 < len(names_s):
                auto, note = names_s[k - 1], f'psp-boot-pos:skill-{k - 1}'
            elif 243 <= k <= 346 and k - 243 < len(names_i):
                auto, note = names_i[k - 243], f'psp-boot-pos:item-{k - 243}'
        rows.append((k, [str(k), f'{p:08X}', ja, auto, note if auto else '']))
    return 'idx\tptr\tja\ten\tnote', rows


def table_names(base, stride, count, off, length):
    return be_padded_names(_boot.us_boot(), base, stride, count, off, length, US_MAP)


def le_names(base, stride, count):
    return le_stride_names(_boot.us_boot(), base, stride, count, US_MAP)


def _write_pair(manual_path, gen_rel, head, rows, psp=None):
    """Canonical writer (docs/TEXT_ARCHITECTURE.md): every domain lands in
    its real file's toolbelt table - id | pos | psp | en [, note]. The ja
    column is dropped (lookup = pos); over-cap rows carry en = the full
    PSP wording + note = 'over limit N/cap' and live in manual; plain gaps
    go to manual with an empty en (visible as empty). The only writer for
    boot_tables domains - no script may hand-roll TSV output."""
    import toolbelt as t
    cols = head.split('\t')
    ei = cols.index('en')

    def col(*names):
        for n in names:
            if n in cols:
                return cols.index(n)
        return None

    pi = col('record', 'ram', 'addr', 'ptr')
    if pi is None:
        print(f'boot_tables: {gen_rel}: no position column {cols} - SKIPPED '
              f'(needs per-overlay pos; todo)')
        return
    ii = col('id', 'idx')
    ni = cols.index('note') if 'note' in cols else None
    rel = os.path.dirname(gen_rel).removesuffix('.BIN')
    auto, gap = [], []
    for _id, fields in sorted(rows):
        en = fields[ei].strip()
        raw = fields[pi].strip()
        n = int(raw, 16)
        # Record scans yield file offsets; RAM addresses convert
        pos = raw if n < 0x80010000 else hex(t.va_file_offset(n))
        note = fields[ni].strip() if ni is not None else ''
        src = (psp or {}).get(fields[ii] if ii is not None else _id, '')
        if not en and note.startswith('over limit'):
            # over the slot: the note IS the row (reason; draft), en stays
            # empty - the build must never fail on a draft (JA ships).
            # route_over is THE over-limit writer and also drops any stale
            # generated row here, so a draft never keeps building.
            reason, _sep, draft = note.partition('; ')
            t.route_over(rel, pos, src, draft, reason)
            gap.append(1)
        elif en:
            auto.append({'pos': pos, 'en': en, 'psp': src})
        # plain gaps: nothing anywhere - the empty en in generated IS the
        # gap indicator; no filler notes
    if auto:
        t.upsert_generated(rel, auto)
    print(f'boot_tables: {gen_rel}: {len(auto)} auto, {len(gap)} over limit -> manual')
    print(f'boot_tables: {gen_rel}: done')


def write_cache(rows):
    """Refresh the disc-text cache: [(table, idx, offset, en)]."""
    old = {}
    if os.path.exists(CACHE):
        for r in strlib.tsv_rows(CACHE, required=('table', 'idx', 'offset', 'en')):
            old[(r['table'], int(r['idx']))] = (r['offset'], r['en'])
    for t, i, o, e in rows:
        old[(t, i)] = (f'{o:#x}', e)
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, 'w', encoding='utf-8', newline=NL) as f:
        f.write('table\tidx\toffset\ten' + NL)
        for (t, i), (o, e) in sorted(old.items()):
            f.write(f'{t}\t{i}\t{o}\t{e}' + NL)
    print(f'boot_tables: cache {CACHE} ({len(old)} rows)')


def main():
    cache = []
    for dom in sys.argv[1:] or ['personas']:
        if dom == 'banner':
            head, rows = gen_banner()
            _write_pair(os.path.join(ROOT, 'translation', 'manual', 'BTLP.BIN', 'BANNER.tsv'),
                        os.path.join('BTLP.BIN', 'BANNER.tsv'), head, rows)
            continue
        if dom == 'banks':
            rows = be_chain(_boot.us_boot(), BANKS[0], BANKS[1], US_MAP)
            if not rows:
                print('banks: chain parse FAILED')
                continue
            print(f'banks: {len(rows)} strings '
                  f'{BANKS[0]:#x}-{rows[-1][0]:#x}: {rows[0][1][:40]!r} ... {rows[-1][1][:40]!r}')
            path = os.path.join(ROOT, 'data', 'cache', 'boot_banks.tsv')
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8', newline=NL) as f:
                f.write('offset\ten' + NL)
                for off, text in rows:
                    f.write(f'{off:#x}\t{text}' + NL)
            print(f'banks: cache {path} ({len(rows)} rows)')
            continue
        if dom == 'be':
            rows = be_runs(_boot.us_boot())
            print(f'be: {len(rows)} records, '
                  f'{sum(1 for _, _, t in rows if t == "FF01")} boxes, '
                  f'{rows[0][0]:#x}-{rows[-1][0]:#x}')
            path = os.path.join(ROOT, 'data', 'cache', 'boot_be.tsv')
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8', newline=NL) as f:
                f.write('offset\tterm\ten' + NL)
                for off, text, term in rows:
                    f.write(f'{off:#x}\t{term}\t{text}' + NL)
            print(f'be: cache {path} ({len(rows)} rows)')
            continue
        if dom == 'races':
            base, stride, count = LE_TABLES['races']
            names = le_names(base, stride, count)
            if names is None:
                print('races: table parse FAILED')
                continue
            print(f'races: {len(names)} names: {", ".join(names)}')
            cache += [('races', i, base + i * stride, n) for i, n in enumerate(names)]
            # canonical: the same 26-name race table sits in every overlay
            # (identical copies - demons.build asserts it), so every spot gets
            # a row (the multi-spot rule, pos = each overlay's field offset)
            import demons as _demons
            import toolbelt as _t
            for ovl, va in _demons.RACE_TABLES.items():
                spec = [{'pos': hex(va - _demons.OVL_BASE + i * _demons.RACE_LEN),
                         'psp': f'EBOOT:{base + i * stride:x}', 'en': n}
                        for i, n in enumerate(names)]
                _t.upsert_generated(ovl, spec)
                _t.route_gaps(ovl, [r['pos'] for r in spec])
            continue
        base, stride, count, off, length = TABLES[dom]
        names = table_names(base, stride, count, off, length)
        if names is None:
            print(f'{dom}: table parse FAILED')
            continue
        print(f'{dom}: {len(names)} names, e.g. {names[:4]} ... {names[-2:]}')
        name_off = base + off * 2  # BE name words -> byte offset of slot 0
        cache += [(dom, i, name_off + i * stride, n) for i, n in enumerate(names)]
        man = os.path.join(ROOT, 'translation', 'manual', 'SLPS_005.00')
        if dom == 'personas':
            head, rows = gen_personas(names)
            psp = {str(i): f'EBOOT:{name_off + (i - 1) * stride:x}' for i in range(1, len(names) + 1)}
            _write_pair(os.path.join(man, 'PERSONAS.tsv'), os.path.join('SLPS_005.00', 'PERSONAS.tsv'), head, rows, psp=psp)
        elif dom == 'demons':
            head, rows = gen_demons(names)
            # the pointer names the slot the text came from (names[k - 1]):
            # a pointer one slot ahead shows the NEXT demon's name beside
            # this one.
            psp = {str(i): f'EBOOT:{name_off + (i - 1) * stride:x}' for i in range(1, len(names) + 1)}
            _write_pair(os.path.join(man, 'DEMONS.tsv'), os.path.join('SLPS_005.00', 'DEMONS.tsv'), head, rows, psp=psp)
        elif dom == 'items':
            head, rows = gen_items(names)
            psp = {str(i): f'EBOOT:{name_off + i * stride:x}' for i in range(len(names))}
            _write_pair(os.path.join(man, 'ITEMS.tsv'), os.path.join('SLPS_005.00', 'ITEMS.tsv'), head, rows, psp=psp)
        elif dom == 'skills':
            head, rows = gen_skills(names)
            psp = {str(i): f'EBOOT:{name_off + i * stride:x}' for i in range(len(names))}
            _write_pair(os.path.join(man, 'SKILLS.tsv'), os.path.join('SLPS_005.00', 'SKILLS.tsv'), head, rows, psp=psp)
        elif dom == 'nicknames':
            head, rows = gen_nicknames(names)
            psp = {str(i): f'EBOOT:{name_off + i * stride:x}' for i in range(len(names))}
            _write_pair(os.path.join(man, 'NICKNAMES.tsv'), os.path.join('SLPS_005.00', 'NICKNAMES.tsv'), head, rows, psp=psp)
    if cache:
        write_cache(cache)


if __name__ == '__main__':
    main()
