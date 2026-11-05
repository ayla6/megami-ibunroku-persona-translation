"""Disc-table discovery must not confuse support wording with injected rows;
the structural audit must accept every legitimate builder change and reject
writes outside the file extents and records it owns."""
import contextlib
import hashlib
import io
import struct
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import verify_disc

SECTOR = 2048
RAW = 2352


class TranslationTables(unittest.TestCase):
    def test_support_inputs_excluded_but_unknown_tables_still_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated, manual = root / 'generated', root / 'manual'
            generated.mkdir()
            manual.mkdir()
            support = manual / 'terms.tsv'
            support.write_text('domain\tkey\ten\tnote\n')
            (manual / 'unexpected.tsv').write_text('broken header\n')
            (generated / 'S2D.tsv').write_text('id\tpos\tpsp\ten\n')
            with patch.object(verify_disc.toolbelt, 'GENERATED', str(generated)), \
                    patch.object(verify_disc.toolbelt, 'MANUAL', str(manual)), \
                    patch.object(verify_disc.toolbelt, 'WORDING_TABLES', (str(support),)):
                self.assertEqual(verify_disc.translation_rels(), {'S2D', 'unexpected'})


def _record(name, extent, size, flags=0):
    length = 33 + len(name)
    length += length & 1
    record = bytearray(length)
    record[0] = length
    struct.pack_into('<I', record, 2, extent)
    struct.pack_into('>I', record, 6, extent)
    struct.pack_into('<I', record, 10, size)
    struct.pack_into('>I', record, 14, size)
    record[25] = flags
    record[32] = len(name)
    record[33:33 + len(name)] = name
    return bytes(record)


def _directory(records):
    data = bytearray(SECTOR)
    position = 0
    for record in records:
        data[position:position + len(record)] = record
        position += len(record)
    return bytes(data)


def _image(path, files, volume, dir_lba=17):
    """A minimal Mode 1 image: user data at RAW[24:24+SECTOR]."""
    sectors = [bytearray(RAW) for _ in range(volume)]
    for name, (extent, size, content) in files.items():
        sectors[extent][24:24 + min(len(content), SECTOR)] = content[:SECTOR]
    records = [_record(b'\x00', dir_lba, SECTOR, 2),
               _record(b'\x01', dir_lba, SECTOR, 2)]
    records += [_record(name.encode(), ext, size)
                for name, (ext, size, _content) in files.items()]
    sectors[dir_lba][24:24 + SECTOR] = _directory(records)
    pvd = bytearray(SECTOR)
    struct.pack_into('<I', pvd, 80, volume)
    struct.pack_into('>I', pvd, 84, volume)
    pvd[156:156 + 34] = _record(b'\x00', dir_lba, SECTOR, 2)
    sectors[16][24:24 + SECTOR] = pvd
    with open(path, 'wb') as output:
        for sector in sectors:
            output.write(sector)


class StructureAudit(unittest.TestCase):
    """A 22-sector image: A.BIN plus its ISO and game tables."""

    NAMES = ('A.BIN', 'FNAME.DAT', 'FSECT.DAT', 'FSIZE.DAT')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.build = self.root / 'build'
        self.build.mkdir()
        self.original = self.root / 'original.bin'
        self.patched = self.root / 'patched.bin'

    def tearDown(self):
        self.tmp.cleanup()

    def files(self, a_extent=21, a_content=None, table_extent=None):
        a_content = bytes(SECTOR) if a_content is None else a_content
        fname = b''.join(name.encode() + b'\0' for name in self.NAMES)
        entries = {'A.BIN': (a_extent, SECTOR, a_content),
                   'FNAME.DAT': (18, len(fname), fname),
                   'FSECT.DAT': (19, 16, b''),
                   'FSIZE.DAT': (20, 16, b'')}
        extents = {name: entry[0] for name, entry in entries.items()}
        if table_extent is not None:
            extents['A.BIN'] = table_extent
        entries['FSECT.DAT'] = (19, 16, b''.join(
            struct.pack('<I', extents[name]) for name in self.NAMES))
        entries['FSIZE.DAT'] = (20, 16, b''.join(
            struct.pack('<I', SECTOR) for _name in self.NAMES))
        return entries

    def run_audit(self):
        verify_disc.fails = verify_disc.checks = 0
        report = io.StringIO()
        patched = verify_disc.Disc(self.patched)
        original = verify_disc.Disc(self.original)
        try:
            with contextlib.redirect_stdout(report):
                verify_disc.audit_structure(patched, original, str(self.build))
        finally:
            patched.f.close()
            original.f.close()
        return report.getvalue()

    def run_placement(self, rows):
        """Structure + level 1 against a placement record, never the tree."""
        verify_disc.fails = verify_disc.checks = 0
        report = io.StringIO()
        patched = verify_disc.Disc(self.patched)
        original = verify_disc.Disc(self.original)
        placed = [(name, ext, size, sha) for name, ext, size, sha in rows]
        try:
            with contextlib.redirect_stdout(report):
                structured = verify_disc.audit_structure(
                    patched, original, str(self.build), placed)
                pvd = patched.user(16)
                root_lba, = struct.unpack_from('<I', pvd, 156 + 2)
                root_size, = struct.unpack_from('<I', pvd, 156 + 10)
                entries = {p.upper(): (e, s)
                           for p, e, s in patched.walk(root_lba, root_size)}

                def read_file(path):
                    ext, size = entries[path]
                    return b''.join(patched.user(ext + n)
                                    for n in range((size + 2047) // 2048))[:size]
                n, bad = verify_disc.level1(patched, str(self.build), entries,
                                            read_file, placed)
        finally:
            patched.f.close()
            original.f.close()
        return structured, n, bad, report.getvalue()

    def audit(self, patched_files, original_files, volume, original_volume=22):
        _image(self.original, original_files, original_volume)
        _image(self.patched, patched_files, volume)
        (self.build / 'A.BIN').write_bytes(patched_files['A.BIN'][2])
        return self.run_audit()

    def test_clean_in_place_patch_passes(self):
        original = self.files()
        patched = self.files(a_content=b'patched'.ljust(SECTOR, b'\0'))
        report = self.audit(patched, original, 22)
        self.assertNotIn('FAIL', report, report)
        self.assertIn('1 changed file(s)', report)

    def test_change_outside_every_extent_fails(self):
        original = self.files()
        patched = self.files(a_content=b'patched'.ljust(SECTOR, b'\0'))
        _image(self.original, original, 22)
        _image(self.patched, patched, 22)
        data = bytearray(Path(self.patched).read_bytes())
        data[15 * RAW + 24] = 1          # system area, owned by nobody
        Path(self.patched).write_bytes(data)
        self.assertIn('changed outside the intended files', self.run_audit())

    def test_pvd_change_outside_volume_size_fails(self):
        files = self.files()
        _image(self.original, files, 22)
        _image(self.patched, files, 22)
        data = bytearray(self.patched.read_bytes())
        data[16 * RAW + 24 + 1] ^= 1
        self.patched.write_bytes(data)
        self.assertIn('PVD changed outside the volume size', self.run_audit())

    def test_relocated_file_passes(self):
        original = self.files()
        patched = self.files(a_extent=22, a_content=b'moved'.ljust(SECTOR, b'\0'))
        (self.build / 'A.BIN').write_bytes(b'moved'.ljust(SECTOR, b'\0'))
        report = self.audit(patched, original, 23)
        self.assertNotIn('FAIL', report, report)
        self.assertIn('1 changed file(s)', report)

    def test_zero_padding_past_retail_passes(self):
        original = self.files()
        patched = self.files(a_content=b'patched'.ljust(SECTOR, b'\0'))
        report = self.audit(patched, original, 23)
        self.assertNotIn('FAIL', report, report)

    def test_nonzero_bytes_past_retail_fail(self):
        original = self.files()
        patched = self.files(a_content=b'patched'.ljust(SECTOR, b'\0'))
        _image(self.original, original, 22)
        _image(self.patched, patched, 23)
        data = bytearray(Path(self.patched).read_bytes())
        data[22 * RAW + 24] = 1
        Path(self.patched).write_bytes(data)
        self.assertIn('changed outside the intended files', self.run_audit())

    def test_game_table_disagreement_fails(self):
        original = self.files()
        patched = self.files(table_extent=5)
        report = self.audit(patched, original, 22)
        self.assertIn('game-table mismatch', report)

    def test_overlapping_extents_fail(self):
        original = self.files()
        patched = self.files()
        # point A.BIN's ISO record and its FSECT entry at FNAME.DAT's extent
        patched['FSECT.DAT'] = (19, 16, b''.join(
            struct.pack('<I', 18 if name == 'A.BIN' else ext)
            for name, ext in zip(self.NAMES, (21, 18, 19, 20))))
        _image(self.original, original, 22)
        _image(self.patched, patched, 22)
        data = bytearray(Path(self.patched).read_bytes())
        base = 17 * RAW + 24
        position = 0
        while data[base + position]:
            length = data[base + position]
            if data[base + position + 33:base + position + 38] == b'A.BIN':
                struct.pack_into('<I', data, base + position + 2, 18)
                struct.pack_into('>I', data, base + position + 6, 18)
                break
            position += length
        Path(self.patched).write_bytes(data)
        self.assertIn('overlapping extent', self.run_audit())

    def test_renamed_directory_record_fails(self):
        original = self.files()
        patched = self.files()
        _image(self.original, original, 22)
        _image(self.patched, patched, 22)
        data = bytearray(Path(self.patched).read_bytes())
        base = 17 * RAW + 24
        position = 0
        while data[base + position]:
            length = data[base + position]
            if data[base + position + 33:base + position + 38] == b'A.BIN':
                data[base + position + 33] = ord('B')
                break
            position += length
        Path(self.patched).write_bytes(data)
        self.assertIn('directory record(s) changed', self.run_audit())


    def placement_rows(self, content, extent=21, sha=None):
        return [('A.BIN', extent, len(content),
                 sha or hashlib.sha256(content).hexdigest())]

    def test_placement_record_audits_an_image_without_its_build_tree(self):
        # the point of the record: a finished image is auditable on its own,
        # even while build/ is empty or being rewritten by the next variant
        content = b'patched'.ljust(SECTOR, b'\0')
        _image(self.original, self.files(), 22)
        _image(self.patched, self.files(a_content=content), 22)
        self.assertEqual(list(self.build.iterdir()), [])
        structured, n, bad, report = self.run_placement(self.placement_rows(content))
        self.assertTrue(structured, report)
        self.assertEqual((n, bad), (1, 0), report)
        self.assertIn('1 changed file(s)', report)
        self.assertIn('1 placed files on the disc, 0 byte mismatches', report)
        self.assertNotIn('FAIL', report)

    def test_placement_hash_mismatch_is_a_byte_mismatch(self):
        content = b'patched'.ljust(SECTOR, b'\0')
        _image(self.original, self.files(), 22)
        _image(self.patched, self.files(a_content=content), 22)
        rows = self.placement_rows(content, sha='0' * 64)
        structured, n, bad, report = self.run_placement(rows)
        self.assertTrue(structured, report)
        self.assertEqual((n, bad), (1, 1), report)
        self.assertIn('MISMATCH A.BIN: disc bytes differ from the placement record', report)

    def test_placement_must_agree_with_the_iso_record(self):
        content = b'patched'.ljust(SECTOR, b'\0')
        _image(self.original, self.files(), 22)
        _image(self.patched, self.files(a_content=content), 22)
        _structured, _n, _bad, report = self.run_placement(
            self.placement_rows(content, extent=20))
        self.assertIn('placement record mismatch', report)

    def test_placement_file_round_trips_and_rejects_a_foreign_header(self):
        path = self.root / 'variant.bin.placement.tsv'
        content = b'patched'.ljust(SECTOR, b'\0')
        path.write_text('path\textent\tsize\tsha256\n'
                        f'A.BIN\t21\t{len(content)}\t'
                        f'{hashlib.sha256(content).hexdigest()}\n')
        self.assertEqual(verify_disc.read_placement(path),
                         [('A.BIN', 21, len(content),
                           hashlib.sha256(content).hexdigest())])
        path.write_text('name\tlba\tbytes\thash\nA.BIN\t21\t2048\t00\n')
        with self.assertRaises(ValueError):
            verify_disc.read_placement(path)


if __name__ == '__main__':
    unittest.main()
