"""D00-D0F dungeon packs: one table per real file, names + boxes.

  python src/injection_tools/dngpacks.py dump     scaffolds for every pack file
  python src/injection_tools/dngpacks.py build    writes build/<D0x>/ packs

Files (docs/TEXT_ARCHITECTURE.md):
  D0?M.BIN  8 name fields (entry table at +8; 10 u16 glyph cells each;
            stride 0xC4) - the map-screen floor titles. Short EN ships as
            centred glyph cells, 11-18 char EN as pre-swapped VWF script
            bytes (pack_field); longer stays JA for the map-title hook
            (dng/map_title.asm + build/dng_titles.asm).
  D0?.BIN   dialogue boxes (FF01-terminated, FF21-marked; the scan is the
            proven dngtext one) written in place into their slot + zero
            padding, JA indent preserved. Over-cap FAILS the build (the
            row needs relocation or a spill prefix - never silent JA).

All table IO and merging goes through toolbelt. This module owns box and
name-field placement; dngspill supplies overflow text through its hook.
"""
import glob
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext      # noqa: E402
import toolbelt   # noqa: E402
import vwf_wrap   # noqa: E402

ROOT = toolbelt.ROOT
PSX = os.path.join(ROOT, 'data', 'psx')
END = bytes((0xFF, 0x01))
TOK = re.compile(r'<FF0[2-4]>')
SLOTS = 10
SCRIPT_MAX = 18


def pack_files():
    """[(rel, path)] every dungeon pack, disc-relative (no extension)."""
    for fp in sorted(glob.glob(os.path.join(PSX, 'D0*', 'D*.BIN'))):
        rel = os.path.relpath(fp, PSX)[:-4]
        yield rel, fp


def name_fields(d):
    """[(offset, ja)] the map-name fields of a D0?M pack (dngnames scan)."""
    o = struct.unpack_from('<4I', d, 0)[2]
    p = o
    while p + 2 * SLOTS <= len(d):
        glyphs = struct.unpack_from('<10H', d, p)
        if any(w not in etext.glyph for w in glyphs):
            break
        ja = ''.join(etext.glyph[w] for w in glyphs)
        if not ja.strip('　'):
            break
        yield p, ja
        p += 0xC4


def boxes(d):
    """[(offset, length, japanese)] of every dialogue box (dngtext scan)."""
    out, prev = [], 0
    for m in re.finditer(b'\xff\x01', d):
        seg = d[prev:m.start() + 2]
        start = prev
        prev = m.start() + 2
        k = seg.rfind(b'\xff\x21\x00\x00')
        if k >= 0:
            seg, start = seg[k + 4:], start + k + 4
        # A text block starts on a 4-byte boundary: the bytes between the
        # previous FF01 and that boundary are alignment padding, not text.
        # Keeping them gave the box a phantom full-width indent, and the box
        # head the script points at (FF55 target) then differed from the spill
        # fingerprint, so the runtime kept the Japanese.
        pad = (-start) & 3
        if pad and not any(seg[:pad]):
            seg, start = seg[pad:], start + pad
        if b'\xff\x02' not in seg:
            continue
        if k < 0 and len(seg) > 400:
            continue      # unmarked run: the cap keeps data regions out;
                          # FF21-marked boxes hold arbitrary text
        try:
            t = etext.decode(seg)
        except Exception:
            continue
        if sum(1 for c in t if ord(c) > 0x2000) < 3:
            continue
        out.append((start, len(seg), t))
    return out


def slot_cap(d, off, ln):
    """The box's in-place capacity: its slot plus the zero padding that
    follows it in the pack."""
    cap = ln
    while off + cap < len(d) and d[off + cap] == 0:
        cap += 1
    return cap


def indent_en(en, ja):
    """The JA box's leading indent preserved in the English."""
    lead = len(ja) - len(ja.lstrip('　'))
    return ('　' * lead + en) if (lead and not en.startswith('　')
                          and '<FF06>' not in en) else en


def place(en, ja, d, off, ln):
    """(encoded bytes or None, capacity, chosen en) - where a row's English
    builds. It goes in place when it fits the box's capacity (the JA indent
    preserved when that still fits); otherwise the box is left Japanese and
    the spill hook ships the full text (dngspill). Boxes hold arbitrary
    text - nothing is ever cut."""
    cap = slot_cap(d, off, ln)
    for cand in (indent_en(en, ja), en):
        eb = etext.encode(cand, end=END)
        if len(eb) <= cap:
            return eb, cap, cand
    return None, cap, en


def width_ok(en):
    t = en.replace('<FF0F>　', '<FF0F>あ').replace('<FF07>　', '<FF07>あ').replace('<FF08>　', '<FF08>あ')
    return all(vwf_wrap.text_width(l) <= vwf_wrap.BOX_WIDTH + 1
               for l in TOK.sub('<FF03>', t).split('<FF03>'))


# ---------------------------------------------------------------------------
# name fields (pack_field: the injector behind the Image-2 fix)
# ---------------------------------------------------------------------------

EXTRA_VWF = b''


def vwf_bytes(en):
    out = bytearray()
    for c in en:
        o = ord(c)
        if not 0x20 <= o <= 0x7E:
            toolbelt.fail(f'{en!r}: {c!r} has no VWF byte')
        out.append(o + 0x68)
    return bytes(out) + b'\xff\x01'


def pack_field(en):
    """20 field bytes for EN (glyph cells <=10 chars; pre-swapped VWF
    script bytes 11-18; None = leave JA for the map-title hook)."""
    if not en or not en.strip():
        return None
    if len(en) <= SLOTS:
        lead = (SLOTS - len(en)) // 2
        s = ' ' * lead + en
        s += ' ' * (SLOTS - len(s))
        return b''.join(struct.pack('<H', 0 if c == ' ' else toolbelt.glyph_char(c))
                        for c in s)
    script = vwf_bytes(en)[:-2]
    if len(script) > SCRIPT_MAX:
        return None
    if len(script) % 2:
        script += b'\x88'   # terminator must sit at an even cell offset
    raw = script + b'\xff\x01'
    swapped = b''.join(bytes((raw[i + 1], raw[i]))
                       for i in range(0, len(raw), 2))
    return swapped + b'\x00' * (20 - len(swapped))


# ---------------------------------------------------------------------------
# dump + build
# ---------------------------------------------------------------------------

def dump():
    total = 0
    for rel, fp in pack_files():
        d = open(fp, 'rb').read()
        base = os.path.basename(rel)
        if len(base) == 3:                                  # D00.BIN: boxes
            slots = [(hex(off), '') for off, _ln, _ja in boxes(d)]
        elif base.endswith('M'):                            # D00M.BIN: names
            slots = [(hex(off), '') for off, _ja in name_fields(d)]
        else:
            # D00S.BIN and friends are not a text family of this tool: their
            # header decodes as glyphs, which would scaffold a garbage row.
            continue
        rows, _man = toolbelt.dump_scaffold(rel, slots)
        total += len(rows)
    print(f'dngpacks: {total} rows scaffolded')


def build():
    n_names = n_boxes = n_files = n_spill = 0
    for rel, fp in pack_files():
        base = os.path.basename(rel)
        d = bytearray(open(fp, 'rb').read())
        rows = {r['pos']: r for r in toolbelt.merged_rows(rel)}
        changed = False
        if len(base) == 3:                                  # boxes file
            orig = bytes(d)
            for off, ln, ja in boxes(orig):
                r = rows.get(hex(off))
                en = (r['en'] if r else '').strip()
                if not en:
                    continue
                eb, cap, en = place(en, ja, orig, off, ln)
                if eb is None:
                    n_spill += 1     # dngspill ships the full text via hook
                    continue
                if '<FF06>' not in en and not width_ok(en.lstrip('　')):
                    toolbelt.fail(f'dngpacks: {rel}:{off:#x} over-wide: the box '
                                  f'would wrap it mid-word (never shipped as-is)')
                d[off:off + cap] = eb + bytes(cap - len(eb))
                n_boxes += 1
        elif base.endswith('M'):                            # name-fields pack
            for off, _ja in name_fields(bytes(d)):
                r = rows.get(hex(off))
                en = (r['en'] if r else '').strip()
                field = pack_field(en) if en else None
                if field is None:
                    continue            # long names stay JA for the hook
                d[off:off + 2 * SLOTS] = field
                n_names += 1
        if changed or n_names or n_boxes:                    # rows changed above
            pass
        out = os.path.join(ROOT, 'build', *rel.split('/')) + '.BIN'
        toolbelt.ensure_parent(out)
        with open(out, 'wb') as o:
            o.write(bytes(d))
        n_files += 1
    print(f'dngpacks: {n_names} name fields + {n_boxes} boxes in {n_files} packs '
          f'({n_spill} boxes spill)')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'dump': dump, 'build': build}[sys.argv[1] if sys.argv[1:] else 'build']()
