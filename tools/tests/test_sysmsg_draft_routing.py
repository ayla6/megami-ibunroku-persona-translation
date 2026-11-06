"""A sysmsg wording over its viewport line never ships and never fails the
build: a tool's wording goes to manual as an over-limit draft, a human's row
is kept and reported, and the message keeps its Japanese."""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import sysmsg
import toolbelt

# The Velvet Room Persona-delete prompt: one 240 px row, 342 px wording.
POS = '0x56df2'
INDEX = 7                      # 0x56df2 is message 7 in the zone order
PSP = 'EBOOT:2d4b02'
WIDENED = 'Are you certain that you wish to<FF03>delete this Persona?<FF01>'
DRAFT = 'Are you certain that you wish to delete this Persona?<FF01>'
REASON = 'over limit 342px/240px'


def run_build(rows, manual):
    with TemporaryDirectory() as d:
        root = Path(d)
        with patch.object(sysmsg, 'OUT', str(root / 'sysmsg.asm')), \
             patch.object(sysmsg, 'PLACED', str(root / 'sysmsg_placed.json')), \
             patch.object(sysmsg, 'DRAFT_OUT', str(root / 'sysmsg_drafts.tsv')), \
             patch.object(sysmsg, 'read_tsv', return_value=rows), \
             patch.object(toolbelt, 'read_manual', return_value=manual), \
             patch.object(toolbelt, 'route_over') as route:
            sysmsg.build()
            return route, (root / 'sysmsg_drafts.tsv').read_text(), \
                (root / 'sysmsg.asm').read_text()


def row(en):
    return {'id': '1', 'pos': POS, 'psp': PSP, 'en': en, 'note': 'PSP-US'}


class OverLimitRows(unittest.TestCase):
    def test_a_tool_row_is_routed_to_manual_as_a_draft(self):
        route, drafts, asm = run_build({INDEX: row(WIDENED)}, [])
        route.assert_called_once()
        rel, pos, psp, draft, reason = route.call_args.args
        self.assertEqual((rel, pos, psp), ('ADV', POS, PSP))
        self.assertEqual(draft, DRAFT)
        self.assertEqual(reason, REASON)
        self.assertIn(f'{POS}\t342\t240\t{DRAFT}', drafts)
        # the message keeps its Japanese: no slot fill, no reference patch
        self.assertNotIn('0x800bb1b6', asm)
        self.assertNotIn('0x800a4194', asm)

    def test_a_human_row_is_kept_and_reported_not_rewritten(self):
        # manual English is the human's: the build must not touch it; the
        # Japanese still ships and the report names the row and draft
        human = [row(WIDENED)]
        route, drafts, asm = run_build({INDEX: row(WIDENED)}, human)
        route.assert_not_called()
        self.assertEqual(human[0]['en'], WIDENED)
        self.assertEqual(human[0]['note'], 'PSP-US')
        self.assertIn(f'{POS}\t342\t240\t{DRAFT}', drafts)
        self.assertNotIn('0x800bb1b6', asm)
        self.assertNotIn('0x800a4194', asm)

    def test_a_row_that_fits_the_viewport_still_ships(self):
        fits = 'Are you certain?<FF01>'
        route, drafts, asm = run_build({INDEX: row(fits)}, [])
        route.assert_not_called()
        self.assertNotIn(POS, drafts)
        self.assertIn('0x800a4194', asm)      # the reference is patched
        self.assertIn('0x800bb1b6', asm)      # the slot is freed for the text


if __name__ == '__main__':
    unittest.main()
