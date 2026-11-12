"""PNG art -> a 256-colour page for the PS1 (shared by mark.py and western_indicator.py)."""


# A CLUT halfword of 0x0000 is see-through; an opaque entry sets bit 15
# (0x8000). That is how the disc itself stores opaque black without punching
# a hole in the art, so match and write colours in the same convention.
TRANSPARENT = 0x0000
OPAQUE = 0x8000
RGB15 = 0x7FFF


def pixels(im):
    return (im.get_flattened_data() if hasattr(im, 'get_flattened_data')
            else im.getdata())


def rgb15(r, g, b):
    return (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10)


def art_colours(im):
    """One 15-bit colour per pixel, or None where the PNG is transparent."""
    return [None if a == 0 else rgb15(r, g, b) for r, g, b, a in pixels(im)]


def rgba_to_page(im, palette, name='art', tool='mark'):
    """An RGBA PNG -> (256-entry palette halfwords, pixel index bytes).

    The original palette is already full, so new colours reuse the slots of
    original entries the art no longer uses. Colours the two share keep their
    original index, so untouched pixels re-index to the same bytes. Slot 0
    belongs to transparency alone: an opaque colour that happens to match
    what the disc stores there (usually black) gets a slot of its own."""
    orig = list(palette)[:256]
    while len(orig) < 256:
        orig.append(TRANSPARENT)
    counts = {}
    for v in art_colours(im):
        if v is not None:
            counts[v] = counts.get(v, 0) + 1
    if len(counts) > 255:
        raise SystemExit(f'{tool}: {name}: {len(counts)} opaque colours, but '
                         f'palette slot 0 is the transparent key - at most '
                         f'255 fit')
    pal = orig[:]
    pal[0] = TRANSPARENT
    slot = {}
    used = set()
    for v in counts:
        for i in range(1, 256):
            if (orig[i] & RGB15) == v and i not in used:
                slot[v] = i
                used.add(i)
                break
    free = [i for i in range(1, 256) if i not in used]
    for v in counts:
        if v not in slot:
            if not free:
                raise SystemExit(f'{tool}: {name}: no free palette slot left')
            slot[v] = free.pop()       # highest free index first
        pal[slot[v]] = OPAQUE | v
    pix = bytearray()
    for v in art_colours(im):
        pix.append(0 if v is None else slot[v])
    return pal, bytes(pix)
