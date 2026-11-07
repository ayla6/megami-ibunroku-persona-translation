"""Every QoL variant must assemble without silently overwriting another block.

The suite's overlay tests read the base build in build/. The release builder
is the only thing that assembles the QoL variants, so a QoL block could claim
addresses another patch owns and nothing in the suite would notice until the
release gate failed (or, worse, the disc shipped). The 60fps overworld block
did exactly that: it started at the image extension end and ran through the
status bar's fixed slots.

Assemble the real main.asm for the base, every QoL option on its own, and all
of them together in an isolated mirror of the tree, then hand each listing to
the generic write guard. The guard knows every output's limit and rejects any
write that covers data written earlier, so this covers any overlap between a
QoL block and any other feature - present or added later - without naming a
single block or address here.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src' / 'injection_tools'))
import build
import write_guard

ADDRESSES = ROOT / 'src/asm/common/addresses.inc'
# main.asm reads these generated includes and binaries; without a prepared
# build tree there is nothing to assemble, so the test skips instead of
# reporting a half-built tree as a translation bug.
REQUIRED = ('features.inc', 's2d.asm', 'slps.asm', 'btlp.asm', 'affinity.asm',
            'end_credits.asm')


class QolWriteGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.armips = ROOT / 'external_tools/armips/armips'
        if not cls.armips.exists():
            cls.armips = shutil.which('armips')
        if not cls.armips:
            raise unittest.SkipTest('requires armips')
        missing = [name for name in REQUIRED if not (ROOT / 'build' / name).exists()]
        if missing:
            raise unittest.SkipTest('requires a prepared build tree')

    def mirror(self, directory):
        """A tree where the assembly can run without touching build/."""
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT / 'src/asm', directory / 'src/asm')
        os.symlink(ROOT / 'data', directory / 'data')
        equ = write_guard._equ_map(str(ADDRESSES))
        outputs = set(write_guard.output_limits(equ, str(ROOT)))
        for parent, dirnames, filenames in os.walk(ROOT / 'build'):
            for name in dirnames:
                (directory / 'build' /
                 Path(parent, name).relative_to(ROOT / 'build')).mkdir(
                     parents=True, exist_ok=True)
            for name in filenames:
                path = Path(parent, name)
                if os.path.normpath(path) in outputs:
                    continue                 # the assembly owns these bytes
                target = directory / 'build' / path.relative_to(ROOT / 'build')
                target.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(path, target)
        for output in outputs:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
        return directory

    def assemble(self, directory, patches):
        args = [str(self.armips), '-erroronwarning', 'main.asm',
                '-sym2', 'persona.sym', '-temp', 'armips-main.lst']
        for name in patches:
            args += ['-definelabel', build.QOL_PATCHES[name][0], '1']
        return subprocess.run(args, cwd=directory / 'src/asm',
                              capture_output=True, text=True)

    def guard(self, directory):
        listing = directory / 'src/asm/armips-main.lst'
        problems, failures, stats = write_guard.check_listing(listing, directory)
        return problems + failures, stats

    def test_no_qol_variant_loses_a_write(self):
        variants = ([[]] + [[name] for name in build.QOL_PATCHES] +
                    [list(build.QOL_PATCHES)])
        with tempfile.TemporaryDirectory() as temp:
            directory = self.mirror(Path(temp))
            for patches in variants:
                label = '+'.join(patches) or 'base'
                with self.subTest(variant=label):
                    result = self.assemble(directory, patches)
                    self.assertEqual(result.returncode, 0,
                                     result.stdout + result.stderr)
                    failures, stats = self.guard(directory)
                    self.assertEqual(failures, [],
                                     f'{label}: ' + '\n'.join(failures[:10]))
                    self.assertGreater(stats['sections'], 0)
                    self.assertEqual(stats['lost'], 0)


if __name__ == '__main__':
    unittest.main()
