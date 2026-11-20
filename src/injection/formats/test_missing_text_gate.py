"""Unresolved diagnostic placeholders cannot become in-game dialogue."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import etext


class MissingTextGate(unittest.TestCase):
    def test_placeholder_is_rejected_even_across_control_codes(self):
        for text in ('PART-MISSING', 'MISSING TEXT', 'MISSING<FFF6>TEXT',
                     'Elly: PART-MISSING PART-MISSING'):
            with self.subTest(text=text), self.assertRaisesRegex(
                    ValueError, 'unresolved missing-text placeholder'):
                etext.encode(text)

    def test_ordinary_wording_is_not_a_placeholder(self):
        for text in ("We're missing someone.", 'WHAT ME MISSING!?',
                     'The missing text is on the page.'):
            with self.subTest(text=text):
                self.assertTrue(etext.encode(text))
