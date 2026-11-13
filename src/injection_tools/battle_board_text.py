"""Translate battle object-text boards and register their source spans.

The retail battle overlay draws a handful of BtlGfxText lists through the
small-font object renderer.  This module:

  * discovers those lists structurally (never by wording or a fixed address);
  * keeps the lists whose visible rows name records in the translation
    inventory and ignores shared blank strings;
  * translates a list only when every translated row fits before the next row
    at the same y (a list whose wording collides with the next column keeps its
    Japanese and is reported as deferred);
  * packs the English into the physical source spans of the translated lists,
    deduplicating repeated wording, protects every record another descriptor
    still reads, and repoints the descriptors;
  * allocates the ownership directory in reclaimed immutable battle text
    overlay, because the resident VWF table area is full and only the battle
    renderer calls btl_owned_span.

Row positions stay the original source slots (the translation TSV key); the
built image may carry the same wording at a different address.
"""
import struct

import etext

BASE = 0x800643c4
# File offsets of the contiguous, four-byte-aligned retail text pools.
POOLS = ((0x7a2fc, 0x7a398, 14), (0x7b9b8, 0x7ba24, 11),
         (0x7a84c, 0x7a868, 4))
# Additional descriptor-backed fixed-size source records. Their consumer
# reachability is not established; they remain source candidates and are
# translated only when a discovered list names them.
FIXED_POOLS = ((0x795f4, 14, 10), (0x79d2c, 9, 10), (0x79fbc, 4, 10),
               (0x7a0fc, 3, 10), (0x7a12e, 4, 10), (0x7b68c, 15, 10),
               (0x7b034, 7, 5), (0x7a0e8, 2, 10), (0x7a11a, 2, 10),
               (0x7a156, 3, 10), (0x79d86, 1, 10))
# Source board descriptor tables (12-byte BtlGfxText records); the last field
# indexes the combined pool list (POOLS then FIXED_POOLS in order).
BOARDS = ((0x7a398, 11, 0), (0x7ba24, 16, 1), (0x7bae4, 1, 1),
          (0x7a8a4, 15, 2), (0x7a958, 1, 2), (0x7968c, 14, 3),
          (0x79d90, 9, 4), (0x79fe4, 4, 5), (0x7a18c, 3, 6),
          (0x7a1c8, 4, 7), (0x7b72c, 15, 8), (0x7b0ac, 7, 9),
          (0x7a174, 2, 10), (0x7a1b0, 2, 11), (0x7a1f8, 3, 12),
          (0x79dfc, 6, 13))

NULL = 0xFF


def _pool_ranges():
    """Every physical source pool as (file start, file end)."""
    return ([(first, end) for first, end, _count in POOLS]
            + [(first, first + count * stride)
               for first, count, stride in FIXED_POOLS])


def _inventory(data):
    """Return (file offset, record end, decoded Japanese) for every source slot.

    The declared pools define the physical record geometry; anything that does
    not match it is a build-time error, never a silently skipped row.
    """
    out = []
    for first, end, expected_count in POOLS:
        if end > len(data):
            raise ValueError('battle board: source pool is outside BTLP')
        count = 0
        p = first
        while p < end:
            q = data.find(b'\xff', p, end)
            if q < 0 or q == p:
                raise ValueError(f'battle board: invalid string at {p:#x}')
            glyphs = data[p:q]
            if any(code not in etext.glyph for code in glyphs):
                raise ValueError(f'battle board: unknown retail glyph at {p:#x}')
            next_p = (q + 4) & ~3
            if next_p > end or any(data[q + 1:next_p]):
                raise ValueError(f'battle board: nonzero alignment at {p:#x}')
            out.append((p, next_p, ''.join(etext.glyph[code] for code in glyphs)))
            count += 1
            p = next_p
        if count != expected_count:
            raise ValueError('battle board: source pool record count changed')
    for first, count, stride in FIXED_POOLS:
        if first + count * stride > len(data):
            raise ValueError('battle board: fixed source pool is outside BTLP')
        for i in range(count):
            off = first + i * stride
            record = data[off:off + stride]
            end = record.find(b'\xff')
            if end <= 0 or any(record[end + 1:]) or any(c not in etext.glyph for c in record[:end]):
                raise ValueError(f'battle board: invalid fixed source slot at {off:#x}')
            out.append((off, off + stride,
                        ''.join(etext.glyph[c] for c in record[:end])))
    return out


def scan(data):
    """Return (file offset, decoded Japanese) in declared pool order; fail on drift."""
    rows = _inventory(data)
    ranges = _pool_ranges()
    starts = []
    for first, end in ranges:
        starts.append({off for off, _e, _ja in rows if first <= off < end})
    for table, count, index in BOARDS:
        if table + count * 12 > len(data):
            raise ValueError('battle board: descriptor table is outside BTLP')
        for i in range(count):
            off = table + i * 12
            pointer = struct.unpack_from('<I', data, off + 4)[0]
            if pointer - BASE not in starts[index]:
                raise ValueError(f'battle board: unowned descriptor pointer at {off:#x}')
    return [(off, ja) for off, _e, ja in rows]


def record_spans(data):
    """{file offset: physical end} for every declared source record."""
    return {off: end for off, end, _ja in _inventory(data)}


def initial_references(data):
    """Physical starts named by descriptors in the original file image."""
    return {struct.unpack_from('<I', data, table + i * 12 + 4)[0] - BASE
            for table, count, _pool in BOARDS for i in range(count)}


def direct_assignments(data):
    """Adjacent LUI/ADDIU/LUI/SW assignments into a descriptor pointer field.

    This is positive evidence, not an exhaustive indirect-reference scan.
    Return (code offset, source start, descriptor offset) for each assignment.
    """
    source = {off for off, _ja in scan(data)}
    def signed(n):
        return n - 0x10000 if n & 0x8000 else n
    out = []
    for off in range(0, len(data) - 15, 4):
        a, b, c, d = struct.unpack_from('<4I', data, off)
        if (a >> 26, b >> 26, c >> 26, d >> 26) != (15, 9, 15, 43):
            continue
        src, dst, high = (a >> 16) & 31, (b >> 16) & 31, (c >> 16) & 31
        if not src or src != (b >> 21) & 31 or src != dst or high != (d >> 21) & 31 or dst != (d >> 16) & 31:
            continue
        value = ((((a & 0xffff) << 16) + signed(b & 0xffff)) & 0xffffffff) - BASE
        field = ((((c & 0xffff) << 16) + signed(d & 0xffff)) & 0xffffffff) - BASE
        if value in source:
            out.append((off, value, field - 4))
    return out


# ---------------------------------------------------------------------------
# Text-list discovery
# ---------------------------------------------------------------------------

def _text_kind(data, off, count):
    """'text', 'blank', or None for a row's text pointer.

    A visible row is text when an FF-terminated run of known glyphs follows the
    pointer.  A deliberate blank has no terminator but count zero bytes (the
    retail renderer draws `count` cells and stops).  Anything else is not a
    battle text row.
    """
    if off < 0 or off >= len(data):
        return None
    if data[off] == NULL:
        return 'blank'          # empty literal: the renderer stops immediately
    end = data.find(b'\xff', off)
    if end > off and all(c in etext.glyph for c in data[off:end]):
        return 'text'
    if count > 0 and off + count <= len(data) and not any(data[off:off + count]):
        return 'blank'
    return None


def _has_text(data, off):
    """True when a source record carries a non-space glyph."""
    if off is None or off < 0 or off >= len(data):
        return False
    end = data.find(b'\xff', off)
    return end > off and any(data[off:end])


def scan_lists(data):
    """Structurally discover BtlGfxTextList heads.

    Return [(list offset, count, entries)] where each entry is a dict with the
    descriptor offset, x, y, text offset (None when count == 0), glyph count,
    palette and validated text kind.  No wording or table address is consulted.
    """
    found = []
    for at in range(0, len(data) - 7, 4):
        count, pointer = struct.unpack_from('<II', data, at)
        if not 1 <= count <= 255:
            continue
        start = pointer - BASE
        if start < 0 or start % 4 or start + count * 12 > len(data):
            continue
        entries = []
        for i in range(count):
            desc = start + i * 12
            x, y, text, n, clut, h, v = struct.unpack_from('<hhIBBBB', data, desc)
            if not 0 < clut <= 0x7F or h != 12 or v != 0:
                entries = None
                break
            if n == 0:
                entries.append({'desc': desc, 'x': x, 'y': y, 'text': None,
                                'n': 0, 'kind': None})
                continue
            text_off = text - BASE
            kind = _text_kind(data, text_off, n)
            if kind is None:
                entries = None
                break
            entries.append({'desc': desc, 'x': x, 'y': y, 'text': text_off,
                            'n': n, 'kind': kind})
        if entries:
            found.append((at, count, entries))
    return found


def source_lists(data):
    """The discovered lists whose visible text rows name translation sources.

    Shared blank rows (a pointer to a run of zero cells) are allowed: they draw
    nothing and are not part of the wording.  A list that shows even one text
    row from outside the inventory is not ours.
    """
    sources = {off for off, _ja in scan(data)}
    out = []
    for at, count, entries in scan_lists(data):
        visible = [e for e in entries if e['n'] > 0]
        if not any(e['kind'] == 'text' and e['text'] in sources for e in visible):
            continue
        if any(e['kind'] == 'text' and e['text'] not in sources for e in visible):
            continue
        out.append((at, count, entries))
    return out


# ---------------------------------------------------------------------------
# Encoding, layout and packing
# ---------------------------------------------------------------------------

def _encode(text):
    import toolbelt
    return bytes(toolbelt.smallfont_char(c) for c in text)


def _width(text):
    import smallfont_vwf
    import toolbelt
    return smallfont_vwf.codes_px(toolbelt.smallfont_char(c) for c in text)


def _row_map(rows):
    """Accept the builder's list of rows or an already pos-keyed mapping."""
    return rows if isinstance(rows, dict) else {r['pos']: r for r in rows}


def _english(rows, off):
    if off is None:
        return ''
    return (rows.get(hex(off)) or {}).get('en', '').strip()


def _pool_span(start, ranges):
    """The declared physical pool containing a source start, else None."""
    for first, end in ranges:
        if first <= start < end:
            return (first, end)
    return None


def _subtract(intervals, cuts):
    out = list(intervals)
    for cut_start, cut_end in cuts:
        nxt = []
        for start, end in out:
            if cut_end <= start or cut_start >= end:
                nxt.append((start, end))
                continue
            if start < cut_start:
                nxt.append((start, cut_start))
            if cut_end < end:
                nxt.append((cut_end, end))
        out = nxt
    return out


def _merge(intervals):
    out = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def _file_offset(value):
    """A symbol value as a file offset inside this overlay."""
    return value - BASE if value >= BASE else value


def plan(data, rows):
    """Decide what ships where, without writing anything.

    `rows` maps a source position ('0x...') to its merged translation row.
    The returned dict is deterministic for a given stock image and row set.
    """
    import toolbelt
    rows = _row_map(rows)
    spans = record_spans(data)
    inventory = {off for off in spans}
    ranges = _pool_ranges()

    lists = []
    for at, count, entries in source_lists(data):
        visible = [e for e in entries if e['n'] > 0]
        reason = ''
        if not any(e['kind'] == 'text' for e in visible):
            reason = 'no visible text'
        for e in visible:
            if e['kind'] != 'text' or reason:
                continue
            en = _english(rows, e['text'])
            if not en:
                reason = f'missing translation at {e["text"]:#x}'
                break
            gap = min((o['x'] - e['x'] for o in visible
                       if o['y'] == e['y'] and o['x'] > e['x']), default=None)
            if gap is not None and _width(en) > gap:
                reason = f'{en!r} is {_width(en)} px before a {gap} px column'
                break
        lists.append({'at': at, 'count': count, 'entries': entries,
                      'translate': not reason, 'reason': reason})
    translated = [entry for entry in lists if entry['translate']]
    if not translated:
        raise ValueError('battle board: no translatable list survived the fit gate')

    translated_descs = {e['desc'] for entry in translated for e in entry['entries']}

    # Values the code assigns into a descriptor pointer at runtime.  The
    # static count must cover the longest value, and a shorter value is
    # space-padded so the shared descriptor always draws a complete word.
    assigned = {}
    for _code, source, desc in direct_assignments(data):
        en = _english(rows, source)
        if en:
            assigned.setdefault(desc, {})[source] = en
    values = {desc: items for desc, items in assigned.items()
              if desc in translated_descs}
    shared_counts = {}
    pinned = {}
    for desc, items in values.items():
        length = max(len(_encode(en)) for en in items.values())
        shared_counts[desc] = length
        for source, en in items.items():
            end = spans.get(source)
            body = _encode(en).ljust(length, b'\x00')
            if end is None or len(body) + 1 > end - source:
                raise ValueError(
                    f'battle board: runtime value at {source:#x} needs '
                    f'{len(body) + 1} bytes, record has '
                    f'{0 if end is None else end - source}')
            pinned[source] = body + bytes([NULL])

    # Unique wording from every visible row of a translated list, first use
    # first so placement is deterministic before the longest-first sort.
    order = []
    seen = set()
    for entry in translated:
        for e in entry['entries']:
            if e['n'] == 0 or e['kind'] != 'text':
                continue
            en = _english(rows, e['text'])
            if en and en not in seen:
                seen.add(en)
                order.append(en)

    # The arena is the union of the source pools the translated rows and the
    # pinned runtime values come from.  Everything else in the overlay stays
    # untouched.
    arena_pools = set()
    for entry in translated:
        for e in entry['entries']:
            if e['n'] > 0 and e['kind'] == 'text':
                arena_pools.add(_pool_span(e['text'], ranges))
    for source in pinned:
        arena_pools.add(_pool_span(source, ranges))
    if None in arena_pools:
        raise ValueError('battle board: a translated row is outside every source pool')
    arena = _merge(arena_pools)

    # A record inside the arena that another descriptor still reads must keep
    # its bytes.  Hidden rows (count 0) never read their pointer; those records
    # are reusable.  This is derived from every discovered descriptor, never a
    # per-record exception.
    referenced = {e['text'] for entry in lists
                  for e in entry['entries'] if e['n'] > 0}
    referenced |= {struct.unpack_from('<I', data, table + i * 12 + 4)[0] - BASE
                   for table, count, _pool in BOARDS for i in range(count)}
    shipped = {e['text'] for entry in translated for e in entry['entries']
               if e['n'] > 0 and e['kind'] == 'text'}
    shipped |= set(pinned)
    protected = [(off, spans[off]) for start, end in arena
                 for off in sorted(inventory)
                 if start <= off < end and off in referenced and off not in shipped]

    pinned_spans = [(source, source + len(body)) for source, body in pinned.items()]
    free = _subtract(arena, [*pinned_spans, *protected])
    free = [(start, end) for start, end in free if end > start]

    placed = {_english(rows, source): (source, body)
              for source, body in pinned.items()}
    todo = [text for text in order if text not in placed]
    for text in sorted(todo, key=lambda value: (-len(_encode(value)), value)):
        body = _encode(text) + bytes([NULL])
        for index, (start, end) in enumerate(free):
            if end - start >= len(body):
                placed[text] = (start, body)
                free[index] = (start + len(body), end)
                break
        else:
            raise ValueError(f'battle board: no room for {text!r}')
    strings = sorted(placed.values())

    descriptors = {}
    for entry in translated:
        top = min(e['y'] for e in entry['entries'] if e['n'] > 0)
        # A heading is the list's sole top row; a multi-column grid has no
        # centred caption even though a middle column may straddle the origin.
        heading = sum(1 for e in entry['entries']
                      if e['n'] > 0 and e['y'] == top) == 1
        for e in entry['entries']:
            if e['n'] == 0 or e['kind'] != 'text':
                continue
            en = _english(rows, e['text'])
            desc = e['desc']
            addr, body = placed[en]
            if desc in shared_counts:
                descriptors[desc] = (desc, None, addr, shared_counts[desc])
                continue
            new_x = None
            if heading and e['y'] == top and e['x'] < 0 < e['x'] + e['n'] * 8:
                new_x = -(_width(en) // 2)
            descriptors[desc] = (desc, new_x, addr, len(body) - 1)
    descriptor_list = sorted(descriptors.values())

    # The directory: every arena pool, the ANALYZE buffers and label block,
    # and the command-stage member boards' full-length Persona rows
    # (produced by btlp/status_persona.asm).
    directory = [(BASE + start, end - start) for start, end in arena]
    for name in ('NAME', 'LABEL', 'SPELL', 'TRAIT', 'RANK', 'KIND'):
        base = toolbelt.asm_equ(f'ANALYZE_{name}_BUF')
        end = toolbelt.asm_equ(f'ANALYZE_{name}_END')
        directory.append((base, end - base))
    directory.append((toolbelt.asm_equ('BTLP_STATUS_PERSONA_BUF'),
                      toolbelt.asm_equ('BTLP_STATUS_PERSONA_END')
                      - toolbelt.asm_equ('BTLP_STATUS_PERSONA_BUF')))
    # Board 23 (R1 enemy-kind list): its arcana label table is drawn in place
    # and its three full-name rows live in the retail name/arcana pools
    # (btlp/board23_names.asm).
    directory.append((toolbelt.asm_equ('BTLP_BOARD23_TAG_TABLE'),
                      toolbelt.asm_equ('BTLP_BOARD23_TAG_TABLE_END')
                      - toolbelt.asm_equ('BTLP_BOARD23_TAG_TABLE')))
    directory.append((toolbelt.asm_equ('BTLP_BOARD23_NAMES_ADDR'),
                      toolbelt.asm_equ('BTLP_BOARD23_NAMES_END')
                      - toolbelt.asm_equ('BTLP_BOARD23_NAMES_ADDR')))
    directory.append((toolbelt.asm_equ('BTLP_BOARD23_NAME_ROW_2'),
                      toolbelt.asm_equ('BTLP_BOARD23_NAME_END_2')
                      - toolbelt.asm_equ('BTLP_BOARD23_NAME_ROW_2')))
    directory.sort()
    # Spans that touch share one entry while the merged span still fits the
    # entry's size byte: the directory lives in reclaimed space, not a pool.
    merged = []
    for base, span in directory:
        if merged and base <= merged[-1][0] + merged[-1][1]:
            end = max(merged[-1][0] + merged[-1][1], base + span)
            if end - merged[-1][0] <= 0xff:
                merged[-1] = (merged[-1][0], end - merged[-1][0])
                continue
        merged.append((base, span))
    directory = merged
    table = bytearray()
    for base, span in directory:
        if not 0 < span <= 0xff or base & 0xff000000 != 0x80000000:
            raise ValueError(f'battle board: span {base:#x}+{span} does not fit its entry')
        table += struct.pack('<I', (span << 24) | (base & 0xffffff))
    table += struct.pack('<I', 0)
    table_at = None
    for start, end in free:
        aligned = (start + 3) & ~3
        if aligned + len(table) <= end:
            table_at = aligned
            break
    if table_at is None:
        raise ValueError(f'battle board: no reclaimed immutable space for {len(table)}-byte directory')

    unshipped = sorted(off for off in inventory
                       if _english(rows, off) and off not in shipped)
    deferred = sorted({e['text'] for entry in lists if not entry['translate']
                       for e in entry['entries']
                       if e['n'] > 0 and e['kind'] == 'text'
                       and _english(rows, e['text'])})
    return {
        'lists': lists,
        'translated': translated,
        'strings': strings,
        'descriptors': descriptor_list,
        'directory': directory,
        'table': (table_at, bytes(table)),
        'shipped': shipped,
        'unshipped': unshipped,
        'deferred': deferred,
    }


def build(data, rows):
    """Return the assembly body (a list of lines) for the board writes."""
    result = plan(data, rows)
    body = []
    for addr, encoded in result['strings']:
        body.append(f'.org {BASE + addr:#x}')
        body.append('    .byte ' + ', '.join(f'0x{x:02X}' for x in encoded))
    for desc, new_x, addr, count in result['descriptors']:
        if new_x is not None:
            body.append(f'.org {BASE + desc:#x}')
            body.append(f'    .halfword {new_x}')
        body.append(f'.org {BASE + desc + 4:#x}')
        body.append(f'    .word {BASE + addr:#x}')
        body.append(f'.org {BASE + desc + 8:#x}')
        body.append(f'    .byte {count}')
    addr, table = result['table']
    body.append(f'.definelabel BTL_BOARD_SPANS_ADDR, {BASE + addr:#x}')
    body.append(f'.org {BASE + addr:#x}')
    body.append('    .byte ' + ', '.join(f'0x{x:02X}' for x in table))
    return body, result


def verify(data, image, rows):
    """Prove a built BTLP image carries exactly the current board plan."""
    result = plan(data, rows)
    for addr, encoded in result['strings']:
        if image[addr:addr + len(encoded)] != encoded:
            raise ValueError(f'battle board: text at {BASE + addr:#x} differs')
    for desc, new_x, addr, count in result['descriptors']:
        if new_x is not None and struct.unpack_from('<h', image, desc)[0] != new_x:
            raise ValueError(f'battle board: heading at {BASE + desc:#x} is not centred')
        if struct.unpack_from('<I', image, desc + 4)[0] != BASE + addr:
            raise ValueError(f'battle board: pointer at {BASE + desc + 4:#x} differs')
        if image[desc + 8] != count:
            raise ValueError(f'battle board: count at {BASE + desc + 8:#x} differs')
    addr, table = result['table']
    if image[addr:addr + len(table)] != table:
        raise ValueError(f'battle board: ownership directory at {BASE + addr:#x} differs')
    spans = [(base, base + span) for base, span in result['directory']]
    for desc, _x, target, _count in result['descriptors']:
        address = BASE + target
        if not any(lo <= address < hi for lo, hi in spans):
            raise ValueError(f'battle board: row at {BASE + desc:#x} points outside owned spans')
    return result
