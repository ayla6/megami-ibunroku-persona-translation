"""--qol=range: a move's reach painted on the battle floor (qol/range_btlp.asm).

The overlay replaces BtlDrawObjects' debug-grid block (0x80082B78..0x80082E6B)
and runs here on the R3000 model with the GTE stood in by an offset
projection (screen = world + (1000, 2000)), so the quads' corners can be read
back as world coordinates. While a pick is up (rng_state) and a fighter is on
the target motion, each lane's run of lit reach cells is one orange quad
and the cells of the fighters on motion 10/11 red ones, linked into the arena
entry of the ordering table behind one DR_MODE. The command menu's, the skill
board's and the item board's frames are followed by a preview of what is
under the cursor, painted all red for two frames.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/tests')]
from mips_cpu import CPU, REG  # noqa: E402

BTLP = 0x800643C4
START, LEAVE = 0x80082B78, 0x80082E6C
REACH, CELLS, ACTORS = 0x800F7414, 0x800F7FFC, 0x8005D678
G4_NEXT, DRMODE_NEXT = 0x800EEC44, 0x800EEC4C
POOL = 0x80100000
OT = POOL + 0xD6C0
G4_RUN, G4_END = POOL + 0x6C68, POOL + 0x7568
OBJS = 0x80140000
AREA, TARGET = 0x2A1070B4, 0x2A2020E0
SX, SY = 1000, 2000
SPELL_UPDATE, ACTOR_PERSONA, MARK_AREA = 0x800A5288, 0x800AE774, 0x80095644
ACTOR_TURN, PERSONA_SPELLS, SPELL_DATA = 0x800D224C, 0x8005CDDB, 0x80047D44
PICK_UPDATE, PICK_ROW, MENU_KEY = 0x800A4EF0, 0x800D2234, 0x8009C93C
ITEM_ROW, ITEM_SLOTS, ITEM_DEFS = 0x800D2244, 0x800F8088, 0x80044404
PICKS = {'rng_wrap_move': 0x800A7180, 'rng_wrap_member': 0x800A4548,
         'rng_wrap_party': 0x800A46B0, 'rng_wrap_enemies': 0x800A48EC,
         'rng_wrap_attack': 0x800A2388}
ENEMY_SIDE = {(l, r) for l in range(5) for r in range(5)}
PARTY_SIDE = {(l, r) for l in range(5) for r in range(10, 15)}
SENTINEL = 0x80001000


def assemble(work):
    armips = ROOT / 'external_tools/armips/armips'
    source = work / 'range.asm'
    out = work / 'BTLP.BIN'
    source.write_text(
        '.psx\n'
        f'.include "{ROOT / "src/asm/common/addresses.inc"}"\n'
        f'.open "{ROOT / "data/psx/BTLP.BIN"}", "{out}", {BTLP:#x}\n'
        f'.include "{ROOT / "src/asm/qol/range_btlp.asm"}"\n'
        '.close\n')
    symbols = work / 'range.sym'
    result = subprocess.run([str(armips), str(source), '-sym2', str(symbols), '-erroronwarning'],
                            capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    sym = {}
    for line in symbols.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2:
            sym[parts[1].lower()] = int(parts[0], 16)
    return out.read_bytes(), sym


def s16(x):
    return x - 0x10000 if x & 0x8000 else x


class Gte:
    """mtc2 / swc2 / rtpt / rtps, enough for the overlay."""

    def __init__(self):
        self.data = [0] * 32

    def project(self, n, out):
        xy = self.data[2 * n]
        x, y = s16(xy & 0xFFFF), s16(xy >> 16)
        self.data[out] = ((y + SY) & 0xFFFF) << 16 | ((x + SX) & 0xFFFF)

    def __call__(self, c):
        word = c.read(c.pc)
        op = word >> 26
        if op not in (0x32, 0x3A, 0x12):
            return False
        if op == 0x12 and (word >> 21) & 31 == 4:            # mtc2
            self.data[(word >> 11) & 31] = c.r[(word >> 16) & 31]
        elif op == 0x12:
            if word == 0x4A280030:                       # rtpt
                for n in range(3):
                    self.project(n, 12 + n)
            elif word == 0x4A180001:                     # rtps: the FIFO's newest slot
                self.project(0, 14)
            else:
                raise AssertionError(f'GTE op {word:#x}')
        else:
            base = c.r[(word >> 21) & 31]
            reg = (word >> 16) & 31
            address = (base + s16(word & 0xFFFF)) & 0xFFFFFFFF
            if op == 0x32:
                self.data[reg] = c.read(address)
            else:
                c.write(address, self.data[reg])
        c.pc += 4
        c.next_pc = c.pc + 4
        return True


class Range(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / 'external_tools/armips/armips').exists():
            raise unittest.SkipTest('requires armips')
        with tempfile.TemporaryDirectory(prefix='range-') as work:
            cls.image, cls.sym = assemble(Path(work))

    def battle(self, lit=(), fighters=(), state=1):
        """lit: (lane, row) reach cells; fighters: (record, lane, row, motion);
        state: rng_state (0 no pick, 1 a pick, 3 a party pick)."""
        c = CPU()
        c.load(BTLP, self.image)
        c.write(0x800D0000 - 0xF08, 0, 1)                     # g_btl_frame
        c.write(0x800D0000 - 0xF68, POOL)                     # g_btl_prim_pool
        c.write(G4_NEXT, G4_RUN)
        c.write(DRMODE_NEXT, POOL + 0xC1A8)
        c.write(OT, 0x00FFFFFF)
        c.write(ACTOR_TURN, 0xFFFF, 2)                       # no member acting unless a test says so
        for lane, row in lit:
            c.write(REACH + lane * 15 + row, 0xFF, 1)
        c.write(self.sym['rng_state'], state, 1)
        for record, lane, row, motion in fighters:
            actor, obj = ACTORS + record * 0xEC, OBJS + record * 0xD8
            c.write(actor + 0x3E, 1, 1)
            c.write(actor + 0x60, obj)
            c.write(obj + 0xB0, lane * 2, 1)
            c.write(obj + 0xB1, row, 1)
            c.write(obj + 0xD1, motion, 1)
        return c

    def run_overlay(self, c):
        c.r[REG['sp']] = 0x801FF000
        c.start(START)
        c.run(LEAVE, 20000, Gte())
        self.assertEqual(c.pc, LEAVE)

    def quads(self, c):
        """The OT entry's list: [('mode', word)] then [(colour, corners)]."""
        out, p = [], c.read(OT) & 0xFFFFFF
        while p != 0xFFFFFF:
            a = 0x80000000 | p
            n = c.read(a) >> 24
            if n == 2:
                out.append(('mode', c.read(a + 4)))
            else:
                self.assertEqual(n, 5)
                corners = []
                for k in range(4):
                    xy = c.read(a + 8 + 4 * k)
                    corners.append((s16(xy & 0xFFFF) - SX, s16(xy >> 16) - SY))
                out.append((c.read(a + 4), corners))
            p = c.read(a) & 0xFFFFFF
        return out

    def rect(self, lane, first, last):
        x0, y0, y1 = -75 + 30 * lane, -150 + 20 * first, -150 + 20 * (last + 1)
        return [(x0, y0), (x0 + 30, y0), (x0, y1), (x0 + 30, y1)]

    def test_nothing_without_a_pick(self):
        c = self.battle(lit=[(2, r) for r in range(5)], fighters=[(5, 2, 1, 0), (0, 2, 2, 3)])
        self.run_overlay(c)
        self.assertEqual(c.read(OT), 0x00FFFFFF)
        self.assertEqual(c.read(G4_NEXT), G4_RUN)

    def test_the_target_motion_outside_a_pick_is_nothing(self):
        """The negotiation keeps its demons on motion 10; no pick is up."""
        c = self.battle(lit=[(2, r) for r in range(5)], fighters=[(5, 2, 1, 10), (6, 3, 1, 11)],
                        state=0)
        self.run_overlay(c)
        self.assertEqual(c.read(OT), 0x00FFFFFF)

    def test_area_orange_targets_red(self):
        lit = [(2, r) for r in range(5)] + [(1, 3)]
        c = self.battle(lit=lit, fighters=[(6, 2, 1, 10), (7, 4, 0, 0), (0, 2, 1, 0)])
        self.run_overlay(c)
        got = self.quads(c)
        self.assertEqual(got[0], ('mode', 0xE1000660))         # met first: the blend
        self.assertEqual(got[1:], [(AREA, self.rect(1, 3, 3)),
                                   (AREA, self.rect(2, 0, 0)),
                                   (TARGET, self.rect(2, 1, 1)),
                                   (AREA, self.rect(2, 2, 4))][::-1])
        self.assertEqual(c.read(G4_NEXT), G4_RUN + 4 * 36)
        self.assertEqual(c.read(DRMODE_NEXT), POOL + 0xC1A8 + 12)

    def test_a_member_stands_ten_rows_on(self):
        c = self.battle(fighters=[(1, 0, 2, 11)], state=3)
        self.run_overlay(c)
        self.assertEqual(self.quads(c)[1:], [(TARGET, self.rect(0, 12, 12))])

    def test_the_g4_run_end_is_kept(self):
        c = self.battle(lit=[(l, 0) for l in range(5)], fighters=[(5, 0, 0, 10)])
        c.write(G4_NEXT, G4_END - 2 * 36)
        self.run_overlay(c)
        self.assertEqual(len(self.quads(c)), 1 + 2)
        self.assertEqual(c.read(G4_NEXT), G4_END)

    def test_the_reach_grid_is_not_written(self):
        lit = [(3, r) for r in range(15)]
        c = self.battle(lit=lit, fighters=[(5, 3, 4, 10)])
        self.run_overlay(c)
        for lane in range(5):
            for row in range(15):
                self.assertEqual(c.read(REACH + lane * 15 + row, 1),
                                 0xFF if (lane, row) in lit else 0)

    def test_members_are_targets_only_in_a_party_pick(self):
        """BtlSingleOutMember bobs the acting member on motion 10 through the
        whole command; in a party pick every member on it is a target, the
        acting member as much as any."""
        c = self.battle(lit=[(1, 0)], fighters=[(1, 2, 2, 10)], state=0)
        c.write(ACTOR_TURN, 1, 2)
        c.write(self.sym['rng_hover'], 2, 1)
        self.run_overlay(c)
        self.assertEqual(self.quads(c)[1:], [(TARGET, self.rect(1, 0, 0))])   # a menu's preview, all red
        c = self.battle(fighters=[(1, 2, 2, 10)])
        c.write(ACTOR_TURN, 1, 2)
        self.run_overlay(c)
        self.assertEqual(c.read(OT), 0x00FFFFFF)                            # an enemy pick's frame
        for picked in ((1,), (1, 3)):
            c = self.battle(lit=PARTY_SIDE, fighters=[(m, m, 1, 10) for m in picked], state=3)
            c.write(ACTOR_TURN, 1, 2)
            self.run_overlay(c)
            want = []
            for lane in range(5):
                if lane in picked:
                    want += [(AREA, self.rect(lane, 10, 10)), (TARGET, self.rect(lane, 11, 11)),
                             (AREA, self.rect(lane, 12, 14))]
                else:
                    want.append((AREA, self.rect(lane, 10, 14)))
            self.assertEqual(self.quads(c)[1:], want[::-1])

    def pick(self, entry, a1=0x42, setup=None):
        """Run one wrapper entry with its pick stubbed; answer what the pick
        saw (rng_state, a0, a1, the lit reach cells) and the CPU after."""
        c = CPU()
        c.load(BTLP, self.image)
        state = self.sym['rng_state']
        for i in range(75):
            c.write(REACH + i, 0x5A, 1)
        if setup:
            setup(c)
        seen = []

        def stub(cpu):
            if cpu.pc != PICKS[entry]:
                return False
            lit = {(i // 15, i % 15) for i in range(75) if cpu.read(REACH + i, 1) == 0xFF}
            seen.append((cpu.read(state, 1), cpu.r[REG['a0']], cpu.r[REG['a1']], lit))
            cpu.r[REG['v0']] = 0x1234
            cpu.pc = cpu.r[REG['ra']]
            cpu.next_pc = cpu.pc + 4
            return True

        c.r[REG['sp']], c.r[REG['ra']] = 0x801FF000, SENTINEL
        c.r[REG['a0']], c.r[REG['a1']] = 0x8005D678, a1
        c.start(self.sym[entry])
        c.run(SENTINEL, 2000, stub)
        self.assertEqual(len(seen), 1)
        self.assertEqual((c.read(state, 1), c.r[REG['v0']], c.r[REG['sp']]), (0, 0x1234, 0x801FF000))
        return seen[0]

    def test_each_pick_runs_raised_on_its_side(self):
        for entry, want_state, side in (('rng_wrap_member', 3, PARTY_SIDE),
                                        ('rng_wrap_party', 3, PARTY_SIDE),
                                        ('rng_wrap_enemies', 1, ENEMY_SIDE),
                                        ('rng_wrap_attack', 1, ENEMY_SIDE)):
            with self.subTest(entry=entry):
                state, a0, a1, lit = self.pick(entry)
                self.assertEqual((state, a0, a1, lit), (want_state, 0x8005D678, 0x42, side))

    def test_the_move_pick_fills_the_moves_side(self):
        """BtlPickMoveTarget: the side the move's kind reaches; an aimed move
        is left to the pick's own BtlMarkMoveArea."""
        for move, kind, side in ((0x10, 0x02, ENEMY_SIDE), (0x30, 0x14, PARTY_SIDE),
                                 (0x54, 0x1A, ENEMY_SIDE), (0x80, 0x02, set())):
            with self.subTest(move=hex(move)):
                kind_at = SPELL_DATA + move * 0x14 + 0x0A
                state, a0, a1, lit = self.pick('rng_wrap_move', a1=move,
                                               setup=lambda c: c.write(kind_at, kind, 1))
                self.assertEqual((state, a0, a1, lit), (1, 0x8005D678, move, side))

    def test_the_party_reset_is_followed_by_the_party_side(self):
        """BtlPartyResetGfx clears g_btl_reach; the whole-party pick's call of
        it is followed by the party's side."""
        c = CPU()
        c.load(BTLP, self.image)
        for i in range(75):
            c.write(REACH + i, 0x5A, 1)
        calls = []

        def stub(cpu):
            if cpu.pc != 0x800C7424:
                return False
            calls.append(cpu.pc)
            for i in range(75):
                cpu.write(REACH + i, 0, 1)
            cpu.pc = cpu.r[REG['ra']]
            cpu.next_pc = cpu.pc + 4
            return True

        c.r[REG['sp']], c.r[REG['ra']] = 0x801FF000, SENTINEL
        c.start(self.sym['rng_party_reset'])
        c.run(SENTINEL, 2000, stub)
        lit = {(i // 15, i % 15) for i in range(75) if c.read(REACH + i, 1) == 0xFF}
        self.assertEqual((calls, lit, c.r[REG['sp']]), ([0x800C7424], PARTY_SIDE, 0x801FF000))
        self.assertEqual(sum(c.read(REACH + i, 1) for i in range(75)), 0xFF * 25)

    def test_a_party_pick_raises_the_state(self):
        c = CPU()
        c.load(BTLP, self.image)
        c.write(self.sym['rng_state'], 1, 1)
        c.start(self.sym['rng_party_on'])
        c.r[REG['ra']] = SENTINEL
        c.run(0x800C8004, 20)
        self.assertEqual(c.read(self.sym['rng_state'], 1), 3)

    def test_the_hook_sites(self):
        jal = lambda t: (3 << 26) | (t >> 2 & 0x3FFFFFF)
        word = lambda a: int.from_bytes(self.image[a - BTLP:a - BTLP + 4], 'little')
        for site, target in ((0x800A7C8C, 'rng_party_on'), (0x800A7E4C, 'rng_party_on'),
                             (0x800A37C0, 'rng_wrap_move'), (0x800A3EC8, 'rng_wrap_move'),
                             (0x800A3FE0, 'rng_wrap_member'), (0x800A4170, 'rng_wrap_party'),
                             (0x800A4280, 'rng_wrap_enemies'), (0x800A345C, 'rng_board_frame'),
                             (0x800A3AE4, 'rng_item_frame'), (0x8009E358, 'rng_menu_frame'),
                             (0x800A7E54, 'rng_party_reset')):
            self.assertEqual(word(site), jal(self.sym[target]), hex(site))
        for entry in (0, 3):
            self.assertEqual(word(0x800D22E0 + 4 * entry), self.sym['rng_wrap_attack'])

    def test_the_preview_is_all_red_for_its_frames(self):
        c = self.battle(lit=[(1, r) for r in range(3)], state=0)
        c.write(self.sym['rng_hover'], 2, 1)
        self.run_overlay(c)
        self.assertEqual(self.quads(c)[1:], [(TARGET, self.rect(1, 0, 2))])
        self.assertEqual(c.read(self.sym['rng_hover'], 1), 1)
        c.write(OT, 0x00FFFFFF)
        c.write(self.sym['rng_hover'], 0, 1)
        self.run_overlay(c)
        self.assertEqual(c.read(OT), 0x00FFFFFF)

    def test_a_pick_wins_over_the_preview(self):
        c = self.battle(lit=[(1, 0), (1, 1)], fighters=[(5, 1, 1, 10)])
        c.write(self.sym['rng_hover'], 2, 1)
        self.run_overlay(c)
        self.assertEqual(self.quads(c)[1:], [(TARGET, self.rect(1, 1, 1)),
                                             (AREA, self.rect(1, 0, 0))])

    def board(self, move, kind=0, target=3, aim=0x12):
        """One frame of the board with move under the cursor (row 2 of Persona 4, member 1)."""
        c = CPU()
        c.load(BTLP, self.image)
        c.write(ACTOR_TURN, 1, 2)
        row = 0x801F0000
        c.write(row, 2, 2)
        c.write(PERSONA_SPELLS + 4 * 0x48 + 2, move, 1)
        rec = SPELL_DATA + move * 0x14
        c.write(rec + 0x0A, kind, 1)
        c.write(rec + 0x0D, target, 1)
        c.write(rec + 0x10, aim, 1)
        for i in range(75):
            c.write(REACH + i, 0x5A, 1)
        calls = []

        def stub(cpu):
            if cpu.pc not in (SPELL_UPDATE, ACTOR_PERSONA, MARK_AREA):
                return False
            calls.append((cpu.pc, cpu.r[REG['a0']], cpu.r[REG['a1']], cpu.r[REG['a2']]))
            cpu.r[REG['v0']] = {SPELL_UPDATE: 0xFFFFFF00, ACTOR_PERSONA: 4, MARK_AREA: 3}[cpu.pc]
            for name in ('t0', 't1', 't2', 'a1', 'a2', 'a3', 'v1'):
                cpu.r[REG[name]] = 0xDEAD0000          # callees keep nothing
            cpu.pc = cpu.r[REG['ra']]
            cpu.next_pc = cpu.pc + 4
            return True

        c.r[REG['sp']] = 0x801FF000
        c.r[REG['ra']] = SENTINEL
        c.r[REG['a0']] = row
        c.start(self.sym['rng_board_frame'])
        c.run(SENTINEL, 5000, stub)
        self.assertEqual(c.r[REG['v0']], 0xFFFFFF00)           # the board's answer
        self.assertEqual(c.r[REG['sp']], 0x801FF000)
        self.assertEqual(calls[0][:2], (SPELL_UPDATE, row))
        self.assertEqual(calls[1][:2], (ACTOR_PERSONA, 1))
        lit = {(i // 15, i % 15) for i in range(75) if c.read(REACH + i, 1) == 0xFF}
        return c, calls[2:], lit

    def test_an_aimed_move_is_thrown_as_the_pick_throws_it(self):
        c, calls, _ = self.board(0x80, target=3, aim=0x12)
        self.assertEqual(calls, [(MARK_AREA, ACTORS + 0xEC, 3, 2)])
        self.assertEqual(c.read(self.sym['rng_hover'], 1), 2)

    def test_other_moves_reach_a_whole_side(self):
        enemies = {(l, r) for l in range(5) for r in range(5)}
        party = {(l, r) for l in range(5) for r in range(10, 15)}
        for move, kind, side in ((0x10, 0x02, enemies), (0x30, 0x14, party),
                                 (0x31, 0x33, party), (0x54, 0x1A, enemies),
                                 (0x5B, 0x1C, enemies), (0x6E, 0x32, enemies),
                                 (0xDB, 0x1E, party)):
            with self.subTest(move=hex(move)):
                c, calls, lit = self.board(move, kind=kind)
                self.assertEqual(calls, [])
                self.assertEqual(lit, side)
                self.assertEqual(c.read(self.sym['rng_hover'], 1), 2)

    def test_an_empty_row_previews_nothing(self):
        c, calls, _ = self.board(0)
        self.assertEqual(calls, [])
        self.assertEqual(c.read(self.sym['rng_hover'], 1), 0)

    def frame(self, entry, setup):
        """One frame of a menu hook (member 1 acting): its menu stubbed to
        answer 0xFFFFFF00; answer the calls made, the lit reach cells and
        rng_hover."""
        c = CPU()
        c.load(BTLP, self.image)
        c.write(ACTOR_TURN, 1, 2)
        for i in range(75):
            c.write(REACH + i, 0x5A, 1)
        setup(c)
        calls = []

        def stub(cpu):
            if cpu.pc not in (PICK_UPDATE, MENU_KEY, MARK_AREA):
                return False
            calls.append((cpu.pc, cpu.r[REG['a0']], cpu.r[REG['a1']], cpu.r[REG['a2']]))
            cpu.r[REG['v0']] = 0xFFFFFF00 if cpu.pc != MARK_AREA else 3
            for name in ('t0', 't1', 't2', 'a1', 'a2', 'a3', 'v1'):
                cpu.r[REG[name]] = 0xDEAD0000
            cpu.pc = cpu.r[REG['ra']]
            cpu.next_pc = cpu.pc + 4
            return True

        c.r[REG['sp']], c.r[REG['ra']], c.r[REG['a0']] = 0x801FF000, SENTINEL, PICK_ROW
        c.start(self.sym[entry])
        c.run(SENTINEL, 5000, stub)
        self.assertEqual((c.r[REG['v0']], c.r[REG['sp']]), (0xFFFFFF00, 0x801FF000))
        lit = {(i // 15, i % 15) for i in range(75) if c.read(REACH + i, 1) == 0xFF}
        return calls[1:], lit, c.read(self.sym['rng_hover'], 1)

    def test_the_command_menu_previews_the_sword_and_the_gun(self):
        member = ACTORS + 0xEC

        def equip(row, sword, gun):
            def setup(c):
                c.write(PICK_ROW, row, 2)
                c.write(member + 0x20, sword, 2)
                c.write(member + 0x22, gun, 2)
                c.write(ITEM_DEFS + sword * 0x20 + 0x19, 5, 1)
                c.write(ITEM_DEFS + sword * 0x20 + 0x1A, 0x82, 1)
                if gun:
                    c.write(ITEM_DEFS + gun * 0x20 + 0x19, 7, 1)
                    c.write(ITEM_DEFS + gun * 0x20 + 0x1A, 0x04, 1)
            return setup

        self.assertEqual(self.frame('rng_menu_frame', equip(0, 0x40, 0x60))[0::2],
                         ([(MARK_AREA, member, 5, 0x82)], 2))
        self.assertEqual(self.frame('rng_menu_frame', equip(3, 0x40, 0x60))[0::2],
                         ([(MARK_AREA, member, 7, 0x04)], 2))
        for row, gun in ((3, 0), (1, 0x60), (2, 0x60), (5, 0x60)):
            with self.subTest(row=row, gun=gun):
                self.assertEqual(self.frame('rng_menu_frame', equip(row, 0x40, gun))[0::2], ([], 0))

    def test_the_item_board_previews_the_item(self):
        def item(item_id, move=0, kind=0, row=3):
            def setup(c):
                c.write(ITEM_ROW, row, 2)
                c.write(ITEM_SLOTS + 2 * row, 5 << 9 | item_id, 2)
                c.write(ITEM_DEFS + item_id * 0x20 + 0x12, move, 1)
                rec = SPELL_DATA + move * 0x14
                c.write(rec + 0x0A, kind, 1)
                c.write(rec + 0x0D, 3, 1)
                c.write(rec + 0x10, 0x12, 1)
            return setup

        self.assertEqual(self.frame('rng_item_frame', item(0x50, move=0x20, kind=0x02))[1:],
                         (ENEMY_SIDE, 2))
        self.assertEqual(self.frame('rng_item_frame', item(0x51, move=0x30, kind=0x14))[1:],
                         (PARTY_SIDE, 2))
        self.assertEqual(self.frame('rng_item_frame', item(0x52, move=0x80))[0::2],
                         ([(MARK_AREA, ACTORS + 0xEC, 3, 2)], 2))
        for item_id, side in ((0x1A, PARTY_SIDE), (0x1E, PARTY_SIDE), (0x1F, ENEMY_SIDE),
                              (0x21, ENEMY_SIDE), (0x22, PARTY_SIDE)):
            with self.subTest(item=hex(item_id)):
                self.assertEqual(self.frame('rng_item_frame', item(item_id))[1:], (side, 2))
        for item_id in (0x19, 0x23, 0):
            with self.subTest(item=hex(item_id)):
                self.assertEqual(self.frame('rng_item_frame', item(item_id)), ([], set(), 0))

    def test_the_addresses_are_the_ones_retail_code_uses(self):
        """Each RAM address the overlay reads is formed (lui + offset) by the
        retail BTLP code itself; the fighter fields many times over."""
        import struct
        retail = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        w = struct.unpack_from(f'<{len(retail) // 4}I', retail)
        formed = {}
        for i, x in enumerate(w):
            if x >> 26 != 0xF:
                continue
            rt, hi = (x >> 16) & 31, x & 0xFFFF
            for y in w[i + 1:i + 8]:
                if (y >> 21) & 31 == rt and (y >> 26) in (9, 0x20, 0x21, 0x23, 0x24, 0x25,
                                                          0x28, 0x29, 0x2B):
                    a = ((hi << 16) + s16(y & 0xFFFF)) & 0xFFFFFFFF
                    formed[a] = formed.get(a, 0) + 1
                    break
        for address, least in ((ACTORS, 50), (ACTORS + 0x3E, 50), (ACTORS + 0x60, 50),
                               (REACH, 3), (G4_NEXT, 1), (DRMODE_NEXT, 1), (ACTOR_TURN, 3),
                               (CELLS, 1), (PICK_ROW, 3), (ITEM_ROW, 3), (ITEM_SLOTS, 1),
                               (ITEM_DEFS, 3)):
            self.assertGreaterEqual(formed.get(address, 0), least, hex(address))

    def test_only_the_hook_sites_change(self):
        retail = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        for i in range(0, len(retail), 4):
            if self.image[i:i + 4] != retail[i:i + 4]:
                a = BTLP + i
                self.assertTrue(START <= a < LEAVE or 0x8008EF60 <= a < 0x8008F05C
                                or 0x8008F2F4 <= a < 0x8008F5DC
                                or 0x80098C18 <= a < 0x80098CF4
                                or a in (0x800A345C, 0x800A37C0, 0x800A3EC8, 0x800A7C8C,
                                         0x800A7E4C, 0x800A3FE0, 0x800A4170, 0x800A4280,
                                         0x800A3AE4, 0x8009E358, 0x800D22E0, 0x800D22EC, 0x800A7E54),
                                hex(a))


if __name__ == '__main__':
    unittest.main()
