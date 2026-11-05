"""Prove PSP notice twins using matching executable consumers and an anchor.

Only plain, unique, exact Japanese source records are eligible. A PSP data
pointer must have a relocation, and its direct-load consumer must have exactly
one matching instruction fingerprint in each regional executable. At least one
immediately adjacent relocated pointer must be an independently proven JP/US
pair; all such nearby proven pairs must agree. Source addresses and wording are
read from the binaries and extracted corpora, never from an authored map.
"""
import collections
import csv
import os
import struct
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
import codec
import match_jp
import reward_notice
import tables
import toolbelt

RELOC_POINTER = 0x10102  # PSP R_MIPS_32: source and target in PT_LOAD 1
SPAN = 19


def elf(blob):
    """Return code/data extents and relocated data-pointer locations."""
    if blob[:6] != b'\x7fELF\x01\x01':
        raise ValueError('expected a little-endian 32-bit PSP ELF')
    phoff = struct.unpack_from('<I', blob, 0x1c)[0]
    phsize, phcount = struct.unpack_from('<HH', blob, 0x2a)
    if phsize < 32 or phoff + phsize * phcount > len(blob):
        raise ValueError('invalid ELF program table')
    loads = [struct.unpack_from('<8I', blob, phoff + i * phsize)
             for i in range(phcount)]
    loads = [p for p in loads if p[0] == 1]
    if len(loads) < 2:
        raise ValueError('missing PSP load segments')
    segments = [(p[1], p[1] + p[4]) for p in loads[:2]]
    if any(lo >= hi or hi > len(blob) for lo, hi in segments):
        raise ValueError('invalid PSP load extent')
    shoff = struct.unpack_from('<I', blob, 0x20)[0]
    shsize, shcount, names = struct.unpack_from('<HHH', blob, 0x2e)
    if shsize < 40 or not shcount or names >= shcount or shoff + shsize * shcount > len(blob):
        raise ValueError('invalid ELF section table')
    sections = [struct.unpack_from('<10I', blob, shoff + i * shsize)
                for i in range(shcount)]
    nt = sections[names]
    if nt[4] + nt[5] > len(blob):
        raise ValueError('invalid ELF section-name table')
    strtab = blob[nt[4]:nt[4] + nt[5]]
    def name(s):
        at = s[0]
        if at >= len(strtab):
            raise ValueError('invalid ELF section name')
        end = strtab.find(b'\0', at)
        if end < 0:
            raise ValueError('unterminated ELF section name')
        return strtab[at:end]
    candidates = [(i, s) for i, s in enumerate(sections) if name(s) == b'.rel.data']
    if len(candidates) != 1:
        raise ValueError('missing or ambiguous data relocations')
    _, rel = candidates[0]
    if rel[1] != 0x700000a0 or rel[9] != 8 or rel[5] % 8 or rel[4] + rel[5] > len(blob):
        raise ValueError('invalid PSP data relocations')
    data_lo, data_hi = segments[1]
    slots = set()
    for offset in range(rel[4], rel[4] + rel[5], 8):
        slot, info = struct.unpack_from('<II', blob, offset)
        if info != RELOC_POINTER:
            continue
        at = data_lo + slot
        if at % 4 or at < data_lo or at + 4 > data_hi or at in slots:
            raise ValueError('invalid or duplicate relocated pointer')
        slots.add(at)
    return segments, slots


def pointed(blob, segments, slot):
    """An unadorned, bounded PSP BE string read from a data pointer."""
    lo, hi = segments[1]
    if slot < lo or slot + 4 > hi:
        return None
    ptr = lo + struct.unpack_from('<I', blob, slot)[0]
    if ptr < lo or ptr % 2 or ptr >= hi:
        return None
    end = next((i for i in range(ptr, min(ptr + 512, hi - 1), 2)
                if blob[i:i + 2] == b'\xff\x01'), None)
    if end is None:
        return None
    raw = blob[ptr:end]
    if not raw or any(raw[i] == 0xff for i in range(0, len(raw), 2)):
        return None
    try:
        text = codec.decode_box(raw)
    except LookupError:
        return None
    return (ptr, text + '<FF01>') if text else None


def plain_key(text):
    """Ignore only a leading presentation arrow and Unicode width spelling."""
    if text.endswith('<FF01>'):
        text = text[:-6]
    if '<' in text or '>' in text[1:]:
        return None
    text = unicodedata.normalize('NFKC', text).strip()
    if text.startswith('>'):
        text = text[1:].strip()
    return text or None


def source_rows(rows):
    out = collections.defaultdict(list)
    for row in rows:
        if not row['text'].endswith('<FF01>'):
            continue
        key = plain_key(row['text'])
        if key:
            out[key].append(row)
    return out


def norm_instruction(word):
    op = word >> 26
    if op in (2, 3):
        return word & 0xfc000000  # relocation-dependent jump target
    if op in (15, 35):
        return word & 0xffff0000  # regional data displacement
    return word


def fingerprint(blob, start):
    if start < 0 or start + 4 * SPAN > len(blob):
        return None
    words = struct.unpack_from(f'<{SPAN}I', blob, start)
    # Actor call; lbu argument; direct data load in a call delay slot.
    if (words[0] >> 26 != 3 or words[1] != 0x90440004
            or words[2] & 0xffff0000 != 0x3c020000
            or words[3] >> 26 != 3 or words[4] & 0xffff0000 != 0x8c440000):
        return None
    return tuple(norm_instruction(w) for w in words)


def consumer_index(blob, segment):
    """Build a bounded index of code fingerprints and loaded data offsets."""
    result = collections.defaultdict(list)
    lo, hi = segment
    for at in range(lo, hi - 4 * SPAN + 1, 4):
        if struct.unpack_from('<I', blob, at + 4)[0] != 0x90440004:
            continue
        fp = fingerprint(blob, at)
        if fp is None:
            continue
        hiword = struct.unpack_from('<I', blob, at + 8)[0] & 0xffff
        lowword = struct.unpack_from('<h', blob, at + 16)[0]
        result[fp].append((at, (hiword << 16) + lowword))
    return result


def proven_pairs():
    """Independent accepted PSP pair grades only; never 'align'."""
    pairs = collections.defaultdict(set)
    path = os.path.join(toolbelt.MAPPINGS, 'psp_pairs.tsv')
    with open(path, encoding='utf-8', newline='') as source:
        for row in csv.reader(source, delimiter='\t'):
            if (len(row) >= 4 and row[0] == 'EBOOT'
                    and match_jp.PROVEN.intersection(row[3].split(','))):
                try:
                    pairs[int(row[2], 16)].add(int(row[1], 16))
                except ValueError:
                    continue
    return pairs


def candidates(messages, jp_blob, us_blob, jp_rows, us_rows, pairs):
    """Yield (message index, US extracted row) only for complete proofs."""
    js, jr = elf(jp_blob)
    us, ur = elf(us_blob)
    ji, ui = consumer_index(jp_blob, js[0]), consumer_index(us_blob, us[0])
    jrows, urows = source_rows(jp_rows), source_rows(us_rows)
    message_keys = collections.Counter(plain_key(text) for _i, text in messages)
    # Re-index only relocation targets that actually name a unique JP row.
    slots_by_row = collections.defaultdict(list)
    position_rows = collections.defaultdict(list)
    for rows in jrows.values():
        for row in rows:
            position_rows[int(row['pos'], 16)].append(row)
    by_position = {p: rows[0] for p, rows in position_rows.items() if len(rows) == 1}
    for slot in jr:
        decoded = pointed(jp_blob, js, slot)
        if decoded is None:
            continue
        ptr, text = decoded
        for pos in range(ptr - 8, ptr + 1, 2):
            row = by_position.get(pos)
            if row and row['text'] == text:
                slots_by_row[pos].append(slot)
    result = []
    for idx, ja in messages:
        key = plain_key(ja)
        if not key or message_keys[key] != 1 or len(jrows.get(key, ())) != 1:
            continue
        row = jrows[key][0]
        jpos = int(row['pos'], 16)
        if reward_notice.overlaps(jpos, jp_rows):
            continue
        slots = slots_by_row.get(jpos, ())
        if len(slots) != 1:
            continue
        jslot = slots[0]
        matches = [(fp, sites[0]) for fp, sites in ji.items()
                   if len(sites) == 1 and sites[0][1] + js[1][0] == jslot]
        if len(matches) != 1:
            continue
        fp, _site = matches[0]
        if len(ui.get(fp, ())) != 1:
            continue
        uslot = ui[fp][0][1] + us[1][0]
        if uslot not in ur:
            continue
        anchor_count = 0
        conflict = False
        for delta in (-4, 4):
            if jslot + delta not in jr or uslot + delta not in ur:
                continue
            jn = js[1][0] + struct.unpack_from('<I', jp_blob, jslot + delta)[0]
            un = us[1][0] + struct.unpack_from('<I', us_blob, uslot + delta)[0]
            if jn in pairs:
                anchor_count += 1
                if pairs[jn] != {un}:
                    conflict = True
        if not anchor_count or conflict:
            continue
        decoded = pointed(us_blob, us, uslot)
        if decoded is None:
            continue
        uptr, text = decoded
        ukey = plain_key(text)
        possible = [r for r in urows.get(ukey, ())
                    if r['text'] == text and 0 <= uptr - int(r['pos'], 16) <= 8]
        if len(urows.get(ukey, ())) != 1 or len(possible) != 1:
            continue
        found = possible[0]
        if reward_notice.overlaps(int(found['pos'], 16), us_rows):
            continue
        result.append((idx, found))
    return result


def derive(messages):
    """Read source material and return executable-consumer-proven candidates."""
    jp_rows = sorted(toolbelt.read_extracted('psp_jp', 'EBOOT'), key=lambda r: int(r['pos'], 16))
    us_rows = sorted(toolbelt.read_extracted('psp_us', 'EBOOT'), key=lambda r: int(r['pos'], 16))
    return candidates(messages, tables.jp_boot(), tables.us_boot(), jp_rows, us_rows, proven_pairs())
