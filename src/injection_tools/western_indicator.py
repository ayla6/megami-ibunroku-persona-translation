"""The blinking button icon in the corner of the battle's choice menus.

Pressing the cancel key pushes a choice menu aside so the text behind it can be
read, and the corner icon says which key that is. Retail draws a Cross there.
With --qol=western the cancel key of controller TYPE 1 is Circle, so the icon
is src/assets/western/indicator.png: a 64x24 RGBA picture of the two blink
frames side by side (left plain plate, right the button; transparent where the
disc leaves it clear). It starts as the retail picture (Cross); the Circle is
painted over it by hand. `build` converts it the way the mark art is converted -
colours the retail palette already holds keep their slot, new ones take free
slots - and writes build/western_indicator.mes, which qol/western_btlp.asm lays
over the retail blob (BTLP.BIN 0x7E044, RAM 0x800E2408).

  western_indicator.py export  write indicator.png from the retail icon (only
                               when it does not exist yet)
  western_indicator.py build   indicator.png -> build/western_indicator.mes
  western_indicator.py verify  check the built blob shows the PNG and fits
"""
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import mescodec  # noqa: E402
from pngpage import RGB15, rgba_to_page  # noqa: E402

BTLP = os.path.join(ROOT, 'data', 'psx', 'BTLP.BIN')
PNG = os.path.join(ROOT, 'src', 'assets', 'western', 'indicator.png')
OUT = os.path.join(ROOT, 'build', 'western_indicator.mes')
BLOB = 0x7E044          # compressed image in BTLP.BIN
PAL = 0x200             # 256 BGR555 entries, then 64x24 8bpp pixels
W, H, FRAME = 64, 24, 32


def retail():
    with open(BTLP, 'rb') as f:
        f.seek(BLOB)
        raw, used = mescodec.decode(f.read(0x1000), PAL + W * H)
    palette = [int.from_bytes(raw[i * 2:i * 2 + 2], 'little') for i in range(256)]
    return palette, raw[PAL:], used


def export():
    """The retail picture, untouched, as the base to edit."""
    if os.path.exists(PNG):
        sys.exit(f'western_indicator: {PNG} exists; edit it instead')
    palette, px, _ = retail()
    im = Image.new('RGBA', (W, H))
    for i, v in enumerate(px):
        c = palette[v]
        im.putpixel((i % W, i // W), (0, 0, 0, 0) if c == 0 else
                    ((c & 31) << 3, ((c >> 5) & 31) << 3, ((c >> 10) & 31) << 3, 255))
    os.makedirs(os.path.dirname(PNG), exist_ok=True)
    im.save(PNG)


def convert():
    im = Image.open(PNG).convert('RGBA')
    if im.size != (W, H):
        sys.exit(f'western_indicator: {PNG} must be {W}x{H}, not {im.size[0]}x{im.size[1]}')
    palette, _, used = retail()
    pal, pix = rgba_to_page(im, palette, 'indicator.png', tool='western_indicator')
    blob = b''.join((p & RGB15).to_bytes(2, 'little') for p in pal) + pix
    data = mescodec.encode_opt(blob)
    if len(data) > used:
        sys.exit(f'western_indicator: {len(data)} compressed bytes, retail blob has {used}')
    return pal, pix, data


def build():
    data = convert()[2]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'wb') as f:
        f.write(data)


def verify():
    pal, pix, data = convert()
    with open(OUT, 'rb') as f:
        built = f.read()
    raw = mescodec.decode(built, PAL + W * H)[0]
    if raw[PAL:] != pix or built != data:
        sys.exit('western_indicator: build/western_indicator.mes does not show indicator.png')
    print(f'western_indicator: ok ({len(built)} bytes)')


if __name__ == '__main__':
    {'export': export, 'build': build, 'verify': verify}[sys.argv[1]]()
