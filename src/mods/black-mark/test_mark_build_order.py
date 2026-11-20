"""Mark's MES asset must be installed after assembly, before packaging."""
import sys
from contextlib import nullcontext
import tempfile
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import build
import features


class MarkBuildOrder(unittest.TestCase):
    def test_mark_is_applied_after_assembly(self):
        events = []
        import asm_main     # assemble_variant writes build/main.asm: never the real one here
        import image_replacements
        import armips_products
        import mod_build
        import preparation_cache
        with patch.object(mod_build, 'restore'), patch.object(preparation_cache, 'ending', side_effect=lambda action, *args: action()), patch.object(armips_products, 'memory_outputs', return_value=nullcontext({})), patch.object(image_replacements, 'restore'), patch.object(asm_main, 'write', return_value=asm_main.OUT), \
             patch.object(build, 'run_all', side_effect=lambda *cmds: [build.run(*c) for c in cmds]), \
             patch.object(build, 'run', side_effect=lambda *args: events.append(args)), \
             patch.object(build, 'run_from', side_effect=lambda *args: events.append(('assemble',))), \
             patch.object(features, 'on', return_value=False):
            build.assemble_variant(sys.executable, ['black-mark'],
                                   os.path.join(tempfile.gettempdir(), 'mark-test.bin'))
        assembly = events.index(('assemble',))
        mark_build = next(i for i, args in enumerate(events)
                          if any(str(a).endswith('image_replacements.py') for a in args) and 'build' in args)
        mark_verify = next(i for i, args in enumerate(events)
                           if any(str(a).endswith('image_replacements.py') for a in args) and 'verify' in args)
        disc = next(i for i, args in enumerate(events)
                    if any(str(a).endswith('build_disc.py') for a in args))
        self.assertLess(assembly, mark_build)
        self.assertLess(mark_build, mark_verify)
        self.assertLess(mark_verify, disc)


if __name__ == '__main__':
    unittest.main()
