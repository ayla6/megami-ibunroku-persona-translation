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
sys.path.insert(0, str(ROOT / 'src' / 'injection_tools'))
import build


class _Assembled(Exception):
    """Stops assemble_variant at the armips call so nothing else runs."""


class AssemblyWarningGate(unittest.TestCase):
    def test_armips_runs_with_warnings_fatal(self):
        calls = []

        def capture(cwd, *cmd):
            calls.append((cwd, cmd))
            raise _Assembled

        with patch.object(build, 'run', lambda *a, **k: None), \
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
        self.assertIn('main.asm', cmd)


if __name__ == '__main__':
    unittest.main()
