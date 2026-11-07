"""Battle small-font page: retail fixed art plus separate proportional cells.

  python tools/btlfont.py        write build/B/BF.BIN (original/B/BF.BIN = /B/BF.BIN of the original disc,
                                 `python src/extraction_tools/psx/extract.py <image.bin> data/psx B/BF.BIN`)

At battle start BTLP decompresses (MES codec, decoder BTLP 0x80081C08; tools/mescodec.py) a 4bpp TIM from the battle
field data (/B/BF.BIN, one copy per battle field, 67 identical copies) and uploads it to VRAM (960,256) 64x128: the
battle small-font page. Its cells 0xCD+ are battle icons, cell rows 0-2 match every other small-font page. Each copy is
decoded, every pixel that still holds the retail page gets the sheet's pixel (tools/smallfont_vwf.py page_copy - the
icon rows differ from retail and stay the copy's own), and it is re-encoded with the optimal-parse encoder (smaller than
the original stream, so it is written in place; the bytes after the end code are left alone). Replaces the earlier
VRAM copy hook, which copied garbage in overworld battles.
"""
import os
import sys
import struct
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mescodec   # noqa: E402
import menu_gfx   # noqa: E402
import smallfont_vwf  # noqa: E402
import tim        # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, 'data', 'psx', 'B', 'BF.BIN')
OUT = os.path.join(ROOT, 'build', 'B', 'BF.BIN')

# The battle copy's icon rows differ from this reference and stay untouched.
_src = open(os.path.join(ROOT, 'data', 'psx', 'ADV', 'ADVCMD.BIN'), 'rb').read()
_t = tim.parse(_src, menu_gfx.PAGE)
REF = smallfont_vwf.unpack_page(_src[_t['at']:_t['at'] + 128 * 256])
@lru_cache(maxsize=1)
def art_mapping():
    """Pack letters and punctuation into encoder-derived spare kana runs,
    preserving every fixed-cell Latin glyph at its original address."""
    import smallfont_lc
    import smallfont_variants as variants
    import toolbelt
    lower = [toolbelt.smallfont_char(c)
             for c in "abcdefghijklmnopqrstuvwxyz" + ''.join(smallfont_lc.PUNCT)]
    upper = [toolbelt.smallfont_char(c) for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ']
    low_min, low_end = min(lower), max(lower) + 1
    up_min, up_end = min(upper), max(upper) + 1
    size = low_end - low_min + up_end - up_min
    spare = set(variants.spare_codes())
    start = next((c for c in sorted(spare) if set(range(c, c + size)) <= spare), None)
    if start is None:
        raise SystemExit('btlfont: no safe contiguous Latin sprite allocation')
    biases = start - low_min, start + low_end - low_min - up_min
    mapping = {c: c + biases[0] for c in lower}
    mapping.update({c: c + biases[1] for c in upper})
    numerals = [toolbelt.smallfont_char(c) for c in '0123456789/:-']
    nmin, nend = min(numerals), max(numerals) + 1
    unused = spare - set(range(start, start + size))
    nstart = next(c for c in sorted(unused) if set(range(c, c + nend - nmin)) <= unused)
    nbias = nstart - nmin
    mapping.update({c: c + nbias for c in numerals})
    return mapping, (low_end, biases[0], up_end, biases[1], nbias)


def battle_page():
    import smallfont_lc
    import features
    retail, _, _ = smallfont_vwf.disc_page()
    if not features.on('SF_LATIN'):
        return retail
    smallfont_lc.draw(retail, 256)
    if features.on('SF_VWF'):
        regular = smallfont_vwf.thin_page_indices()[0]
        for code, dest in art_mapping()[0].items():
            for y in range(12):
                src = (code // 31 * 12 + y) * 256 + code % 31 * 8
                dst = (dest // 31 * 12 + y) * 256 + dest % 31 * 8
                retail[dst:dst + 8] = regular[src:src + 8]
    return retail


SHEET = battle_page()


def proportional_uv(code):
    cell = art_mapping()[0].get(code, code)
    return cell % 31 * 8, cell // 31 * 12
# first bytes of the compressed page (TIM header 10 00 00 00 08 00 00 00 ec 00 ... as literal / zero-run tokens)
PREFIX = bytes.fromhex('8010e28008e280ece482e0011' + '0e08007e281ff7f')


def persona_vwf_flags():
    """Bit per canonical Persona ID with an actually written English name."""
    import personas
    import skills
    bits = bytearray((personas.COUNT + 1 + 7) // 8)
    for ident, name in personas.record_en().items():
        if name.strip():
            skills.encode_glyphs(ident, name.strip())
            bits[ident >> 3] |= 1 << (ident & 7)
    return bytes(bits)


def item_vwf_records():
    """Complete English names eligible for the battle item producer."""
    import items
    import toolbelt
    origin = toolbelt.asm_equ('ITEM_NAME_BASE')
    limit = toolbelt.asm_equ('BTLP_ITEM_ID_COUNT')
    records = {}
    for row in toolbelt.merged_rows('SLPS_005.00'):
        address = int(row['pos'], 16) + items.BASE
        delta = address - origin
        text = row['en'].strip()
        if text and delta % items.STRIDE == 0 and 0 < delta // items.STRIDE < limit:
            records[delta // items.STRIDE] = items.encode(text)
    return records


def item_vwf_flags():
    import toolbelt
    bits = bytearray((toolbelt.asm_equ('BTLP_ITEM_ID_COUNT') + 7) // 8)
    for ident in item_vwf_records():
        bits[ident >> 3] |= 1 << (ident & 7)
    return bytes(bits)


def main():
    constants = ('BTL_ART_LOW_END', 'BTL_ART_LOW_BIAS', 'BTL_ART_UPPER_END', 'BTL_ART_UPPER_BIAS', 'BTL_ART_NUM_BIAS')
    Path(ROOT, 'build', 'btl_art.asm').write_text(''.join(
        f'.definelabel {key}, {value}\n' for key, value in zip(constants, art_mapping()[1])))
    Path(ROOT, 'build', 'btl_item_vwf_flags.bin').write_bytes(item_vwf_flags())
    flags = persona_vwf_flags()
    Path(ROOT, 'build', 'persona_vwf_flags.bin').write_bytes(flags)
    d = bytearray(open(SRC, 'rb').read())
    hits = []
    i = d.find(PREFIX)
    while i >= 0:
        raw, used = mescodec.decode(bytes(d[i:i + 0x4000]), 0x8000)
        t = tim.parse(raw, 0)
        if (t['w'], t['h']) == (64, 128):           # the TIM says (768,0); BTLP uploads it to (960,256) itself
            hits.append((i, used, raw))
        i = d.find(PREFIX, i + 1)
    if not hits:
        raise SystemExit('btlfont: no battle font page found in BF.BIN')
    cache = {}
    if not os.path.exists(OUT):
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
    for s, used, raw in hits:
        if raw not in cache:
            t = tim.parse(raw, 0)
            at = t['at']
            new = bytearray(raw)
            old = bytes(raw[at:at + 128 * t['h']])
            new[at:at + len(old)] = smallfont_vwf.page_copy(
                smallfont_vwf.unpack_page(old), REF, SHEET, 256, t['h'])
            cache[raw] = mescodec.encode_opt(bytes(new))
        enc = cache[raw]
        if len(enc) > used:
            raise SystemExit(f'btlfont: page at {s:#x} re-encodes to {len(enc)} bytes > {used}')
        d[s:s + len(enc)] = enc
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'wb').write(bytes(d))
    print(f'btlfont: {len(hits)} battle font pages patched ({len(cache)} distinct, '
          f'{len(next(iter(cache.values())))} of {hits[0][1]} bytes) -> {OUT}')


def persona_battle_glyphs(stock, built, resident, widths):
    """Prove name ink fits the rev0 header and PRS-CHG first-step board."""
    import personas
    import skills
    import toolbelt

    base = 0x800643C4
    def unpack(fmt, data, address):
        size = struct.calcsize(fmt)
        off = address - base
        if off < 0 or off + size > len(data):
            raise SystemExit('btlfont: Persona board graph points outside BTLP')
        return struct.unpack_from(fmt, data, off)
    def unchanged(address, size):
        off = address - base
        if off < 0 or off + size > len(stock) or off + size > len(built) or stock[off:off+size] != built[off:off+size]:
            raise SystemExit('btlfont: Persona board graph or frame was modified')
    def part(root, index, expected_kind):
        entry_addr = root + index*8
        unchanged(entry_addr, 8)
        defs, entry, kind, page, _clut = unpack('<IBBBB', stock, entry_addr)
        if kind != expected_kind:
            raise SystemExit('btlfont: changed Persona board layer kind')
        definition = defs + entry*8
        unchanged(definition, 8)
        _attr, script = unpack('<II', stock, definition)
        unchanged(script, 8)
        (value,) = unpack('<I', stock, script)
        unchanged(value, 8)
        count, cells = unpack('<II', stock, value)
        if count > 128:
            raise SystemExit('btlfont: invalid Persona board layer count')
        if kind in (1, 7): unchanged(cells, count*8)
        return page, count, cells

    root = 0x800E2288                 # rev0 PRS-CHG board root
    page, count, rows = part(root, 0, 3)
    if page != 31 or count != 22 or rows + 5*12 != toolbelt.asm_equ('BTLP_PRSCHG_DESC'):
        raise SystemExit('btlfont: Persona text list no longer belongs to the expected board')
    _page, n, border = part(root, 1, 1)
    border_cells = [unpack('<hhBBBB', stock, border + i*8) for i in range(n)]
    _page, n, background = part(root, 2, 7)
    bg = [unpack('<hhBBBB', stock, background + i*8) for i in range(n)]
    if not bg or not border_cells:
        raise SystemExit('btlfont: empty Persona frame geometry')
    # Vertical 8x8 border cells are the interior horizontal boundary; the
    # background tiles independently prove that the whole row is covered.
    vertical = [(x,y,w,h) for x,y,_u,_v,w,h in border_cells if w == 8 and h == 8]
    def inner_edges(y, h):
        left, right = [], []
        for pixel_y in range(y, y+h):
            l = [x+w for x,yy,w,hh in vertical if x < 0 and yy <= pixel_y < yy+hh]
            r = [x for x,yy,w,hh in vertical if x > 0 and yy <= pixel_y < yy+hh]
            if not l or not r:
                raise SystemExit('btlfont: Persona row lacks vertical border coverage')
            left.append(max(l)); right.append(min(r))
        return max(left), min(right)
    def background_covers(x0, x1, y, h):
        for yy in range(y, y+h):
            intervals = sorted((x,x+w) for x,by,_u,_v,w,bh in bg if by <= yy < by+bh)
            edge = x0
            for lo,hi in intervals:
                if lo > edge: break
                edge = max(edge, hi)
            if edge < x1: return False
        return True

    header = toolbelt.asm_equ('BTLP_HDR_NAME_DESC')
    label = toolbelt.asm_equ('BTLP_HDR_LABEL_DESC')
    hx,hy,_ptr,_n,_cl,h,v = unpack('<hhIBBBB', built, header)
    lx,ly,lptr,ln,_cl,lh,lv = unpack('<hhIBBBB', built, label)
    if (hy,h,v) != (ly,lh,lv) or (h,v) != (12,0):
        raise SystemExit('btlfont: unexpected Persona header/label geometry')
    if lptr != toolbelt.asm_equ('BATTLE_LABEL_BUF'):
        raise SystemExit('btlfont: the header label row does not point at its static slot')
    # The label string itself is written in the resident image (its bank is a
    # dead run there), so read its bytes from that image, not from BTLP.
    elf_base = struct.unpack_from('<I', resident, 0x18)[0]
    def label_byte(va):
        off = 0x800 + va - elf_base
        if off < 0 or off >= len(resident):
            raise SystemExit('btlfont: the header label row leaves the resident image')
        return resident[off:off+1]
    required = {0}                    # fixed-size names use zero padding
    label_ink = []
    pen = 0
    for i in range(ln):
        (code,) = label_byte(lptr+i)
        if code == 0xFF: break
        # The label is not owned: retail fixed cells, one 8 px step per glyph.
        x,y = code % 31 * 8, code // 31 * 12
        if y + 12 > 128: raise SystemExit('btlfont: header label glyph outside atlas')
        required.add(code)
        label_ink += [lx + pen + col for row in range(12) for col in range(8)
                      if SHEET[(y+row)*256+x+col]]
        pen += 8
    if not label_ink:
        raise SystemExit('btlfont: Persona header label has no measured ink')
    header_right = min(label_ink)
    if any(SHEET[row*256+col] for row in range(12) for col in range(8)):
        raise SystemExit('btlfont: Persona padding cell is not blank')
    maximum = 0
    for ident, text in personas.record_en().items():
        if not text.strip(): continue
        codes = skills.encode_glyphs(ident, text.strip())
        if len(codes) > personas.MAXLEN:
            raise SystemExit(f'btlfont: Persona {ident} exceeds its slot')
        pen = 0
        left, right = 1 << 30, -(1 << 30)
        for code in codes:
            required.add(code)
            x,y = proportional_uv(code)
            if y + 12 > 128 or not (widths[code] & 15):
                raise SystemExit(f'btlfont: Persona {ident} has invalid font glyph {code:#x}')
            ink = [col for row in range(12) for col in range(8)
                   if SHEET[(y+row)*256+x+col]]
            if ink:
                left = min(left, pen - (widths[code] >> 4) + min(ink))
                right = max(right, pen - (widths[code] >> 4) + max(ink) + 1)
            pen += widths[code] & 15
        if right < left: continue
        maximum = max(maximum, right)
        if hx + right > header_right:
            raise SystemExit(f'btlfont: Persona {ident} overlaps the header label')
        for i in range(3):
            desc = rows + (5+i)*12
            x,y,_ptr,_n,_cl,h,v = unpack('<hhIBBBB', built, desc)
            rx,ry,_rptr,_rn,_rcl,rh,rv = unpack('<hhIBBBB', stock, desc)
            if (x,y,h,v) != (rx,ry,rh,rv) or (h,v) != (12,0):
                raise SystemExit('btlfont: changed Persona row geometry')
            lo,hi = inner_edges(y,h)
            # On these three rows the adjacent skill column starts at x=56.
            sx,sy,_p,_n,_c,sh,sv = unpack('<hhIBBBB', stock, rows + (11+i)*12)
            if (sy,sh,sv) != (y,h,v):
                raise SystemExit('btlfont: Persona neighbor geometry changed')
            if x+left < lo or x+right > min(hi,sx) or not background_covers(x+left,x+right,y,h):
                raise SystemExit(f'btlfont: Persona {ident} exceeds board/neighbor geometry')
    return required, maximum


def item_battle_glyphs(stock, built, widths):
    """Validate full item rows and their count-column clearance."""
    import items
    import toolbelt
    base = 0x800643C4
    first = toolbelt.asm_equ('BTLP_ITEM_DESC')
    names = toolbelt.asm_equ('BTLP_ITEM_NAMES_ADDR')
    counters = toolbelt.asm_equ('BTLP_ITEM_COUNT_ADDR')
    rows = toolbelt.asm_equ('BTLP_ITEM_ROWS')
    field = toolbelt.asm_equ('BTLP_ITEM_FIELD')
    full = toolbelt.asm_equ('BTLP_ITEM_FULL_ADDR')
    stride = toolbelt.asm_equ('BTLP_ITEM_FULL_STRIDE')
    def source_address(at):
        upper,lower = struct.unpack_from('<II',stock,at-base)
        reg = (upper>>16)&31
        if upper>>26 != 15 or lower>>26 != 9 or (lower>>21)&31 != reg:
            raise SystemExit('btlfont: changed item producer address construction')
        immediate = (lower&0xFFFF) - (0x10000 if lower&0x8000 else 0)
        return (((upper&0xFFFF)<<16)+immediate)&0xFFFFFFFF
    if (source_address(0x800ACF10) != first
            or source_address(0x800ACF20) != names
            or source_address(0x800ACF2C) != counters
            or source_address(0x800ACF44) != toolbelt.asm_equ('BTLP_ITEM_IDS_ADDR')):
        raise SystemExit('btlfont: item metadata does not match its actual producer')
    for index in range(rows):
        at = first - base + index * 12
        x,y,ptr,count,clut,h,v = struct.unpack_from('<hhIBBBB',stock,at)
        expected = (x,y,full+index*stride,20,clut,h,v)
        if (ptr,count,h,v) != (names+index*field,field,12,0) or struct.unpack_from('<hhIBBBB',built,at) != expected:
            raise SystemExit('btlfont: changed item name descriptor')
        counter = first - base + rows*12 + index*12
        cx,cy,cp,cn,cc,ch,cv = struct.unpack_from('<hhIBBBB',stock,counter)
        if ((cp,cn,cy,ch,cv) != (counters+index*3,2,y,h,v)
                or struct.unpack_from('<hhIBBBB',built,counter) != (cx+12,cy,cp,cn,cc,ch,cv)):
            raise SystemExit('btlfont: changed item numeric descriptor')
    # Count formatting and row heights remain retail in both producers.
    for lo,hi in ((0x800ACF28,0x800AD014),(0x800AD09C,0x800AD0F8),
                  (0x800AD0FC,0x800AD110),(0x800AD118,0x800AD13C),
                  (0x800AD424,0x800AD49C),(0x800AD4A4,0x800AD4F4),
                  (0x800AD4F8,0x800AD550)):
        if built[lo-base:hi-base] != stock[lo-base:hi-base]:
            raise SystemExit('btlfont: item producer contract changed')
    required = set()
    resident = Path(ROOT,'build','SLPS_005.00').read_bytes()
    for ident,codes in item_vwf_records().items():
        address = toolbelt.asm_equ('ITEM_NAME_BASE') + ident*items.STRIDE - items.BASE
        actual = resident[address:address+field].split(b'\xff')[0]
        if actual != codes[:field]:
            raise SystemExit('btlfont: owned item bytes differ from canonical complete wording')
        pen = 0
        for code in codes:
            required.add(code)
            x,y = proportional_uv(code)
            if y+12 > 128 or not widths[code]&15:
                raise SystemExit('btlfont: invalid item atlas glyph')
            ink = [col for row in range(12) for col in range(8) if SHEET[(y+row)*256+x+col]]
            left = pen-(widths[code]>>4)
            if ink and (left+min(ink)<0 or left+max(ink)+1>100):
                raise SystemExit(f'btlfont: item {ident} exceeds its 100px battle column')
            pen += widths[code]&15
    return required


def verify_skill_vwf():
    """Fail closed unless every emitted skill fits the retail battle font and row."""
    import skills
    import slps
    import toolbelt

    stock = Path(os.path.join(ROOT, 'data', 'psx', 'BTLP.BIN')).read_bytes()
    built = Path(os.path.join(ROOT, 'build', 'BTLP.BIN')).read_bytes()
    widths = Path(os.path.join(ROOT, 'build', 'sf_width.bin')).read_bytes()
    battle_widths = Path(os.path.join(ROOT, 'build', 'btl_sf_width.bin')).read_bytes()
    base = 0x800643C4
    width_addr = toolbelt.asm_equ('BTLP_SF_WIDTH_ADDR')
    code_addr = toolbelt.asm_equ('BTLP_SF_CODE_ADDR')
    end_addr = toolbelt.asm_equ('BTLP_SF_END_ADDR')
    stock_end = base + len(stock)
    sector_end = base + ((len(stock) + 2047) // 2048) * 2048
    name_start = toolbelt.asm_equ('BTLP_NAME_DATA_ADDR')
    name_limit = toolbelt.asm_equ('BTLP_NAME_DATA_END')
    if not (stock_end <= width_addr and width_addr + len(battle_widths) == code_addr
            and code_addr < end_addr == sector_end
            and name_start == sector_end and sector_end < base + len(built) <= name_limit
            and (len(built) + 2047) // 2048 == (len(stock) + 2047) // 2048 + 1):
        raise SystemExit('btlfont: battle VWF or name data overlaps another owner')
    if built[width_addr-base:code_addr-base] != battle_widths:
        raise SystemExit('btlfont: battle VWF width table differs from the generated '
                         'text-cell / retail-cell split')
    bits = Path(os.path.join(ROOT, 'build', 'btl_text_bits.bin')).read_bytes()
    for code in range(256):
        text = bool(bits[code >> 3] & (1 << (code & 7)))
        if text != (battle_widths[code] != 0x08):
            raise SystemExit(f'btlfont: battle width table marks code {code:#x} wrong '
                             f'(text={text}, metric={battle_widths[code]:#x})')
    for hook, label in ((0x80088F84, code_addr), (0x800892C8, code_addr + 0x20)):
        actual, delay = struct.unpack_from('<II', built, hook - base)
        expected = 0x08000000 | ((label >> 2) & 0x3FFFFFF)
        if (actual, delay) != (expected, 0):
            raise SystemExit(f'btlfont: missing battle VWF hook at {hook:#x}')

    # The battle skill menu's display bound is the width between the two
    # list-A columns (144 px). The patch has always drawn 120 px in both
    # lists; skills.NAME_PX is that measured policy, not a guessed count.
    descriptor_ptrs = set()
    skill_buffer = toolbelt.asm_equ('SKILL_MENU_BUF')
    stride = toolbelt.asm_equ('SKILL_MENU_STRIDE')
    for key in ('BTLP_SKILL_DESC_A', 'BTLP_SKILL_DESC_B'):
        first = toolbelt.asm_equ(key)
        columns = set()
        for i in range(7):
            at = first - base + 12*i
            x, y, _, count, clut, height, v = struct.unpack_from('<hhIBBBB', stock, at)
            if height != 12 or v != 0 or not count:
                raise SystemExit('btlfont: unexpected retail skill descriptor geometry')
            columns.add(x)
            bx, by, ptr, n, bc, h, vv = struct.unpack_from('<hhIBBBB', built, at)
            if (bx, by, ptr, n, bc, h, vv) != (x, y, skill_buffer + i*stride, skills.MAXLEN, clut, height, v):
                raise SystemExit('btlfont: changed battle skill slot descriptor')
            descriptor_ptrs.add(at + 4)
        if len(columns) > 1 and skills.NAME_PX > max(columns) - min(columns):
            raise SystemExit('btlfont: skill width cap reaches into the next retail column')
    limit = skills.NAME_PX
    skill0 = slps.SK_FIRST - slps.BASE
    required = set()
    translated_ids = []
    count = 0
    for row in toolbelt.merged_rows('SLPS_005.00'):
        pos = int(row['pos'], 16)
        text = row['en'].strip()
        if not (text and skill0 <= pos < skill0 + slps.SK_COUNT * slps.SK_STRIDE
                and (pos - skill0) % slps.SK_STRIDE == 0):
            continue
        translated_ids.append((pos - skill0) // slps.SK_STRIDE + 1)
        chars = skills.encode(0, text)
        pen = 0
        for c in chars:
            required.add(c)
            x, y = proportional_uv(c)
            if y + 12 > 128:
                raise SystemExit(f'btlfont: skill glyph {c:#x} exceeds the battle font page')
            ink = [i for j in range(12) for i in range(8) if SHEET[(y+j)*256+x+i]]
            origin = pen - (widths[c] >> 4)
            if ink and (origin + min(ink) < 0 or origin + max(ink) + 1 > limit):
                raise SystemExit(f'btlfont: skill {row["pos"]} exceeds its {limit}px battle-menu column footprint')
            pen += widths[c] & 15
        count += 1

    resident = Path(os.path.join(ROOT, 'build', 'SLPS_005.00')).read_bytes()
    persona_required, persona_max = persona_battle_glyphs(stock, built, resident, widths)
    required.update(persona_required)
    required.update(item_battle_glyphs(stock,built,widths))

    flag_offset = toolbelt.asm_equ('SKILL_VWF_FLAGS_ADDR') - slps.BASE
    expected_flags = skills.vwf_ownership(translated_ids)
    if resident[flag_offset:flag_offset + len(expected_flags)] != expected_flags:
        raise SystemExit('btlfont: skill VWF ownership bitmap does not match the written English records')
    slots_addr = toolbelt.asm_equ('SKILL_VWF_SLOTS_ADDR')
    expected_slots = b'\x00\x00'
    if slots_addr % 2 or resident[slots_addr - slps.BASE:slots_addr - slps.BASE + 2] != expected_slots:
        raise SystemExit('btlfont: battle name-slot ownership halfword is not clear at boot')
    # The Persona header bank (4 x 16 bytes: three owned name slots and the
    # fixed-width "Cost" label) and the skill bank (7 x 24 bytes) are separate
    # ranges of one ownership bitmap: Persona bits 0..2, skill slot i at bit
    # 3+i. Each must fill its own dead run exactly; the label's slot is outside
    # the owned Persona range.
    persona_buf = toolbelt.asm_equ('PERSONA_HDR_BUF')
    hdr_stride = toolbelt.asm_equ('PERSONA_HDR_STRIDE')
    persona_end = toolbelt.asm_equ('PERSONA_HDR_BUF_END')
    skill_end = toolbelt.asm_equ('SKILL_MENU_BUF_END')
    if (persona_buf + 4 * hdr_stride != persona_end
            or persona_end > toolbelt.asm_equ('PERSONA_HDR_LIMIT')
            or skill_buffer + 7 * stride != skill_end
            or skill_end > toolbelt.asm_equ('BANNER_SPILL_ADDR')):
        raise SystemExit('btlfont: Persona and skill slot banks do not fill their own dead runs')
    for key, offsets in (('BTLP_HDR_NAME_DESC', (0,)), ('BTLP_PRSCHG_DESC', (0, 1, 2))):
        first = toolbelt.asm_equ(key)
        for index in offsets:
            at = first - base + index * 12
            ptr, n = struct.unpack_from('<IB', built, at + 4)
            if (ptr, n) != (persona_buf + index * hdr_stride, 16):
                raise SystemExit('btlfont: Persona descriptor does not point to its owned slot')
            descriptor_ptrs.add(at + 4)
    # Both semantic banks use the same predicate. Static references to any
    # eligible slot require the same independent atlas/geometry proof.
    for at in range(0, len(built) - 3, 4):
        ptr = struct.unpack_from('<I', built, at)[0]
        if skill_buffer <= ptr < skill_buffer + 7*stride and (ptr-skill_buffer) % stride == 0:
            if at not in descriptor_ptrs:
                raise SystemExit(f'btlfont: unverified battle skill-buffer pointer at {base + at:#x}')
    symbols = {}
    for line in Path(ROOT, 'build', 'persona.sym').read_text().splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                symbols[parts[1]] = int(parts[0], 16)
            except ValueError:
                pass
    name_table = symbols.get('btl_name_ranges',0)
    item_flags_addr = symbols.get('btl_item_vwf_flags',0)
    owner = symbols.get('btl_item_owner',0)
    packed = (struct.pack('<IHHIHHHHII',persona_buf,3 * hdr_stride,hdr_stride,
                          0,0,0xFFFF,toolbelt.asm_equ('PERSONA_BIT_OFFSET') + 3,
                          toolbelt.asm_equ('PERSONA_BIT_OFFSET'),slots_addr,0)
              + struct.pack('<IHHIHHHHII',skill_buffer,skill_end - skill_buffer,stride,
                            0,0,0xFFFF,toolbelt.asm_equ('SKILL_BIT_OFFSET') + 7,
                            toolbelt.asm_equ('SKILL_BIT_OFFSET'),slots_addr,0)
              + struct.pack('<IHHIHHHHII',toolbelt.asm_equ('BTLP_ITEM_FULL_ADDR'),
                            toolbelt.asm_equ('BTLP_ITEM_ROWS') * toolbelt.asm_equ('BTLP_ITEM_FULL_STRIDE'),
                            toolbelt.asm_equ('BTLP_ITEM_FULL_STRIDE'),
                            toolbelt.asm_equ('BTLP_ITEM_IDS_ADDR'),2,0x1FF,
                            toolbelt.asm_equ('BTLP_ITEM_ID_COUNT'),0,item_flags_addr,owner)
              + struct.pack('<I',0))
    def resident_bytes(address,size):
        return resident[address-slps.BASE:address-slps.BASE+size]
    if not (toolbelt.asm_equ('VWF_DATA_ADDR') <= name_table
            and name_table + len(packed) <= toolbelt.asm_equ('VWF_DATA_ADDR') + toolbelt.asm_equ('VWF_DATA_SIZE')
            and item_flags_addr <= owner < toolbelt.asm_equ('PARTY_NAME_VWF_ADDR')):
        raise SystemExit('btlfont: semantic name metadata escapes its resident owner')
    if (resident_bytes(name_table,len(packed)) != packed
            or resident_bytes(item_flags_addr,len(item_vwf_flags())) != item_vwf_flags()
            or resident_bytes(owner,1) != b'\x00'):
        raise SystemExit('btlfont: semantic name directory or item source flags mismatch')
    for address,label,delay in ((0x800ACF0C,'btl_item_owner_begin',0x27BDFFD0),
                                (0x800AD110,'btl_item_owner_commit',0x8FBF002C),
                                (0x800AD41C,'btl_item_owner_clear',0x3C0C8005)):
        expected=0x08000000 | ((symbols[label]>>2)&0x3FFFFFF)
        if struct.unpack_from('<II',built,address-base) != (expected,delay):
            raise SystemExit('btlfont: missing item producer ownership hook')
    flag_addr = symbols.get('persona_vwf_flags', 0)
    persona_flags = persona_vwf_flags()
    if not (0x800AC99C <= flag_addr and flag_addr + len(persona_flags) <= 0x800ACA44):
        raise SystemExit('btlfont: Persona source ownership bitmap escapes its owned area')
    if built[flag_addr-base:flag_addr-base+len(persona_flags)] != persona_flags:
        raise SystemExit('btlfont: Persona source ownership bitmap differs from canonical rows')
    if toolbelt.asm_equ('PERSONA_VWF_CODE_ADDR') + 48 != toolbelt.asm_equ('VWF_BTLP_CODE_ADDR'):
        raise SystemExit('btlfont: Persona registration code overlaps the next resident owner')

    # Every battle field's compressed stage-6 page must have the same glyph
    # cells as the sheet from which the existing advances were measured.
    original = Path(SRC).read_bytes()
    image = Path(OUT).read_bytes()
    offset = original.find(PREFIX)
    pages = 0
    while offset >= 0:
        raw, _ = mescodec.decode(original[offset:offset+0x4000], 0x8000)
        t = tim.parse(raw, 0)
        if (t['w'], t['h']) == (64, 128):
            current, _ = mescodec.decode(image[offset:offset+0x4000], 0x8000)
            page = tim.parse(current, 0)
            pixels = smallfont_vwf.unpack_page(current[page['at']:page['at']+128*128])
            mapping = art_mapping()[0]
            regular = smallfont_vwf.thin_page_indices()[0]
            for code, dest in mapping.items():
                x, y = dest % 31 * 8, dest // 31 * 12
                sx, sy = code % 31 * 8, code // 31 * 12
                if any(pixels[(y+j)*256+x:(y+j)*256+x+8] != regular[(sy+j)*256+sx:(sy+j)*256+sx+8]
                       for j in range(12)):
                    raise SystemExit(f'btlfont: battle page {offset:#x} lost VWF sprite {code:#x}')
            for c in required:
                x, y = c % 31 * 8, c // 31 * 12
                if any(pixels[(y+j)*256+x:(y+j)*256+x+8] != SHEET[(y+j)*256+x:(y+j)*256+x+8]
                       for j in range(12)):
                    raise SystemExit(f'btlfont: battle font page {offset:#x} differs for skill glyph {c:#x}')
            pages += 1
        offset = original.find(PREFIX, offset+1)
    if not pages:
        raise SystemExit('btlfont: no battle font pages verified')
    print(f'btlfont verify: {count} source-derived skills, {pages} battle pages, '
          f'{limit}px skill footprint, Persona max {persona_max}px and same-sector VWF bridge intact')


if __name__ == '__main__':
    {'build': main, 'verify': verify_skill_vwf}[sys.argv[1] if len(sys.argv) > 1 else 'build']()
