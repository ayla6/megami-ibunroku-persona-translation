"""Banner promotion must be source-derived, deterministic and fail closed."""
from pathlib import Path
import importlib.util
import sys
import unittest
from unittest.mock import patch
import re

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
spec = importlib.util.spec_from_file_location('port_btlbanner', ROOT / 'src/extraction_tools/matching/port_btlbanner.py')
porter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(porter)
import btlp


class BannerPorter(unittest.TestCase):
    def test_shared_pointer_with_conflicting_sources_is_not_promoted(self):
        records = [(1, btlp.B + 10, 'same'), (2, btlp.B + 10, 'same')]
        names = {1: ('First', 'EBOOT:1'), 2: ('Second', 'EBOOT:2')}
        with self.assertRaisesRegex(ValueError, 'conflicting PSP names'):
            list(porter.candidates(records, names))
        names[2] = ('First', 'EBOOT:2')
        self.assertEqual(list(porter.candidates(records, names)),
                         [{'pos': '0xa', 'psp': 'EBOOT:1', 'en': 'First'}])

    def test_full_packer_is_hash_seed_independent(self):
        import os
        import subprocess
        code = ("import sys,hashlib;sys.path.insert(0,'src/injection_tools');"
                "import btlp,toolbelt;chunks=[];"
                "toolbelt.write_asm=lambda p,o,s:chunks.append(s);"
                "btlp.ban_build(btlp.data(),{r['pos']:r for r in "
                "toolbelt.merged_rows('BTLP')},[]);"
                "print(hashlib.sha256(''.join(chunks).encode()).hexdigest())")
        hashes = []
        for seed in ('0', '1', '17'):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                                    env=env, capture_output=True, text=True, check=True)
            hashes.append(result.stdout.strip().splitlines()[-1])
        self.assertEqual(len(set(hashes)), 1)

    def test_banner_spills_do_not_touch_skill_menu_reservation(self):
        import toolbelt
        chunks = {}
        rows = {r['pos']: r for r in toolbelt.merged_rows('BTLP')}
        with patch.object(toolbelt, 'write_asm', side_effect=lambda path, owner, body: chunks.update({path: body})):
            self.assertEqual(btlp.ban_build(btlp.data(), rows, []), btlp.BAN_COUNT)
        slps = chunks[btlp.BAN_OUT_SLPS]
        reserved_start = toolbelt.asm_equ('SKILL_MENU_BUF')
        reserved_end = toolbelt.asm_equ('SKILL_MENU_BUF_END')
        for addr, literals in re.findall(r'\.org (0x[0-9a-fA-F]+)\s+\.byte ([^\n]+)', slps):
            start = int(addr, 16)
            end = start + len(literals.split(','))
            self.assertTrue(end <= reserved_start or start >= reserved_end,
                            f'banner spill {start:#x}..{end:#x} overlaps skill menu')

    def test_mechanical_psp_source_contains_reported_action(self):
        records = btlp.ban_records(btlp.data())
        names = btlp.banner_wording()
        index, ptr, original = records[80]
        self.assertEqual(index, 80)
        self.assertEqual(original, 'ハンマ')
        actual = next(r for r in porter.candidates(records, names) if r['pos'] == hex(ptr - btlp.B))
        self.assertEqual(actual['en'], names[index][0])
        self.assertEqual(actual['psp'], names[index][1])
        self.assertLessEqual(porter.vwf_wrap.text_width(actual['en']), porter.frame_width())


if __name__ == '__main__':
    unittest.main()
