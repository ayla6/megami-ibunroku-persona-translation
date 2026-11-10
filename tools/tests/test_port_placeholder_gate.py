"""The port must not report success with diagnostics in generated text."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/extraction_tools/matching'))
import port


class PortPlaceholderGate(unittest.TestCase):
    def test_japanese_source_takes_precedence_over_cached_plans(self):
        with patch.object(port.os.path, 'exists', return_value=True):
            self.assertEqual(port.plan_args('port_btlneg.py', ('--apply',), True),
                             ('--apply',))
            self.assertEqual(port.plan_args('port_btlneg.py', ('--apply',), False),
                             ('--apply', '--without-psp-jp'))

    def test_rejects_placeholder_in_any_generated_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'nested').mkdir()
            path = root / 'nested' / 'text.tsv'
            path.write_text('pos\ten\n0x1\tPART-MISSING\n')
            with self.assertRaisesRegex(ValueError, 'text.tsv:2'):
                port.validate_generated(root)
            path.write_text('pos\ten\n0x1\tThe text is missing.\n')
            port.validate_generated(root)


if __name__ == '__main__':
    unittest.main()
