"""Affinity regeneration must not rewrite existing human worklist rows."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'src/extraction_tools/matching')]
import affinity
import port_affinity
import toolbelt

class AffinityManualPreservation(unittest.TestCase):
    def test_purge_preserves_existing_note_even_with_machine_prefix(self):
        row = {'id': '0', 'pos': hex(0x8004c848 - port_affinity.B),
               'psp': 'EBOOT:1', 'en': 'Human',
               'note': 'over limit is my own note'}
        before = dict(row)
        with patch.object(affinity, 'records', return_value=[(0, 0x8004c848, 'ja')]), \
             patch.object(toolbelt, 'read_generated', return_value=[]), \
             patch.object(toolbelt, 'read_manual', return_value=[row]), \
             patch.object(toolbelt, 'write_manual') as write:
            port_affinity.purge()
        self.assertEqual(row, before)
        write.assert_not_called()

    def test_queue_does_not_replace_manual_english(self):
        pos = hex(0x8004c848 - port_affinity.B)
        for en, note in [('Human translation', 'Human note')]:
            row = {'id':'0', 'pos':pos, 'psp':'EBOOT:1', 'en':en, 'note':note}
            before = dict(row)
            with self.subTest(en=en), \
                 patch.object(port_affinity, '_be', return_value=[(0x27baa4 + i, 'source', 'FF01') for i in range(120)]), \
                 patch.object(affinity, 'records', return_value=[(0, 0x8004c848, 'ja')]), \
                 patch.object(toolbelt, 'read_manual', return_value=[row]), \
                 patch.object(toolbelt, 'write_manual') as write:
                port_affinity.queue_manual()
            self.assertEqual(row, before)
            write.assert_called_once_with('SLPS_005.00', [row])

    def test_queues_exact_sources_and_no_english(self):
        source = [(0x27baa4 + i, f'US {i}<FF01>', 'FF01') for i in range(120)]
        with patch.object(port_affinity, '_be', return_value=source), \
             patch.object(affinity, 'records', return_value=[(2, 0x8004c87a, '日本語')]), \
             patch.object(toolbelt, 'read_manual', return_value=[]), \
             patch.object(toolbelt, 'write_manual') as write:
            port_affinity.queue_manual()
        row = write.call_args.args[1][0]
        self.assertEqual(row['en'], '')
        self.assertEqual(row['psp'], 'EBOOT:27baa6')
        self.assertEqual(row['note'], 'JP: 日本語 | US: US 2')

if __name__ == '__main__':
    unittest.main()
