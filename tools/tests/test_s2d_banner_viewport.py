"""The QoL subframe path must retain the banner's temporary viewport offset."""
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASE = 0x800643C4


class BannerViewport(unittest.TestCase):
    def test_text_and_plate_retain_matching_offsets_and_restore_the_object(self):
        original = (ROOT / 'data/psx/S2D.BIN').read_bytes()
        built = (ROOT / 'build/S2D.BIN').read_bytes()
        # Text: load object.geom_x, add the viewport offset, write it back.
        # After drawing, restore geom_x from saved_geom_x. The plate then
        # independently adds the same offset to its local copy. These are
        # geometry operations, so all remain intact on interpolated draws.
        for address, count in ((0x80093E14, 6), (0x80093E8C, 5), (0x80093F88, 4)):
            at = address - BASE
            self.assertEqual(built[at:at + count * 4], original[at:at + count * 4])
        self.assertEqual(struct.unpack_from('<I', built, 0x80093E20 - BASE)[0], 0x244200F0)
        self.assertEqual(struct.unpack_from('<I', built, 0x80093F90 - BASE)[0], 0x248400F0)
