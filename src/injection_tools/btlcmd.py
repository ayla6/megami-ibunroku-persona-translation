"""CONTACT command names of BTLP.BIN (the 4 commands of every party member).

  python tools/btlcmd.py     write build/btlcmd.asm (included in the BTLP section of main.asm)

36 strings "説得する<FFF5>" ... in BTLP RAM 0x800CB330-0x800CB459 (leading 00 blanks are alignment for the 16 px window), a
word table at 0x800CB45C (character * 4 + slot, characters 1..9: protagonist, Maki, Brown, Nanjo, Mark, Elly, Ayase, Yukino,
Reiji) and a few lui/addiu references. They are drawn by the 16 px string renderer (0x8007BF44), which vwf/vwf_btlp_str16.asm
sends through the VWF engine, so English is plain VWF text. Strings are re-packed in the same zone (identical English shares
one copy) and every reference is patched (tools/btlmsg.py machinery). Both PSP executables
carry 36 corresponding indexed pointers; every JP target must equal the PSX
slot's actual Japanese before its PSP-US wording is ported. Builds read the
canonical BTLP rows without PSP binaries.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'extraction_tools', 'psp'))
import btlmsg   # noqa: E402
import codec    # noqa: E402
import etext    # noqa: E402
import tables   # noqa: E402

ZONE = (0x800CB330, 0x800CB459)
B = btlmsg.B
NL = chr(10)
OUT = os.path.join(btlmsg.ROOT, 'build', 'btlcmd.asm')
PSX_TABLE = 0x800CB45C
# These are the two regional, indexed command-pointer tables, not name maps.
JP_TABLE = 0x298288
US_TABLE = 0x2AC928
COUNT = 36


def data_segment(blob):
    """File extent of PSP ELF's second PT_LOAD, whose pointers are relative."""
    if blob[:6] != b'\x7fELF\x01\x01':
        raise ValueError('expected a little-endian 32-bit PSP ELF')
    offset = struct.unpack_from('<I', blob, 0x1c)[0]
    size, count = struct.unpack_from('<HH', blob, 0x2a)
    if size < 32 or offset + size * count > len(blob):
        raise ValueError('invalid PSP program-header table')
    segments = [struct.unpack_from('<8I', blob, offset + i * size)
                for i in range(count)]
    segments = [s for s in segments if s[0] == 1]
    if len(segments) < 2:
        raise ValueError('missing PSP data load segment')
    start, length = segments[1][1], segments[1][4]
    if start + length > len(blob):
        raise ValueError('PSP data segment exceeds file')
    return start, start + length


def pointer_text(blob, table, count=COUNT):
    """Decode each indexed BE string at its actual relative pointer, fail closed."""
    start, limit = data_segment(blob)
    if table < start or table + 4 * count > limit or table % 4:
        raise ValueError('command pointer table outside PSP data segment')
    pointers = struct.unpack_from(f'<{count}I', blob, table)
    if len(set(pointers)) != count:
        raise ValueError('aliased command pointer slots')
    result = []
    for rel in pointers:
        at = start + rel
        if at < start or at % 2 or at >= limit:
            raise ValueError('command pointer outside PSP data segment')
        end = next((p for p in range(at, min(at + 128, limit - 1), 2)
                    if blob[p:p + 2] == b'\xff\x01'), None)
        if end is None:
            raise ValueError('unterminated PSP command')
        raw = blob[at:end]
        if not raw or any(raw[i] == 0xFF for i in range(0, len(raw), 2)):
            raise ValueError('empty or controlled PSP command')
        text = codec.decode_box(raw).strip()
        if not text or any(c in text for c in '<>[]'):
            raise ValueError('invalid PSP command glyph')
        result.append(text)
    return result


def source_commands(psx, jp, us):
    """Slot proof: pointer identity plus all 36 exact JP-vs-PSX commands."""
    jp_names = pointer_text(jp, JP_TABLE)
    us_names = pointer_text(us, US_TABLE)
    repeats = {}
    for ja, en in zip(jp_names, us_names):
        if ja in repeats and repeats[ja] != en:
            raise ValueError('inconsistent regional duplicate command slots')
        repeats[ja] = en
    pointers = struct.unpack_from(f'<{COUNT}I', psx, PSX_TABLE - B)
    if len(set(pointers)) != COUNT:
        raise ValueError('aliased PSX command pointer slots')
    for i, ptr in enumerate(pointers):
        if not ZONE[0] <= ptr < ZONE[1]:
            raise ValueError(f'PSX command pointer {i} outside its zone')
        end = psx.find(b'\xff\xf5', ptr - B, ZONE[1] - B)
        if end < 0:
            raise ValueError(f'unterminated PSX command {i}')
        ja = btlmsg.dec(psx, ptr, B + end + 2).strip()
        if ja != jp_names[i]:
            raise ValueError(f'PSP-JP/PSX command mismatch at slot {i}')
    return list(zip(pointers, us_names))


def translated_commands(psx):
    """Read the indexed PSX commands from the merged canonical rows."""
    import toolbelt
    pointers = struct.unpack_from(f'<{COUNT}I', psx, PSX_TABLE - B)
    if len(set(pointers)) != COUNT or any(not ZONE[0] <= p < ZONE[1] for p in pointers):
        raise ValueError('invalid PSX command pointer table')
    rows = {r['pos']: r for r in toolbelt.merged_rows('BTLP')}
    commands = []
    for address in pointers:
        text = (rows.get(hex(address - B), {}).get('en') or '').strip()
        if not text:
            raise ValueError(f'missing battle command at {address - B:#x}')
        commands.append((address, text))
    return commands


def main():
    previous = btlmsg.ZONE
    try:
        btlmsg.ZONE = ZONE
        build_commands()
    finally:
        btlmsg.ZONE = previous


def build_commands():
    d = btlmsg.data()
    msgs = btlmsg.messages(d)
    commands = translated_commands(d)
    if [a for a, _e in msgs] != [a for a, _text in commands]:
        raise SystemExit('btlcmd: physical commands differ from indexed slots')
    rf = btlmsg.refs(d)
    new = {a: etext.encode(text, end=btlmsg.END) for a, text in commands}
    # re-pack, identical strings share one copy
    pos = btlmsg.ZONE[0]
    where = {}
    placed = {}
    for a, _text in commands:
        b = new[a]
        if b in placed:
            where[a] = placed[b]
            continue
        placed[b] = pos
        where[a] = pos
        pos += len(b)
    if pos > btlmsg.ZONE[1]:
        raise SystemExit(f'btlcmd: {pos - btlmsg.ZONE[0]} bytes > zone {btlmsg.ZONE[1] - btlmsg.ZONE[0]}')
    with open(OUT, 'w', newline=NL) as o:
        o.write(';; generated by tools/btlcmd.py - do not edit' + NL)
        o.write(f'.org {btlmsg.ZONE[0]:#x}{NL}    .fill {btlmsg.ZONE[1] - btlmsg.ZONE[0]:#x}, 0{NL}')
        for b, p in placed.items():
            o.write(f'.org {p:#x}{NL}    .byte ' + ', '.join(f'0x{c:02X}' for c in b) + NL)
        nref = 0
        for (a, e) in msgs:
            for kind, w in rf.get(a, []):
                nref += 1
                if kind == 'word':
                    o.write(f'.org {w:#x}{NL}    .word {where[a]:#x}{NL}')
                else:
                    o.write(f'.org {w:#x}{NL}    .halfword {where[a] & 0xFFFF:#x}{NL}')
    print(f'btlcmd: 36 commands, {len(placed)} distinct, {pos - btlmsg.ZONE[0]} of {btlmsg.ZONE[1] - btlmsg.ZONE[0]} bytes, {nref} references')


def verify(path=None):
    """Back-check every patched pointer and complete source-derived string."""
    path = path or os.path.join(btlmsg.ROOT, 'build', 'BTLP.BIN')
    with open(path, 'rb') as source:
        built = source.read()
    commands = translated_commands(btlmsg.data())
    if PSX_TABLE - B + COUNT * 4 > len(built):
        raise SystemExit('btlcmd verify: pointer table outside BTLP')
    for index, (_original, text) in enumerate(commands):
        ptr = struct.unpack_from('<I', built, PSX_TABLE - B + index * 4)[0]
        expected = etext.encode(text, end=btlmsg.END)
        offset = ptr - B
        first_string = ZONE[0]
        if offset < first_string - B or offset + len(expected) > ZONE[1] - B:
            raise SystemExit(f'btlcmd verify: pointer outside zone at slot {index}')
        if built[offset:offset + len(expected)] != expected:
            raise SystemExit(f'btlcmd verify: text mismatch at slot {index}')
    print(f'btlcmd verify: {len(commands)} PSP-derived pointers and strings intact')


if __name__ == '__main__':
    if len(sys.argv) == 1:
        main()
    elif sys.argv[1:] == ['verify']:
        verify()
    else:
        raise SystemExit('usage: btlcmd.py [verify]')
