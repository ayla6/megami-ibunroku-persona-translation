"""Every patch that takes slots from BTLP's per-frame primitive pool has a
contract test.

BtlInitObjects tags the pool's typed runs once per battle; the game's users
take slots by advancing a run's cursor and rewrite only colours and corners
(addresses.inc, "BTLP's per-frame primitive pool"). A patch that takes a slot
and leaves it as another primitive breaks whichever retail user takes that
slot next - the range overlay's flat quads once turned the level-up board's
stat bars into screen-wide triangles.

This scans the assembled BTLP: every patched instruction pair (lui + load or
store) that reaches a run cursor must come from a source file registered in
CONTRACTS with the test that proves its slots keep the game's shape.

Run after a build: it reads build/BTLP.BIN, build/armips-main.lst.
"""
from pathlib import Path
import importlib
import re
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
from toolbelt import asm_equ  # noqa: E402

BASE = 0x800643C4
CURSORS = ('BTL_SPRT_NEXT', 'BTL_TILE_NEXT', 'BTL_POLYFT4_NEXT', 'BTL_POLYF4_NEXT',
           'BTL_POLYG4_NEXT', 'BTL_LINEG2_NEXT', 'BTL_DRMODE_NEXT')
# source file -> (test module, class, method) proving the contract
CONTRACTS = {
    'src/asm/qol/range_btlp.asm': ('test_qol_range', 'Range',
                                   'test_borrowed_slots_keep_the_games_shape'),
}
LOADS_STORES = (0x20, 0x21, 0x23, 0x24, 0x25, 0x28, 0x29, 0x2B)


def cursor_sites(words, base, cursors, patched):
    """Addresses of patched instructions whose lui pair reaches a cursor."""
    out = set()
    for i, word in enumerate(words):
        if word >> 26 != 0x0F or base + 4 * i not in patched:
            continue
        rt, hi = (word >> 16) & 31, (word & 0xFFFF) << 16
        for j in range(i + 1, min(i + 64, len(words))):
            other = words[j]
            op = other >> 26
            if op in LOADS_STORES + (0x09,) and (other >> 21) & 31 == rt:
                imm = other & 0xFFFF
                target = (hi + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF
                if target in cursors:
                    out.add(base + 4 * j)
            # follow the base register until something else is written to it
            dest = (other >> 11) & 31 if op == 0 else (
                None if op in (0x28, 0x29, 0x2B, 0x3A) or 1 <= op <= 7 else (other >> 16) & 31)
            if dest == rt:
                break
    return out


def listing_sources():
    """address -> source file of every BTLP-range instruction in the build."""
    out = {}
    pattern = re.compile(r'^([0-9A-F]{8}) .*; (\S+\.asm) line \d+')
    for line in (ROOT / 'build/armips-main.lst').read_text(errors='replace').splitlines():
        match = pattern.match(line)
        if match:
            address = int(match[1], 16)
            path = Path(match[2])
            try:
                path = path.resolve().relative_to(ROOT)
            except ValueError:
                pass
            out[address] = str(path)
    return out


class PrimPoolBorrowers(unittest.TestCase):
    def test_every_cursor_user_has_a_contract_test(self):
        built_path = ROOT / 'build/BTLP.BIN'
        if not built_path.exists() or not (ROOT / 'build/armips-main.lst').exists():
            self.skipTest('requires an assembled build')
        built = built_path.read_bytes()
        retail = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        words = struct.unpack_from(f'<{len(built) // 4}I', built)
        patched = {BASE + 4 * i for i, word in enumerate(words)
                   if 4 * i + 4 > len(retail) or
                   struct.unpack_from('<I', retail, 4 * i)[0] != word}
        cursors = {asm_equ(name) for name in CURSORS}
        sources = listing_sources()
        sites = cursor_sites(words, BASE, cursors, patched)
        users = {}
        for site in sites:
            users.setdefault(sources.get(site, f'unknown source at {site:#x}'), []).append(site)
        unregistered = {src: [hex(a) for a in sorted(sites)]
                        for src, sites in users.items() if src not in CONTRACTS}
        self.assertFalse(unregistered,
                         'patch code takes primitive-pool slots without a contract test '
                         '(add one like test_qol_range.Range.test_borrowed_slots_keep_the_games_shape '
                         f'and register it in CONTRACTS): {unregistered}')

    def test_registered_contracts_exist(self):
        for source, (module, cls, method) in CONTRACTS.items():
            with self.subTest(source=source):
                self.assertTrue((ROOT / source).exists())
                self.assertTrue(callable(getattr(getattr(importlib.import_module(module), cls),
                                                 method, None)))

    def test_the_scan_sees_a_borrower(self):
        """A lui / lw pair on a cursor in patched code is found; the same
        pair in unpatched code is not."""
        cursor = asm_equ('BTL_POLYG4_NEXT')
        hi = (cursor + 0x8000) >> 16
        lo = (cursor - (hi << 16)) & 0xFFFF
        words = (0x3C100000 | hi, 0x8E110000 | lo)      # lui s0, hi / lw s1, lo(s0)
        self.assertEqual(cursor_sites(words, BASE, {cursor}, {BASE, BASE + 4}), {BASE + 4})
        self.assertEqual(cursor_sites(words, BASE, {cursor}, set()), set())


if __name__ == '__main__':
    unittest.main()
