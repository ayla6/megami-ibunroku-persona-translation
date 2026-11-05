"""Shared save-panel artwork, composed from the retail ADV frame tiles.

The title uploads shared 160x12 8bpp strips into unused UI VRAM.
ADV draws the same index map with TileMapDrawWindow/TileMapDrawBox.
No lettering is invented or redrawn here.
"""
from pathlib import Path
import struct

import tim

ROOT = Path(__file__).resolve().parents[2]
WIDTH, HEIGHT = 320, 192
COLS, ROWS = 40, 16
FRAME_TIM = 0x11CA0


def panel_map():
    top = [1, 2] + [3] * (COLS - 4) + [4, 5]
    middle = [6] + [7] * (COLS - 2) + [8]
    bottom = [9, 10] + [11] * (COLS - 4) + [12, 13]
    cells = top + middle * (ROWS - 2) + bottom
    for col in (1, 21):
        for row in range(7):
            at = (1 + row * 2) * COLS + col
            cells[at:at + 18] = [14] + [15] * 16 + [16]
            at += COLS
            cells[at:at + 18] = [20] + [21] * 16 + [22]
    return cells


def panel_pixels():
    data = (ROOT / 'data/psx/ADV/ADVCMD0.BIN').read_bytes()
    image = tim.parse(data, FRAME_TIM)
    assert image['bpp'] == 4 and image['px_w'] == 256
    packed = data[image['at']:image['end']]
    pixels = bytes(n for byte in packed for n in (byte & 15, byte >> 4))
    result = bytearray(WIDTH * HEIGHT)
    colors = struct.unpack_from('<48H', data, image['clut']['at'])
    palette = []
    for i, cell in enumerate(panel_map()):
        # FontCellsInit maps index 1 to the first 8x12 frame tile.
        u, v = ((cell - 1) % 31) * 8, ((cell - 1) // 31) * 12
        x, y = (i % COLS) * 8, (i // COLS) * 12
        for line in range(12):
            for column in range(8):
                # DrawBox's inner tiles use the second retail palette.
                color = colors[(16 if cell >= 14 else 0) + pixels[(v + line) * 256 + u + column]]
                if color not in palette:
                    palette.append(color)
                result[(y + line) * WIDTH + x + column] = palette.index(color)
    assert len(palette) <= 32
    return result, struct.pack('<32H', *(palette + [0] * (32 - len(palette))))


def build():
    pixels, palette = panel_pixels()
    out = ROOT / 'build'
    out.mkdir(exist_ok=True)
    strips, uploads = {}, []
    for col in range(2):
        for row in range(ROWS):
            half = bytes(pixels[(row * 12 + y) * WIDTH + col * 160 + x] for y in range(12) for x in range(160))
            packed = half  # 8bpp preserves both palettes without quantizing
            index = strips.setdefault(packed, len(strips))
            uploads.append((832 + col * 80, 256 + row * 12, index))
    for packed, index in strips.items():
        (out / f'qol_save_strip_{index}.bin').write_bytes(packed)
    (out / 'qol_save_panel_clut.bin').write_bytes(palette)
    # Empty saves use ADV's grey ink bank. Retain the title atlas's other
    # colors (including opaque black shadow), changing only its ink entry.
    title = (ROOT / 'data/psx/OPEN.BIN').read_bytes()
    title_font = tim.parse(title, 0x35A60)
    grey = bytearray(title[title_font['clut']['at']:title_font['clut']['at'] + 32])
    adv = (ROOT / 'data/psx/ADV/ADVCMD0.BIN').read_bytes()
    font = tim.parse(adv, 0x20)
    grey[2:4] = adv[font['clut']['at'] + 32 + 2:font['clut']['at'] + 32 + 4]
    (out / 'qol_save_grey_clut.bin').write_bytes(grey)
    original_size = (ROOT / 'data/psx/OPEN.BIN').stat().st_size
    lines = [f'.org OPEN_ADDR + {original_size:#x}', '.align 4', 'qol_save_assets_start:']
    for index in range(len(strips)):
        lines += [f'qol_save_strip_{index}:', f'    .incbin "../../build/qol_save_strip_{index}.bin"', '.align 4']
    lines += ['qol_save_panel_clut:', '    .incbin "../../build/qol_save_panel_clut.bin"',
              'qol_save_grey_clut:', '    .incbin "../../build/qol_save_grey_clut.bin"',
              'qol_save_assets_end:', '.if qol_save_assets_end > 0x801E0000',
              '    .error "save-panel assets overlap resident FONT.BIN"', '.endif']
    (out / 'qol_save_assets.asm').write_text('\n'.join(lines) + '\n')
    lines = ['qol_save_uploads:']
    for x, y, index in uploads:
        lines += [f'    .halfword {x}, {y}, 80, 12', f'    .word qol_save_strip_{index}']
    (out / 'qol_save_uploads.asm').write_text('\n'.join(lines) + '\n')
    # Crop the retail 160px cursor's cel list to the shared 144px row.
    # Keep its original cel blocks, colour, flicker and animation.
    adv = (ROOT / 'data/psx/ADV.BIN').read_bytes()
    base, at = 0x800643C4, 0x800B1E90
    cursor = ['qol_cursor_def:']
    while True:
        block = struct.unpack_from('<I', adv, at - base)[0]
        if block == 0xFFFFFFFF:
            break
        dx, dy, z, pad = struct.unpack_from('<hhHH', adv, at - base + 4)
        cols, rows, attr, w, h = struct.unpack_from('<BBHHH', adv, block - base)
        if 0 <= dx and dx + cols * w <= 144:
            cursor += [f'    .word {block:#x}', f'    .halfword {dx}, {dy}, {z}, {pad}']
        at += 12
    cursor += ['    .word -1, 0, 0, 0']
    (out / 'qol_save_cursor.asm').write_text('\n'.join(cursor) + '\n')
    print(f'save_ui: matching 320x192 panel, {len(strips)} shared 8bpp strips, both retail palettes intact')


if __name__ == '__main__':
    build()
