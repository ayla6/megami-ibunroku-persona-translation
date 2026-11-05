"""Disc discovery and extraction without depending on the real game data."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src' / 'injection_tools'))
import disc_data
import image_check

SECTOR = disc_data.ISO_SECTOR


def _record(name, lba, size, flags=0):
    raw = name if isinstance(name, bytes) else name.encode('ascii')
    length = 33 + len(raw)
    if length % 2:
        length += 1
    rec = bytearray(length)
    rec[0] = length
    struct.pack_into('<I', rec, 2, lba)
    struct.pack_into('<I', rec, 10, size)
    rec[25] = flags
    rec[32] = len(raw)
    rec[33:33 + len(raw)] = raw
    return bytes(rec)


def _dir(*records):
    data = b''.join(records)
    return data + b'\0' * (SECTOR - len(data))


def _sfo(fields):
    keys = list(fields.items())
    key_table = bytearray()
    key_offsets = {}
    for key, _value in keys:
        key_offsets[key] = len(key_table)
        key_table += key.encode('ascii') + b'\0'
    key_start = 20 + 16 * len(keys)
    data_start = key_start + len(key_table)
    values = bytearray()
    value_offsets = {}
    for key, value in keys:
        value_offsets[key] = len(values)
        raw = value if isinstance(value, bytes) else str(value).encode('utf-8') + b'\0'
        values += raw
    out = bytearray(20 + 16 * len(keys))
    struct.pack_into('<4sIIII', out, 0, b'\0PSF', 0x101, key_start,
                     data_start, len(keys))
    for i, (key, value) in enumerate(keys):
        raw = value if isinstance(value, bytes) else str(value).encode('utf-8') + b'\0'
        struct.pack_into('<HHIII', out, 20 + 16 * i, key_offsets[key], 0x0204,
                         len(raw), len(raw), value_offsets[key])
    return bytes(out) + bytes(key_table) + bytes(values)


def make_iso(path, disc_id='ULUS12345', title='Test Persona'):
    """A tiny but valid PSP-shaped ISO with a nested PSP_GAME tree."""
    param = _sfo({'DISC_ID': disc_id, 'TITLE': title})
    sectors = {
        16: None,   # PVD, filled below
        20: _dir(_record(b'\0', 20, SECTOR, 2), _record(b'\1', 20, SECTOR, 2),
                 _record('PSP_GAME', 21, SECTOR, 2),
                 _record('UMD_DATA.BIN;1', 26, 4)),
        21: _dir(_record(b'\0', 21, SECTOR, 2), _record(b'\1', 20, SECTOR, 2),
                 _record('PARAM.SFO;1', 22, len(param)),
                 _record('SYSDIR', 23, SECTOR, 2),
                 _record('USRDIR', 24, SECTOR, 2)),
        22: param,
        23: _dir(_record(b'\0', 23, SECTOR, 2), _record(b'\1', 21, SECTOR, 2),
                 _record('EBOOT.BIN;1', 25, 4)),
        24: _dir(_record(b'\0', 24, SECTOR, 2), _record(b'\1', 21, SECTOR, 2),
                 _record('pack', 27, SECTOR, 2)),
        25: b'BOOT',
        26: b'UMD!',
        27: _dir(_record(b'\0', 27, SECTOR, 2), _record(b'\1', 24, SECTOR, 2),
                 _record('talk', 28, SECTOR, 2)),
        28: _dir(_record(b'\0', 28, SECTOR, 2), _record(b'\1', 27, SECTOR, 2),
                 _record('TEST.BIN;1', 29, 5)),
        29: b'TALK!',
    }
    pvd = bytearray(SECTOR)
    pvd[0] = 1
    pvd[1:6] = b'CD001'
    pvd[6] = 1
    root = _record(b'\0', 20, SECTOR, 2)
    pvd[156:156 + len(root)] = root
    sectors[16] = bytes(pvd)
    with open(path, 'wb') as f:
        for lba in range(max(sectors) + 1):
            data = sectors.get(lba, b'')
            f.write(data + b'\0' * (SECTOR - len(data)))
    return path


def sparse(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as f:
        f.truncate(size)
    return path


class Identify(unittest.TestCase):

    def test_psp_iso_is_identified_from_its_own_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            iso = make_iso(Path(tmp) / 'arbitrary name.iso')
            disc = disc_data.identify(iso)
        self.assertIsNotNone(disc)
        self.assertEqual(disc.kind, 'psp-us')
        self.assertEqual(disc.disc_id, 'ULUS12345')
        self.assertIn('Test Persona', disc.label)

    def test_psp_region_comes_from_sony_title_ids(self):
        cases = {
            'ULUS10432': 'us', 'ULJM05422': 'jp', 'ULJS00001': 'jp',
            'ULES01374': 'eu', 'ULKS00001': 'korea', 'ULAS00001': 'asia',
            'NPUG00001': 'us', 'NPJH50001': 'jp', 'NPEB00001': 'eu',
            'not-a-title': None,
        }
        for title_id, region in cases.items():
            self.assertEqual(disc_data.psp_region(title_id), region, title_id)

    def test_psx_revision_is_identified_by_size_and_crc(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            rev0 = sparse(tmp / 'rev0.bin', image_check.SIZE)
            rev1 = sparse(tmp / 'rev1.bin', image_check.REV1_SIZE)
            with patch.object(disc_data.image_check, 'crc32',
                              return_value=image_check.CRC32):
                self.assertEqual(disc_data.identify(rev0).kind, 'psx')
            with patch.object(disc_data.image_check, 'crc32',
                              return_value=image_check.REV1_CRC32):
                self.assertEqual(disc_data.identify(rev1).kind, 'psx-rev1')
            with patch.object(disc_data.image_check, 'crc32', return_value=0):
                self.assertIsNone(disc_data.identify(rev0))
                self.assertIsNone(disc_data.identify(rev1))

    def test_iso_dot_records_are_not_file_names(self):
        self.assertIsNone(disc_data._iso_name(b'\0'))
        self.assertIsNone(disc_data._iso_name(b'\1'))
        self.assertEqual(disc_data._iso_name(b'PSP_GAME'), 'PSP_GAME')
        self.assertEqual(disc_data._iso_name(b'PARAM.SFO;1'), 'PARAM.SFO')


class Extract(unittest.TestCase):

    def test_psp_iso_extracts_the_whole_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            iso = make_iso(tmp / 'us.iso')
            out = tmp / 'psp_us'
            disc_data.extract_psp(iso, 'us', out_dir=out, force=True,
                                  log=lambda *_: None)
            self.assertTrue(disc_data.psp_complete('us', out))
            self.assertEqual((out / 'UMD_DATA.BIN').read_bytes(), b'UMD!')
            self.assertEqual((out / 'PSP_GAME' / 'SYSDIR' / 'EBOOT.BIN').read_bytes(),
                             b'BOOT')
            self.assertEqual((out / 'PSP_GAME' / 'USRDIR' / 'pack' / 'talk'
                              / 'TEST.BIN').read_bytes(), b'TALK!')

    def test_psp_extraction_refuses_the_wrong_region(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            iso = make_iso(tmp / 'jp.iso', disc_id='ULJM05422', title='Persona')
            with self.assertRaises(SystemExit):
                disc_data.extract_psp(iso, 'us', out_dir=tmp / 'out', force=True,
                                      log=lambda *_: None)

    def test_resolve_psx_searches_data_discs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            discs = tmp / 'discs'
            image = sparse(discs / 'some folder' / 'whatever.bin',
                           image_check.SIZE)
            with patch.object(disc_data.image_check, 'crc32',
                              return_value=image_check.CRC32):
                found = disc_data.resolve_psx(tmp / 'missing.bin', discs)
            self.assertEqual(found, str(image))

    def test_resolve_psx_explains_a_rev1_only_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            discs = tmp / 'discs'
            sparse(discs / 'rev1.bin', image_check.REV1_SIZE)
            with patch.object(disc_data.image_check, 'crc32',
                              return_value=image_check.REV1_CRC32):
                with self.assertRaisesRegex(SystemExit, 'only the Rev 1'):
                    disc_data.resolve_psx(tmp / 'missing.bin', discs)

    def test_psx_extraction_reuses_the_existing_extractor(self):
        with patch.object(disc_data.subprocess, 'run') as run:
            disc_data.extract_psx('image.bin', '/tmp/out', rev1=True, force=True,
                                  log=lambda *_: None)
        command = run.call_args.args[0]
        self.assertEqual(Path(command[1]), disc_data.PSX_EXTRACT)
        self.assertIn('--rev1', command)

    def test_psx_complete_requires_the_files_the_build_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            for name in disc_data.PSX_REQUIRED:
                path = out / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'x')
            (out / 'TALK').mkdir()
            self.assertFalse(disc_data.psx_complete(out))
            (out / 'TALK' / 'ALIEN.BIN').write_bytes(b'x')
            self.assertTrue(disc_data.psx_complete(out))

    def test_requested_kind_without_a_disc_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, 'no psp-us disc'):
                disc_data.prepare(tmp, only={'psp-us'}, log=lambda *_: None)


if __name__ == '__main__':
    unittest.main()
