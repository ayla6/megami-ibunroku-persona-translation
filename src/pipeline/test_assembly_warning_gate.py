"""An assembler warning is a build failure, never a shipped hook.

armips exits 0 on a load/branch-delay warning unless -erroronwarning is
given. The map-title hook once shipped that way and silently fell back to
retail for every Japanese-keyed field, so pin the flag on the real command.
"""
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import build


class _Assembled(Exception):
    """Stops assemble_variant at the armips call so nothing else runs."""


class AssemblyWarningGate(unittest.TestCase):
    def test_armips_runs_with_warnings_fatal(self):
        import asm_main
        import armips_products
        import mod_build
        import image_replacements
        import preparation_cache
        calls = []

        def capture(cwd, *cmd):
            calls.append((cwd, cmd))
            raise _Assembled

        with patch.object(asm_main, 'write', return_value=asm_main.OUT), \
                patch.object(armips_products, 'memory_outputs', return_value=contextlib.nullcontext({})), \
                patch.object(mod_build, 'restore'), patch.object(image_replacements, 'restore'), \
                patch.object(preparation_cache, 'ending', side_effect=lambda action, *args: action()), \
                patch.object(build, 'run', lambda *a, **k: None), \
                patch.object(build, 'run_from', side_effect=capture), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(_Assembled):
                build.assemble_variant(sys.executable, [],
                                       str(ROOT / 'build' / 'unused.bin'),
                                       make_disc=False)

        self.assertTrue(calls, 'assemble_variant never assembled')
        _cwd, cmd = calls[0]
        self.assertEqual(cmd[0], build.ARMIPS)
        self.assertIn('-erroronwarning', cmd)
        self.assertTrue(any(str(arg).endswith('build/main.asm') for arg in cmd), cmd)


if __name__ == '__main__':
    unittest.main()
