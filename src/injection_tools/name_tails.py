"""Full-length item/demon names: record heads and per-overlay tail banks.

The ten-byte record field holds the head; longer names continue in
[len][glyphs...] entries ordered by id. A has-tail bitmap determines which
ids consume entries. Each overlay carries its own banks and copy helpers.
The helpers produce an FF-terminated name in the shared 21-byte scratch:
at most 20 glyphs plus the terminator. Assembly placement guards bound the
bank and helper block in each overlay.

Names come only from canonical SLPS_005.00 rows. Family capacities are
shared with their builders; this module never truncates wording.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import items     # noqa: E402
import demons     # noqa: E402
import skills     # noqa: E402
import slps       # noqa: E402

ROOT = toolbelt.ROOT
REL = 'SLPS_005.00'
NL = chr(10)

ITEM_MAXLEN = items.MAXLEN
DEMON_MAXLEN = demons.MAXLEN


def item_rows():
    """[(id, en)] in id order (id 1-based: the record the game draws)."""
    out = []
    it0 = slps.IT_FIRST - slps.BASE
    for r in toolbelt.merged_rows(REL):
        pos = int(r['pos'], 16)
        if not (it0 <= pos < it0 + slps.IT_STRIDE * slps.IT_COUNT):
            continue
        if (pos - it0) % slps.IT_STRIDE:
            continue
        t = (r.get('en') or '').strip()
        if t:
            out.append(((pos - it0) // slps.IT_STRIDE + 1, t))
    return sorted(out)


def demon_rows():
    """[(id, en)] in id order (id 1-based)."""
    out = []
    for k, a, _ja in demons.records():
        for r in toolbelt.merged_rows(REL):
            if int(r['pos'], 16) == a - slps.BASE:
                t = (r.get('en') or '').strip()
                if t:
                    out.append((k, t))
                break
    return sorted(out)


def split(name, field, maxlen, what):
    """(head glyphs, tail glyphs) - the record's 10 + the rest. Refuses
    only what the destination truly cannot hold."""
    b = items.encode(name)            # the small-font glyphs, no length cap
    if len(b) > maxlen:
        toolbelt.fail(f'name_tails: {what} {name!r} is {len(b)} glyphs '
                      f'(max {maxlen})')
    return b[:field], b[field:]


def build_battle_data():
    """The same item tail format and helper, in the battle-owned data gap."""
    import etext
    rows = item_rows()
    bits = bytearray((slps.IT_COUNT + 7) // 8)
    english = bytearray((slps.IT_COUNT + 8) // 8)
    bank = bytearray()
    for ident, text in rows:
        english[ident // 8] |= 1 << (ident % 8)
        _, tail = split(text, items.FIELD, ITEM_MAXLEN, f'item {ident}')
        if tail:
            bits[(ident - 1) // 8] |= 1 << ((ident - 1) % 8)
            bank.extend(bytes([len(tail)]) + tail)
    metrics_map = bytearray(215)
    for character in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .'-/:":
        glyph = items.glyph(character)
        encoded = etext.encode(character, end=None)
        if len(encoded) != 1 or encoded[0] == 255:
            toolbelt.fail(f'battle insert character is not compact: {character!r}')
        metrics_map[glyph] = encoded[0]
    def byte_lines(blob):
        return '\n'.join('    .byte ' + ', '.join(f'0x{x:02x}' for x in blob[i:i + 16])
                         for i in range(0, len(blob), 16))
    data = (' .org BTLP_NAME_DATA_ADDR\nitem_tail_bank_btlp:\n' + byte_lines(bank)
            + '\nitem_tail_bits_btlp:\n' + byte_lines(bits)
            + '\nbtl_name_compact_map:\n' + byte_lines(metrics_map)
            + '\nbtl_result_item_english:\n' + byte_lines(english)
            + '\nbtl_name_data_end:\n.if . > BTLP_NAME_DATA_END\n'
              '    .error "battle name data reaches sound-work buffer"\n.endif\n')
    toolbelt.write_asm(os.path.join(ROOT, 'build', 'name_data_btlp.asm'), 'name_tails', data)
    source = open(os.path.join(ROOT, 'src/asm/slps_005.00/item_names.asm')).read()
    source = source[source.index('item_name_copy:'):source.index(';; a0 = destination (21 bytes), a1 = demon')]
    # The three battle callers have no live t0-t3 across this call. Remove
    # only the shared helper's callee-preservation frame; its copy and tail
    # traversal remain the same. Guard the transformation against source drift.
    prologue = source[source.index('    addiu   sp, sp, -0x10'):source.index('    move    t0, a0')]
    epilogue = source[source.index('    lw      t0, 0x0C(sp)'):source.index('    jr      ra')]
    if prologue.count('\n') != 5 or epilogue.count('\n') != 4:
        toolbelt.fail('battle item helper: unexpected shared register-save frame')
    source = source.replace(prologue, '', 1).replace(epilogue, '', 1)
    source = source.replace('    addiu   sp, sp, 0x10', '    nop', 1)
    for label in ('item_name_copy', 'name_copy_body', 'item_tail_bank', 'item_tail_bits'):
        source = re.sub(rf'\b{label}\b', label + '_btlp', source)
    toolbelt.write_asm(os.path.join(ROOT, 'build', 'item_name_copy_btlp.asm'), 'name_tails', source)


def build():
    items_ = item_rows()
    dems = demon_rows()
    item_entries, item_map = [], {}
    for i, t in items_:
        head, tail = split(t, items.FIELD, ITEM_MAXLEN, f'item {i}')
        if not tail and len(head) < items.FIELD:
            continue                    # its own field holds it (FF-terminated)
        item_map[i] = (head, tail)
        if tail:
            item_entries.append((i, len(tail)))
    dem_entries = []
    for k, t in dems:
        head, tail = split(t, demons.FIELD, DEMON_MAXLEN, f'demon {k}')
        if tail:
            dem_entries.append((k, len(tail)))
    # the bitmaps: one bit per id, set when the name has a tail
    ibits = bytearray((slps.IT_COUNT + 7) // 8)
    for i, _ln in item_entries:
        ibits[(i - 1) // 8] |= 1 << ((i - 1) % 8)
    dbits = bytearray((demons.COUNT + 7) // 8)
    for k, _ln in dem_entries:
        dbits[(k - 1) // 8] |= 1 << ((k - 1) % 8)

    item_bytes = bytearray()
    for i, ln in item_entries:
        _head, tail = item_map[i]
        item_bytes += bytes([len(tail)]) + tail
    dem_bytes = bytearray()
    dem_map = dict(dems)
    for k, ln in dem_entries:
        _h, tail = split(dem_map[k], demons.FIELD, DEMON_MAXLEN, f'demon {k}')
        dem_bytes += bytes([len(tail)]) + tail
    out = []
    out.append(';; generated by tools/name_tails.py build - do not edit')
    out.append(';; tails of over-10-glyph item/demon names: [len][glyphs], id')
    out.append(';; order, each id in its family\'s has-tail bitmap')
    out.append('item_tail_bank:')
    for j in range(0, len(item_bytes), 16):
        out.append('    .byte ' + ', '.join(f'0x{x:02X}' for x in item_bytes[j:j + 16]))
    out.append('demon_tail_bank:')
    for j in range(0, len(dem_bytes), 16):
        out.append('    .byte ' + ', '.join(f'0x{x:02X}' for x in dem_bytes[j:j + 16]))
    out.append('item_tail_bits:')
    for j in range(0, len(ibits), 16):
        out.append('    .byte ' + ', '.join(f'0x{x:02X}' for x in ibits[j:j + 16]))
    out.append('demon_tail_bits:')
    for j in range(0, len(dbits), 16):
        out.append('    .byte ' + ', '.join(f'0x{x:02X}' for x in dbits[j:j + 16]))
    body = NL.join(out) + NL
    # one copy per overlay: the full-name block rides each overlay's
    # extension (read only while that overlay is the live one; the game's
    # BSS above the main image is wiped at boot, so nothing build-time can
    # be resident any more)
    item_src = open(os.path.join(ROOT, 'src', 'asm', 'slps_005.00',
                                 'item_names.asm')).read()
    # Each overlay owns its scratch: replace the resident helper's buffer
    # label and let the overlay wrapper place the zero-filled storage.
    item_src = item_src.split('\nname_scratch:')[0]
    labels = ('item_tail_bank', 'demon_tail_bank', 'item_tail_bits',
              'demon_tail_bits', 'item_name_copy', 'demon_name_copy', 'name_copy_body')
    for ovl in ('adv', 'dng', 's2d'):
        asm = body
        for label in labels:
            asm = re.sub(rf'\b{label}\b', f'{label}_{ovl}', asm)
        toolbelt.write_asm(os.path.join(ROOT, 'build', f'name_tails_{ovl}.asm'),
                           f'name_tails_{ovl}', asm)
        # the copy helpers read this overlay's own banks
        item_asm = re.sub(r'\b(name_scratch)\b', f'sf_name_scratch_{ovl}', item_src)
        for label in labels:
            item_asm = re.sub(rf'\b{label}\b', f'{label}_{ovl}', item_asm)
        toolbelt.write_asm(os.path.join(ROOT, 'build', f'item_names_{ovl}.asm'),
                           f'item_names_{ovl}', item_asm)
    used = len(item_bytes) + len(dem_bytes) + len(ibits) + len(dbits)
    print(f'name_tails: {len(item_entries)} item tails ({len(item_bytes)} B), '
          f'{len(dem_entries)} demon tails ({len(dem_bytes)} B), '
          f'{used} B x 3 overlay copies')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'build': build}[sys.argv[1] if sys.argv[1:] else 'build']()
