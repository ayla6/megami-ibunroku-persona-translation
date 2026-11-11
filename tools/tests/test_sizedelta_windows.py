"""The fast preimage scan must emit the same VCDIFF as the scalar scan."""
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import sizedelta


class Image:
    def __init__(self, data):
        self.array = np.frombuffer(data, dtype=np.uint8)
        self.size = len(data)


def scalar_window(source, target, start, end, slice_start):
    """Independent bytewise baseline for preimage runs and VCDIFF framing."""
    length = end - start
    target_bytes = target.array[start:end].tobytes()
    source_bytes = source.array[slice_start:slice_start + length].tobytes()
    data, instructions, addresses = bytearray(), bytearray(), bytearray()
    index, literal = 0, None
    while index < len(source_bytes):
        if target_bytes[index] == source_bytes[index]:
            if literal is not None:
                sizedelta.emit_literals(data, instructions, target_bytes[literal:index])
                literal = None
            stop = index + 1
            while stop < len(source_bytes) and target_bytes[stop] == source_bytes[stop]:
                stop += 1
            if stop - index >= 4:
                sizedelta.emit_copy(instructions, addresses, index, stop - index)
            else:
                literal = index
            index = stop
        else:
            if literal is None:
                literal = index
            index += 1
    if literal is not None:
        sizedelta.emit_literals(data, instructions, target_bytes[literal:length])
    elif len(source_bytes) < length:
        sizedelta.emit_literals(data, instructions, target_bytes[len(source_bytes):length])
    import struct
    import zlib
    body = (sizedelta.varint(length) + b'\0' + sizedelta.varint(len(data)) +
            sizedelta.varint(len(instructions)) + sizedelta.varint(len(addresses)) +
            struct.pack('>I', zlib.adler32(target_bytes)) + data + instructions + addresses)
    return (bytes([sizedelta.VCD_SOURCE | sizedelta.VCD_ADLER32]) +
            sizedelta.varint(length) + sizedelta.varint(slice_start) +
            sizedelta.varint(len(body)) + body)


class SizeDeltaWindows(unittest.TestCase):
    def test_image_reads_only_requested_user_sectors(self):
        sectors = [bytes([n]) * sizedelta.USER for n in range(4)]
        raw = b''.join(bytes(sizedelta.USER_OFFSET) + data +
                       bytes(sizedelta.SECTOR - sizedelta.USER_OFFSET - sizedelta.USER)
                       for data in sectors)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'disc.bin'
            path.write_bytes(raw)
            image = sizedelta.Image(path)
            self.assertTrue(np.shares_memory(image.sectors, image.array))
            self.assertEqual(image.user_bytes(1, sizedelta.USER + 7), sectors[1] + sectors[2][:7])
            self.assertEqual(image.user_bytes(3, sizedelta.USER * 2), sectors[3])
            self.assertEqual(image.user_bytes(0, 0), b'')

    def test_fast_scan_matches_scalar_for_sparse_dense_and_short_inputs(self):
        rng = random.Random(12091)
        for length in (0, 1, 2, 3, 4, 5, 17, 255, 4096):
            for mode in ('equal', 'sparse', 'alternating', 'random', 'short'):
                with self.subTest(length=length, mode=mode):
                    target = bytes(rng.randrange(256) for _ in range(length))
                    source = bytearray(target)
                    if mode == 'sparse':
                        for i in range(0, length, 127):
                            source[i] ^= 0xff
                    elif mode == 'alternating':
                        for i in range(0, length, 2):
                            source[i] ^= 0xff
                    elif mode == 'random':
                        source = bytearray(rng.randrange(256) for _ in range(length))
                    elif mode == 'short':
                        del source[length // 2:]
                    source, target = Image(bytes(source)), Image(target)
                    self.assertEqual(sizedelta.build_window(source, target, 0, length, 0),
                                     scalar_window(source, target, 0, length, 0))

    def test_nonzero_source_and_target_offsets(self):
        source = Image(b'header' + b'unchanged--middle--tail' + b'extra')
        target = Image(b'other-header' + b'unchanged!!middle--tail' + b'extra')
        start, length, origin = len(b'other-header'), len(b'unchanged!!middle--tail'), len(b'header')
        self.assertEqual(sizedelta.build_window(source, target, start, start + length, origin),
                         scalar_window(source, target, start, start + length, origin))

    @unittest.skipUnless(shutil.which('xdelta3'), 'xdelta3 not installed')
    def test_window_round_trips_with_real_decoder(self):
        source = bytes(range(256)) * 32
        target = bytearray(source)
        target[123:130] = b'changed'
        target[4000:4100] = bytes(100)
        with tempfile.TemporaryDirectory() as tmp:
            src, delta, out = (Path(tmp) / name for name in ('source', 'delta', 'out'))
            src.write_bytes(source)
            delta.write_bytes(b'\xd6\xc3\xc4\0\0' + sizedelta.build_window(
                Image(source), Image(bytes(target)), 0, len(target), 0))
            subprocess.run([shutil.which('xdelta3'), '-d', '-s', str(src),
                            str(delta), str(out)], check=True)
            self.assertEqual(out.read_bytes(), bytes(target))


if __name__ == '__main__':
    unittest.main()
