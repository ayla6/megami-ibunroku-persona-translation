"""Independent US extraction and PSX TALK injection do not need PSP-JP."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'src/extraction_tools/psp')]
sys.path.insert(0, str(ROOT / 'src/extraction_tools/matching'))
import eboot
import tables
import talk
import port_talk
import toolbelt


class PSPJPIndependence(unittest.TestCase):
    def test_us_only_extract_never_opens_japanese_boot(self):
        with patch.object(sys, 'argv', ['eboot.py', '--us-only']), \
                patch.object(eboot, 'us_boot', return_value=b'us'), \
                patch.object(eboot, 'dump') as dump, \
                patch.object(tables, 'jp_boot', side_effect=AssertionError('JP read')), \
                patch.object(tables, 'jp_map', side_effect=AssertionError('JP map')):
            eboot.main()
        dump.assert_called_once()
        self.assertEqual(dump.call_args.args[:2], ('psp_us', b'us'))

    def test_talk_build_does_not_refresh_psp_japanese(self):
        unit = talk.etext.encode('Original<FFF5>', end=None)
        fake = SimpleNamespace(units=[unit], starts=[16], ok=False, data=b'original',
                               rebuild=lambda edits, answers: edits[0])
        with tempfile.TemporaryDirectory() as output, \
                patch.object(talk, 'files', return_value=['TEST.BIN']), \
                patch.object(talk, 'load', return_value=fake), \
                patch.object(talk, 'canon_texts', return_value=({'0x10': 'Hello<FFF5>'}, {})), \
                patch.object(talk, '_qa', return_value=[]), \
                patch.object(talk, '_refresh_corpus', side_effect=AssertionError('JP read')):
            talk.cmd_build(output)
            self.assertEqual((Path(output) / 'TEST.BIN').read_bytes(),
                             talk.etext.encode('Hello<FFF5>', end=None))

    @unittest.skipUnless((ROOT / 'data/psx/TALK/ALIEN.BIN').exists() and
                         (ROOT / 'data/psp_us/PSP_GAME/USRDIR/pack/talk/ALIEN.BIN').exists(),
                         'requires PSX and PSP-US TALK inputs')
    def test_talk_port_does_not_read_japanese_psp_text(self):
        read = toolbelt.read_extracted
        def no_jp(region, *args, **kwargs):
            if region == 'psp_jp':
                raise AssertionError('PSP-JP text was read')
            return read(region, *args, **kwargs)
        with patch.object(toolbelt, 'read_extracted', side_effect=no_jp), \
                patch.object(toolbelt, 'upsert_generated'), \
                patch.object(toolbelt, 'route_over'), \
                patch.object(toolbelt, 'route_gaps'):
            rows = port_talk.main('ALIEN', max_units=20, verbose=False)
        self.assertTrue(rows)


if __name__ == '__main__':
    unittest.main()
