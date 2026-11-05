"""Every translated S2D script reference must reach its encoded wording."""
import re
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/extraction_tools/matching'), str(ROOT / 'src/injection_tools')]
import etext
import port_s2d
import s2d
import toolbelt


def labelled(raw):
    """PSP dialogue with its per-page speaker labels turned into inline text.

    The PSP names the speaker at the head of every page; a merged PSX box
    names a speaker only when it changes and suppresses consecutive repeats
    (docs/TEXT_LAYOUT_SPEC.md, S2D portrait dialogue)."""
    last = None

    def one(m):
        nonlocal last
        speaker = m.group(1).strip()
        out = '' if speaker == last else speaker + ': '
        last = speaker
        return out

    return re.sub(r'<FF1B>([^<>]+)<FF03>', one, raw)


class BuiltS2dScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / 'build/S2D.BIN'
        if not path.exists():
            raise unittest.SkipTest('requires assembled build/S2D.BIN')
        cls.built = path.read_bytes()
        cls.stock = s2d.data()
        cls.boxes = s2d.script_boxes(cls.stock)
        cls.refs = s2d.script_refs(cls.stock, cls.boxes)

    def test_auto_matched_plain_dialogue_keeps_complete_psp_wording(self):
        index = port_s2d.portrait_index(toolbelt.read_extracted('psp_jp', 'EBOOT'))
        translated = {r['pos']: r for r in toolbelt.merged_rows('S2D') if r.get('en', '').strip()}
        checked = set()
        for start, end in self.boxes:
            pos = hex(start - s2d.B)
            row = translated.get(pos)
            if not row:
                continue
            ja = etext.decode(self.stock[start - s2d.B:end - s2d.B - 2])
            us = port_s2d.portrait_twin(ja, index)
            if not us or row.get('psp', '').lower() != ('eboot:' + us['pos'].removeprefix('0x')).lower():
                continue
            # A plain dialogue has no parameters/inserts requiring a separate
            # code-aware comparison; its only controls are layout and labels.
            raw = us['text']
            if set(re.findall(r'<FF([0-9A-F]{2})>', raw)) - {'01','02','03','04','1B'}:
                continue
            expected = labelled(raw)
            # PSP word-wrapped hyphens are joined, other newlines are spaces.
            expected = re.sub(r'(-?)[ \t\r\n]*<FF03>[ \t\r\n]*',
                              lambda m: '-' if m.group(1) else ' ', expected)
            def plain(text):
                # Name inserts are structure the PSX row carries and the PSP
                # wording does not: compare wording, not insert count.
                text = re.sub(r'<FF(?:07|08|0F)>(?:<[0-9A-F]{2}>)?', '', text)
                text = re.sub(r'<FF(?:01|02|04)>', ' ', text)
                return ' '.join(text.split())
            self.assertEqual(plain(row['en'].replace('<FF03>', ' ')), plain(expected), pos)
            checked.add(pos)
        for pos in ('0x46d08', '0x46d54'):
            self.assertIn(pos, checked, 'captured shrine box did not reach its full PSP wording')

    def test_all_translated_original_references_reach_encoded_text(self):
        rows = {int(r['pos'], 16): r for r in toolbelt.merged_rows('S2D') if r.get('en', '').strip()}
        checked = 0
        for i, (start, _end) in enumerate(self.boxes):
            row = rows.get(start - s2d.B)
            if row is None:
                continue
            self.assertTrue(self.refs[i], f'script box {i} has no references')
            original = etext.decode(self.stock[start - s2d.B:self.boxes[i][1] - s2d.B - 2])
            expected = etext.encode(s2d.fill_pauses(original, row['en'].strip()))
            for where in self.refs[i]:
                with self.subTest(box=i, pointer=hex(where)):
                    off = where - s2d.B
                    dest = struct.unpack_from('<I', self.built, off)[0]
                    data_off = dest - s2d.B
                    self.assertGreaterEqual(data_off, 0)
                    self.assertLessEqual(data_off + len(expected), len(self.built))
                    self.assertEqual(self.built[data_off:data_off + len(expected)], expected)
                checked += 1
        self.assertGreater(checked, 0)


if __name__ == '__main__':
    unittest.main()
