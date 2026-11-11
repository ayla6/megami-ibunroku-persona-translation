"""Build-time field-title constraints and independent readback failure cases."""
import contextlib
import io
import re
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src' / 'injection_tools'))
import dngnames
import vwf_wrap


class TitleGeneratorGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.asm = str(Path(self.tmp.name) / 'titles.asm')
        self.bin = str(Path(self.tmp.name) / 'titles.bin')
        self.widths = (ROOT / 'src/asm/font/vwf_width.bin').read_bytes()
        index = (ROOT / 'src/asm/font/vwf_index.bin').read_bytes()
        self.offsets = struct.unpack(f'<{len(self.widths)}H', index)

    def emit(self, label, script=None, width=None):
        rows = [('unused', 0, 'key', label, '')]
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(dngnames, 'TITLE_ASM', self.asm))
            stack.enter_context(patch.object(dngnames, 'TITLE_IMAGE', self.bin))
            stack.enter_context(patch.object(dngnames, 'pack_field', return_value=bytes(range(20))))
            if script is not None:
                stack.enter_context(patch.object(dngnames, 'vwf_bytes', return_value=script))
            if width is not None:
                stack.enter_context(patch.object(vwf_wrap, 'text_width', return_value=width))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            dngnames.emit_titles(rows, {'key': label})

    def test_serializes_complete_valid_title(self):
        self.emit('A')
        data = Path(self.bin).read_bytes()
        self.assertEqual(data[:20], bytes(range(20)))
        self.assertEqual(data[20], self.widths[ord('A') - 0x20])
        self.assertEqual(data[24:], b'\xa9\xff\x01')
        self.assertIn('dng_title_blob_end:', Path(self.asm).read_text())

    def test_rejects_overwide_full_title_without_shortening(self):
        # 19 'R's is 171px: wider than the 160px held-pause strip, but still
        # short enough to reach that check (33+ glyphs fail the cells first).
        with self.assertRaisesRegex(SystemExit, 'exceeds held-pause strip'):
            self.emit('R' * 19)
        self.assertFalse(Path(self.bin).exists())

    def test_rejects_title_longer_than_the_map_name_cells(self):
        # MapDrawName's script area is 0x22 bytes: 32 glyph bytes + FF 01.
        with self.assertRaisesRegex(SystemExit, 'map-name cells'):
            self.emit('R' * 33)
        self.assertFalse(Path(self.bin).exists())

    def test_rejects_non_vwf_encoded_byte(self):
        with self.assertRaisesRegex(SystemExit, 'not a plain VWF glyph run'):
            self.emit('A', script=b'\x87\xff\x01', width=1)

    def test_rejects_nonspace_glyph_that_shares_the_blank_slot(self):
        missing = next((i for i in range(1, len(self.offsets)-1) if self.offsets[i] == self.offsets[0]), None)
        if missing is None:
            self.skipTest('the current font allocates every glyph')
        with self.assertRaisesRegex(SystemExit, 'unallocated VWF glyph'):
            self.emit('A', script=bytes([missing + 0x88, 0xff, 1]), width=self.widths[missing])

    def test_rejects_width_disagreement(self):
        with self.assertRaisesRegex(SystemExit, 'width disagrees'):
            self.emit('A', width=1)


class TitleReadbackGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = [ROOT / 'build' / n for n in ('DNG.BIN', 'dng_titles.bin', 'persona.sym')]
        if not all(p.exists() for p in required):
            raise unittest.SkipTest('requires assembled field-title output')
        cls.original = required[0].read_bytes()
        cls.title = required[1].read_bytes()
        cls.symtext = required[2].read_text()
        cls.sym = {m[2]: int(m[1],16) for line in cls.symtext.splitlines()
                   if (m := re.fullmatch(r'([0-9a-fA-F]{8}) (\w+)', line))}
        if 'dng_field_title_pixels' not in cls.sym:
            raise AssertionError('assembled symbols missing field-title hook')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'build').mkdir()
        for part in ('data', 'src', 'external_tools'):
            (self.root / part).symlink_to(ROOT / part, target_is_directory=True)
        self.image = self.root / 'build/DNG.BIN'
        self.image.write_bytes(self.original)
        (self.root / 'build/dng_titles.bin').write_bytes(self.title)
        (self.root / 'build/persona.sym').write_text(self.symtext)

    def verify(self):
        with patch.object(dngnames, 'ROOT', str(self.root)), \
             patch.object(dngnames, 'TITLE_IMAGE', str(self.root / 'build/dng_titles.bin')), \
             contextlib.redirect_stdout(io.StringIO()):
            dngnames.verify()

    def corrupt(self, address):
        data = bytearray(self.original)
        data[address - 0x800643C4] ^= 1
        self.image.write_bytes(data)

    def test_valid_reassembly_passes(self):
        self.verify()

    def test_rejects_later_writer_overwriting_uploader_jump(self):
        self.corrupt(0x8006E700)
        with self.assertRaisesRegex(SystemExit, 'hook/code differs'):
            self.verify()

    def test_rejects_later_writer_overwriting_hook_code(self):
        self.corrupt(self.sym['dng_field_title_hook'] + 0x40)
        with self.assertRaisesRegex(SystemExit, 'hook/code differs'):
            self.verify()

    def test_rejects_nonzero_pixel_scratch(self):
        self.corrupt(self.sym['dng_field_title_pixels'])
        with self.assertRaisesRegex(SystemExit, 'scratch is not zero'):
            self.verify()

    def test_every_translated_built_floor_resolves_its_complete_title(self):
        rows = dngnames.build_rows()
        resolved = dngnames.resolved_en(rows)
        idx = self.sym['dng_title_idx'] - 0x800643C4
        blob = self.sym['dng_title_blob'] - 0x800643C4
        count = (blob - idx) // 24
        titles = {}
        for i in range(count):
            row = self.original[idx + i * 24:idx + (i + 1) * 24]
            offset = struct.unpack_from('<H', row, 22)[0]
            start = blob + offset
            end = self.original.index(b'\xff\x01', start) + 2
            titles[row[:20]] = self.original[start:end]
        checked = 0
        for rel, off, ja, _generated, _psp in rows:
            en = resolved.get(ja, '')
            if not en.strip():
                continue
            path = ROOT / 'build' / (rel + '.BIN')
            data = path.read_bytes()
            key = data[off:off + 20]
            with self.subTest(rel=rel, offset=hex(off)):
                self.assertIn(key, titles, 'built floor field does not resolve in the title table')
                self.assertEqual(titles[key], dngnames.vwf_bytes(en),
                                 'built floor resolves to different wording')
            checked += 1
        self.assertGreater(checked, 0)

    def test_rejects_corrupted_title_table(self):
        self.corrupt(self.sym['dng_title_idx'])
        with self.assertRaisesRegex(SystemExit, 'table/blob differs'):
            self.verify()


if __name__ == '__main__':
    unittest.main()
