"""Extract original GIMs from PSP pack/end/ENDALL.BIN and make PNG previews.

Each archive entry has a 16-byte container header followed by a standalone GIM.
The `gim` command extracts those GIM bytes unchanged. PNG conversion reads the
GIM image/palette headers, follows the frame offsets, and applies the declared
NORMAL or PSPIMAGE pixel order. ENDALL text images use INDEX4 with an RGBA4444
white/alpha palette.

  python src/extraction_tools/psp/end_images.py credits /tmp/endpic    extract relevant text screens
  python src/extraction_tools/psp/end_images.py list                  entry index, offset, size, format, WxH
  python src/extraction_tools/psp/end_images.py get 25 26 92 /tmp/endpic
  python src/extraction_tools/psp/end_images.py all /tmp/endpic        extract every entry
  python src/extraction_tools/psp/end_images.py gim /tmp/endpic/gim    extract original GIM files
  python src/extraction_tools/psp/end_images.py transcript            write the text extract

The text in these images is pixels, not glyph strings, so it is TRANSCRIBED:
translation/manual/ending/ENDALL.tsv holds one row per archive entry
(entry, offset = entry offset, text with literal \n line breaks), read off
the image itself; a credits job title keeps the image's own '■' marker, and a
multi-column screen reads column by column. `transcript` writes it to
extracted_text/psp_us/pack/end/ENDALL.tsv, where every reader finds it.

Source archive exists in both regions (byte-identical layout checked for
entry geometry; pixels differ JP/US where text is baked in).
"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
NL = chr(10)

ARCH = os.path.join(ROOT, 'data', 'psp_us', 'PSP_GAME', 'USRDIR', 'pack', 'end', 'ENDALL.BIN')
CREDITS = {17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 31, 32, 92}


def entries(data=None):
    d = data if data is not None else open(ARCH, 'rb').read()
    offs = []
    j = 0
    while j + 4 <= len(d):
        v = struct.unpack_from('<I', d, j)[0]
        if j > 0 and v < offs[-1]:
            break
        offs.append(v)
        j += 4
    return d, [(offs[2 * i], offs[2 * i + 1]) for i in range(len(offs) // 2)]


def gim_header(data, a, b):
    """(GIM base, size) for the GIM inside an ENDALL container entry."""
    base = a + 0x10  # ENDALL's 16-byte entry header precedes the GIM file.
    if base + 0x10 > b or data[base:base + 11] != b'MIG.00.1PSP':
        return None
    size = struct.unpack_from('<I', data, a + 4)[0]
    if size < 0x20 or base + size > b:
        raise ValueError(f'invalid GIM size {size:#x} at archive offset {a:#x}')
    return base, size


def geometry(data, a, b):
    """(format, pixel_order, width, height) from the GIM image block."""
    header = gim_header(data, a, b)
    if header is None:
        return None
    base, _ = header
    block = base + 0x30  # third-level image block in ENDALL GIMs
    if struct.unpack_from('<H', data, block)[0] != 4:
        return None
    image = block + struct.unpack_from('<I', data, block + 0x0c)[0]
    fmt, order, w, h = struct.unpack_from('<4H', data, image + 4)
    if fmt not in (4, 5) or order not in (0, 1):
        return None
    if not (8 <= w <= 1024 and 8 <= h <= 1024):
        return None
    return fmt, order, w, h


def entry_info(data, a, b):
    """(fmt, order, w, h, bufw, start, end, palette) for indexed GIMs."""
    geo = geometry(data, a, b)
    if geo is None:
        return None
    fmt, order, w, h = geo
    base, _ = gim_header(data, a, b)
    image_block = base + 0x30
    image = image_block + struct.unpack_from('<I', data, image_block + 0x0c)[0]
    index_start, pixels_start, pixels_end = struct.unpack_from('<3I', data, image + 0x18)
    frame_start = struct.unpack_from('<I', data, image + index_start)[0]
    start = image + frame_start
    end = image + pixels_end
    height_align = struct.unpack_from('<H', data, image + 0x10)[0] or 1
    padded_h = ((h + height_align - 1) // height_align) * height_align
    if start >= end or end > b or (end - start) % padded_h:
        return None
    rowbytes = (end - start) // padded_h
    bufw = rowbytes * (2 if fmt == 4 else 1)
    if bufw < w:
        return None
    image_size = struct.unpack_from('<I', data, image_block + 4)[0]
    palette_block = image_block + image_size
    if struct.unpack_from('<H', data, palette_block)[0] != 5:
        return None
    palette = palette_block + struct.unpack_from('<I', data, palette_block + 0x0c)[0]
    palette_fmt, palette_order, _, _ = struct.unpack_from('<4H', data, palette + 4)
    if palette_fmt not in (2, 3) or palette_order not in (0, 1):
        return None
    palette_index_start, _, palette_pixels_end = struct.unpack_from('<3I', data, palette + 0x18)
    palette_frame = struct.unpack_from('<I', data, palette + palette_index_start)[0]
    palette_start = palette + palette_frame
    palette_end = palette + palette_pixels_end
    colors = 16 if fmt == 4 else 256
    color_bytes = 2 if palette_fmt == 2 else 4
    if palette_start >= palette_end or palette_start + colors * color_bytes > palette_end:
        return None
    rgba_palette = []
    for n in range(colors):
        at = palette_start + n * color_bytes
        if palette_fmt == 2:  # RGBA4444
            value = struct.unpack_from('<H', data, at)[0]
            rgba_palette.append(tuple(((value >> shift) & 0x0f) * 17 for shift in (0, 4, 8, 12)))
        else:  # RGBA8888
            rgba_palette.append(tuple(data[at:at + 4]))
    return fmt, order, w, h, bufw, start, end, rgba_palette


def unswizzle(data, w, h, bufw, t4):
    """Return indexed pixels from PSP's 16-byte x 8-row PSPIMAGE layout."""
    block_pixels = 32 if t4 else 16
    blocks_x = (bufw + block_pixels - 1) // block_pixels
    out = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            if t4:
                src = (y // 8 * blocks_x + x // 32) * 128 + (y % 8) * 16 + ((x % 32) // 2)
                v = data[src] if src < len(data) else 0
                out[y * w + x] = (v >> ((x % 2) * 4)) & 0xF
            else:
                src = (y // 8 * blocks_x + x // 16) * 128 + (y % 8) * 16 + (x % 16)
                out[y * w + x] = data[src] if src < len(data) else 0
    return bytes(out)


def render(data, a, b, info):
    from PIL import Image
    fmt, order, w, h, bufw, start, end, palette = info
    raw = data[start:end]
    t4 = fmt == 4
    if order == 1:
        indices = unswizzle(raw, w, h, bufw, t4)
    else:
        indices = bytearray(w * h)
        rowbytes = (bufw + 1) // 2 if t4 else bufw
        for y in range(h):
            for x in range(w):
                value = raw[y * rowbytes + x // 2] if t4 else raw[y * rowbytes + x]
                indices[y * w + x] = (value >> ((x % 2) * 4)) & 0x0f if t4 else value
    rgba = bytearray(w * h * 4)
    for i, index in enumerate(indices):
        rgba[i * 4:i * 4 + 4] = bytes(palette[index])
    return Image.frombytes('RGBA', (w, h), bytes(rgba))


def original_gim(data, a, b):
    """Return the standalone GIM bytes stored in one archive entry."""
    header = gim_header(data, a, b)
    if header is None:
        return None
    base, size = header
    return data[base:base + size]


def cmd_list():
    d, ents = entries()
    for i, (a, b) in enumerate(ents):
        info = entry_info(d, a, b)
        summary = None if info is None else (*info[:7], f'{len(info[7])} colors')
        print(f'{i}\t{a:#x}\t{b - a:#x}\t{summary}')


def cmd_all(outdir, only=None):
    os.makedirs(outdir, exist_ok=True)
    d, ents = entries()
    n = 0
    for i, (a, b) in enumerate(ents):
        if only is not None and i not in only:
            continue
        info = entry_info(d, a, b)
        if info is None:
            print(f'{i}: no geometry')
            continue
        img = render(d, a, b, info)
        if img is None:
            print(f'{i}: short payload')
            continue
        _, _, w, h, _, _, _, _ = info
        img.save(os.path.join(outdir, f'end{i:03d}_{w}x{h}.png'))
        n += 1
    print(f'{n} images -> {outdir}')


def cmd_gim(outdir, only=None):
    """Extract exact embedded GIM files without decoding or altering pixels."""
    os.makedirs(outdir, exist_ok=True)
    d, ents = entries()
    n = 0
    for i, (a, b) in enumerate(ents):
        if only is not None and i not in only:
            continue
        raw = original_gim(d, a, b)
        if raw is None:
            continue
        path = os.path.join(outdir, f'end{i:03d}.gim')
        with open(path, 'wb') as f:
            f.write(raw)
        n += 1
    print(f'{n} original GIM files -> {outdir}')


TRANSCRIPT = os.path.join(ROOT, 'translation', 'manual', 'ending', 'ENDALL.tsv')


def cmd_transcript():
    sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
    import strlib
    import toolbelt
    rows = strlib.tsv_rows(TRANSCRIPT, required=('entry', 'offset', 'text'))
    toolbelt.write_extracted('psp_us', 'pack/end/ENDALL',
                             [{'entry': r['entry'], 'box': '0', 'pos': r['offset'],
                               'text': r['text']} for r in rows])
    print(f'{len(rows)} transcribed ENDALL entries -> extracted_text/psp_us/pack/end/ENDALL.tsv')


if __name__ == '__main__':
    a = sys.argv[1:] or ['list']
    if a[0] == 'list':
        cmd_list()
    elif a[0] == 'all':
        cmd_all(a[1] if len(a) > 1 else '/tmp/opencode/endpic')
    elif a[0] == 'get':
        nums = [int(x) for x in a[1:] if x.isdigit()]
        rest = [x for x in a[1:] if not x.isdigit()]
        cmd_all(rest[0] if rest else '/tmp/endpic', set(nums))
    elif a[0] == 'credits':
        cmd_all(a[1] if len(a) > 1 else '/tmp/endpic', CREDITS)
    elif a[0] == 'transcript':
        cmd_transcript()
    elif a[0] == 'gim':
        nums = [int(x) for x in a[1:] if x.isdigit()]
        rest = [x for x in a[1:] if not x.isdigit()]
        cmd_gim(rest[0] if rest else '/tmp/opencode/endpic/original_gim', set(nums) if nums else None)
    else:
        raise SystemExit(__doc__)
