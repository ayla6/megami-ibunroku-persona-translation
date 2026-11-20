"""Scale note velocities of source-derived menu cues wherever they are shared.

Cue identities come from retail UI archives and the overworld menu-bank
sequence table. Only complete matching MIDI event streams are changed;
notes, programs, timing, controllers and every other byte remain intact.
"""
from __future__ import annotations

import csv
import io
import os
from pathlib import Path
import struct
import sys
from dataclasses import dataclass
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import toolpath
import build_step_cache as steps

ROOT: Final = Path(toolpath.ROOT)
RETAIL: Final = ROOT / 'data/psx'
BUILD: Final = ROOT / 'build'
CACHE: Final = BUILD / 'step_cache/menu-sounds'
MAGIC: Final = b'pQES'
FIELDS: Final = ('path', 'offset', 'before', 'after')
UI_SOURCES: Final = {
    # Shared field/ADV input: back, list navigation, confirm, wheel navigation,
    # alternate confirm. The quieter, darker open/back-alternate cue is not selected. Source: common/ui/input.c,
    # adv/ui/menucursor.c and adv/audio/sound.c's +0x20 sequence table.
    'ADV/ADVCMD.BIN': tuple(range(8, 13)),
}
# Complete streams also match the field-menu copies in 2DSEQ packs.



@dataclass(frozen=True)
class Edit:
    path: str
    offset: int
    before: int
    after: int


def vlq(data: bytes, at: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        byte = data[at]
        at += 1
        value = (value << 7) | (byte & 127)
        if byte < 128:
            return value, at
    raise ValueError('menu sounds: malformed MIDI variable-length value')


def events(data: bytes, start: int) -> tuple[int, list[int]]:
    """End of a SEQ event stream and absolute offsets of nonzero note velocities."""
    at, status = start, 0
    velocities: list[int] = []
    while at < len(data):
        _delta, at = vlq(data, at)
        if data[at] >= 128:
            status = data[at]
            at += 1
        if status == 255:
            kind = data[at]
            length, at = vlq(data, at + 1)
            at += length
            if kind == 47:
                if length:
                    raise ValueError('menu sounds: malformed MIDI end marker')
                return at, velocities
        elif status in (240, 247):
            length, at = vlq(data, at)
            at += length
        elif 128 <= status < 240:
            count = 1 if status >> 4 in (12, 13) else 2
            if any(byte >= 128 for byte in data[at:at + count]) or at + count > len(data):
                raise ValueError('menu sounds: invalid MIDI data')
            if status >> 4 == 9 and data[at + 1]:
                velocities.append(at + 1)
            at += count
        else:
            raise ValueError('menu sounds: MIDI event without status')
    raise ValueError('menu sounds: missing MIDI end marker')


def cues() -> dict[bytes, tuple[int, ...]]:
    result: dict[bytes, tuple[int, ...]] = {}
    paths = [RETAIL / p for p in UI_SOURCES]
    for path in paths:
        data = path.read_bytes()
        indices = UI_SOURCES[path.relative_to(RETAIL).as_posix()]
        starts = [struct.unpack_from('<I', data, i * 4)[0] for i in indices]
        for start in starts:
            if data[start:start + 4] != MAGIC:
                raise ValueError(f'{path}: menu sequence is not SEQ')
            body = start + 15
            end, velocities = events(data, body)
            if velocities:
                result[data[body:end]] = tuple(at - body for at in velocities)
    return result


def serialize(edits: list[Edit]) -> str:
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
    writer.writerow(FIELDS)
    writer.writerows((e.path, e.offset, e.before, e.after) for e in edits)
    return stream.getvalue()


def read(path: Path) -> list[Edit]:
    with path.open(newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if reader.fieldnames != list(FIELDS):
            raise ValueError('menu sounds: invalid edit manifest')
        return [Edit(row['path'], int(row['offset']), int(row['before']), int(row['after']))
                for row in reader]


def default_level() -> int:
    import mods
    mod = mods.by_label()[Path(__file__).parent.name]
    return next(setting.default for setting in mod.ranges if setting.key == 'level')


def plan(percent: int | None = None) -> list[Edit]:
    if percent is None:
        percent = default_level()
    if not 0 <= percent <= 100:
        raise ValueError("menu sounds: percentage must be between 0 and 100")
    target = CACHE / 'plan.tsv'

    def generate() -> None:
        templates = cues()
        edits: dict[tuple[str, int], Edit] = {}
        for path in sorted(RETAIL.rglob('*')):
            if not path.is_file():
                continue
            data = path.read_bytes()
            relative = path.relative_to(RETAIL).as_posix()
            for cue, velocities in templates.items():
                at = data.find(cue)
                while at >= 0:
                    for pos in velocities:
                        before = data[at + pos]
                        edits[relative, at + pos] = Edit(relative, at + pos, before, (max(1, (before * percent + 50) // 100) if percent else 0))
                    at = data.find(cue, at + len(cue))
        if not edits:
            raise ValueError('menu sounds: no source menu cues found')
        target.write_text(serialize([edits[key] for key in sorted(edits)]))

    steps.run('menu sound cue map', [Path(__file__), RETAIL], [target], generate,
              CACHE / 'inputs.tsv', context=(str(percent),))
    return read(target)


def apply(edits: list[Edit], reverse: bool = False) -> None:
    by_path: dict[str, list[Edit]] = {}
    for edit in edits:
        by_path.setdefault(edit.path, []).append(edit)
    for relative, rows in by_path.items():
        dest = BUILD / relative
        if reverse and not dest.is_file():
            continue
        data = bytearray((dest if dest.is_file() else RETAIL / relative).read_bytes())
        changed = False
        for edit in rows:
            before, after = (edit.after, edit.before) if reverse else (edit.before, edit.after)
            if reverse and data[edit.offset] == after:
                continue
            if data[edit.offset] != before:
                raise ValueError(f'{relative}:{edit.offset:#x}: menu cue changed before attenuation')
            data[edit.offset] = after
            changed = True
        if changed:
            dest.parent.mkdir(parents=True, exist_ok=True)
            temporary = dest.with_suffix(dest.suffix + '.tmp')
            temporary.write_bytes(data)
            os.replace(temporary, dest)


def retail() -> None:
    active = CACHE / 'active.tsv'
    if active.exists():
        apply(read(active), reverse=True)
        active.unlink()


def main() -> None:
    active = CACHE / 'active.tsv'
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'retail'))
    parser.add_argument('--percent', type=int, default=default_level())
    args = parser.parse_args()
    if args.command == 'retail':
        retail()
    elif args.command == 'build':
        edits = plan(args.percent)
        # Record before mutation so interruption can still restore completed writes.
        with (CACHE / 'values.tsv').open('w', newline='') as stream:
            writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
            writer.writerow(('path', 'offset', 'parameter', 'original'))
            writer.writerows((e.path, e.offset, 'level', e.before) for e in edits)
        active.write_text(serialize(edits))
        apply(edits)
        print(f'menu sounds: {len(edits)} menu navigation/confirm/back note velocities at {args.percent}%')
    else:
        raise SystemExit('usage: menu_sounds.py build|retail')


if __name__ == '__main__':
    main()
