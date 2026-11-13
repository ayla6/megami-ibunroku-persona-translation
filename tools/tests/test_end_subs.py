"""The endings' movies get in-engine subtitles (END.EXE's own player).

END.EXE's EndPlayMovie looks its movie up with CdSearchFile; the hook reads
the renderer blob from the tail of END.EXE's file to 0x80160000 first, then
hands the lookup its own arguments. The frame loop's PadRead, the idle
StGetNext poll and the true-frame capture reach the renderer's END entries.
Requires a build (build/EXE/END.EXE, build/persona.sym, build/movie_subs_end.bin).
"""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/tests')]
from mips_cpu import CPU, REG  # noqa: E402

IMAGE = 0x80080000
SEARCH, POS_TO_INT, INT_TO_POS, READ = 0x8008A598, 0x80088BC4, 0x80088AC0, 0x80082EF8
BLOB_FILE_AT = 0x2E000
SENTINEL = 0x80001000


def word(image, address):
    at = address - IMAGE + 0x800
    return int.from_bytes(image[at:at + 4], 'little')


class EndSubtitles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = (ROOT / 'build/EXE/END.EXE').read_bytes()
        cls.blob = (ROOT / 'build/movie_subs_end.bin').read_bytes()
        cls.sym = {m[2].lower(): int(m[1], 16)
                   for line in (ROOT / 'build/persona.sym').read_text().splitlines()
                   if (m := re.fullmatch(r'([0-9A-Fa-f]{8}) (\S+)', line))}

    def test_blob_rides_at_the_file_tail(self):
        self.assertEqual(self.image[BLOB_FILE_AT:BLOB_FILE_AT + len(self.blob)], self.blob)
        self.assertEqual(int.from_bytes(self.image[0x1C:0x20], 'little'),
                         len(self.image) - 0x800)

    def test_hooks_reach_the_renderer(self):
        jal = lambda target: (3 << 26) | (target >> 2 & 0x3FFFFFF)
        j = lambda target: (2 << 26) | (target >> 2 & 0x3FFFFFF)
        self.assertEqual(word(self.image, 0x8008285C), jal(0x80160020))   # PadRead(1)
        self.assertEqual(word(self.image, 0x80082860), 0x34040001)        # a0 = 1 kept
        self.assertEqual(word(self.image, 0x80082ACC), jal(0x80160028))   # StGetNext
        self.assertEqual(word(self.image, 0x80082B0C), j(0x80161FA0))     # true frame
        self.assertEqual(word(self.image, 0x80082790), jal(self.sym['end_subs_load']))
        # the blob's fixed END entries (0x80160020/28) are jumps into its code
        for at in (0x20, 0x28):
            self.assertEqual(int.from_bytes(self.blob[at:at + 4], 'little') >> 26, 2)

    def test_loader_reads_the_blob_then_looks_the_movie_up(self):
        c = CPU()
        c.load(IMAGE, self.image[0x800:0x800 + 0x2D800])
        c.r[REG['sp']] = 0x801FF000
        c.r[REG['ra']] = SENTINEL
        c.r[REG['a0']], c.r[REG['a1']] = 0x801FE018, 0x801FE038
        calls = []

        def intercept(cpu):
            if cpu.pc in (SEARCH, POS_TO_INT, INT_TO_POS, READ):
                a = [cpu.r[REG[r]] for r in ('a0', 'a1', 'a2')]
                calls.append((cpu.pc, a, cpu.r[REG['ra']]))
                if cpu.pc == SEARCH and cpu.r[REG['ra']] == SENTINEL:
                    cpu.pc = SENTINEL          # the movie's own lookup: done
                    return True
                if cpu.pc == SEARCH:
                    name = bytes(cpu.read(a[1] + i, 1) for i in range(14))
                    self.assertEqual(name, b'\\EXE\\END.EXE;1')
                    cpu.r[REG['v0']] = 1
                elif cpu.pc == POS_TO_INT:
                    cpu.r[REG['v0']] = 1000
                cpu.pc = cpu.r[REG['ra']]
                cpu.next_pc = cpu.pc + 4
                return True
            return False

        c.start(self.sym['end_subs_load'])
        c.run(SENTINEL, 2000, intercept)
        order = [pc for pc, _, _ in calls]
        self.assertEqual(order, [SEARCH, POS_TO_INT, INT_TO_POS, READ, SEARCH])
        self.assertEqual(calls[2][1][0], 1000 + BLOB_FILE_AT // 0x800)
        self.assertEqual(calls[3][1][1:], [(len(self.blob) + 0x7FF) // 0x800, 0x80160000])
        self.assertEqual(calls[4][1][:2], [0x801FE018, 0x801FE038])
        self.assertEqual(c.r[REG['sp']], 0x801FF000)


if __name__ == '__main__':
    unittest.main()


class EndRoll(unittest.TestCase):
    """The roll's added pages: main's first call copies the new image table
    and roll scripts from the file tail to END_ROLL_HOME, and every reader
    points there."""

    @classmethod
    def setUpClass(cls):
        cls.image = (ROOT / 'build/EXE/END.EXE').read_bytes()
        cls.retail = (ROOT / 'data/psx/EXE/END.EXE').read_bytes()
        cls.sym = {m[2].lower(): int(m[1], 16)
                   for line in (ROOT / 'build/persona.sym').read_text().splitlines()
                   if (m := re.fullmatch(r'([0-9A-Fa-f]{8}) (\S+)', line))}
        equ = dict(re.findall(r'^(END_ROLL_\w+) equ (0x[0-9a-f]+|\d+)$',
                              (ROOT / 'build/end_roll.asm').read_text(), re.M))
        cls.equ = {k: int(v, 0) for k, v in equ.items()}

    def copied(self):
        c = CPU()
        c.load(IMAGE, self.image[0x800:])
        c.r[REG['sp']] = 0x801FF000
        c.r[REG['ra']] = SENTINEL
        c.start(self.sym['end_roll_copy'])
        c.run(0x80083024, 20000)
        return c

    def test_copy_lands_at_home_and_keeps_the_retail_table(self):
        c = self.copied()
        home = self.equ['END_ROLL_HOME']
        retail = [word(self.retail, 0x80099698 + 2 * i) & 0xFFFF for i in range(86)]
        table = [c.read(home + 2 * i, 2) for i in range(86 + self.equ['END_ROLL_PAGES'] + 1)]
        self.assertEqual(table[:86], retail)
        self.assertEqual(table[86] * 0x800, len((ROOT / 'data/psx/EXE/END.BIN').read_bytes()))
        self.assertEqual(table[-1] * 0x800, len((ROOT / 'build/EXE/END.BIN').read_bytes()))

    def test_roll_scripts_show_the_pages_before_presented_by(self):
        c = self.copied()
        pages = self.equ['END_ROLL_PAGES']
        for k in (1, 2, 3, 4):
            self.assertEqual(word(self.image, 0x80099FF4 + 4 * k), self.equ[f'END_ROLL_SCRIPT{k}'])
            at = self.equ[f'END_ROLL_SCRIPT{k}'] + 2 * self.equ[f'END_ROLL_SCRIPT{k}_CUT']
            got = [c.read(at + 2 * i, 2) for i in range(10 * pages + 2)]
            want = []
            for n in range(pages):
                want += [2, 86 + n, 5, 0x2D, 3, 4, 5, 0x96, 4, 4]
            self.assertEqual(got, want + [8, 0x48])
        # ending 0 has no roll: its retail script stays
        self.assertEqual(word(self.image, 0x80099FF4), word(self.retail, 0x80099FF4))


class EndRollHome(unittest.TestCase):
    def test_home_is_above_everything_end_exe_names(self):
        """END.EXE's own work areas (its libraries' BSS, which main's SsInit
        clears) end below the roll data's home, and the subtitle renderer's
        lookups start above it."""
        import struct
        image = (ROOT / 'data/psx/EXE/END.EXE').read_bytes()[0x800:]
        w = struct.unpack_from('<%dI' % (len(image) // 4), image)
        top = 0
        for i, x in enumerate(w):
            if x >> 26 != 0xF or not 0x8010 <= (x & 0xFFFF) <= 0x8013:
                continue
            rt = (x >> 16) & 31
            for y in w[i + 1:i + 10]:
                if (y >> 21) & 31 == rt and (y >> 26) in (9, 0x20, 0x21, 0x23, 0x24, 0x25,
                                                          0x28, 0x29, 0x2B, 0xD):
                    imm = y & 0xFFFF
                    if y >> 26 != 0xD and imm & 0x8000:
                        imm -= 0x10000
                    top = max(top, ((x & 0xFFFF) << 16) + imm)
                    break
        equ = dict(re.findall(r'^(END_ROLL_\w+) equ (0x[0-9a-f]+|\d+)$',
                              (ROOT / 'build/end_roll.asm').read_text(), re.M))
        home, size = int(equ['END_ROLL_HOME'], 0), int(equ['END_ROLL_SIZE'], 0)
        self.assertGreater(home, top + 0x1000)
        self.assertLessEqual(home + size, 0x80128000)
