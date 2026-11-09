"""Battle UI texts of BTLP.BIN outside the btlmsg zone: ANALYZE labels, race tags, CONTACT personalities, AUTO modes.

  python tools/btlui.py     write build/btlui.asm (included in the BTLP section of main.asm)

* Race tags (ANALYZE header "シキ:Zombie Gir"): BTLP table at RAM 0x800E2060, 8-byte slots, slot k = race id k
  (id 1 = ヤマ ... 27 = ボンジン), small font + ':' (0xCB) + FF. Slots 1-22 come from the PSP-US BOOT race table
  (translation/generated/strings/RACES.tsv, positional); 24/26 reuse it shifted (シニガミ/マオウ). Ids 23 ジボシン,
  25 ジャシン, 27 ボンジン (a human) are not in any PSP table found so far; their English is literal and flagged
  in review.tsv (pack-survey target).
* ANALYZE labels (small font, FF end, text-object records at 0x800DEB90..): まほうこうげき / まほうぼうぎょ (8-byte slots) and
  とくせい： (slot of 8). The trait text itself is a separate record whose x is moved one cell right (0xFFA0 -> 0xFFA8,
  halfword at 0x800DEBF4) so that "TRAIT:" (6 cells) does not touch it. Its 47-cell head + pool-tail
  buffer, append hook and descriptor pointer/count live in btlp/analyze_trait.asm.
* CONTACT personalities: eight complete PSP-US source strings in the 64-byte
  private small-font bank at 0x800C87EC, with pointers at 0x800CDD50. Source
  bit/slot identity is proved from both PSP consumers and 193 PSX/PSP profile
  masks. The offer-only GTE quad path uses packed small-font bearings/advances;
  its original four-column frame and layout are unchanged.
* AUTO modes (small font, 3 strings, 10-byte slots, FF end) at 0x800DE5FC / 0x800DE606 / 0x800DE610.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import etext   # noqa: E402
import items   # noqa: E402
import features  # noqa: E402
import personality_source  # noqa: E402
import smallfont_vwf  # noqa: E402
import skills  # noqa: E402
import strlib  # noqa: E402

ROOT = etext.ROOT
B = 0x800643C4
NL = chr(10)
OUT = os.path.join(ROOT, 'build', 'btlui.asm')

# BTLP-only slots with no PSP source (literal glosses from glossary.tsv).
LITERAL_RACES = {int(k): v for k, v in strlib.glossary('race_literal').items()}


def psp_races():
    """27 race tags: PSP-BOOT positional for every slot the field table covers
    (1-22 direct, 24/26 shifted past the BTLP-only slots), literals above.
    Source: the canonical race rows - every overlay holds an identical copy
    of the 26-name table (multi-spot rule)."""
    import demons
    import toolbelt
    gen = {}
    for rel in ('ADV', 'DNG', 'S2D'):
        rows = {}
        for r in (toolbelt.read_generated(rel, optional=True)
                  + toolbelt.read_manual(rel, optional=True)):
            pos = int(r['pos'], 16)
            base = demons.RACE_TABLES[rel] - demons.OVL_BASE
            if base <= pos < base + demons.RACE_COUNT * demons.RACE_LEN:
                rows[(pos - base) // demons.RACE_LEN + 1] = (r.get('en') or '').strip()
        if len([v for v in rows.values() if v]) >= 26:
            gen = rows
            break
    if len([v for v in gen.values() if v]) < 26:
        raise SystemExit('btlui: the canonical race rows are incomplete '
                         '(run src/extraction_tools/psp/boot_tables.py races)')
    out = [gen[k] for k in range(1, 23)]
    # BTLP slots past 22 skip field 25 (マジンノウ has no BTLP tag), so the
    # generated ids do not line up 1:1 here: 24 = field 23, 26 = field 24.
    shifted = {24: 23, 26: 24}  # BTLP slot -> generated RACES id
    out += [LITERAL_RACES[k] if k in LITERAL_RACES else gen[shifted[k]] for k in (23, 24, 25, 26, 27)]
    assert len(out) == 27, out
    return out


RACES = None  # resolved in main() from psp_races()
PERSONALITIES = None  # resolved at build from the proven PSP pointer table
AUTO = [(int(k, 16), v) for k, v in sorted(strlib.glossary('auto').items())]


def sf(t):
    return bytes(skills.glyph(c) for c in t)       # small font: A-Z, a-z, 0-9, space, - . ' / :


def vwf(t):
    return bytes(ord(c) + 0x68 for c in t)


def block(addr, b):
    return f'.org {addr:#x}{NL}    .byte ' + ', '.join(f'0x{x:02X}' for x in b) + NL


def guard_offer_retail(d):
    """Fail closed if the retail hook sites or candidate duplicate drift."""
    hook_sites = (
        (0x80078574, (0x001410c0, 0xafa00028)),
        (0x800788b8, (0xac2283a8, 0x00671824, 0x00641825, 0xaca30000,
                       0x92230000, 0x340200ff, 0x1462ff24, 0x26940001)),
        # The eight quad-text glyph loads (U/V of the offer panel's four
        # corners) retarget through the proportional selector; each keeps its
        # retail footprint (the load moves into the call's delay slot).
        (0x80078608, (0x92240000, 0)), (0x8007863c, (0x92220000, 0)),
        (0x80078670, (0x92240000, 0)), (0x800786a8, (0x92220000, 0)),
        (0x800786dc, (0x92240000, 0)), (0x80078710, (0x92220000, 0)),
        (0x80078748, (0x92240000, 0)), (0x80078780, (0x92220000, 0)),
    )
    for at, expected in hook_sites:
        actual = struct.unpack_from(f'<{len(expected)}I', d, at - B)
        if actual != expected:
            raise ValueError(f'btlui: retail offer glyph hook changed at {at:#x}')
    dead = 0x800b9f58 - B
    if d[dead:dead + 32] != d[dead - 32:dead] or len(d[dead:dead + 32]) != 32:
        raise ValueError('btlui: duplicate BTLP code fragment changed')
    # Check all active BTLP/SLPS aligned words for direct entry into ANY byte
    # of the candidate: jumps, branches, addresses and nearby LUI pairs.
    main = os.path.join(ROOT, 'data', 'psx', 'SLPS_005.00')
    with open(main, 'rb') as source:
        exe = source.read()
    exe_base = struct.unpack_from('<I', exe, 0x18)[0]
    inputs = [(d, B, True), (exe[0x800:], exe_base, True)]
    for path in sorted(os.listdir(os.path.join(ROOT, 'data', 'psx'))):
        if not path.endswith('.BIN') or path == 'BTLP.BIN':
            continue
        full = os.path.join(ROOT, 'data', 'psx', path)
        if os.path.getsize(full) > 3_000_000:
            continue
        with open(full, 'rb') as source:
            inputs.append((source.read(), B, False))
    bank_refs, table_refs = set(), set()
    for blob, base, active in inputs:
        words = [x[0] for x in struct.iter_unpack('<I', blob[:len(blob) & ~3])]
        lo, hi = 0x800b9f58, 0x800b9f78
        for i, word in enumerate(words):
            pc = base + 4 * i
            if active and base == B and lo <= pc < hi:
                continue
            op = word >> 26
            targets = [word]
            if op in (2, 3):
                targets.append(((pc + 4) & 0xf0000000) | ((word & 0x03ffffff) << 2))
            if active and op in (1, 4, 5, 6, 7):
                imm = word & 0xffff
                imm -= 0x10000 if imm & 0x8000 else 0
                targets.append((pc + 4 + imm * 4) & 0xffffffff)
            if op == 15:
                reg, high = (word >> 16) & 31, (word & 0xffff) << 16
                for nxt in words[i + 1:i + 9]:
                    kind = nxt >> 26
                    if kind in (9, 13) and (nxt >> 21) & 31 == reg:
                        imm = nxt & 0xffff
                        if kind == 9 and imm & 0x8000:
                            imm -= 0x10000
                        targets.append((high + imm) & 0xffffffff)
            if any(lo <= target < hi for target in targets):
                raise ValueError(f'btlui: reference to offer helper code at {pc:#x}')
            if active:
                bank_refs.update((pc, target) for target in targets
                                 if 0x800c87ec <= target < 0x800c882c)
                table_refs.update((pc, target) for target in targets
                                  if 0x800cdd50 <= target < 0x800cdd70)
    pointers = struct.unpack_from('<8I', d, 0x800cdd50 - B)
    expected = {(0x800cdd50 + 4 * i, ptr) for i, ptr in enumerate(pointers)}
    if bank_refs != expected or table_refs != {(0x8007524c, 0x800cdd50)}:
        raise ValueError('btlui: unexpected personality-bank/table consumer')


def offer_data():
    """Full PSP labels, private FF-terminated bytes and source-derived widths."""
    names = personality_source.read()
    with open(os.path.join(ROOT, 'build', 'sf_width.bin'), 'rb') as source:
        widths = source.read()
    if len(widths) != 256:
        raise ValueError('btlui: invalid small-font metrics')
    encoded = [bytes(smallfont_vwf.char_code(c) for c in text) for text in names]
    if sum(len(text) + 1 for text in encoded) > 0x40:
        raise ValueError('btlui: full PSP personalities exceed their owned bank')
    columns = [[] for _ in range(4)]
    for i, text in enumerate(encoded):
        if not text or any(c == 0xff for c in text):
            raise ValueError('btlui: invalid personality glyph')
        pen, left, right = 0, 0x7fffffff, -1
        for code in text:
            packed = widths[code]
            if not packed & 15:
                raise ValueError(f'btlui: personality glyph {code:#x} has no font advance')
            origin = pen - (packed >> 4)
            left, right = min(left, origin), max(right, origin + 8)
            pen += packed & 15
        x = 16 + 48 * (i >> 1)
        if x + left < 0 or x + right > 208:
            raise ValueError(f'btlui: personality slot {i} exceeds the offer frame')
        columns[i >> 1].append((x + left, x + right))
    for a, b in zip(columns, columns[1:]):
        if max(r for _l, r in a) >= min(l for l, _r in b):
            raise ValueError('btlui: offer personality columns overlap')
    return names, encoded


def main():
    global RACES, PERSONALITIES
    RACES = psp_races()
    if features.on('SF_VWF'):
        PERSONALITIES, offer_encoded = offer_data()
    else:
        PERSONALITIES = [strlib.glossary('personality')[str(i)] for i in range(8)]
        offer_encoded = [sf(t) for t in PERSONALITIES]
    with open(os.path.join(ROOT, 'data', 'psx', 'BTLP.BIN'), 'rb') as source:
        d = source.read()
    if features.on('SF_VWF'):
        guard_offer_retail(d)
    out = [';; generated by tools/btlui.py - do not edit' + NL]
    # race tags: 27 slots of 8 bytes from 0x800E2068
    for k, name in enumerate(RACES, 1):
        a = 0x800E2060 + 8 * k
        ja = d[a - B:a - B + 8]
        assert ja.index(b'\xff') in (3, 4, 5, 6, 7) and ja[ja.index(b'\xff') - 1] == 0xCB, (k, ja.hex())
        b = sf(name) + bytes([0xCB, 0xFF])
        assert len(b) <= 8, name
        out.append(f'; race {k} {name}{NL}' + block(a, b + bytes(8 - len(b))))
    # ANALYZE labels
    _lbl = strlib.glossary('btlui_label')
    for a, room in ((0x800dea2c, 8), (0x800dea34, 8), (0x800dea3c, 8)):
        t = _lbl[f'{a:#x}']
        b = bytes(items.glyph(c) for c in t) + b'\xff'
        out.append(f'; {t}{NL}' + block(a, b + bytes(room - len(b))))
    out.append(f'; trait text one cell right{NL}.org 0x800debf4{NL}    .halfword 0xFFA8{NL}')
    # CONTACT personalities: FF-terminated strings in the private BTLP bank,
    # pointed at by the BTLP pointer table.
    bank = 0x800c87ec
    words = []
    blob = b''
    for text in offer_encoded:
        words.append(bank + len(blob))
        blob += text + (b'\xff' if features.on('SF_VWF') else b'\xff\xf5')
    assert len(blob) <= 0x40, len(blob)
    out.append('; personalities' + NL + block(0x800c87ec, blob + bytes(0x40 - len(blob))))
    out.append(f'.org 0x800cdd50{NL}    .word ' + ', '.join(f'{w:#x}' for w in words) + NL)
    # AUTO modes
    for a, t in AUTO:
        b = sf(t) + b'\xff'
        out.append(f'; {t}{NL}' + block(a, b + bytes(10 - len(b))))
    open(OUT, 'w', newline=NL).write(''.join(out))
    print(f'btlui: {len(RACES)} races, 3 analyze labels, {len(PERSONALITIES)} personalities, {len(AUTO)} auto modes')


def verify(battle_path=None, resident_path=None):
    """Verify offer source bytes, metrics and all owned hook code after assembly."""
    if not features.on('SF_VWF'):
        print('btlui verify: offer VWF disabled')
        return
    _names, encoded = offer_data()
    battle_path = battle_path or os.path.join(ROOT, 'build', 'BTLP.BIN')
    resident_path = resident_path or os.path.join(ROOT, 'build', 'SLPS_005.00')
    with open(battle_path, 'rb') as source:
        battle = source.read()
    with open(resident_path, 'rb') as source:
        resident = source.read()
    elf_base = struct.unpack_from('<I', resident, 0x18)[0]
    symbols = {}
    with open(os.path.join(ROOT, 'build', 'persona.sym'), encoding='utf-8') as source:
        for line in source:
            fields = line.split()
            if len(fields) == 2 and len(fields[0]) == 8:
                try:
                    symbols[fields[1]] = int(fields[0], 16)
                except ValueError:
                    pass
    for name in ('offer_maybe_name', 'offer_lookup', 'offer_finish_position',
                 'offer_name_ret', 'offer_gate', 'offer_position',
                 'offer_advance', 'offer_art_v', 'btl_sf_art_code',
                 'btl_trait_tail'):
        if name not in symbols:
            raise SystemExit(f'btlui verify: missing symbol {name}')
    expected_pos = 0x800c87ec
    for i, text in enumerate(encoded):
        ptr = struct.unpack_from('<I', battle, 0x800cdd50 - B + 4 * i)[0]
        if ptr != expected_pos or battle[ptr - B:ptr - B + len(text) + 1] != text + b'\xff':
            raise SystemExit(f'btlui verify: personality source mismatch at slot {i}')
        expected_pos += len(text) + 1
    if (not 0x80015510 <= symbols['offer_name_ret']
            or symbols['offer_finish_position'] + 12 > 0x8001560c):
        raise SystemExit('btlui verify: offer exits outside the resident dead function')
    def jal(at):
        return 0x0c000000 | ((at >> 2) & 0x03ffffff)
    def jump(at):
        return 0x08000000 | ((at >> 2) & 0x03ffffff)
    def bnez_pc(rs, target, pc):
        return 0x14000000 | (rs << 21) | (((target - (pc + 4)) >> 2) & 0xffff)
    # beqz t0, offer_name_ret - the window exit moved into the resident tail.
    window_exit = 0x11000000 | (
        (symbols['offer_name_ret'] - (symbols['offer_maybe_name'] + 8)) >> 2)
    lookup_words = (0x2d080014, window_exit,
                    0, 0x3c088010, 0x010b4021,
                    0x91028960, 0, 0x11800004, 0x3049000f, 0x2529ffff,
                    0x03e00008, 0x0289a021, jump(symbols['offer_finish_position']),
                    0x00024902, 0x03e00008, 0)
    # Gated position rows record art mode 0; every other position row masks it
    # to -1. The advance phase must leave `at` alone for the retail delay-slot
    # store, so offer_name_ret is shared and masks with t4-1.
    name_ret_words = (0x258dffff, 0x002d0825, 0x03e00008, 0)
    finish_words = (0x34010000, 0x03e00008, 0x02891023)
    # The gate covers the personality bank, the stock-name bank, then the
    # offer name scratch (whose own length check lives in offer_maybe_name).
    gate = symbols['offer_gate']
    personality_size = (toolbelt.asm_equ('BTLP_PERSONALITY_BANK_END')
                        - toolbelt.asm_equ('BTLP_PERSONALITY_BANK'))
    stock_size = toolbelt.asm_equ('BTLP_STOCK_FULL_SIZE')
    def lui_t0(value):
        return 0x3c080000 | (((value + 0x8000) >> 16) & 0xffff)
    def addiu_t0(value):
        return 0x25080000 | (value & 0xffff)
    gate_words = (0x022c5023,                          # subu t2,s1,t4
                  lui_t0(toolbelt.asm_equ('BTLP_PERSONALITY_BANK')),
                  addiu_t0(toolbelt.asm_equ('BTLP_PERSONALITY_BANK')),
                  0x01484823,                          # subu t1,t2,t0
                  0x2d290000 | personality_size,
                  bnez_pc(9, gate + 68, gate + 20),
                  0x914b0000,                          # lbu t3,0(t2)
                  lui_t0(toolbelt.asm_equ('BTLP_STOCK_FULL_ADDR')),
                  addiu_t0(toolbelt.asm_equ('BTLP_STOCK_FULL_ADDR')),
                  0x01484823,
                  0x2d290000 | stock_size,
                  bnez_pc(9, gate + 68, gate + 44),
                  0x914b0000,
                  lui_t0(toolbelt.asm_equ('PERSONA_HDR_BUF')),
                  addiu_t0(toolbelt.asm_equ('PERSONA_HDR_BUF')),
                  jump(symbols['offer_maybe_name']),
                  0x01484023,                          # subu t0,t2,t0
                  jump(symbols['offer_lookup']),
                  0)
    stub_words = (0x340c0000, jump(symbols['offer_gate']), 0x001410c0,
                  0x340c0001, 0x340e00ff, jump(symbols['offer_gate']), 0x26940001)
    checks = (
        (resident, elf_base - 0x800, symbols['offer_maybe_name'], lookup_words),
        (resident, elf_base - 0x800, symbols['offer_name_ret'], name_ret_words),
        (resident, elf_base - 0x800, symbols['offer_finish_position'], finish_words),
        (battle, B, symbols['offer_gate'], gate_words),
        (battle, B, symbols['offer_position'], stub_words),
        (battle, B, 0x80078574, (jal(symbols['offer_position']), 0xafa00028)),
        (battle, B, 0x800788b8, (jal(symbols['offer_advance']), 0xac2283a8,
                                  0x00671824, 0x00641825, 0x92220000,
                                  0xaca30000, 0x144eff24, 0)),
        # Every quad-text glyph load routes through the panel art selector,
        # which reads the row's art mode from at (set by the position phase).
        *[(battle, B, at, (jal(symbols['btl_sf_art_code']), 0x92240000))
          for at in (0x80078608, 0x80078670, 0x800786dc, 0x80078748)],
        *[(battle, B, at, (jal(symbols['offer_art_v']), 0x92220000))
          for at in (0x8007863c, 0x800786a8, 0x80078710, 0x80078780)],
    )
    for blob, base, at, expected in checks:
        off = at - base
        if off < 0 or off + 4 * len(expected) > len(blob) or struct.unpack_from(
                f'<{len(expected)}I', blob, off) != expected:
            raise SystemExit(f'btlui verify: offer code mismatch at {at:#x}')

    # ---- the ANALYZE trait line: record head + pool tail ----
    # The retail 28-byte slot ends at g_btl_slot_owner; the full 47-cell line
    # and its append code/pool live in the zeroed run of the retail image,
    # which is only free up to 0x800F85B0 - the battle runtime keeps a heap
    # pointer there and writes it, so the zero padding beyond that word is not
    # a home. Verify the stock bytes there were free, then the moved producers,
    # the descriptor and the installed append hook.
    stock = open(os.path.join(ROOT, 'data', 'psx', 'BTLP.BIN'), 'rb').read()
    trait = toolbelt.asm_equ('ANALYZE_TRAIT_BUF')
    trait_end = toolbelt.asm_equ('ANALYZE_TRAIT_END')
    code = toolbelt.asm_equ('BTLP_TRAIT_CODE_ADDR')
    pool = toolbelt.asm_equ('BTLP_TRAIT_POOL_ADDR')
    free_end = toolbelt.asm_equ('BTLP_TRAIT_POOL_END')
    if any(stock[trait - B:free_end - B]):
        raise SystemExit('btlui verify: trait line would overwrite retail BTLP data')
    if (trait_end - trait, code, pool, free_end) != (47, trait + 0x30, trait + 0xa0, trait + 0x1f0):
        raise SystemExit('btlui verify: trait layout constants moved')
    def la(reg, address):
        return (0x3c000000 | reg << 16 | ((address + 0x8000) >> 16) & 0xffff,
                0x24000000 | reg << 21 | reg << 16 | (address & 0xffff))
    for at, expect in (
            (0x800AD980, la(7, trait)),          # producer's destination
            (0x800ADE38, la(6, trait)),          # unanalysed placeholder row
            (0x800ADA90, (jal(symbols['btl_trait_tail']), 0x8e050000))):
        if struct.unpack_from('<II', battle, at - B) != expect:
            raise SystemExit(f'btlui verify: trait producer hook differs at {at:#x}')
    # The FF after the three `?` cells keeps the retail two-instruction
    # shape; the next store in the same block still reuses `at`.
    ff = (0x3c018010, 0xa0220000 | (trait + 3) & 0xffff,
          0x3c018010, 0xa0220000 | -0x781e & 0xffff)
    if struct.unpack_from('<IIII', battle, 0x800ADFDC - B) != ff:
        raise SystemExit('btlui verify: trait placeholder terminator differs')
    row = struct.unpack_from('<hhIBBBB', battle, 0x800DEBF4 - B)
    if row != (0xFFA8 - 0x10000, 36, trait, trait_end - trait, 0x20, 12, 0):
        raise SystemExit(f'btlui verify: trait descriptor {row}')
    pool_bytes = open(os.path.join(ROOT, 'build', 'affinity_pool.bin'), 'rb').read()
    if battle[pool - B:pool - B + len(pool_bytes)] != pool_bytes:
        raise SystemExit('btlui verify: battle affinity pool differs from the canonical one')
    print('btlui verify: 8 PSP personalities, both art modes, all offer hooks and the '
          'complete ANALYZE trait line intact')


if __name__ == '__main__':
    if len(sys.argv) == 1:
        main()
    elif sys.argv[1:] == ['verify']:
        verify()
    else:
        raise SystemExit('usage: btlui.py [verify]')
