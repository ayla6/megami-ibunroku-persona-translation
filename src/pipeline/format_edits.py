"""Container-aware edits over prepared payloads; no image encoding at apply time."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import csv
from pathlib import Path
from functools import lru_cache
import struct
from typing import Final

SECTOR: Final = 2048
MES_ENTRIES: Final = 256
MES_TABLE_BYTES: Final = (MES_ENTRIES + 1) * 2

@dataclass(frozen=True)
class EntryEdit:
    index: int
    data: bytes
    source: str


def mes_table(data: bytes) -> tuple[int, ...]:
    if len(data) < MES_TABLE_BYTES:
        raise ValueError('MES: truncated table')
    table = struct.unpack_from('<257H', data)
    if table[0] < 1 or table[-1] * SECTOR > len(data) or any(a > b for a, b in zip(table, table[1:])):
        raise ValueError('MES: invalid entry extents')
    return table


def mes_entry(data: bytes, index: int) -> bytes:
    if not 0 <= index < MES_ENTRIES:
        raise ValueError('MES: entry index outside table')
    table = mes_table(data)
    return data[table[index] * SECTOR:table[index + 1] * SECTOR]


def replace_mes(data: bytes, edits: list[EntryEdit]) -> bytes:
    """Keep extents where payloads fit, otherwise repack once in entry order.

    Checks are per entry, so changes to another entry do not invalidate an edit.
    Padding is deterministic; table changes belong to this container operation.
    """
    table = mes_table(data)
    replacements: dict[int, bytes] = {}
    for edit in edits:
        if edit.index in replacements:
            raise ValueError('MES: duplicate entry edit')
        original = mes_entry(data, edit.index)
        if hashlib.sha1(original).hexdigest() != edit.source:
            raise ValueError(f'MES: source entry {edit.index} differs')
        if len(edit.data) < 10 or edit.data[-2:] != b'\x7f\xff':
            raise ValueError('MES: prepared entry lacks header or end token')
        replacements[edit.index] = edit.data
    if all(len(blob) <= (table[i + 1] - table[i]) * SECTOR for i, blob in replacements.items()):
        result = bytearray(data)
        for i, blob in replacements.items():
            start, end = table[i] * SECTOR, table[i + 1] * SECTOR
            result[start:end] = blob + bytes(end - start - len(blob))
        return bytes(result)
    pieces: list[bytes] = []
    starts: list[int] = [table[0]]
    for index in range(MES_ENTRIES):
        blob = replacements.get(index, data[table[index] * SECTOR:table[index + 1] * SECTOR])
        pieces.append(blob)
        starts.append(starts[-1] + (len(blob) + SECTOR - 1) // SECTOR)
    if starts[-1] > 65535:
        raise ValueError('MES: sector table overflow')
    result = bytearray(data[:table[0] * SECTOR])
    struct.pack_into('<257H', result, 0, *starts)
    for blob in pieces:
        result.extend(blob)
        result.extend(bytes((-len(blob)) % SECTOR))
    return bytes(result)


def mes_changes(before: bytes, after: bytes) -> list[EntryEdit]:
    """Represent changed encoded entries, excluding only trailing sector padding."""
    import mescodec
    first, second = mes_table(before), mes_table(after)
    result: list[EntryEdit] = []
    for index in range(MES_ENTRIES):
        old = before[first[index] * SECTOR:first[index + 1] * SECTOR]
        new = after[second[index] * SECTOR:second[index + 1] * SECTOR]
        if old == new:
            continue
        if len(new) < 10:
            raise ValueError('MES: replacement entry is empty')
        # A clipped decoded tail can precede the end token: the original encoder
        # may include bytes after the game's decode limit. Find the real token
        # by decoding with a sufficiently high limit instead.
        _decoded, used = mescodec.decode(new[8:], limit=1 << 24)
        end = 8 + used + 1
        if new[end - 2:end] != b'\x7f\xff' or any(new[end:]):
            raise ValueError('MES: non-padding bytes after encoded entry')
        result.append(EntryEdit(index, new[:end], hashlib.sha1(old).hexdigest()))
    return result


@lru_cache(maxsize=1)
def registry() -> dict[str, str]:
    with Path(__file__).with_name('file_formats.tsv').open(newline='') as stream:
        reader=csv.DictReader(stream,delimiter='\t')
        if reader.fieldnames!=['path','format']: raise ValueError('invalid format registry')
        result: dict[str,str]={}
        for row in reader:
            if row['path'] in result or row['format']!='mes': raise ValueError('invalid format registry entry')
            result[row['path']]=row['format']
        return result


_prepared: dict[tuple[str,str],tuple[EntryEdit,...]]={}

def prepared_mes_changes(before: bytes, after: bytes) -> list[EntryEdit]:
    key=(hashlib.sha1(before).hexdigest(),hashlib.sha1(after).hexdigest())
    if key not in _prepared:
        entries=mes_changes(before,after)
        if replace_mes(before,entries)!=after: raise ValueError('MES edits do not reproduce the archive')
        if len(_prepared)>=4: _prepared.pop(next(iter(_prepared)))
        _prepared[key]=tuple(entries)
    return list(_prepared[key])
