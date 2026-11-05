"""TALK messages can start and end on either side of unit pointers."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/extraction_tools/matching'))
import port_talk


class TalkBoundaries(unittest.TestCase):
    def rows(self, name):
        if not Path(port_talk.PUS, name + '.BIN').exists():
            self.skipTest('PSP TALK data unavailable')
        with patch.object(port_talk.toolbelt, 'upsert_generated'), \
             patch.object(port_talk.toolbelt, 'route_over'), \
             patch.object(port_talk.toolbelt, 'route_gaps'):
            return {k: en for k, _ja, en, _err in port_talk.main(name, verbose=False)}

    def test_first_message_includes_prefix_before_first_pointer(self):
        rows = self.rows('BASKET')
        self.assertTrue(rows[0].startswith('Athletic types like me'))

    def test_complete_tail_does_not_absorb_next_message(self):
        rows = self.rows('GAKI')
        self.assertEqual(rows[164], '...Later!<FFEF>')
        self.assertEqual(rows[165], "You're such a cool<FFF6>guy, so take this too!<FFEF>")
        self.assertNotIn('I wa<FFEF>', rows[214])


if __name__ == '__main__':
    unittest.main()
