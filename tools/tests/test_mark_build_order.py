"""Mark's MES asset must be installed after assembly, before packaging."""
import sys
import tempfile
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import build
import features


class MarkBuildOrder(unittest.TestCase):
    def test_mark_is_applied_after_assembly(self):
        events = []
        with patch.object(build, 'run', side_effect=lambda *args: events.append(args)), \
             patch.object(build, 'run_from', side_effect=lambda *args: events.append(('assemble',))), \
             patch.object(features, 'on', return_value=False):
            build.assemble_variant(sys.executable, ['mark'],
                                   os.path.join(tempfile.gettempdir(), 'mark-test.bin'))
        assembly = events.index(('assemble',))
        mark_build = next(i for i, args in enumerate(events)
                          if any(str(a).endswith('mark.py') for a in args) and 'build' in args)
        mark_verify = next(i for i, args in enumerate(events)
                           if any(str(a).endswith('mark.py') for a in args) and 'verify' in args)
        disc = next(i for i, args in enumerate(events)
                    if any(str(a).endswith('build_disc.py') for a in args))
        self.assertLess(assembly, mark_build)
        self.assertLess(mark_build, mark_verify)
        self.assertLess(mark_verify, disc)


if __name__ == '__main__':
    unittest.main()
