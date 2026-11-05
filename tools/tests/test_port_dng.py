"""Dungeon pair freshness and provenance regressions."""
from pathlib import Path
import sys
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/extraction_tools/matching'))
import port_dng


class DungeonNameCodes(unittest.TestCase):
    def test_source_pointer_is_the_selected_box_not_the_search_anchor(self):
        with patch.object(port_dng, 'boxes', return_value=[(0x100, 'Other'),
                                                            (0x180, 'Target words')]):
            self.assertEqual(port_dng.us_near('d00', 0x190, 'Target'),
                             ('d00', 0x180, 'Target words'))
        with patch.object(port_dng, 'boxes', return_value=[]), \
                patch.object(port_dng, 'us_all', return_value=[('d01', 0x220, 'Target words')]):
            self.assertEqual(port_dng.us_near('d00', 0x190, 'Target'),
                             ('d01', 0x220, 'Target words'))

    def test_psp_names_gain_field_hero_operand_without_swapping(self):
        self.assertEqual(port_dng.clean_us('<FF07> / <FF08> / <FF0F> / <FF10>'),
                         '<FF07><00> / <FF08><00> / <FF0F><00> / <FF07><00> <FF0F><00>')
        self.assertEqual(port_dng.clean_us('<FF07><02>'), '<FF07><02>')

    def test_english_name_kind_does_not_have_to_match_japanese(self):
        ja = '日本語<FF0F><00><FF02><FF01>'
        en = 'Hello <FF07><00>!<FF02><FF01>'
        self.assertNotIn('codes differ', port_dng.fit_report(ja, en, None))

    @unittest.skipUnless((ROOT / 'data/psx/DNG.BIN').exists()
                         and (ROOT / 'data/psx/ADV.BIN').exists(), 'requires retail overlays')
    def test_retail_dispatch_and_name_slots(self):
        # The original jump tables and address loads prove the opcode-to-slot
        # mapping independently of the reference decompilation's labels.
        import partynames
        slots = dict(partynames.retail_slots())
        self.assertNotEqual(slots[2], slots[3])
        base = 0x800643C4
        def word(data, address):
            return struct.unpack_from('<I', data, address - base)[0]
        adv = (ROOT / 'data/psx/ADV.BIN').read_bytes()
        jump = 0x800643D0
        given, family = (word(adv, jump + (op - 1) * 4) for op in (7, 15))
        self.assertEqual((word(adv, given + 12), word(adv, family + 16)),
                         (0x2484904A, 0x24849040))
        dng = (ROOT / 'data/psx/DNG.BIN').read_bytes()
        jump = 0x8006444C
        given, family = (word(dng, jump + op * 4) for op in (7, 15))
        # Operand 1 indexes slot 3 for 07 and slot 2 for 0F; zero branches
        # to the corresponding hero field.
        self.assertEqual(word(dng, given + 12), 0x00021040)  # id * 2
        self.assertEqual(word(dng, given + 16), 0x24510001)  # +1
        self.assertEqual(word(dng, family + 12), 0x00048840)  # id * 2


class DungeonPairs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for region in ('jp', 'us'):
            p = self.root / f'data/psp_{region}/PSP_GAME/USRDIR/pack/dng/d00/d00.bin'
            p.parent.mkdir(parents=True)
            p.write_bytes(b'fixture')
        p = patch.object(port_dng, 'ROOT', str(self.root))
        p.start()
        self.addCleanup(p.stop)

    def test_refreshes_both_regions_without_existing_cache_tree(self):
        samples = {'jp': [(0x100, '日本語')], 'us': [(0x200, 'English text')]}
        with patch.object(port_dng, 'boxes', side_effect=lambda r, sub: samples[r]) as reader:
            pairs = port_dng.paired_boxes()
        self.assertEqual(reader.call_args_list[0].args, ('jp', 'd00'))
        self.assertEqual(reader.call_args_list[1].args, ('us', 'd00'))
        self.assertEqual(pairs, [('d00', 0x200, port_dng.strlib.norm('日本語'), 'English text')])

    def test_differently_paginated_regions_do_not_pair_by_index(self):
        samples = {'jp': [(0x100, '日本語'), (0x150, '日本語')],
                   'us': [(0x200, 'English text')]}
        with patch.object(port_dng, 'boxes', side_effect=lambda r, sub: samples[r]):
            self.assertEqual(port_dng.paired_boxes(), [])

    def test_generated_translation_supersedes_queue_rows_but_keeps_human_english(self):
        toolbelt = port_dng.toolbelt
        generated = self.root / 'generated'
        manual = self.root / 'manual'
        with patch.object(toolbelt, 'GENERATED', str(generated)), \
                patch.object(toolbelt, 'MANUAL', str(manual)), \
                patch.object(toolbelt, 'psx_text_of', return_value={}):
            path = Path(toolbelt.man_path('D00/D00'))
            path.parent.mkdir(parents=True)
            path.write_text('id\tpos\tpsp\ten\tnote\n'
                            '0\t0x10\t\t\tunpaired; ja 日本語\n'
                            '1\t0x20\t\tHuman text\t\n'
                            '2\t0x30\t\t\tcheck the tone\n', encoding='utf-8')
            toolbelt.upsert_generated('D00/D00',
                                     [{'pos': '0x10', 'psp': 'd00:200', 'en': 'Source text'},
                                      {'pos': '0x30', 'psp': 'd00:230', 'en': 'Other text'}])
            rows = toolbelt.read_manual('D00/D00')
            # Rows with empty English are queue rows whatever their note:
            # filled generated wording supersedes both; human English stays.
            self.assertEqual([(r['pos'], r['en']) for r in rows],
                             [('0x20', 'Human text')])
            self.assertEqual(toolbelt.read_generated('D00/D00')[0]['en'], 'Source text')

    def test_missing_region_is_not_a_pair(self):
        (self.root / 'data/psp_us/PSP_GAME/USRDIR/pack/dng/d00/d00.bin').unlink()
        with patch.object(port_dng, 'boxes') as reader:
            self.assertEqual(port_dng.paired_boxes(), [])
            reader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
