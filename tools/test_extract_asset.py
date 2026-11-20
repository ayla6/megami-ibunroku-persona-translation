"""The asset browser reads TIMs safely and never overwrites an export."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest
sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1]/'src')]
import toolpath
import extract_asset


class AssetExtraction(unittest.TestCase):
    def test_lists_complete_images_and_ignores_truncated_headers(self):
        header=struct.pack('<II',0x10,2)
        body=struct.pack('<IHHHH',20,0,0,2,2)+bytes(8)
        data=bytes(12)+header+body+header
        records=extract_asset.image_records(data)
        self.assertEqual([(r.offset,r.width,r.height,r.bpp)for r in records],[(12,2,2,16)])

    def test_export_protection_keeps_the_existing_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'asset.bin';path.write_bytes(b'edited art')
            with self.assertRaisesRegex(ValueError,'overwrite'):
                extract_asset.new_output(path)
            self.assertEqual(path.read_bytes(),b'edited art')
