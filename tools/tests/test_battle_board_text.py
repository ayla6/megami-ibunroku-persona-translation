"""Battle object-text boards: structural discovery, fit gate and packing."""
from pathlib import Path
import contextlib
import io
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
sys.path.insert(0, str(ROOT / 'src/extraction_tools/psx'))
sys.path.insert(0, str(ROOT / 'tools'))
import battle_board_text as boards
import btlp
import extract_text_all
import smallfont_vwf
import toolbelt
import verify_disc


def apply_body(image, body):
    """Apply a generated assembly body (only .org/.byte/.halfword/.word)."""
    at = None
    for line in body:
        text = line.strip()
        if text.startswith('.org'):
            at = int(text.split()[1], 16) - boards.BASE
        elif text.startswith('.byte'):
            values = [int(v, 0) for v in text.split(None, 1)[1].split(',')]
            image[at:at + len(values)] = bytes(values)
            at += len(values)
        elif text.startswith('.halfword'):
            struct.pack_into('<h', image, at, int(text.split()[1], 0))
            at += 2
        elif text.startswith('.word'):
            struct.pack_into('<I', image, at, int(text.split()[1], 0))
            at += 4
    return image


class BattleBoardText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        cls.rows = {r['pos']: r for r in toolbelt.merged_rows('BTLP')}
        cls.plan = boards.plan(cls.stock, cls.rows)

    def test_pool_scan_and_descriptor_aliases(self):
        rows = boards.scan(self.stock)
        self.assertEqual(len(rows), 93)
        self.assertEqual(len({p for p, _ in rows}), 93)
        offsets = {p for p, _ in rows}
        for at, count, _pool in boards.BOARDS:
            for i in range(count):
                ptr = struct.unpack_from('<I', self.stock, at + i * 12 + 4)[0]
                self.assertIn(ptr - boards.BASE, offsets)

    def test_initial_and_direct_runtime_descriptor_links_are_distinct(self):
        initial = boards.initial_references(self.stock)
        direct = boards.direct_assignments(self.stock)
        self.assertEqual(len(initial), 89)
        # The alternate mode is assigned into the shared descriptor at runtime;
        # absence from the initial table does not prove disuse.
        self.assertNotIn(0x7a304, initial)
        self.assertIn((0x1bc5c, 0x7a304, 0x7a3b0), direct)
        self.assertIn((0x1bd20, 0x7a2fc, 0x7a3b0), direct)
        accounted = initial | {source for _code, source, _field in direct}
        self.assertEqual(len({off for off, _ in boards.scan(self.stock)} - accounted), 3)

    def test_scan_lists_accepts_hidden_rows_and_blank_cells(self):
        lists = {at: entries for at, _count, entries in boards.scan_lists(self.stock)}
        # The config list has rows the renderer never reads (count 0) and one
        # shared blank row; both are structural rows, not missing text.
        config = lists[0x7baf0]
        self.assertTrue(any(e['n'] == 0 and e['text'] is None for e in config))
        self.assertIn(0x7a964, lists)
        self.assertTrue(any(e['kind'] == 'blank' for e in lists[0x7a964]))
        # The debug list ends in a shared blank run, not an unknown record.
        self.assertTrue(any(e['kind'] == 'blank' for e in lists[0x7a228]))

    def test_source_lists_are_exactly_the_translated_inventory(self):
        found = [at for at, _count, _entries in boards.source_lists(self.stock)]
        self.assertEqual(found, [0x79740, 0x79e44, 0x7a014, 0x7a228, 0x7a49c,
                                 0x7a964, 0x7b100, 0x7b7e0, 0x7baf0])

    def test_fit_gate_defers_only_the_overflowing_list(self):
        translated = [entry['at'] for entry in self.plan['translated']]
        deferred = [entry for entry in self.plan['lists'] if not entry['translate']]
        self.assertEqual(len(translated), 8)
        self.assertEqual([entry['at'] for entry in deferred], [0x7a228])
        self.assertIn('px before a', deferred[0]['reason'])
        self.assertEqual(self.plan['deferred'],
                         sorted(entry['text'] for entry in deferred[0]['entries']
                                if entry['n'] > 0 and entry['kind'] == 'text'))

    def test_packing_dedupes_and_never_overwrites_a_live_record(self):
        strings = self.plan['strings']
        bodies = [body for _at, body in strings]
        self.assertEqual(len(bodies), len(set(bodies)))
        self.assertEqual(len(strings), 71)
        spans = boards.record_spans(self.stock)
        directory = [(lo, hi) for lo, span in self.plan['directory']
                     for hi in (lo + span,)]
        live = boards.initial_references(self.stock)
        for _at, _count, entries in boards.scan_lists(self.stock):
            live |= {e['text'] for e in entries
                     if e['n'] > 0 and e['kind'] == 'text'}
        live = {start for start in live if start in spans}
        live -= self.plan['shipped']
        for at, body in strings:
            self.assertTrue(any(lo <= at + boards.BASE < hi for lo, hi in directory))
            self.assertLessEqual(at + len(body), len(self.stock))
            for start in live:
                self.assertFalse(start < at + len(body) and at < spans[start],
                                 f'overwrites {start:#x}')

    def test_descriptor_pointers_counts_and_shared_runtime_values(self):
        by_desc = {desc: (new_x, addr, count)
                   for desc, new_x, addr, count in self.plan['descriptors']}
        # Normal/Easy share one descriptor; its count covers the longer word
        # and the shorter value is space-padded inside its own retail record.
        self.assertEqual(by_desc[0x7a3b0][2], 6)
        normal = boards._encode(self.rows['0x7a2fc']['en'].strip())
        easy = boards._encode(self.rows['0x7a304']['en'].strip())
        self.assertEqual(len(normal), 6)
        self.assertLess(len(easy), 6)
        shared = dict(self.plan['strings'])[by_desc[0x7a3b0][1]]
        self.assertEqual(shared[:len(normal)], normal)
        for entry in self.plan['translated']:
            for row in entry['entries']:
                if row['n'] == 0 or row['kind'] != 'text':
                    continue
                en = self.rows[hex(row['text'])]['en'].strip()
                new_x, addr, count = by_desc[row['desc']]
                self.assertEqual(count, len(dict(self.plan['strings'])[addr]) - 1)
                if row['desc'] != 0x7a3b0:
                    self.assertEqual(addr, next(
                        at for at, body in self.plan['strings']
                        if body[:-1] == boards._encode(en)))
                width = smallfont_vwf.codes_px(
                    toolbelt.smallfont_char(c) for c in en)
                sole_top = sum(1 for other in entry['entries']
                               if other['n'] > 0
                               and other['y'] == min(o['y'] for o in entry['entries']
                                                     if o['n'] > 0)) == 1
                if (sole_top and row['y'] == min(o['y'] for o in entry['entries']
                                                 if o['n'] > 0)
                        and row['x'] < 0 < row['x'] + row['n'] * 8):
                    self.assertEqual(new_x, -(width // 2))
                else:
                    self.assertIsNone(new_x)

    def test_directory_matches_its_declared_size(self):
        at, table = self.plan['table']
        self.assertEqual(at, toolbelt.asm_equ('BTL_BOARD_SPANS_ADDR') - boards.BASE)
        self.assertEqual(len(table), toolbelt.asm_equ('BTL_BOARD_SPANS_SIZE'))
        self.assertEqual(struct.unpack_from('<I', table, len(table) - 4)[0], 0)
        entries = [struct.unpack_from('<IHH', table, i)
                   for i in range(0, len(table) - 4, 8)]
        # Every translated source pool, the three ANALYZE buffers, the five
        # command-stage Persona rows, and board 23's arcana label table plus
        # its three full-name rows (btlp/board23_names.asm).
        self.assertEqual(len(entries), 15)
        self.assertEqual(entries, sorted(entries))
        bases = {base for base, _span, _pad in entries}
        for name in ('ANALYZE_NAME_BUF', 'ANALYZE_SPELL_BUF',
                     'ANALYZE_TRAIT_BUF', 'BTLP_STATUS_PERSONA_BUF',
                     'BTLP_BOARD23_TAG_TABLE', 'BTLP_BOARD23_NAMES_ADDR',
                     'BTLP_BOARD23_NAME_ROW_2'):
            self.assertIn(toolbelt.asm_equ(name), bases)
        for base, span, _pad in entries:
            self.assertTrue(0x800643c4 <= base < 0x800643c4 + len(self.stock))
            self.assertTrue(0 < span < 0x10000)

    def test_build_then_verify_round_trip_and_corruption(self):
        body, result = boards.build(self.stock, self.rows)
        image = apply_body(bytearray(self.stock), body)
        boards.verify(self.stock, image, self.rows)
        self.assertEqual(bytes(image[result['table'][0]:result['table'][0]
                                    + len(result['table'][1])]), result['table'][1])
        at = result['strings'][0][0]
        for mutate in (lambda im: im.__setitem__(at, im[at] ^ 1),
                       lambda im: struct.pack_into('<I', im, result['descriptors'][0][0] + 4, boards.BASE),
                       lambda im: im.__setitem__(result['descriptors'][0][0] + 8,
                                                 im[result['descriptors'][0][0] + 8] ^ 1),
                       lambda im: im.__setitem__(result['table'][0],
                                                 im[result['table'][0]] ^ 1)):
            broken = bytearray(image)
            mutate(broken)
            with self.assertRaises(ValueError):
                boards.verify(self.stock, broken, self.rows)

    def test_board_unshipped_follows_the_sfwvf_gate(self):
        rows = list(self.rows.values())
        self.assertEqual({hex(pos) for pos in self.plan['unshipped']},
                         btlp.board_unshipped(self.stock, rows))
        with mock.patch.object(btlp.features, 'on', return_value=False):
            self.assertEqual(
                {hex(off) for off, _ja in boards.scan(self.stock)
                 if self.rows.get(hex(off), {}).get('en', '').strip()},
                btlp.board_unshipped(self.stock, rows))

    def test_level3_reports_board_rows_kept_japanese(self):
        pos = hex(boards.POOLS[0][0])
        rows = [{'pos': pos, 'en': 'full human draft'}]
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'build').mkdir()
            with mock.patch.object(verify_disc, 'ROOT', tmp), \
                 mock.patch.object(verify_disc, 'fails', 0), mock.patch.object(verify_disc, 'checks', 0), \
                 mock.patch.object(verify_disc, 'translation_rels', return_value={'BTLP'}), \
                 mock.patch.object(verify_disc, '_row_forms', return_value=(None, [])), \
                 mock.patch.object(toolbelt, 'merged_rows', return_value=rows), \
                 mock.patch.object(btlp, 'data', return_value=self.stock), \
                 mock.patch.object(btlp, 'evt_messages', return_value=[]), \
                 mock.patch.object(btlp, 'neg_strings', return_value=[]), \
                 mock.patch.object(btlp, 'board_unshipped', return_value={pos}), \
                 mock.patch.object(verify_disc.features, 'on', return_value=True):
                def check():
                    verify_disc.fails = verify_disc.checks = 0
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        verify_disc.level3(lambda name: self.stock if name == 'BTLP.BIN' else b'')
                    return verify_disc.fails, out.getvalue()
                fails, out = check()
                self.assertEqual(fails, 0)
                self.assertIn('1 battle-board row(s) kept Japanese', out)
            with mock.patch.object(verify_disc, 'ROOT', tmp), \
                 mock.patch.object(verify_disc, 'fails', 0), mock.patch.object(verify_disc, 'checks', 0), \
                 mock.patch.object(verify_disc, 'translation_rels', return_value={'BTLP'}), \
                 mock.patch.object(verify_disc, '_row_forms', return_value=(None, [])), \
                 mock.patch.object(toolbelt, 'merged_rows', return_value=rows), \
                 mock.patch.object(btlp, 'data', return_value=self.stock), \
                 mock.patch.object(btlp, 'evt_messages', return_value=[]), \
                 mock.patch.object(btlp, 'neg_strings', return_value=[]), \
                 mock.patch.object(btlp, 'board_unshipped', return_value=set()), \
                 mock.patch.object(verify_disc.features, 'on', return_value=True):
                verify_disc.fails = verify_disc.checks = 0
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    verify_disc.level3(lambda name: self.stock if name == 'BTLP.BIN' else b'')
                self.assertGreater(verify_disc.fails, 0)
                self.assertIn('LEVEL 3 FAIL BTLP', out.getvalue())

    def test_pointer_and_padding_drift_are_rejected(self):
        altered = bytearray(self.stock)
        struct.pack_into('<I', altered, boards.BOARDS[0][0] + 4, boards.BASE)
        with self.assertRaises(ValueError):
            boards.scan(altered)
        altered = bytearray(self.stock)
        first = boards.POOLS[0][0]
        end = altered.index(0xff, first)
        altered[end + 1] = 1
        with self.assertRaises(ValueError):
            boards.scan(altered)

    def test_all_positions_are_canonical_and_manual(self):
        extracted = {r['pos']: r['text'] for r in toolbelt.read_extracted('psx', 'BTLP')}
        manual = {r['pos']: r for r in toolbelt.read_manual('BTLP')}
        generated = {r['pos']: r for r in toolbelt.read_generated('BTLP')}
        for offset, ja in boards.scan(self.stock):
            pos = hex(offset)
            self.assertEqual(extracted[pos], ja)
            # A later proven PSP match can graduate a gap into generated.
            row = manual.get(pos) or generated.get(pos)
            self.assertIsNotNone(row, pos)
            self.assertTrue(row.get('note') or row.get('en'))

    def test_dump_routes_only_unmatched_board_sources_to_manual(self):
        scanned = boards.scan(self.stock)[:2]
        first, second = (hex(off) for off, _ja in scanned)
        ja = {hex(off): text for off, text in scanned}
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(toolbelt, 'GENERATED', str(Path(tmp, 'generated'))), \
                 mock.patch.object(toolbelt, 'MANUAL', str(Path(tmp, 'manual'))), \
                 mock.patch.object(toolbelt, 'psx_text_of', return_value=ja), \
                 mock.patch.object(btlp, 'data', return_value=self.stock), \
                 mock.patch.object(btlp, 'families', return_value=[(off, 'board') for off, _ in scanned]):
                toolbelt.write_generated('BTLP', [{'id': '0', 'pos': first,
                                                  'psp': 'EBOOT:1234', 'en': 'Matched source'}])
                btlp.dump()
                manual = {r['pos']: r for r in toolbelt.read_manual('BTLP')}
                self.assertNotIn(first, manual)
                self.assertIn(second, manual)
                self.assertEqual(manual[second]['en'], '')
                self.assertIn(ja[second], manual[second]['note'])
                self.assertEqual(toolbelt.read_generated('BTLP')[0]['en'], 'Matched source')

    def test_existing_extract_prefix_matches_binary_family_scan(self):
        rows = extract_text_all.btlp_rows('BTLP', str(ROOT / 'data/psx/BTLP.BIN'))
        canonical = [(int(r['pos'], 16), r['text'])
                     for r in toolbelt.read_extracted('psx', 'BTLP')]
        self.assertEqual(rows, canonical)


if __name__ == '__main__':
    unittest.main()
