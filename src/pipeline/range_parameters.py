"""Integer settings and deterministic percentage writes shared by patch builders."""
from __future__ import annotations
from dataclasses import dataclass
import csv
from pathlib import Path
from collections.abc import Callable, Sequence
from typing import Final

FIELDS: Final = ('path', 'offset', 'parameter', 'original')

@dataclass(frozen=True)
class RangeSetting:
    key: str
    minimum: int
    maximum: int
    step: int
    default: int
    name: str
    edits: str = ''

    def validate(self, text: str) -> int:
        if not text.isascii() or not text.isdecimal():
            raise ValueError(f'{self.key}: expected an integer')
        value = int(text)
        if not self.minimum <= value <= self.maximum or (value - self.minimum) % self.step:
            raise ValueError(f'{self.key}: expected {self.minimum}..{self.maximum}, step {self.step}')
        return value

    def bounds(self) -> str:
        return f'{self.minimum},{self.maximum},{self.step},{self.default}'

@dataclass(frozen=True)
class Scale:
    offset: int
    parameter: str
    original: int

    def value(self, percent: int) -> int:
        return max(1, (self.original * percent + 50) // 100) if percent and self.original else 0


def apply_files(root: Path, build: Path, settings: Sequence[RangeSetting],
                value: Callable[[str], str]) -> None:
    """Apply declared byte settings once per file after its mod is built.

    An original of 100 stores the integer setting directly; other originals
    use percentage scaling. The same maps are embedded in release layers.
    """
    files: dict[Path, bytearray] = {}
    for setting in settings:
        selected = setting.validate(value(setting.key))
        with (root / setting.edits).open(newline='') as stream:
            reader = csv.DictReader(stream, delimiter='\t')
            if reader.fieldnames != list(FIELDS):
                raise ValueError('invalid range edit map')
            for row in reader:
                if row['parameter'] != setting.key:
                    continue
                path = (build / row['path']).resolve()
                if not path.is_relative_to(build.resolve()):
                    raise ValueError('range edit path escapes build directory')
                data = files.get(path)
                if data is None:
                    files[path] = data = bytearray(path.read_bytes())
                scale = Scale(int(row['offset']), setting.key, int(row['original']))
                if not 0 <= scale.offset < len(data):
                    raise ValueError(f'{path}: range edit outside file')
                data[scale.offset] = scale.value(selected)
    for path, data in files.items():
        if path.read_bytes() != data:
            path.write_bytes(data)
