"""Run the tests, wherever they live: each one sits next to what it tests
(a tool's beside the tool, a mod's in its mod folder; tools/tests holds the
few that span the whole build).

    python tools/run_tests.py                       every test
    python tools/run_tests.py test_mod_saves.py     one file (by name)
    python tools/run_tests.py 'test_btlp_*'         a glob over file names

`unittest discover` cannot walk src/: mod folders are named after their mods
(`unified-save-menu`), which are not package names. Test files are found by
name instead and imported like any tool (src/toolpath.py), so names stay
unique across the tree.
"""
from __future__ import annotations

import fnmatch
import argparse
import csv
from dataclasses import dataclass
import os
from pathlib import Path
import sys
import time
import unittest

# Tests that read build/ judge it in the font edition it was assembled in
# (build.py records it), so every row resolves to the layout on that disc.
_EDITION = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'build', 'font_edition')
if 'PERSONA_FONT' not in os.environ and os.path.exists(_EDITION):
    with open(_EDITION, encoding='utf-8') as _f:
        os.environ['PERSONA_FONT'] = _f.read().strip()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)


@dataclass(frozen=True)
class TestTiming:
    name: str
    seconds: float


class TimedResult(unittest.TextTestResult):
    timings: list[TestTiming]
    started: float

    def startTest(self, test: unittest.TestCase) -> None:
        self.started = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test: unittest.TestCase) -> None:
        if not hasattr(self, 'timings'):
            self.timings = []
        self.timings.append(TestTiming(test.id(), time.perf_counter()-self.started))
        super().stopTest(test)


def test_files() -> list[str]:
    """Every test_*.py file name under the tool folders, sorted."""
    return sorted(name for folder in toolpath.folders() for name in os.listdir(folder)
                  if name.startswith('test_') and name.endswith('.py'))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timings', type=Path, help='write per-test and import/execution timing as TSV')
    parser.add_argument('patterns', nargs='*')
    args = parser.parse_args(argv)
    patterns = [arg if arg.endswith('.py') or '*' in arg else arg + '.py' for arg in args.patterns] or ['test_*.py']
    names = [name for name in test_files() if any(fnmatch.fnmatch(name, p) for p in patterns)]
    missing = [p for p in patterns if '*' not in p and p not in names]
    if missing:
        print(f"run_tests.py: no test called {', '.join(missing)}", file=sys.stderr)
        return 2
    before = time.perf_counter()
    suite = unittest.defaultTestLoader.loadTestsFromNames([name[:-3] for name in names])
    loaded = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=1, resultclass=TimedResult if args.timings else unittest.TextTestResult).run(suite)
    finished = time.perf_counter()
    if args.timings and isinstance(result, TimedResult):
        args.timings.parent.mkdir(parents=True, exist_ok=True)
        with args.timings.open('w', newline='') as stream:
            writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
            writer.writerow(('kind', 'name', 'seconds'))
            writer.writerow(('phase', 'test module imports', f'{loaded-before:.6f}'))
            writer.writerow(('phase', 'suite execution', f'{finished-loaded:.6f}'))
            writer.writerows(('test', t.name, f'{t.seconds:.6f}')
                             for t in sorted(getattr(result, 'timings', []), key=lambda t: -t.seconds))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
