"""Menu attenuation changes velocity bytes only and can restore exact inputs."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import toolpath  # noqa: E402,F401
import menu_sounds as sound


class MenuSounds(unittest.TestCase):
    def test_default_comes_from_the_range_setting_and_previews_are_opt_in(self):
        import mods
        self.assertEqual(sound.default_level(), 75)
        self.assertEqual(mods.by_label()['softer-menu-sounds'].defaults(), frozenset(['level=75']))
        # Building the sound edits has no dependency on the analysis/preview module.
        import ast
        tree = ast.parse(Path(sound.__file__).read_text())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertFalse(any('analyze' in ast.unparse(n) for n in imports))

    def test_running_status_note_off_and_midi_structure(self):
        data = bytes([0, 0x90, 60, 100, 10, 62, 80, 10, 62, 0, 0, 0x80, 60, 30, 0, 255, 47, 0])
        end, positions = sound.events(data, 0)
        self.assertEqual(end, len(data))
        self.assertEqual(positions, [3, 6])
        modified = bytearray(data)
        for at in positions:
            modified[at] //= 2
        self.assertEqual(sound.events(bytes(modified), 0), (end, positions))
        with self.assertRaises(ValueError):
            sound.events(b'\0\1\2', 0)

    def test_name_entry_music_is_not_a_menu_cue(self):
        import struct
        data = (sound.RETAIL / 'NAMEDT.BIN').read_bytes()
        start = struct.unpack_from('<I', data, 15 * 4)[0] + 15
        end, _velocities = sound.events(data, start)
        self.assertNotIn(data[start:end], sound.cues())

    def test_field_navigation_confirm_and_back_are_selected(self):
        self.assertEqual(sound.UI_SOURCES, {'ADV/ADVCMD.BIN': tuple(range(8, 13))})
        with self.assertRaises(ValueError):
            sound.plan(-1)

    def test_field_cues_cover_overworld_copies_and_exclude_title_cues(self):
        import struct
        cues = sound.cues()
        data = (sound.RETAIL / '2D/2DSEQ00.BIN').read_bytes()
        for index in range(5, 10):
            start = struct.unpack_from('<I', data, index * 4)[0] + 15
            end, _velocities = sound.events(data, start)
            self.assertIn(data[start:end], cues)
        start = struct.unpack_from('<I', data, 10 * 4)[0] + 15
        end, _velocities = sound.events(data, start)
        self.assertNotIn(data[start:end], cues)
        data = (sound.RETAIL / 'OPEN.BIN').read_bytes()
        for index in (8, 9):
            start = struct.unpack_from('<I', data, index * 4)[0] + 15
            end, _velocities = sound.events(data, start)
            self.assertNotIn(data[start:end], cues)

    def test_apply_restore_preserves_other_bytes_and_existing_build_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            retail, build = root / 'retail', root / 'build'
            retail.mkdir()
            build.mkdir()
            (retail / 'FILE.BIN').write_bytes(b'original')
            live = build / 'FILE.BIN'
            live.write_bytes(b'translat')
            before = live.read_bytes()
            edits = [sound.Edit('FILE.BIN', 3, before[3], before[3] // 2)]
            with patch.object(sound, 'BUILD', build), patch.object(sound, 'RETAIL', retail):
                sound.apply(edits)
                self.assertEqual(live.read_bytes(), before[:3] + bytes([before[3] // 2]) + before[4:])
                sound.apply(edits, reverse=True)
                self.assertEqual(live.read_bytes(), before)
                sound.apply(edits, reverse=True)
                live.write_bytes(b'new data')
                with self.assertRaises(ValueError):
                    sound.apply(edits)
