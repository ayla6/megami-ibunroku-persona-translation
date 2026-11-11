"""The accelerated decoder retains retail token and overlap behavior."""
from pathlib import Path
import hashlib
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import mescodec
import mark


def scalar(data, limit=0x3F900):
    src, out = 0, bytearray()
    while len(out) < limit:
        c = data[src]; src += 1
        if c == 0x7F and data[src] == 0xFF:
            break
        if c < 0x80:
            n = ((c >> 2) & 31) + 2
            dist = 0x400 - (((c & 3) << 8) | data[src]); src += 1
            for _ in range(n):
                out.append(out[-dist])
        elif c < 0xA0:
            n = (c & 31) + 1
            out += data[src:src + n]; src += n
        elif c < 0xC0:
            for _ in range((c & 31) + 1):
                out.append(0); out.append(data[src]); src += 1
        elif c < 0xE0:
            n = (c & 31) + 2
            out += bytes([data[src]]) * n; src += 1
        else:
            if c == 0xFF:
                n = data[src] + 0x20; src += 1
            else:
                n = (c & 31) + 1
            out += bytes(n)
    return bytes(out), src


class MesDecode(unittest.TestCase):
    def test_mark_encoder_preserves_token_selection(self):
        rng = random.Random(1042)
        data = bytes(rng.choice([0, 0, 0, 1, 2, 3, 4, 5]) for _ in range(8192))
        data += b'\0' * 300 + b'ABC' * 100
        encoded = mark.encode(data)
        self.assertEqual(len(encoded), 5068)
        self.assertEqual(hashlib.sha256(encoded).hexdigest(),
                         '1bb78c5f3ce94502a21be089dbdfd675a9d66b14d3784762d7a623237aab7c47')
        self.assertEqual(mescodec.decode(encoded, len(data))[0], data)

    def test_every_retail_scene_at_full_and_clipped_limits(self):
        data = (ROOT / 'data/psx/ADV/MES.BIN').read_bytes()
        for index, (start, end) in enumerate(mescodec.entries(data)):
            raw = data[start * 2048:end * 2048][8:]
            for limit in (1, 97, 0x3F900):
                with self.subTest(index=index, limit=limit):
                    self.assertEqual(mescodec.decode(raw, limit), scalar(raw, limit))

    def test_random_overlapping_copies_and_interleaved_pairs(self):
        rng = random.Random(310)
        for _ in range(500):
            prefix = bytes(rng.randrange(256) for _ in range(32))
            dist = rng.randrange(1, 33)
            count = rng.randrange(2, 34)
            value = 0x400 - dist
            token = bytes([((count - 2) << 2) | (value >> 8), value & 255])
            pairs = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 33)))
            stream = bytes([0x9f]) + prefix + token + bytes([0xA0 | (len(pairs) - 1)]) + pairs + b'\x7f\xff'
            self.assertEqual(mescodec.decode(stream), scalar(stream))

    def test_bad_back_reference_and_truncated_pairs_fail(self):
        for stream in (b'\0\0', b'\xa1\x10'):
            with self.subTest(stream=stream):
                with self.assertRaises(IndexError):
                    scalar(stream)
                with self.assertRaises(IndexError):
                    mescodec.decode(stream)


if __name__ == '__main__':
    unittest.main()
