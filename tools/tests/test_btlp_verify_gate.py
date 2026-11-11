"""Battle unpacker ownership readback rejects later overlapping writers."""
import contextlib
import io
from pathlib import Path
import re
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import btlp
import toolbelt


class BattleReadbackGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ('BTLP.BIN', 'SLPS_005.00', 'persona.sym', 'btlevt_pairs.asm',
                 'affinity_pool.bin')
        if not all((ROOT / 'build' / n).exists() for n in names):
            raise unittest.SkipTest('requires assembled BTLP build')
        cls.files = {n: (ROOT / 'build' / n).read_bytes() for n in names}
        cls.symbols = {m[2]: int(m[1], 16) for line in cls.files['persona.sym'].decode().splitlines()
                       if (m := re.fullmatch(r'([0-9a-fA-F]{8}) (\w+)', line))}
        if 'btlevt_pairs_end' not in cls.symbols:
            raise AssertionError('assembled symbols missing battle unpacker ownership')
        with contextlib.redirect_stdout(io.StringIO()):
            cls.plan = btlp.evt_plan(btlp.data(), {r['pos']: r for r in toolbelt.merged_rows('BTLP')})

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'build').mkdir()
        for name, data in self.files.items():
            (self.root / 'build' / name).write_bytes(data)
        for name in ('src', 'data', 'external_tools'):
            (self.root / name).symlink_to(ROOT / name, target_is_directory=True)

    def run_verify(self):
        with patch.object(btlp, 'ROOT', str(self.root)), \
             patch.object(btlp, 'evt_plan', return_value=self.plan), \
             contextlib.redirect_stdout(io.StringIO()):
            btlp.verify()

    def corrupt(self, path, offset):
        p = self.root / 'build' / path
        data = bytearray(p.read_bytes())
        data[offset] ^= 1
        p.write_bytes(data)

    def test_original_image_passes_independent_reassembly(self):
        self.run_verify()

    def test_later_writer_overwriting_hook_or_code_fails(self):
        self.corrupt('BTLP.BIN', self.symbols['btl_unpack'] - btlp.B + 0x10)
        with self.assertRaisesRegex(SystemExit, 'hook/code differs'):
            self.run_verify()

    def test_pair_table_corruption_fails(self):
        self.corrupt('BTLP.BIN', self.symbols['btlevt_pairs'] - btlp.B)
        with self.assertRaisesRegex(SystemExit, 'pair table differs'):
            self.run_verify()

    def test_packed_message_corruption_fails(self):
        address = next(a for a in self.plan['place'].values() if btlp.EVT_ZONE[0] <= a < btlp.EVT_UNPACK)
        self.corrupt('BTLP.BIN', address - btlp.B)
        with self.assertRaisesRegex(SystemExit, 'packed message .* overwritten'):
            self.run_verify()

    def test_original_message_reference_corruption_fails(self):
        start = next(a for a, _e in self.plan['msgs'] if self.plan['rf'].get(a))
        _kind, where = self.plan['rf'][start][0]
        self.corrupt('BTLP.BIN', where - btlp.B)
        with self.assertRaisesRegex(SystemExit, 'reference .* overwritten'):
            self.run_verify()

    def test_resident_spill_corruption_fails(self):
        address = next(iter(self.plan['spill']))
        exe = self.files['SLPS_005.00']
        base = struct.unpack_from('<I', exe, 0x18)[0]
        self.corrupt('SLPS_005.00', 0x800 + address - base)
        with self.assertRaisesRegex(SystemExit, 'resident packed text was overwritten|packed message .* overwritten'):
            self.run_verify()


if __name__ == '__main__':
    unittest.main()
