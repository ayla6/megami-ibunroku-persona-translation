"""Extract retail BTLP board and descriptor-backed small-font source pools.

Rows are physical FF-terminated strings, not descriptor instances.  Multiple
settings descriptors can point to one value; the translation worklist must
have one row per actual source slot. English drafts are not rendered until the
battle-object VWF, storage ownership and frame budgets are proved.
"""
import struct

import etext

BASE = 0x800643c4
# File offsets of the two contiguous, four-byte-aligned retail text pools.
POOLS = ((0x7a2fc, 0x7a398, 14), (0x7b9b8, 0x7ba24, 11),
         (0x7a84c, 0x7a868, 4))
# Additional descriptor-backed fixed-size source records. Their consumer
# reachability is not established; preserve them as source candidates.
FIXED_POOLS = ((0x795f4, 14, 10), (0x79d2c, 9, 10), (0x79fbc, 4, 10),
               (0x7a0fc, 3, 10), (0x7a12e, 4, 10), (0x7b68c, 15, 10),
               (0x7b034, 7, 5), (0x7a0e8, 2, 10), (0x7a11a, 2, 10),
               (0x7a156, 3, 10), (0x79d86, 1, 10))
# Source board descriptor tables (12-byte BtlGfxText records). Indices after
# POOLS refer to FIXED_POOLS in order.
BOARDS = ((0x7a398, 11, 0), (0x7ba24, 16, 1), (0x7bae4, 1, 1),
          (0x7a8a4, 15, 2), (0x7a958, 1, 2), (0x7968c, 14, 3),
          (0x79d90, 9, 4), (0x79fe4, 4, 5), (0x7a18c, 3, 6),
          (0x7a1c8, 4, 7), (0x7b72c, 15, 8), (0x7b0ac, 7, 9),
          (0x7a174, 2, 10), (0x7a1b0, 2, 11), (0x7a1f8, 3, 12),
          (0x79dfc, 6, 13))


def scan(data):
    """Return (file offset, decoded Japanese) in declared pool order; fail on drift."""
    out = []
    starts = [set() for _ in (*POOLS, *FIXED_POOLS)]
    for index, (first, end, expected_count) in enumerate(POOLS):
        if end > len(data):
            raise ValueError('battle board: source pool is outside BTLP')
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
            starts[index].add(p)
            out.append((p, ''.join(etext.glyph[code] for code in glyphs)))
            p = next_p
        if len(starts[index]) != expected_count:
            raise ValueError('battle board: source pool record count changed')
    for index, (first, count, stride) in enumerate(FIXED_POOLS, start=len(POOLS)):
        if first + count * stride > len(data):
            raise ValueError('battle board: fixed source pool is outside BTLP')
        for i in range(count):
            off = first + i * stride
            record = data[off:off + stride]
            end = record.find(b'\xff')
            if end <= 0 or any(record[end + 1:]) or any(c not in etext.glyph for c in record[:end]):
                raise ValueError(f'battle board: invalid fixed source slot at {off:#x}')
            starts[index].add(off)
            out.append((off, ''.join(etext.glyph[c] for c in record[:end])))
    for table, count, index in BOARDS:
        if table + count * 12 > len(data):
            raise ValueError('battle board: descriptor table is outside BTLP')
        for i in range(count):
            off = table + i * 12
            pointer = struct.unpack_from('<I', data, off + 4)[0]
            if pointer - BASE not in starts[index]:
                raise ValueError(f'battle board: unowned descriptor pointer at {off:#x}')
    return out


def initial_references(data):
    """Physical starts named by descriptors in the original file image."""
    return {struct.unpack_from('<I', data, table + i * 12 + 4)[0] - BASE
            for table, count, _pool in BOARDS for i in range(count)}


def direct_assignments(data):
    """Adjacent LUI/ADDIU/LUI/SW assignments into known descriptor fields.

    This is positive evidence, not an exhaustive indirect-reference scan.
    Return (code offset, pool start, descriptor pointer field).
    """
    source = {off for off, _ in scan(data)}
    fields = {table + i * 12 + 4 for table, count, _pool in BOARDS for i in range(count)}
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
        target = ((((c & 0xffff) << 16) + signed(d & 0xffff)) & 0xffffffff) - BASE
        if value in source and target in fields:
            out.append((off, value, target))
    return out


def verify_retail_bytes(stock, image):
    """Reject an image whose draft-only pools or descriptors are not retail."""
    for lo, hi, _count in POOLS:
        if len(image) < hi or stock[lo:hi] != image[lo:hi]:
            raise ValueError(f'battle board text pool changed at {lo:#x}')
    for off, count, stride in FIXED_POOLS:
        end = off + count * stride
        if len(image) < end or stock[off:end] != image[off:end]:
            raise ValueError(f'battle board fixed text pool changed at {off:#x}')
    for off, count, _pool in BOARDS:
        end = off + count * 12
        if len(image) < end or stock[off:end] != image[off:end]:
            raise ValueError(f'battle board descriptor changed at {off:#x}')


def verify_draft_report(lines, expected):
    """Require the generated report even when there are zero drafts."""
    if lines != ['pos'] + list(expected):
        raise ValueError('battle board draft report is missing, malformed or stale')
