"""Negotiation answers cannot wrap or advance to a second page."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import talk


class AnswerLayout(unittest.TestCase):
    def test_answer_requires_one_line_and_no_page(self):
        ja = 'あ<FFF5>'
        self.assertEqual(talk._answer_qa(ja, 'Yes.<FFF5>'), [])
        for en in ('Yes<FFF6>No<FFF5>', 'Yes<FFFB><FFF7>No<FFF5>'):
            with self.subTest(en=en):
                self.assertTrue(talk._answer_qa(ja, en))

    def test_answer_prices_insert_at_runtime_width(self):
        ja = 'あ<FFF5>'
        self.assertTrue(talk._answer_qa(ja, '<FFF4>' + 'W' * 20 + '<FFF5>'))


if __name__ == '__main__':
    unittest.main()
