"""One retail screen, several overlays: every compiled copy must be patched.

S2D, DNG and ADV each link their own copy of the menu code (the same
source compiled into three overlays). A rewrite of one copy leaves the
other two on retail behaviour, which is how the Analyze -> Demon bar kept
its fixed-width record head after ADV/DNG were fixed: S2D's
PersonaDataDraw was a separate copy nobody had listed.

The copies are not byte-identical, because every overlay links its own
data addresses; they are instruction-identical once the immediates of
`lui`/`addiu`/`ori` are masked. This test fingerprints the retail copy of
each rewritten function and searches every retail code image for windows
with the same structure. The set it finds must be exactly the set of
patch sites the assembler rewrites: a copy nobody declared fails here,
so a new clone shows up as "declare or patch", never as a silent retail
screen.

The scan is a census, not a disassembler. It masks literals only, so a
copy compiled with different `#define`s (DNG's DrawSpellName) is found
from its own declared member, and an unrelated function that happens to
share a whole 20-48 instruction structure is not realistic.

Run after assembly:
    python -m unittest discover -s tools/tests -p test_overlay_clones.py -v
"""
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[2]
OVERLAY_BASE = 0x800643C4

# Every retail image that can carry a copy of the menu code. SLPS and the
# other EXEs are scanned too: they are the same CPU and the same link
# conventions, and the census only needs a base-independent scan.
IMAGES = ('ADV.BIN', 'DNG.BIN', 'S2D.BIN', 'BTLP.BIN', 'CASINO.BIN',
          'SLPS_005.00', 'OPEN.BIN')

# name -> (length, [(overlay, retail address), ...]); each listed address is
# rewritten in place by the assembler (src/asm/<overlay>/).
FAMILIES = {
    'PersonaDataDraw bar tail': (0x70, (
        ('ADV', 0x80099014),
        ('DNG', 0x800998F8),
        ('S2D', 0x800899F4),
    )),
    'StatusPersonaNames': (0xC0, (
        ('ADV', 0x80070144),
        ('DNG', 0x8007F464),
        ('S2D', 0x8006F26C),
    )),
    'CellsWriteRow': (0xC0, (
        ('ADV', 0x8008F730),
        ('DNG', 0x8009392C),
        ('S2D', 0x80083A64),
    )),
    'DrawSpellName': (0xBC, (
        ('ADV', 0x8007BA94),
        ('DNG', 0x8008A8A4),
        ('S2D', 0x8007A908),
    )),
}

# `lui`/`addiu`/`ori` carry overlay-local data addresses (and nothing else in
# these spans), so only their immediate field is ignored. Everything else,
# including branch offsets, is part of the fingerprint.
_LITERAL_IMMEDIATE = {9, 13, 15}          # addiu, ori, lui


def _signature(word):
    """The instruction with its data literal masked."""
    op = word >> 26
    if op in _LITERAL_IMMEDIATE:
        return (op, (word >> 21) & 0x1F, (word >> 16) & 0x1F, None)
    if op == 0:                            # SPECIAL: funct selects the op
        return (0, word & 0x3F, (word >> 6) & 0x1F,
                (word >> 11) & 0x1F, (word >> 16) & 0x1F)
    return (op, (word >> 21) & 0x1F, (word >> 16) & 0x1F, word & 0xFFFF)


class OverlayClones(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        needed = [ROOT / 'build' / f'{n}.BIN' for n in ('ADV', 'DNG', 'S2D')]
        needed += [ROOT / 'data/psx' / n for n in IMAGES]
        if not all(p.exists() for p in needed):
            raise unittest.SkipTest('requires the assembled overlays')
        cls.retail = {n: (ROOT / 'data/psx' / n).read_bytes() for n in IMAGES}
        cls.built = {n: (ROOT / 'build' / f'{n}.BIN').read_bytes()
                     for n in ('ADV', 'DNG', 'S2D')}

    def _words(self, name):
        data = self.retail[name]
        return list(struct.unpack_from(f'<{len(data) // 4}I', data))

    def _find(self, overlay, address, length):
        """Every window in every retail image with this member's structure."""
        member = struct.unpack_from(f'<{length // 4}I',
                                    self.retail[f'{overlay}.BIN'],
                                    address - OVERLAY_BASE)
        want = [_signature(w) for w in member]
        # Only the first instruction is compared until it matches; functions
        # that start alike (addiu sp,sp,-frame) then pay the full comparison.
        first = want[0]
        tail = want[1:]
        hits = []
        for name in IMAGES:
            words = self._words(name)
            base = 0 if name in ('SLPS_005.00', 'OPEN.BIN') else OVERLAY_BASE
            for offset in range(0, len(words) - len(member) + 1):
                if _signature(words[offset]) != first:
                    continue
                if all(_signature(words[offset + i]) == sig
                       for i, sig in enumerate(tail, 1)):
                    hits.append((name, base + offset * 4))
        return hits

    def test_every_compiled_copy_is_a_declared_patch_site(self):
        for family, (length, members) in FAMILIES.items():
            declared = {(f'{overlay}.BIN', address)
                        for overlay, address in members}
            found = set()
            for overlay, address in members:
                found.update(self._find(overlay, address, length))
            with self.subTest(family=family):
                self.assertEqual(
                    sorted(found), sorted(declared),
                    f'{family}: retail copies found outside the declared '
                    f'patch sites: {sorted(found - declared)}; declared but '
                    f'not found (wrong span?): {sorted(declared - found)}')

    def test_every_declared_site_is_rewritten(self):
        # A census is only useful if each listed copy is actually patched;
        # a declared-but-still-retail site would otherwise pass the census.
        for family, (length, members) in FAMILIES.items():
            for overlay, address in members:
                with self.subTest(family=family, overlay=overlay):
                    offset = address - OVERLAY_BASE
                    retail = self.retail[f'{overlay}.BIN'][offset:offset + length]
                    built = self.built[overlay][offset:offset + length]
                    self.assertEqual(len(built), length)
                    self.assertNotEqual(
                        built, retail,
                        f'{family} at {overlay} {address:#x} is still retail')


if __name__ == '__main__':
    unittest.main()
