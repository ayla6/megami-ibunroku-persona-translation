"""ADV event-script commands, and the PSP's confirm prompts carried onto them.

The script VM (references/persona-decomp src/adv/game/script.c): a command
is `FF op a b` plus operands, `g_cmd_len[op]` bytes long, always 4-aligned.
The ones a choice is built from:
    55 - - text32    show a box and wait; a box with <FF0E><n> asks
                     choice n and leaves the answer in g_msg_answer
    54 n - ->        jump if the last answer was n
    22 - - ->        jump
    67 file place    grow a bust picture (file = the character) in
    68 - -           shrink it away (blocks ~16 frames, harmless when none)
    20 - -           no-op
PSX pointers are absolute (efile.BASE + offset); the PSP's are
image-relative. The PSP keeps the PSX's character file numbers for 67.

CONFIRM PROMPTS. Some PSP choices ask again before they take effect - Brown,
Elly and Ayase joining (E0), Kei's and Eriko's help (E1, E3): the choice's
branch for an answer opens with a Yes/No box worded for THAT answer ("...you
want to bring Hidehiko along?" / "...you don't want to..."), and No either
asks the choice again or takes another answer's branch. The PSX has no such
box. Where the PSP has one, the PSX script gets it: the command that shows
the PSX choice prompt jumps to a block appended to the image, which shows
the choice (unless the English already asked it in an earlier box), then
per confirmed answer the PSP's bust and confirm box, and on Yes continues
with that answer's PSX branch, on No asks again / takes the other branch.
Answers the PSP does not confirm run the PSX's own commands.

translation/generated_mappings/confirm_port_plan.tsv (written by
src/porting/confirm_port_plan.py from the PSP-US scripts; the build reads
only this and the PSX script), one row per confirmed answer:
    file     E0..E3
    entry    event entry
    choice   PSX box (pos) whose English asks the choice
    prompt   PSX box (pos) the PSX script shows to ask it: the hook site
    answer   the answer the PSP confirms
    confirm  pos of the added confirm box (ADDED_BASE + its PSP offset)
    psp      the PSP-US box the confirm's English comes from (E0:702)
    bust     the PSP's bust before the confirm, 'file place' hex ('0300'), or '-'
    no       'again' (ask the choice again) or the answer whose branch No takes
The added box's English is an ordinary port row at the `confirm` pos.
"""
from __future__ import annotations

import os
import struct
import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Final

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import toolbelt  # noqa: E402
import strlib    # noqa: E402

ROOT: Final = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
BASE: Final = 0x80100000
# g_cmd_len in the Rev 0 ADV.BIN (file offset; the decomp's 0x800BAC90 is Rev 1)
CMD_LEN_AT: Final = 0x573C8
CMD_COUNT: Final = 0x8B
OP_JUMP: Final = 0x22
OP_ANSWER: Final = 0x54
OP_SAY: Final = 0x55
OP_BUST: Final = 0x67
OP_UNBUST: Final = 0x68
OP_NOP: Final = 0x20
BRANCHING: Final = frozenset({OP_JUMP, OP_ANSWER, OP_SAY})
YES: Final = 0
NO: Final = 1
# An added box's pos offset: an event image is at most 0xFFF8 bytes, so no
# real box starts here, and the PSP offset under it names the source box.
ADDED_BASE: Final = 0x10000
PLAN: Final = os.path.join(toolbelt.MAPPINGS, 'confirm_port_plan.tsv')
PLAN_COLS: Final = ('file', 'entry', 'choice', 'prompt', 'answer', 'confirm',
                    'psp', 'bust', 'no')
AGAIN: Final = 'again'


class ScriptError(ValueError):
    """The script around a planned confirm is not the shape the plan says."""


@lru_cache(maxsize=1)
def cmd_lengths() -> bytes:
    """g_cmd_len from the retail ADV.BIN, checked against known lengths."""
    with open(os.path.join(ROOT, 'data', 'psx', 'ADV.BIN'), 'rb') as f:
        f.seek(CMD_LEN_AT)
        table = f.read(CMD_COUNT)
    known = {0x21: 4, OP_JUMP: 8, OP_ANSWER: 8, OP_SAY: 8, OP_BUST: 4,
             OP_UNBUST: 4, OP_NOP: 4, 0x26: 8}
    if len(table) != CMD_COUNT or any(table[op] != n for op, n in known.items()):
        raise ScriptError(f'ADV.BIN {CMD_LEN_AT:#x} is not g_cmd_len (Rev 0 expected)')
    return table


@dataclass(frozen=True)
class Command:
    at: int                 # image offset
    op: int
    raw: bytes              # the whole command
    target: int | None      # image offset a 22/54/55 points at

    @property
    def n(self) -> int:
        return self.raw[2]


def command_at(body: bytes, at: int, base: int = BASE) -> Command | None:
    """The command at `at`, or None when the bytes there are not one.
    base: BASE for a PSX image, 0 for a PSP one."""
    if at % 4 or at + 4 > len(body) or body[at] != 0xFF:
        return None
    op = body[at + 1]
    if op >= CMD_COUNT or not cmd_lengths()[op]:
        return None
    raw = body[at:at + cmd_lengths()[op]]
    target = None
    if op in BRANCHING and len(raw) >= 8:
        ptr = struct.unpack_from('<I', raw, 4)[0] - base
        if 0 <= ptr < len(body):
            target = ptr
    return Command(at, op, bytes(raw), target)


def says(body: bytes, box: int, base: int = BASE) -> list[int]:
    """Offsets of every 55 command that shows the box starting at `box`."""
    want = struct.pack('<I', base + box)
    out = []
    at = body.find(b'\xff\x55\x00\x00' + want)
    while at >= 0:
        if at % 4 == 0:
            out.append(at)
        at = body.find(b'\xff\x55\x00\x00' + want, at + 1)
    return out


def command(op: int, a: int = 0, b: int = 0, target: int | None = None) -> bytes:
    """Encode a command; `target` is an absolute address (operand word)."""
    raw = bytes([0xFF, op, a, b])
    return raw + struct.pack('<I', target) if target is not None else raw


@dataclass(frozen=True)
class Confirm:
    file: str
    entry: int
    choice: int             # PSX box offset whose English asks the choice
    prompt: int             # PSX box offset the PSX script shows to ask it
    answer: int
    confirm: int            # added box pos offset (ADDED_BASE + PSP offset)
    psp: str
    bust: bytes | None      # 67's two operand bytes
    no: int | None          # None: ask again; else the answer whose branch No takes

    @property
    def pos(self) -> str:
        return f'{self.entry}:{self.confirm:#x}'


def added(pos: str) -> bool:
    """Is a row pos an added box (no PSX box behind it)?"""
    _entry, _sep, off = pos.partition(':')
    return int(off, 16) >= ADDED_BASE


def _pos(entry: int, value: str) -> int:
    e, _sep, off = value.partition(':')
    if int(e) != entry:
        raise ScriptError(f'pos {value} is not in entry {entry}')
    return int(off, 16)


def read_plan(optional: bool = True) -> list[Confirm]:
    if not os.path.exists(PLAN):
        if optional:
            return []
        raise ScriptError(f'{PLAN}: missing (src/porting/confirm_port_plan.py writes it)')
    out = []
    for r in strlib.tsv_rows(PLAN, required=PLAN_COLS):
        entry = int(r['entry'])
        out.append(Confirm(
            r['file'], entry, _pos(entry, r['choice']), _pos(entry, r['prompt']),
            int(r['answer']), _pos(entry, r['confirm']), r['psp'],
            None if r['bust'] == '-' else bytes.fromhex(r['bust']),
            None if r['no'] == AGAIN else int(r['no'])))
    return out


def write_plan(rows: list[Confirm]) -> None:
    lines = ['\t'.join(PLAN_COLS)]
    for c in sorted(rows, key=lambda c: (c.file, c.entry, c.prompt, c.answer)):
        lines.append('\t'.join((
            c.file, str(c.entry), f'{c.entry}:{c.choice:#x}', f'{c.entry}:{c.prompt:#x}',
            str(c.answer), c.pos, c.psp, c.bust.hex() if c.bust else '-',
            AGAIN if c.no is None else str(c.no))))
    os.makedirs(os.path.dirname(PLAN), exist_ok=True)
    with open(PLAN, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')


# What may sit between a prompt's 55 and its answer tests: presentation only
# (no-op, wait, cinema frame, bust, sound mark, screen effect, shake stop).
PRESENTATION: Final = frozenset({OP_NOP, 0x4D, 0x60, 0x61, OP_BUST, OP_UNBUST,
                                 0x69, 0x6C, 0x6D, 0x7A})


@dataclass(frozen=True)
class Site:
    """How the PSX script asks one choice: `say` shows the prompt box."""
    say: int                       # offset of the 55 command
    bust: bytes | None             # the 67 right before it (operands)
    post: tuple[Command, ...]      # PRESENTATION between the 55 and the answer tests
    branches: tuple[tuple[int, int], ...]   # (answer, target) of the 54 chain
    fallthrough: int               # where an answer no 54 takes goes

    @property
    def resume(self) -> int:
        return self.say + 8

    def target(self, answer: int) -> int:
        for n, t in self.branches:
            if n == answer:
                return t
        return self.fallthrough


def site(body: bytes, prompt: int, base: int = BASE) -> Site:
    """The script that shows the box at `prompt` and branches on its answer."""
    at = says(body, prompt, base)
    if len(at) != 1:
        raise ScriptError(f'box {prompt:#x} is shown {len(at)} times (one expected)')
    return site_at(body, at[0], base)


def site_at(body: bytes, say: int, base: int = BASE) -> Site:
    """The answer tests that follow the 55 command at `say`."""
    before = command_at(body, say - 4, base) if say >= 4 else None
    bust = before.raw[2:4] if before is not None and before.op == OP_BUST else None
    p = say + 8
    post = []
    while (c := command_at(body, p, base)) is not None and c.op in PRESENTATION:
        post.append(c)
        p += len(c.raw)
    branches = []
    while (c := command_at(body, p, base)) is not None and c.op == OP_ANSWER:
        if c.target is None:
            raise ScriptError(f'answer test at {p:#x} points outside the image')
        branches.append((c.n, c.target))
        p += len(c.raw)
    if not branches:
        raise ScriptError(f'{say:#x}: no answer test follows the box')
    return Site(say, bust, tuple(post), tuple(branches), p)


def hook(body: bytes, confirms: list[Confirm], texts: dict[int, bytes]
         ) -> Callable[[bytearray, Callable[[int], int]], None]:
    """An efile.Entry.rebuild `extend` step for one entry's confirms.

    texts: {confirm pos offset: encoded box ending in FF 01}. Each prompt's
    55 becomes a jump to a block appended after the image (see the module
    docstring); the confirm boxes follow the blocks."""
    by_prompt: dict[int, list[Confirm]] = {}
    for c in confirms:
        by_prompt.setdefault(c.prompt, []).append(c)
    sites = {p: site(body, p) for p in by_prompt}
    for p, cs in by_prompt.items():
        if len({c.choice for c in cs}) != 1 or len({c.answer for c in cs}) != len(cs):
            raise ScriptError(f'prompt {p:#x}: one choice and one confirm per answer expected')
        for c in cs:
            if c.confirm not in texts:
                raise ScriptError(f'{c.file}/{c.pos}: confirm box has no English')

    def extend(out: bytearray, newpos: Callable[[int], int]) -> None:
        while len(out) % 4:
            out.append(0)
        blocks = [_block(sites[p], sorted(by_prompt[p], key=lambda c: c.answer))
                  for p in sorted(by_prompt)]
        # every command has a fixed length: the boxes go after all blocks
        at = len(out) + sum(b.size for b in blocks)
        boxes: dict[int, int] = {}
        pool = bytearray()
        for p in sorted(by_prompt):
            for c in sorted(by_prompt[p], key=lambda c: c.answer):
                boxes[c.confirm] = at + len(pool)
                pool += texts[c.confirm]
                while len(pool) % 4:
                    pool.append(0)
        for p, b in zip(sorted(by_prompt), blocks):
            start = len(out)
            out += b.emit(start, newpos, boxes)
            say = newpos(sites[p].say)
            out[say:say + 8] = command(OP_JUMP, target=BASE + start)
        out += pool
    return extend


# A block item: raw bytes, or (op, n, where) with `where` one of
# ('label', name), ('old', PSX offset), ('box', confirm pos offset).
Item = bytes | tuple[int, int, tuple[str, int | str]]


@dataclass
class Block:
    items: list[Item]
    labels: dict[str, int]          # name -> offset within the block

    @property
    def size(self) -> int:
        return sum(len(i) if isinstance(i, bytes) else 8 for i in self.items)

    def emit(self, start: int, newpos: Callable[[int], int], boxes: dict[int, int]) -> bytes:
        code = bytearray()
        for i in self.items:
            if isinstance(i, bytes):
                code += i
                continue
            op, n, (kind, value) = i
            if kind == 'label':
                at = start + self.labels[str(value)]
            elif kind == 'old':
                at = newpos(int(value))
            else:
                at = boxes[int(value)]
            code += command(op, n, target=BASE + at)
        return bytes(code)


def _block(s: Site, cs: list[Confirm]) -> Block:
    """One prompt's block (module docstring):
        [55 choice]                   when the prompt box is the choice box
      ask:  54 v -> confirm_v ...     per confirmed answer
            22 -> the PSX's own post-commands and tests
      confirm_v: [68] [67 bust] 55 box [68]
            54 No -> again | no_v
            <post> 22 -> v's branch
      no_v: <post> 22 -> w's branch
      again: [67 the prompt's bust, if a confirm's took its place] 55 choice
             22 -> ask
    The PSX's post-commands (frame down, bust away) run once, after the
    confirm is answered, never before the choice is asked again."""
    choice = cs[0].choice
    items: list[Item] = []
    labels: dict[str, int] = {}
    size = 0

    def put(i: Item) -> None:
        nonlocal size
        items.append(i)
        size += len(i) if isinstance(i, bytes) else 8

    def label(name: str) -> None:
        labels[name] = size

    def post(up: bool) -> bytes:
        """The PSX's post-commands, without a shrink when no bust is up."""
        out = b''
        for c in s.post:
            if c.op == OP_UNBUST and not up:
                continue
            if c.op in (OP_BUST, OP_UNBUST):
                up = c.op == OP_BUST
            out += c.raw
        return out

    if choice == cs[0].prompt:
        put((OP_SAY, 0, ('old', choice)))
    label('ask')
    for c in cs:
        put((OP_ANSWER, c.answer, ('label', f'confirm{c.answer}')))
    put((OP_JUMP, 0, ('old', s.resume)))
    for c in cs:
        label(f'confirm{c.answer}')
        if c.bust:
            if s.bust is not None:
                put(command(OP_UNBUST))
            put(command(OP_BUST, c.bust[0], c.bust[1]))
        put((OP_SAY, 0, ('box', c.confirm)))
        if c.bust:
            put(command(OP_UNBUST))
        put((OP_ANSWER, NO, ('label', 'again' if c.no is None else f'no{c.answer}')))
        up = s.bust is not None and not c.bust
        if post(up):
            put(post(up))
        put((OP_JUMP, 0, ('old', s.target(c.answer))))
        if c.no is not None:
            label(f'no{c.answer}')
            if post(up):
                put(post(up))
            put((OP_JUMP, 0, ('old', s.target(c.no))))
    if any(c.no is None for c in cs):
        label('again')
        if s.bust is not None and any(c.bust for c in cs if c.no is None):
            put(command(OP_BUST, s.bust[0], s.bust[1]))
        put((OP_SAY, 0, ('old', choice)))
        put((OP_JUMP, 0, ('label', 'ask')))
    return Block(items, labels)
