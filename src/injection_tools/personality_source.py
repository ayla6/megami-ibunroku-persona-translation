"""Prove CONTACT personality slots and read their PSP-US pointer-table strings.

The proof uses actual executable consumers and 193 corresponding demon profile
records, not handwritten kana/kanji readings or an authored JP-to-EN map.
The proof runs at port time; builds read the canonical BTLP rows.
"""
import struct

import btlcmd
import btlmsg
import tables

JP_TABLE, US_TABLE = 0x29848c, 0x2acbdc
PSX_LABEL_TABLE = 0x800cdd50
PSX_PROFILE_TABLE = 0x800caf30
JP_PROFILE_ONE, US_PROFILE_ONE = 0x295ac4, 0x2a7ce0
COUNT, PROFILES, PROFILE_SIZE = 8, 193, 20

# The two regional consumers load the indexed label, then advance the pointer
# and test bit i of the same record while incrementing i. Exact instruction
# guards make source revision/control-flow drift a build error.
CONSUMERS = (
    (0xb5e78, (0x3c020004, 0x245486cc), 0xb5e98, 0x8e840000,
     0xb5ecc, (0x1235ff43, 0x26940004, 0x96c20046, 0x7c109620,
                0x02221007, 0x30420001, 0x1040fff9, 0x26310001)),
    (0xb71e0, (0x3c030005, 0x2472965c), 0xb7200, 0x8e440000,
     0xb7254, (0x1235ff3b, 0x26520004, 0x96e2005a, 0x02221007,
                0x30420001, 0x1040fffa, 0x26310001)),
)


def words(blob, offset, count):
    if offset < 0 or offset + 4 * count > len(blob) or offset % 4:
        raise ValueError('personality instruction/table outside binary')
    return struct.unpack_from(f'<{count}I', blob, offset)


def consumer(blob, spec, table):
    setup, setup_words, load, load_word, loop, loop_words = spec
    if (words(blob, setup, len(setup_words)) != setup_words
            or words(blob, load, 1) != (load_word,)
            or words(blob, loop, len(loop_words)) != loop_words):
        raise ValueError('PSP personality bit/pointer consumer changed')
    start, end = btlcmd.data_segment(blob)
    # The guarded LUI/addiu form a pointer relative to PT_LOAD data.
    lo = setup_words[1] & 0xffff
    if lo & 0x8000:
        lo -= 0x10000
    relative = ((setup_words[0] & 0xffff) << 16) + lo
    if start + relative != table or table + COUNT * 4 > end:
        raise ValueError('PSP personality consumer does not name its table')


def prove(psx, jp, us):
    """Return complete PSP-US names only after source and bit-index proof."""
    consumer(jp, CONSUMERS[0], JP_TABLE)
    consumer(us, CONSUMERS[1], US_TABLE)
    psx_guards = (
        (0x8007524c, (0x3c07800d, 0x24e7dd50)),
        (0x80075288, (0x94220000, 0, 0x00a21007, 0x30420001)),
        (0x800752d4, (0x8ce20000, 0x24e70004, 0x24a50001,
                      0xacc20000, 0x28a20008, 0x1440ffe4)),
    )
    if any(words(psx, at - btlmsg.B, len(expected)) != expected
           for at, expected in psx_guards):
        raise ValueError('PSX personality bit/pointer consumer changed')
    jp_names = btlcmd.pointer_text(jp, JP_TABLE, COUNT)
    us_names = btlcmd.pointer_text(us, US_TABLE, COUNT)
    if len(set(jp_names)) != COUNT or len(set(us_names)) != COUNT:
        raise ValueError('ambiguous PSP personality slots')
    label_ptrs = words(psx, PSX_LABEL_TABLE - btlmsg.B, COUNT)
    if len(set(label_ptrs)) != COUNT or any(
            not 0x800c87ec <= p < 0x800c882c for p in label_ptrs):
        raise ValueError('PSX personality pointer table changed')
    jlo, jhi = btlcmd.data_segment(jp)
    ulo, uhi = btlcmd.data_segment(us)
    low_masks = []
    complete_matches = 0
    profile_ptrs = set()
    for i in range(1, PROFILES + 1):
        ptr = words(psx, PSX_PROFILE_TABLE - btlmsg.B + i * 4, 1)[0]
        off = ptr - btlmsg.B
        ja = JP_PROFILE_ONE - (i - 1) * PROFILE_SIZE
        en = US_PROFILE_ONE - (i - 1) * PROFILE_SIZE
        if (off < 0 or off + PROFILE_SIZE > len(psx) or ptr in profile_ptrs
                or not jlo <= ja <= jhi - PROFILE_SIZE
                or not ulo <= en <= uhi - PROFILE_SIZE):
            raise ValueError('invalid personality profile extent or alias')
        profile_ptrs.add(ptr)
        a = psx[off:off + PROFILE_SIZE]
        b = jp[ja:ja + PROFILE_SIZE]
        c = us[en:en + PROFILE_SIZE]
        if a[2] != b[2] or a[2] != c[2]:
            raise ValueError(f'personality profile bit mismatch at index {i}')
        if a == b == c:
            complete_matches += 1
        low_masks.append(a[2])
    if complete_matches < PROFILES - 2:
        raise ValueError('personality profile record correspondence changed')
    vectors = {tuple((mask >> bit) & 1 for mask in low_masks)
               for bit in range(COUNT)}
    if len(vectors) != COUNT:
        raise ValueError('personality bit-slot identities are ambiguous')
    return us_names


def read():
    import toolbelt
    psx = btlmsg.data()
    pointers = words(psx, PSX_LABEL_TABLE - btlmsg.B, COUNT)
    if len(set(pointers)) != COUNT or any(not 0x800c87ec <= p < 0x800c882c for p in pointers):
        raise ValueError('PSX personality pointer table changed')
    rows = {r['pos']: r for r in toolbelt.merged_rows('BTLP')}
    result = [(rows.get(hex(p - btlmsg.B), {}).get('en') or '').strip() for p in pointers]
    if not all(result):
        raise ValueError('missing personality translations in BTLP rows')
    return result
