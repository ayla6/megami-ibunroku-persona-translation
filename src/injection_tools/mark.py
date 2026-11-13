"""Mark QoL patch: swap Mark (and his mother) for edited art.

The Revelations: Persona disc ships a redesigned Mark; Atlus USA never
redesigned the people around him, so his mother - an NPC in the Mikage Sun
Mall boutique - ships as the original Japanese art even on the US disc. The
user edits the exported PNGs, and this patch installs them behind
--qol=mark. Three homes:

  ADV/BST.BIN   the dialogue / status headshot: 80 fixed 5-sector slots, one
                8bpp 88x96 TIM each (scene kind 3, BST_SECTORS 5). Slot 2 is
                Mark. The swap is in place, same size.
  ADV/MES.BIN   the isometric-room walk sheets: 256 packed entries, each an
                8-byte header, a word table and up to eight 8bpp 128x250 TIM
                pages uploaded to the VRAM row at y 0x100. Mark's sheet
                (entry 11 member 1 on both discs) is byte-identical in every
                scene that carries it, so the patch re-encodes exactly the
                entries that hold it and rebuilds the sector table around
                any span that no longer fits. His mother's sheet (entry 18
                member 4, the Rosa Candida boutique; MES_SCENE 18 in the E2
                room script) lives in that one entry only.
  B/P.BIN       the battle sprite sheets. A party member's entry starts with
                a 12-byte header and an 8bpp 128x250 TIM at +0x0C; the
                sectors each entry occupies are listed by the table
                 g_btl_member_file in BTLP.BIN. Mark is member 5; entry 15
                 supplies his gun-action sheet. The patch reads the table,
                 swaps both entries' palettes and pixels in place, and leaves
                the model data after the TIM untouched.

  python src/injection_tools/mark.py export <tree> <outdir> [--suffix S]
          regenerate the reference PNGs (headshot, battle sheets and walk
          sheets) from an extracted disc tree, e.g. data/psx or the
          Revelations tree. Files are written as <name><suffix>.png - the
          plain names in src/assets/mark/black are the user's edits and are
          never written by an export; pass --suffix _revelations to refresh
          the pristine Revelations exports beside them.
  python src/injection_tools/mark.py build [--art DIR]
          write build/ADV/BST.BIN, build/ADV/MES.BIN and build/B/P.BIN
          with the art from src/assets/mark/black (or --art DIR). Run by
          build.py ONLY for --qol=mark.
  python src/injection_tools/mark.py retail
          remove build/ADV/BST.BIN, build/ADV/MES.BIN and build/B/P.BIN so
          the disc falls back to the originals. Run by build.py whenever
          mark is NOT selected: a build must never inherit a previous mark
          swap from build/.
  python src/injection_tools/mark.py verify [--art DIR]
          decode the built files back and check every swapped slot.

The re-encoded MES.BIN is the slow part (a pure-Python encoder over every
scene that carries a sheet). It depends only on the retail MES.BIN, the
walk-sheet art and this tool's code, so build keeps it in
build/.step-cache/mark-mes.bin keyed by the SHA-1 of exactly those files
(build_step_cache.fingerprint); a hit is checked against the recorded SHA-1
of the cached bytes. verify skips the MES decode when build/ADV/MES.BIN is
byte-identical to a cached copy it already verified under the same key.
Deleting build/.step-cache drops the cache.

Art rules: same pixel size as the export. Alpha 0 is palette slot 0, the PS1
transparent key; an opaque pixel never shares that slot, so opaque black does
not become a hole. Slot 0 is reserved for transparency, so the art may use at
most 255 opaque colours. Unchanged colours keep their original palette slots;
new colours are appended.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import os
import struct
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mescodec  # noqa: E402
import tim as timcodec  # noqa: E402
from pngpage import (OPAQUE, RGB15, TRANSPARENT, art_colours, pixels, rgb15,  # noqa: E402,F401
                     rgba_to_page)

# The scene entry / member that ships each walk sheet (established by
# rendering the pages and identifying them), and Mark's BST.BIN face slot.
# Asset indices into the original disc data, not name tables.
MES_SHEETS = [
    # (art file name, MES entry, MES member)
    ('walk.png',   11, 1),         # Mark, byte-identical in every scene that carries it
    ('walk_variant.png', 187, 3),   # alternate scene sheet
    ('mother.png', 18, 4),         # Mark's mother, Rosa Candida boutique only
]
BST_FACE = 2
# The portrait TIM immediately following Mark's mapped ending text page.
ENDING_PORTRAIT = 0xA7804

# The battle sprite sheet lives in the party member's own entry in B/P.BIN.
# The entry starts with three words (TIM address, model start, model end) and
# the TIM begins right after them. The sector offsets are read from
# g_btl_member_file in BTLP.BIN, not typed in.
BATTLE_MEMBER = 5                      # Mark, confirmed against the sheets
BATTLE_GUN_MEMBER = BATTLE_MEMBER + 10  # battle's gun-action reload
BATTLE_TIM_HEADER = 0x0C
BATTLE_SPANS = 20                      # 20 entries plus the end offset
BATTLE_SPAN_MIN = 5
BATTLE_SPAN_MAX = 60

MES_LIMIT = 0x3F900                    # the game's own decode limit (MES_SIZE)
MES_CACHE = os.path.join(ROOT, 'build', '.step-cache', 'mark-mes.bin')
MES_CACHE_TSV = os.path.join(ROOT, 'build', '.step-cache', 'mark-mes.tsv')
BST_SLOT_SIZE = 0x2800


def src_path(*parts):
    return os.path.join(ROOT, *parts)


# ---------------------------------------------------------------------------
# TIM pages inside the decoded MES blobs / BST slots

def parse_tim(blob, off):
    """-> dict describing the TIM at `off` (8bpp pages are what we swap)."""
    flag = struct.unpack_from('<I', blob, off + 4)[0]
    p = off + 8
    clut = None
    if flag & 8:
        bl, cx, cy, cw, ch = struct.unpack_from('<IHHHH', blob, p)
        clut = dict(at=p + 12, n=cw * ch, x=cx, y=cy)
        p += bl
    bl, px, py, pw, ph = struct.unpack_from('<IHHHH', blob, p)
    bpp = {0: 4, 1: 8, 2: 16}[flag & 3]
    px_w = pw * (4 if bpp == 4 else 2 if bpp == 8 else 1)
    return dict(bpp=bpp, px_w=px_w, h=ph, pix_at=p + 12, pix_len=bl - 12,
                clut=clut, px_x=px, px_y=py, tim_off=off,
                flag=flag, px_halfwords=pw)


def clut_rgb15(blob, tim):
    """The page's palette as RGB555 halfwords."""
    c = tim['clut']
    return list(struct.unpack_from('<%dH' % c['n'], blob, c['at']))


def page_pixels(blob, tim):
    return blob[tim['pix_at']:tim['pix_at'] + tim['pix_len']]


def page_image(blob, tim):
    pal = clut_rgb15(blob, tim)
    raw = page_pixels(blob, tim)
    w, h = tim['px_w'], tim['h']
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    px = im.load()
    for i, c in enumerate(raw):
        v = pal[c]
        r, g, b = (v & 31) << 3, ((v >> 5) & 31) << 3, ((v >> 10) & 31) << 3
        px[i % w, i // w] = (0, 0, 0, 0) if c == 0 else (r | r >> 5, g | g >> 5, b | b >> 5, 255)
    return im


def ending_image(blob):
    """Export the ending portrait's full-colour PS1 pixels as RGB."""
    t = timcodec.parse(blob, ENDING_PORTRAIT)
    if t['bpp'] != 16 or (t['px_w'], t['h']) != (149, 208):
        raise SystemExit('mark: unexpected ending portrait TIM')
    raw = blob[t['at']:t['end']]
    values = struct.unpack('<%dH' % (t['px_w'] * t['h']), raw)
    rgb = bytearray()
    for v in values:
        for shift in (0, 5, 10):
            c = (v >> shift) & 31
            rgb.append((c << 3) | (c >> 2))
    return Image.frombytes('RGB', (t['px_w'], t['h']), bytes(rgb))


def ending_swap(blob, art):
    """Replace portrait colours, preserving each retail PS1 high bit."""
    t = timcodec.parse(blob, ENDING_PORTRAIT)
    if t['bpp'] != 16 or art.size != (t['px_w'], t['h']):
        raise SystemExit('mark: ending portrait dimensions or format mismatch')
    values = struct.unpack('<%dH' % (t['px_w'] * t['h']), blob[t['at']:t['end']])
    out = bytearray(blob)
    converted = []
    for original, (r, g, b, a) in zip(values, pixels(art.convert('RGBA'))):
        if a != 255:
            raise SystemExit('mark: ending portrait must be fully opaque')
        converted.append((original & 0x8000) | rgb15(r, g, b))
    struct.pack_into('<%dH' % len(converted), out, t['at'], *converted)
    return bytes(out)


def page_shows_art(pix, pal, art):
    """Pixel positions of a decoded page that do not show the art.

    Compares displayed colours, not palette indices, so an opaque colour
    that landed on the transparent key shows up here as a hole."""
    want = art_colours(art)
    bad = []
    for k, idx in enumerate(pix[:len(want)]):
        got = None if idx == 0 else (pal[idx] & RGB15)
        if got != want[k]:
            bad.append(k)
            if len(bad) >= 8:
                break
    return bad


def build_tim(blob, tim, pal, pix):
    """The TIM at tim['tim_off'] rebuilt with a new palette and pixels."""
    out = bytearray(blob)
    c = tim['clut']
    struct.pack_into('<%dH' % len(pal), out, c['at'], *pal)
    out[tim['pix_at']:tim['pix_at'] + tim['pix_len']] = pix
    return bytes(out)


# ---------------------------------------------------------------------------
# BST.BIN - the headshot slot, fixed size, swapped in place

def bst_face_slot(entry):
    return 0x800 + entry * BST_SLOT_SIZE


def bst_swap(bst, art):
    off = bst_face_slot(BST_FACE) + 8
    tim = parse_tim(bst, off)
    if tim['bpp'] != 8 or (tim['px_w'], tim['h']) != (art.width, art.height):
        raise SystemExit(f'mark: BST face {BST_FACE}: expected 8bpp '
                         f'{tim["px_w"]}x{tim["h"]}, PNG is {art.size}')
    pal, pix = rgba_to_page(art, clut_rgb15(bst, tim))
    if len(pix) != tim['pix_len']:
        raise SystemExit('mark: BST face pixel length mismatch')
    return build_tim(bst, tim, pal, pix)


# ---------------------------------------------------------------------------
# B/P.BIN - the party's battle sprite sheets, swapped in place

def battle_member_sectors(btlp, sectors):
    """The sector offsets of the party entries in B/P.BIN.

    g_btl_member_file is a u16 table in BTLP.BIN: 20 entry starts, the end
    of the last entry, then a zero. Each entry's extent is the pair of
    offsets either side of it, which is what the battle's loader reads. The
    table is found by its shape, so no address or disc revision is typed in.
    """
    found = []
    for off in range(0, len(btlp) - 43, 2):
        v = struct.unpack_from('<22H', btlp, off)
        if (v[0] <= 3 and v[BATTLE_SPANS] == sectors
                and v[BATTLE_SPANS + 1] == 0
                and all(BATTLE_SPAN_MIN <= v[i + 1] - v[i] <= BATTLE_SPAN_MAX
                        for i in range(BATTLE_SPANS))):
            found.append(v[:BATTLE_SPANS + 1])
    if len(found) != 1:
        raise SystemExit(f'mark: expected one battle member table in '
                         f'BTLP.BIN, found {len(found)}')
    return found[0]


def battle_entry_offset(pbin, btlp, member=BATTLE_MEMBER):
    sectors = len(pbin) // 2048
    table = battle_member_sectors(btlp, sectors)
    return table[member] * 2048


def battle_tim(pbin, btlp, member=BATTLE_MEMBER):
    """A party member's TIM inside their B/P.BIN entry."""
    off = battle_entry_offset(pbin, btlp, member) + BATTLE_TIM_HEADER
    # The disc reuses the top half of the TIM's magic word for the palette
    # length; memberload zeroes it before the upload. Only the low half is
    # the TIM magic here.
    if (off + 8 > len(pbin)
            or struct.unpack_from('<H', pbin, off)[0] != 0x10):
        raise SystemExit(f'mark: battle member {member} has no TIM at '
                         f'entry + {BATTLE_TIM_HEADER:#x}')
    tim = parse_tim(pbin, off)
    if tim['bpp'] != 8:
        raise SystemExit(f'mark: battle member {member} TIM is '
                         f'{tim["bpp"]}bpp, expected 8bpp')
    return tim


def battle_image(pbin, btlp, member=BATTLE_MEMBER):
    return page_image(pbin, battle_tim(pbin, btlp, member))


def battle_swap(pbin, btlp, art, member=BATTLE_MEMBER, name='battle.png'):
    """Rebuild a battle sheet in place (same entry, same TIM size)."""
    tim = battle_tim(pbin, btlp, member)
    if (tim['px_w'], tim['h']) != art.size:
        raise SystemExit(f'mark: battle member {member}: expected '
                         f'8bpp {tim["px_w"]}x{tim["h"]}, PNG is {art.size}')
    pal, pix = rgba_to_page(art, clut_rgb15(pbin, tim), name=name)
    if len(pix) != tim['pix_len']:
        raise SystemExit('mark: battle sheet pixel length mismatch')
    return build_tim(pbin, tim, pal, pix)


# ---------------------------------------------------------------------------
# MES.BIN - packed scene entries, rebuilt around the swapped pages

def mes_entries(mes):
    return struct.unpack('<257H', mes[:514])


def mes_blob(mes, i):
    t = mes_entries(mes)
    return mescodec.decode(mes[t[i] * 2048:t[i + 1] * 2048][8:], MES_LIMIT)[0]


def mes_members(blob):
    """(offset, tim) for each 8bpp page the entry's word table lists."""
    out = []
    for k in range(8):
        v = struct.unpack_from('<I', blob, k * 4)[0]
        if v == 0 or v >= len(blob):
            break
        tim = parse_tim(blob, v)
        if tim['bpp'] == 8:
            out.append((v, tim))
    return out


def page_hash(blob, tim):
    return hashlib.sha1(page_pixels(blob, tim)).hexdigest()


def encode(blob):
    """Greedy encoder for the MES token stream (mescodec.decode round-trips it).

    Hash-chained back-references (distance <= 0x400, length <= 33; the 33/1
    combination would spell the 7F FF end marker and is clamped), zero runs,
    same-byte fills, 00,x pairs and literal runs; ends with 7F FF.
    """
    n = len(blob)
    out = bytearray()
    prev = [-1] * (n + 1)              # last position with the same 3 bytes
    last3 = {}
    for i in range(n - 2):
        k = bytes(blob[i:i + 3])
        prev[i] = last3.get(k, -1)
        last3[k] = i
    lit = bytearray()

    def flush():
        while lit:
            c = min(32, len(lit))
            out.append(0x80 | (c - 1))
            out.extend(lit[:c])
            del lit[:c]

    i = 0
    while i < n:
        z = 0
        while z < 0xFF + 0x20 and blob[i + z:i + z + 1] == b'\x00':
            z += 1
        r = 1
        while r < 33 and blob[i + r:i + r + 1] == blob[i:i + 1]:
            r += 1
        emit = None
        if z >= 2:
            emit = ('Z', z)
        elif r >= 3:
            emit = ('R', r)
        else:
            # Zero/fill tokens always win above, so matching them could not
            # affect the chosen output. Search only when a copy can win.
            best_len, best_dist = 0, 0
            if i + 2 < n - 2:
                j = prev[i]
                hops = 0
                cap = min(33, n - i)
                while 0 <= j and i - j <= 0x400 and hops < 16:
                    hops += 1
                    l = 3
                    while l < cap and blob[j + l] == blob[i + l]:
                        l += 1
                    if l > best_len:
                        best_len, best_dist = l, i - j
                    j = prev[j]
            if best_len == 33 and best_dist == 1:
                best_len = 32          # (33, 1) would encode as 7F FF
            if best_len >= 4:
                emit = ('B', best_len, best_dist)
            elif z == 1 and i + 3 < n:
                k = 0
                while k < 32 and i + 2 * k + 1 < n and blob[i + 2 * k:i + 2 * k + 1] == b'\x00':
                    k += 1
                if k >= 2:
                    emit = ('P', k)
        if emit is None:
            lit.append(blob[i])
            i += 1
            if len(lit) == 32:
                flush()
            continue
        flush()
        kind = emit[0]
        if kind == 'Z':
            L = emit[1]
            if L < 32:
                out.append(0xE0 | (L - 1))
            else:
                out += bytes((0xFF, L - 0x20))
            i += L
        elif kind == 'R':
            out += bytes((0xC0 | (emit[1] - 2), blob[i]))
            i += emit[1]
        elif kind == 'P':
            k = emit[1]
            out.append(0xA0 | (k - 1))
            out.extend(blob[i + 1:i + 2 * k:2])
            i += 2 * k
        else:
            L, d = emit[1], emit[2]
            f = 0x400 - d
            out.append(((L - 2) << 2) | (f >> 8))
            out.append(f & 0xFF)
            i += L
    flush()
    out += b'\x7f\xff'
    check, _ = mescodec.decode(bytes(out), n)
    if check != bytes(blob):
        raise SystemExit('mark: encoder round-trip failed')
    return bytes(out)


def mes_swap(mes, sheet_hashes, arts):
    """Replace every page matching one of sheet_hashes with its art.

    sheet_hashes: {hash: art file name}; arts: {art file name: PIL image}.
    -> (new MES.BIN bytes, list of re-encoded entry indexes)."""
    t = mes_entries(mes)
    pieces = []
    changed = []
    jobs = []
    palette_cache = {}
    print('mark: scanning 256 scene entries...', flush=True)
    for i in range(256):
        a = t[i] * 2048
        if a == 0:
            break
        b = t[i + 1] * 2048
        raw = mes[a:b]
        blob = mescodec.decode(raw[8:], MES_LIMIT)[0]
        hits = [(tim, sheet_hashes[page_hash(blob, tim)])
                for _, tim in mes_members(blob)
                if page_hash(blob, tim) in sheet_hashes]
        if not hits:
            pieces.append(raw)
            continue
        new = blob
        for tim, art_name in hits:
            key = (art_name, tuple(clut_rgb15(blob, tim)))
            if key not in palette_cache:
                palette_cache[key] = rgba_to_page(arts[art_name], key[1], name=art_name)
            pal, pix = palette_cache[key]
            if len(pix) != tim['pix_len']:
                raise SystemExit(f'mark: {art_name} page pixel length mismatch')
            new = build_tim(new, tim, pal, pix)
        pieces.append(raw[:8])
        jobs.append((i, new))
        changed.append(i)
    if not changed:
        return mes, changed

    workers = min(4, os.cpu_count() or 1, len(jobs))
    print(f'mark: encoding {len(jobs)} scene entries using {workers} workers...', flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(encode, blob): i for i, blob in jobs}
        for done, future in enumerate(as_completed(pending), 1):
            i = pending[future]
            pieces[i] += future.result()
            if done % 10 == 0 or done == len(jobs):
                print(f'mark: encoded {done}/{len(jobs)} scene entries', flush=True)

    # the table lives in the head before the first entry's sector
    head = mes[:t[0] * 2048]

    # spans: keep each entry's own if the new stream fits (then no other
    # entry moves), otherwise lay every entry out again, same order.
    fits = all(len(p) <= (t[i + 1] - t[i]) * 2048
               for i, p in zip(changed, (pieces[i] for i in changed)))
    if fits:
        body = bytearray()
        for i, piece in enumerate(pieces):
            if i in changed:
                span = (t[i + 1] - t[i]) * 2048
                piece = piece + b'\x00' * (span - len(piece))
            body += piece
        return head + bytes(body), changed

    starts = []
    cur = t[0]
    for i, piece in enumerate(pieces):
        starts.append(cur)
        cur += (len(piece) + 2047) // 2048
    starts.append(cur)
    tab = struct.pack('<257H', *starts)
    body = bytearray()
    for i, piece in enumerate(pieces):
        body += piece
        body += b'\x00' * (starts[i + 1] * 2048 - starts[i] * 2048 - len(piece))
    return tab + mes[514:t[0] * 2048] + bytes(body), changed


# ---------------------------------------------------------------------------
# commands

def load_art(dirpath):
    """The user's edits. A missing file is a hard error naming it: the patch
    must never quietly ship unedited art."""
    names = ['headshot.png', 'battle.png', 'battle_gun.png', 'ending.png'] + [name for name, _, _ in MES_SHEETS]
    for name in names:
        if not os.path.exists(src_path(dirpath, name)):
            raise SystemExit(f'mark: {dirpath}/{name} is missing - that plain '
                             f'name is the edited art the patch installs; '
                             f'pristine exports live beside it as '
                             f'<name>_revelations.png')
    def load(name):
        im = Image.open(src_path(dirpath, name)).convert('RGBA')
        partial = sum(1 for r, g, b, a in pixels(im) if 0 < a < 255)
        if partial:
            print(f'mark: {name}: {partial} partly transparent pixels will be '
                  f'installed as opaque (the PS1 has no per-pixel alpha)',
                  file=sys.stderr)
        return im

    return (load('headshot.png'), load('battle.png'), load('battle_gun.png'), load('ending.png'),
            {name: load(name) for name, _, _ in MES_SHEETS})


def sheet_targets(mes, arts):
    """{original page hash: art name} for every sheet, from the original disc."""
    targets = {}
    for name, entry, member in MES_SHEETS:
        blob = mes_blob(mes, entry)
        tim = mes_members(blob)[member][1]
        targets[page_hash(blob, tim)] = name
    return targets


def mes_cache_key(artdir):
    """Fingerprint of everything the re-encoded MES.BIN depends on."""
    import build_step_cache
    tools = os.path.dirname(os.path.abspath(__file__))
    return build_step_cache.fingerprint(
        [src_path('data', 'psx', 'ADV', 'MES.BIN')]
        + [src_path(artdir, name) for name, _, _ in MES_SHEETS]
        + [os.path.join(tools, name) for name in ('mark.py', 'mescodec.py', 'pngpage.py',
                                                  'tim.py', 'build_step_cache.py')])


def mes_cache_read():
    """{'key', 'sha1', 'changed', 'verified'} from the cache record, or {}."""
    try:
        with open(MES_CACHE_TSV, encoding='utf-8') as f:
            rows = [line.rstrip('\n').split('\t') for line in f]
    except OSError:
        return {}
    if not rows or rows[0] != ['field', 'value'] or any(len(r) != 2 for r in rows):
        return {}
    return dict(rows[1:])


def mes_cache_write(record):
    os.makedirs(os.path.dirname(MES_CACHE_TSV), exist_ok=True)
    tmp = MES_CACHE_TSV + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('field\tvalue\n')
        for field in ('key', 'sha1', 'changed', 'verified'):
            f.write(f'{field}\t{record[field]}\n')
    os.replace(tmp, MES_CACHE_TSV)


def mes_cached(key):
    """(bytes, changed count) of the cached MES.BIN for key, or None."""
    record = mes_cache_read()
    if record.get('key') != key:
        return None
    try:
        data = open(MES_CACHE, 'rb').read()
    except OSError:
        return None
    if hashlib.sha1(data).hexdigest() != record.get('sha1'):
        return None
    return data, int(record['changed'])


def cmd_export(tree, outdir, suffix=''):
    names = ['headshot.png', 'battle.png', 'battle_gun.png', 'ending.png'] + [name for name, _, _ in MES_SHEETS]
    paths = [os.path.join(outdir, os.path.splitext(name)[0] + suffix + '.png')
             for name in names]
    existing = [path for path in paths if os.path.exists(path)]
    if existing:
        raise SystemExit('mark export: refusing to overwrite existing files: ' + ', '.join(existing))
    mes = open(os.path.join(tree, 'ADV', 'MES.BIN'), 'rb').read()
    bst = open(os.path.join(tree, 'ADV', 'BST.BIN'), 'rb').read()
    pbin = open(os.path.join(tree, 'B', 'P.BIN'), 'rb').read()
    btlp = open(os.path.join(tree, 'BTLP.BIN'), 'rb').read()
    ending = open(os.path.join(tree, 'EXE', 'END.BIN'), 'rb').read()
    os.makedirs(outdir, exist_ok=True)
    tim = parse_tim(bst, bst_face_slot(BST_FACE) + 8)
    page_image(bst, tim).save(os.path.join(outdir, 'headshot%s.png' % suffix))
    battle_image(pbin, btlp).save(os.path.join(outdir, 'battle%s.png' % suffix))
    battle_image(pbin, btlp, BATTLE_GUN_MEMBER).save(
        os.path.join(outdir, 'battle_gun%s.png' % suffix))
    ending_image(ending).save(os.path.join(outdir, 'ending%s.png' % suffix))
    for name, entry, member in MES_SHEETS:
        blob = mes_blob(mes, entry)
        tim = mes_members(blob)[member][1]
        page_image(blob, tim).save(os.path.join(outdir, '%s%s.png' % (os.path.splitext(name)[0], suffix)))
    print(f'mark export: BST face {BST_FACE}, B/P.BIN members {BATTLE_MEMBER} and {BATTLE_GUN_MEMBER} '
          f'and {len(MES_SHEETS)} walk sheets -> {outdir}/{{headshot,battle,battle_gun,ending'
          + ''.join(',' + os.path.splitext(n)[0] for n, _, _ in MES_SHEETS)
          + '}' + suffix + '.png')


def cmd_build(artdir):
    mes = open(src_path('data', 'psx', 'ADV', 'MES.BIN'), 'rb').read()
    bst = open(src_path('data', 'psx', 'ADV', 'BST.BIN'), 'rb').read()
    pbin = open(src_path('data', 'psx', 'B', 'P.BIN'), 'rb').read()
    btlp = open(src_path('data', 'psx', 'BTLP.BIN'), 'rb').read()
    head, battle, battle_gun, ending_art, arts = load_art(artdir)
    # the sheets' identity comes from the original disc: whether the build
    # starts from the originals or from an earlier patched copy, the pages
    # to replace are the ones that match what the disc shipped
    targets = sheet_targets(mes, arts)

    bst2 = bst_swap(bst, head)
    pbin2 = battle_swap(pbin, btlp, battle)
    pbin2 = battle_swap(pbin2, btlp, battle_gun, BATTLE_GUN_MEMBER, 'battle_gun.png')
    key = mes_cache_key(artdir)
    cached = mes_cached(key)
    if cached:
        mes2, count = cached
        print(f'mark: walk sheets unchanged; using the cached MES.BIN ({count} entries)', flush=True)
    else:
        mes2, changed = mes_swap(mes, targets, arts)
        count = len(changed)
        if mes_cache_key(artdir) == key:          # no input moved while encoding
            # bytes first, then the record that vouches for them
            os.makedirs(os.path.dirname(MES_CACHE), exist_ok=True)
            open(MES_CACHE + '.tmp', 'wb').write(mes2)
            os.replace(MES_CACHE + '.tmp', MES_CACHE)
            mes_cache_write({'key': key, 'sha1': hashlib.sha1(mes2).hexdigest(),
                             'changed': count, 'verified': 0})
    ending_path = src_path('build', 'EXE', 'END.BIN')
    ending = open(ending_path, 'rb').read()
    ending2 = ending_swap(ending, ending_art)
    os.makedirs(src_path('build', 'ADV'), exist_ok=True)
    os.makedirs(src_path('build', 'B'), exist_ok=True)
    open(src_path('build', 'ADV', 'MES.BIN'), 'wb').write(mes2)
    open(src_path('build', 'ADV', 'BST.BIN'), 'wb').write(bst2)
    open(src_path('build', 'B', 'P.BIN'), 'wb').write(pbin2)
    open(ending_path, 'wb').write(ending2)
    print(f'mark build: BST face {BST_FACE} and battle members {BATTLE_MEMBER}, {BATTLE_GUN_MEMBER} '
          f'swapped; {count} MES entries re-encoded '
          f'(MES.BIN {len(mes)} -> {len(mes2)} bytes)')


def cmd_retail():
    """The build runs this whenever mark is NOT selected: the disc builder
    reads whatever is in build/, so a leftover swap must not survive into a
    build that never asked for it."""
    removed = False
    for parts in (('ADV', 'MES.BIN'), ('ADV', 'BST.BIN'), ('B', 'P.BIN')):
        p = src_path('build', *parts)
        if os.path.exists(p):
            os.remove(p)
            removed = True
    # END.BIN also contains translated text: restore just the retail portrait,
    # leaving every translated page intact when switching build variants.
    ending_path = src_path('build', 'EXE', 'END.BIN')
    if os.path.exists(ending_path):
        with open(src_path('data', 'psx', 'EXE', 'END.BIN'), 'rb') as source:
            original = source.read()
        with open(ending_path, 'rb') as source:
            current = bytearray(source.read())
        t = timcodec.parse(original, ENDING_PORTRAIT)
        current[t['at']:t['end']] = original[t['at']:t['end']]
        with open(ending_path, 'wb') as output:
            output.write(current)
    print('mark retail: build/ADV swap files ' + ('removed' if removed else 'absent'))


def cmd_verify(artdir):
    head, battle, battle_gun, ending_art, arts = load_art(artdir)
    ok = True
    bst = open(src_path('build', 'ADV', 'BST.BIN'), 'rb').read()
    tim = parse_tim(bst, bst_face_slot(BST_FACE) + 8)
    bad = page_shows_art(page_pixels(bst, tim), clut_rgb15(bst, tim), head)
    if bad:
        print(f'BST face: pixels {bad} do not show the headshot')
    print('BST face', 'ok' if not bad else 'MISMATCH')
    ok &= not bad

    ending = open(src_path('build', 'EXE', 'END.BIN'), 'rb').read()
    expected = ending_swap(ending, ending_art)
    t = timcodec.parse(ending, ENDING_PORTRAIT)
    ending_ok = ending[t['at']:t['end']] == expected[t['at']:t['end']]
    print('ending portrait', 'ok' if ending_ok else 'MISMATCH')
    ok &= ending_ok

    pbin = open(src_path('build', 'B', 'P.BIN'), 'rb').read()
    btlp = open(src_path('data', 'psx', 'BTLP.BIN'), 'rb').read()
    for member, art in ((BATTLE_MEMBER, battle), (BATTLE_GUN_MEMBER, battle_gun)):
        tim = battle_tim(pbin, btlp, member)
        bad = page_shows_art(page_pixels(pbin, tim), clut_rgb15(pbin, tim), art)
        if bad:
            print(f'battle member {member}: pixels {bad} do not show the sheet')
        print(f'battle member {member}', 'ok' if not bad else 'MISMATCH')
        ok &= not bad

    mes2 = open(src_path('build', 'ADV', 'MES.BIN'), 'rb').read()
    key = mes_cache_key(artdir)
    record = mes_cache_read()
    built_sha1 = hashlib.sha1(mes2).hexdigest()
    if (record.get('key') == key and record.get('sha1') == built_sha1
            and record.get('verified') == '1'):
        print('MES: identical to the cached build verified earlier')
        if not ok:
            raise SystemExit(1)
        return
    orig = open(src_path('data', 'psx', 'ADV', 'MES.BIN'), 'rb').read()
    targets = sheet_targets(orig, arts)
    t = mes_entries(orig)
    t2 = mes_entries(mes2)
    bad = missed = untouched = 0
    for i in range(256):
        if t[i] == 0 or t[i] == t[i + 1]:
            continue
        blob = mescodec.decode(orig[t[i] * 2048:t[i + 1] * 2048][8:], MES_LIMIT)[0]
        blob2 = mescodec.decode(mes2[t2[i] * 2048:t2[i + 1] * 2048][8:], MES_LIMIT)[0]
        hit_names = {page_hash(blob, tm): targets[page_hash(blob, tm)]
                     for _, tm in mes_members(blob)
                     if page_hash(blob, tm) in targets}
        if not hit_names:
            if orig[t[i] * 2048:t[i + 1] * 2048] == mes2[t2[i] * 2048:t2[i + 1] * 2048]:
                untouched += 1
            else:
                bad += 1
            continue
        # every page the original shipped as a target must now carry its art
        # (mapped into that page's own palette); the game's decode limit clips
        # entry tails, so a prefix match counts
        for name in hit_names.values():
            if not any(not page_shows_art(page_pixels(blob2, tm),
                                         clut_rgb15(blob2, tm), arts[name])
                       for _, tm in mes_members(blob2)):
                missed += 1
                print(f'MES entry {i}: {name} art missing')
    print(f'MES: {untouched} entries untouched, {missed} missing the art, '
          f'{bad} wrongly modified (entry tails clipped by the game\'s own '
          f'decode limit count as matching)')
    ok &= missed == 0 and bad == 0
    if not ok:
        raise SystemExit(1)
    if record.get('key') == key and record.get('sha1') == built_sha1:
        record['verified'] = 1
        mes_cache_write(record)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('export', help='reference PNGs from an extracted tree')
    p.add_argument('tree')
    p.add_argument('outdir')
    p.add_argument('--suffix', default='',
                   help='written after each file name; use _revelations when '
                        'exporting into src/assets/mark/black so the plain '
                        'names (the user\'s edits) are never touched')
    p = sub.add_parser('build', help='swap the art into build/ADV')
    p.add_argument('--art', default='src/assets/mark/black')
    sub.add_parser('retail', help='remove the swap files from build/ADV')
    p = sub.add_parser('verify', help='decode build/ADV back and check')
    p.add_argument('--art', default='src/assets/mark/black')
    a = ap.parse_args()
    if a.cmd == 'export':
        cmd_export(a.tree if os.path.isabs(a.tree) else src_path(a.tree),
                   a.outdir if os.path.isabs(a.outdir) else src_path(a.outdir), a.suffix)
    elif a.cmd == 'build':
        cmd_build(a.art)
    elif a.cmd == 'retail':
        cmd_retail()
    else:
        cmd_verify(a.art)


if __name__ == '__main__':
    main()
