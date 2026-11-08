#!/usr/bin/env python3
"""Encode a layout-changing delta from the preimage map, not a matcher.

A size-changer moves files and shifts extents, but its edit must compose
with every in-place option that came before it. xdelta's matcher is free to
copy repeated bytes from anywhere in the source - a run of zeros in one
file can stand in for the same bytes in another - so a decoration inside
the real preimage silently disappears (the release's original failure:
`add-saves` wiped skipfmv's edits in EXE/MOVIE.EXE).

This writer decides every COPY itself:

* inside a target file extent, a byte is copied from the same file's byte
  in the source layout, so a decoration on that file rides along;
* a target byte that is not inside a source file (a gap) is copied from
  the same offset only when that offset is also a gap in the source, so
  the ISO directory and padding stay consistent with what the decorated
  chain already holds;
* everywhere else the byte is a literal (or a RUN of one repeated byte).

No source byte is ever chosen for its content, so a decoy cannot win.
Windows carry an Adler-32 checksum, and the release build verifies each
patch with `xdelta3 -d -J` before publishing it.

Usage: python tools/sizedelta.py SOURCE TARGET OUTPUT
"""
import os
import struct
import sys
import zlib
from pathlib import Path

SECTOR = 2352
USER_OFFSET = 24
USER = 2048
VCD_SOURCE = 0x01
VCD_ADLER32 = 0x04
WINDOW = 8 * 1024 * 1024


def varint(value):
    groups = [value & 0x7f]
    value >>= 7
    while value:
        groups.append(value & 0x7f)
        value >>= 7
    groups.reverse()
    return bytes([group | 0x80 for group in groups[:-1]] + [groups[-1]])


def op_add(size):
    assert size >= 1
    return bytes([1 + size]) if size <= 17 else bytes([1]) + varint(size)


def op_copy(size):
    assert size >= 4
    return bytes([19 + size - 3]) if size <= 18 else bytes([19]) + varint(size)


def op_run(size):
    assert size >= 1
    return bytes([0]) + varint(size)


class Image:
    """A raw Mode 2 Form 1 image, viewed through its user-data bytes."""

    def __init__(self, path):
        import numpy as np
        self.path = Path(path)
        self.array = np.memmap(path, dtype=np.uint8, mode='r')
        self.size = int(self.array.shape[0])
        if self.size % SECTOR:
            raise ValueError(f'{path}: not a whole number of sectors')
        self.user = self.array.reshape(self.size // SECTOR, SECTOR)[
            :, USER_OFFSET:USER_OFFSET + USER].reshape(-1)

    def user_bytes(self, lba, size):
        return self.user[lba * USER:lba * USER + size].tobytes()

    def entries(self, lba, size):
        data = self.user_bytes(lba, size)
        pos = 0
        while pos < len(data):
            length = data[pos]
            if length == 0:
                pos = (pos // USER + 1) * USER
                continue
            if pos + length > len(data) or length < 34:
                break
            extent, = struct.unpack_from('<I', data, pos + 2)
            extent_size, = struct.unpack_from('<I', data, pos + 10)
            flags = data[pos + 25]
            name_len = data[pos + 32]
            name = data[pos + 33:pos + 33 + name_len]
            if name not in (b'\x00', b'\x01'):
                yield (name.decode('ascii', 'replace').split(';')[0], extent,
                       extent_size, bool(flags & 2))
            pos += length

    def files(self):
        """Every file record in the ISO tree: path -> (extent_lba, size)."""
        pvd = self.user_bytes(16, USER)
        root, = struct.unpack_from('<I', pvd, 158)
        root_size, = struct.unpack_from('<I', pvd, 166)
        found = {}

        def walk(lba, size, prefix, depth):
            for name, extent, extent_size, is_dir in self.entries(lba, size):
                path = prefix + name + ('/' if is_dir else '')
                if is_dir:
                    if depth < 4:
                        walk(extent, extent_size, path, depth + 1)
                else:
                    found[path] = (extent, extent_size)
        walk(root, root_size, '', 0)
        return found


def sector_count(size):
    return (size + USER - 1) // USER


def file_ranges(files):
    ranges = []
    for lba, size in files.values():
        start = lba * SECTOR
        ranges.append((start, start + sector_count(size) * SECTOR))
    ranges.sort()
    return ranges


def gap_parts(start, end, file_spans):
    """Parts of [start, end) that are outside every source file extent."""
    parts = []
    cursor = start
    for file_start, file_end in file_spans:
        if file_end <= cursor:
            continue
        if file_start >= end:
            break
        if file_start > cursor:
            parts.append((cursor, min(file_start, end)))
        cursor = max(cursor, min(file_end, end))
        if cursor >= end:
            break
    if cursor < end:
        parts.append((cursor, end))
    return parts


def plan(before, after, after_len):
    """(start, end, slice_start or None) runs with a contiguous preimage.

    A slice_start means target[start:end] copies source[slice_start:...]
    offset for offset. None means literals. Toolchain timestamps live in
    the source layout, and a target gap that coincides with the source's
    own gap may carry them; a gap inside a source file must not, because
    that file's decorated bytes are not what the one-shot build leaves in
    a hole.
    """
    source_files = file_ranges(before)
    spans = []

    def gap(start, end):
        cursor = start
        for gap_start, gap_end in gap_parts(start, end, source_files):
            if gap_start > cursor:
                spans.append((cursor, gap_start, None))
            spans.append((gap_start, gap_end, gap_start))
            cursor = gap_end
        if cursor < end:
            spans.append((cursor, end, None))

    order = sorted((lba, size, path) for path, (lba, size) in after.items())
    pos = 0
    for lba, size, path in order:
        start = lba * SECTOR
        end = start + sector_count(size) * SECTOR
        if start > pos:
            gap(pos, start)
        if path in before:
            old_lba, old_size = before[path]
            old_start = old_lba * SECTOR
            common = min(sector_count(size), sector_count(old_size)) * SECTOR
            spans.append((start, start + common, old_start))
            if end > start + common:
                spans.append((start + common, end, None))
        else:
            gap(start, end)
        pos = end
    if pos < after_len:
        gap(pos, after_len)
    return spans


def emit_literals(data, instructions, values):
    size = len(values)
    if not size:
        return
    if size >= 4 and values.count(values[0]) == size:
        data.append(values[0])
        instructions.extend(op_run(size))
        return
    data.extend(values)
    instructions.extend(op_add(size))


def emit_copy(instructions, addresses, address, size):
    if not size:
        return
    assert address >= 0
    instructions.extend(op_copy(size))
    addresses.extend(varint(address))


def build_window(source, target, start, end, slice_start):
    """One VCDIFF window covering target[start:end]."""
    length = end - start
    data = bytearray()
    instructions = bytearray()
    addresses = bytearray()
    target_bytes = target.array[start:end].tobytes()
    if slice_start is None:
        emit_literals(data, instructions, target_bytes)
    else:
        source_bytes = source.array[
            slice_start:min(slice_start + length, source.size)].tobytes()
        index = 0
        literal_start = None
        while index < len(source_bytes):
            if target_bytes[index] == source_bytes[index]:
                if literal_start is not None:
                    emit_literals(data, instructions,
                                  target_bytes[literal_start:index])
                    literal_start = None
                run_end = index + 1
                while (run_end < len(source_bytes)
                       and target_bytes[run_end] == source_bytes[run_end]):
                    run_end += 1
                if run_end - index >= 4:
                    emit_copy(instructions, addresses, index, run_end - index)
                else:
                    literal_start = index
                index = run_end
            else:
                if literal_start is None:
                    literal_start = index
                index += 1
        if literal_start is not None:
            emit_literals(data, instructions, target_bytes[literal_start:length])
        elif len(source_bytes) < length:
            emit_literals(data, instructions, target_bytes[len(source_bytes):length])
    head = (bytes([VCD_SOURCE | VCD_ADLER32]) if slice_start is not None
            else bytes([VCD_ADLER32]))
    if slice_start is not None:
        head += varint(length) + varint(slice_start)
    body = (varint(length) + bytes([0]) + varint(len(data))
            + varint(len(instructions)) + varint(len(addresses))
            + struct.pack('>I', zlib.adler32(target_bytes)))
    body += bytes(data) + bytes(instructions) + bytes(addresses)
    return head + varint(len(body)) + body


def build(source_path, target_path, out_path):
    """Write a VCDIFF delta that reconstructs `target_path` from its layout."""
    source = Image(source_path)
    target = Image(target_path)
    spans = plan(source.files(), target.files(), target.size)
    windows = 0
    with open(out_path, 'wb') as out:
        out.write(b'\xd6\xc3\xc4\x00\x00')
        for start, end, slice_start in spans:
            for piece in range(start, end, WINDOW):
                piece_end = min(piece + WINDOW, end)
                piece_slice = (None if slice_start is None
                               else slice_start + piece - start)
                out.write(build_window(source, target, piece, piece_end,
                                       piece_slice))
                windows += 1
    return windows, len(spans)


def main(argv):
    if len(argv) != 4:
        raise SystemExit('usage: sizedelta.py SOURCE TARGET OUTPUT')
    written, total = build(argv[1], argv[2], argv[3])
    print(f'wrote {argv[3]} ({os.path.getsize(argv[3])} bytes, '
          f'{total} spans, {written} windows)')


if __name__ == '__main__':
    main(sys.argv)
