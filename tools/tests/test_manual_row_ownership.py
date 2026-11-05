"""Manual ownership: a row's English is the human's; a row with empty English
(a queue row) is the tools', note and all."""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/injection_tools'))
import toolbelt

class ManualRowOwnership(unittest.TestCase):
    def setUp(self):
        # Never let a unit test touch the real translation tree: an empty
        # write prunes the file it names.
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        for name, sub in (('MANUAL', 'manual'), ('GENERATED', 'generated')):
            p = patch.object(toolbelt, name, str(Path(self._tmp.name, sub)))
            p.start()
            self.addCleanup(p.stop)

    def test_refused_draft_cannot_replace_human_wording_with_psp_locator(self):
        for psp in ('', 'EBOOT:1234'):
            with self.subTest(psp=psp):
                row = {'id': '7', 'pos': '0x123', 'psp': psp,
                       'en': 'Human wording', 'note': 'Human note'}
                before = dict(row)
                with patch.object(toolbelt, 'read_manual', return_value=[row]), \
                     patch.object(toolbelt, 'write_manual') as write, \
                     patch.object(toolbelt, '_drop_generated') as drop:
                    changed = toolbelt.route_to_manual('BTLP', {
                        'pos': row['pos'], 'psp': 'EBOOT:9999', 'en': '',
                        'note': 'over limit 20 chars/15 chars; PSP wording'})
                self.assertFalse(changed)
                self.assertEqual(row, before)
                write.assert_not_called()
                drop.assert_not_called()

    def test_route_over_preserves_human_english_and_note_with_source(self):
        row = {'id': '7', 'pos': '0x123', 'psp': 'EBOOT:1234',
               'en': 'Full human wording', 'note': 'Do not alter this'}
        before = dict(row)
        with patch.object(toolbelt, 'read_manual', return_value=[row]), \
             patch.object(toolbelt, 'read_generated', return_value=[]), \
             patch.object(toolbelt, 'write_manual') as write:
            toolbelt.route_over('BTLP', row['pos'], 'EBOOT:9999',
                                'source wording', 'over limit 20 chars/15 chars')
        self.assertEqual(row, before)
        write.assert_not_called()

    def test_filled_generated_row_supersedes_every_queue_row(self):
        for note in ('psp exact candidate', 'over limit 18 chars/15 chars; full wording',
                     'unpaired; ja example', 'Please keep this research note', ''):
            with self.subTest(note=note):
                row={'id':'7','pos':'0x123','psp':'EBOOT:1234','en':'','note':note}
                with patch.object(toolbelt,'read_manual',return_value=[dict(row)]), \
                     patch.object(toolbelt,'read_generated',return_value=[{'pos':'0x123','en':'Covered'}]), \
                     patch.object(toolbelt,'psx_text_of',return_value={'0x123':'source'}), \
                     patch.object(toolbelt,'write_manual') as write:
                    toolbelt.route_gaps('BTLP',['0x123'])
                self.assertEqual(write.call_args.args[1],[])

    def test_a_queue_rows_note_is_the_tools(self):
        for old in ('psp exact; an annotation', 'unpaired; ja example', 'anything at all'):
            with self.subTest(old=old):
                row={'id':'7','pos':'0x123','psp':'','en':'','note':old}
                new='over limit 11 cells/10 cells; GODDESS SET'
                with patch.object(toolbelt,'read_manual',return_value=[dict(row)]), \
                     patch.object(toolbelt,'write_manual') as write, \
                     patch.object(toolbelt,'_drop_generated'):
                    toolbelt.route_to_manual('BTLP',{'pos':'0x123','en':'','note':new})
                self.assertEqual(write.call_args.args[1][0]['note'], new)

    def test_manual_writer_protects_rows_with_english(self):
        row={'id':'7','pos':'0x123','psp':'','en':'Human wording','note':'my note'}
        for field,new in (('en','Replacement'),('en',''),('note','over limit; machine replacement')):
            changed=dict(row);changed[field]=new
            with self.subTest(field=field,new=new), patch.object(toolbelt,'read_manual',return_value=[row]):
                with self.assertRaises(SystemExit):toolbelt.write_manual('BTLP',[changed])
        with patch.object(toolbelt,'read_manual',return_value=[row]):
            with self.assertRaises(SystemExit):toolbelt.write_manual('BTLP',[])

    def test_manual_writer_may_drop_any_queue_row(self):
        for note in ('unpaired; ja example', 'Keep this note; it is mine'):
            row={'id':'7','pos':'0x123','psp':'','en':'','note':note}
            with self.subTest(note=note), patch.object(toolbelt,'read_manual',return_value=[row]):
                self.assertEqual(toolbelt.write_manual('BTLP',[]),0)


if __name__ == '__main__':
    unittest.main()
