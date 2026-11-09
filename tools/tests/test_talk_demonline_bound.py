"""Demon reaction-line references stay inside each TALK pack's text pool.

BtlSayDemonLine resolves a line through the pack directory and replaces it
with the "nothing" script when the resolved pointer is outside the scratch
window.  btlp/demonline_bound.asm bounds that window by the pack's own pool
end (header word 2, which the loader copies into g_btl_scratch_end) instead of
the retail 64 KB constant.  This test pins the corpus fact the patch relies
on: every reaction line the pack actually has resolves inside its text pool,
so the tighter bound rejects no real line.
"""
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src' / 'injection_tools'))
import talk  # noqa: E402

RECORD = 0x18          # one talk line's directory record
FIRST = 4              # first line record, just past the pool end word
MORE = 0x478           # second table (the other three lines of a reaction)
MORE_MASK = 0x7FFF
LINES = (MORE - FIRST) // RECORD
SLOT_NONE = 0xFFFF
NO_ENTRY = 0xFFFFFFFF  # directory slot with no string


def _u16(data, off):
    return struct.unpack_from('<H', data, off)[0]


def _u32(data, off):
    return struct.unpack_from('<I', data, off)[0]


def references(data):
    """Yield (line, act, slot, address) for each reaction line the pack has.

    Mirrors BtlSayDemonLine: two directory slots per reaction plus three more
    from the second table named by the record's `more` field.  Slots that name
    no string (0xFFFF, or a directory entry of 0xFFFFFFFF) are the engine's
    "nothing" case and are skipped; a record whose second-table index falls
    outside the pack is a junk row the guard rejects, also skipped.
    """
    end = _u32(data, 8)
    directory = _u32(data, 0)
    for line in range(LINES):
        record = end + FIRST + line * RECORD
        if record + RECORD > len(data):
            break
        for act in range(4):
            at = record + act * 6
            slots = [_u16(data, at), _u16(data, at + 2)]
            more = _u16(data, at + 4)
            if more != SLOT_NONE:
                second = end + MORE + (more & MORE_MASK) * RECORD + act * 6
                if second + 6 > len(data):
                    continue
                slots += [_u16(data, second + k * 2) for k in range(3)]
            for slot in slots:
                if slot == SLOT_NONE:
                    continue
                pointer = directory + slot * 4
                if pointer + 4 > len(data):
                    continue
                entry = _u32(data, pointer)
                if entry == NO_ENTRY:
                    continue
                yield line, act, slot, entry + directory


class DemonLineBound(unittest.TestCase):
    def test_referenced_lines_stay_below_the_packs_own_pool_end(self):
        packs = []
        for talk_dir in (ROOT / 'build' / 'TALK', ROOT / 'data' / 'psx' / 'TALK'):
            if talk_dir.is_dir():
                packs += sorted(talk_dir.glob('*.BIN'))
        if not packs:
            raise unittest.SkipTest('requires TALK data')

        checked = 0
        bad = []
        for path in packs:
            data = path.read_bytes()
            pack = talk.Talk(path.stem, data)
            if pack.hdr[1] <= pack.starts[0]:
                continue  # flat string table (the message pack), no line records
            end = pack.hdr[2]
            for line, act, slot, address in references(data):
                checked += 1
                if address >= end:
                    bad.append((path.parent.parent.name, path.name, line, act,
                                slot, f'0x{address:08x}', f'end 0x{end:08x}'))
        self.assertGreater(checked, 0, 'no reaction lines were checked')
        self.assertEqual(bad, [], 'reaction-line pointer past the pack text pool')


if __name__ == '__main__':
    unittest.main()
