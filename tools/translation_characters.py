"""List characters in the current merged English wording for both editions."""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
import re
import sys
from typing import Final, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import toolpath
import choices
import etext
import make_vwf_font
import toolbelt
import vwf_wrap

CONTROL: Final = re.compile(r"<FFFD>(?:<[^>]+>|.)|<FF(?:07|08|0F)>あ|<G([0-9A-F]{3})>|<[^>]+>")
NATIVE: Final = "native glyph token"
WORDING: Final = "wording"


def wording() -> Iterator[tuple[Path, str]]:
    root = Path(toolpath.TRANSLATION)
    gen, manual = root / "generated", root / "manual"
    paired: set[Path] = set()
    choice_positions = {int(row["ptr"]) - choices.BASE for row in choices.original()}
    for base in (gen, manual):
        for path in sorted(base.rglob("*.tsv")):
            rel = path.relative_to(base).with_suffix("")
            with path.open(encoding="utf-8", newline="") as stream:
                rows = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
                keys = set(rows.fieldnames or ())
                if {"id", "pos", "en"} <= keys:
                    if rel not in paired:
                        paired.add(rel)
                        for row in toolbelt.merge(
                            rel.as_posix(), toolbelt._raw_generated(rel.as_posix(), optional=True),
                            toolbelt._raw_manual(rel.as_posix())
                        ):
                            text = row["en"]
                            if rel.as_posix() == "SLPS_005.00" and int(row["pos"], 16) in choice_positions:
                                text = text.replace("|", "")
                            yield rel, text
                elif keys & {"en", "text"}:
                    field = "en" if "en" in keys else "text"
                    for row in rows:
                        yield rel, row[field] or ""


def visible(text: str) -> Iterator[tuple[str, str]]:
    at = 0
    for token in CONTROL.finditer(text):
        yield from ((ch, WORDING) for ch in text[at:token.start()] if ch.isprintable())
        if token[1] is not None:
            char = etext.glyph.get(int(token[1], 16))
            yield char if char and len(char) == 1 else token[0], NATIVE
        at = token.end()
    yield from ((ch, WORDING) for ch in text[at:] if ch.isprintable())


def inventory() -> dict[tuple[str, str], set[str]]:
    found: dict[tuple[str, str], set[str]] = defaultdict(set)
    for _, text in wording():
        for edition in toolpath.FONT_EDITIONS:
            rendered = vwf_wrap.edition_text(text, edition).replace(r"\n", "\n")
            for key in visible(rendered):
                found[key].add(edition)
    return dict(found)


def dialogue_cell(char: str) -> str:
    ch = make_vwf_font.spell(char)
    if ch not in make_vwf_font.EXTRA_CODE and ch not in make_vwf_font.ATLAS_CODE:
        ch = {"＞": ">", "＜": "<"}.get(ch, ch)
    if len(ch) == 1 and (0x20 <= ord(ch) <= 0x7E or ch in make_vwf_font.EXTRA_CODE or ch in make_vwf_font.ATLAS_CODE):
        return ch
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = inventory()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
    stream = args.output.open("w", encoding="utf-8", newline="") if args.output else None
    try:
        writer = csv.writer(stream or sys.stdout, delimiter="\t", lineterminator="\n",
                            quoting=csv.QUOTE_NONE, quotechar=None)
        writer.writerow(("character", "unicode", "source", "large", "small", "dialogue_cell"))
        for (char, source), editions in sorted(rows.items()):
            writer.writerow((char, f"U+{ord(char):04X}" if len(char) == 1 else "", source,
                             "yes" if "large" in editions else "",
                             "yes" if "small" in editions else "",
                             dialogue_cell(char) if source == WORDING else ""))
    finally:
        if stream:
            stream.close()


if __name__ == "__main__":
    main()
