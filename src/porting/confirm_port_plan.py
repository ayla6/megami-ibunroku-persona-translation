"""Find the PSP's confirm prompts the PSX lacks: translation/generated_mappings/confirm_port_plan.tsv.

  python src/porting/confirm_port_plan.py           write the plan, print it

The shape, read off the PSP-US scripts (src/injection/formats/escript.py
has the commands and the plan's columns): a 55 shows a choice box, a 54
chain branches on its answer, and the branch of answer v opens - past bust
pictures and jumps - with a 55 showing a DIFFERENT box that asks Yes/No
(<FF0E><00>), followed by its own 54 chain where Yes falls through to v's
branch and No either reaches the choice's 55 again ('again') or the head of
another answer w's branch (w). That Yes/No box is a confirm; it is ported
when no PSX box carries its English (its PSP-US box is nobody's source), or
the only one that does is the PSX's own choice prompt (the PSX asked in two
boxes - a line, then the prompt - where the PSP asks in one, and the slot
join paired the prompt with the confirm).

The PSX side: `choice` is the PSX box whose English comes from the PSP
choice box; `prompt` is the box the PSX script shows to ask (the choice box
itself, or the next said box that asks the same choice id in Japanese). A
choice whose PSX side does not have that shape is reported and skipped.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Final

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import escript   # noqa: E402
import efile     # noqa: E402
import etext     # noqa: E402
from escript import Command, Confirm, ScriptError, command_at  # noqa: E402

FILES: Final = ('E0', 'E1', 'E2', 'E3')
# how far a branch head may sit behind 67/68/20/22 before its 55
HEAD_STEPS: Final = 8
# how many commands after the choice line the PSX prompt may sit
PROMPT_STEPS: Final = 24


@dataclass(frozen=True)
class Box:
    start: int
    raw: bytes

    def choice_id(self) -> int | None:
        """The n of <FF0E><n> (PSP: the u16's low byte comes first), or None."""
        i = self.raw.find(b'\xff\x0e')
        return self.raw[i + 2] if i >= 0 and i + 2 < len(self.raw) else None


def head(body: bytes, at: int, base: int) -> Command | None:
    """The first command at a branch head that is not 67/68/20/22 (jumps
    followed)."""
    for _ in range(HEAD_STEPS):
        c = command_at(body, at, base)
        if c is None:
            return None
        if c.op == escript.OP_JUMP and c.target is not None:
            at = c.target
        elif c.op in (escript.OP_BUST, escript.OP_UNBUST, escript.OP_NOP):
            at += len(c.raw)
        else:
            return c
    return None


def bust_before(body: bytes, branch: int, say: int, base: int) -> bytes | None:
    """The last 67 between a branch head and the 55 it leads to."""
    bust = None
    at = branch
    for _ in range(HEAD_STEPS):
        if at == say:
            return bust
        c = command_at(body, at, base)
        if c is None:
            return bust
        if c.op == escript.OP_BUST:
            bust = c.raw[2:4]
        elif c.op == escript.OP_UNBUST:
            bust = None
        at = c.target if c.op == escript.OP_JUMP and c.target is not None else at + len(c.raw)
    return bust


@dataclass(frozen=True)
class PspConfirm:
    entry: int
    choice: Box
    choice_say: int
    answer: int
    confirm: Box
    bust: bytes | None
    no: int | None


def option_count(choice_id: int) -> int:
    import choices
    rows = choices.original()
    if choice_id >= len(rows):
        return 0
    params = rows[choice_id]['params']
    return params[0] * params[1]


def psp_confirms(f: str) -> list[PspConfirm]:
    sys.path.insert(0, os.path.join(HERE, '..', 'extraction', 'psp'))
    import text as psp_text
    out = []
    for entry in psp_text.load_psp(f, 'us').entries:
        body = entry.body
        boxes = {s: Box(s, body[s:e]) for s, e in entry.boxes}
        for at in range(0, len(body) - 8, 4):
            c = command_at(body, at, 0)
            if c is None or c.op != escript.OP_SAY or c.target not in boxes:
                continue
            choice = boxes[c.target]
            cid = choice.choice_id()
            if cid is None:
                continue
            try:
                s = escript.site_at(body, at, 0)
            except ScriptError:
                continue
            heads = {}
            for v in range(option_count(cid)):
                heads[v] = s.target(v)
            for v, branch in heads.items():
                h = head(body, branch, 0)
                if h is None or h.op != escript.OP_SAY or h.target not in boxes:
                    continue
                confirm = boxes[h.target]
                if confirm.start == choice.start or confirm.choice_id() != 0:
                    continue
                try:
                    cs = escript.site_at(body, h.at, 0)
                except ScriptError:
                    continue
                if cs.target(escript.YES) != cs.fallthrough:
                    continue
                no_at = cs.target(escript.NO)
                n = head(body, no_at, 0)
                if n is not None and n.op == escript.OP_SAY and n.target == choice.start:
                    no = None
                else:
                    others = [w for w, t in heads.items() if w != v and
                              head(body, t, 0) == n]
                    if len(others) != 1:
                        print(f'{f}/{entry.index}: confirm {confirm.start:#x} for answer {v}: '
                              f'No goes to {no_at:#x}, neither the choice nor one branch - skipped')
                        continue
                    no = others[0]
                out.append(PspConfirm(entry.index, choice, at, v, confirm,
                                      bust_before(body, branch, h.at, 0), no))
    return out


def plan() -> list[Confirm]:
    import port_story
    out = []
    for f in FILES:
        found = psp_confirms(f)
        if not found:
            continue
        psp_of = port_story.psp_lookup(f)
        ids = {(int(r['entry']), int(r['pos'].split(':')[1], 16)): r['id']
               for r in toolbelt_extracted(f)}
        psx = efile.load(etext.path(f)).entries
        for pc in found:
            e = psx[pc.entry]
            sources = {}
            for k in range(len(e.boxes)):
                sources.setdefault(psp_of(pc.entry, k), []).append(k)
            choice_id = f'{f}:{ids[(pc.entry, pc.choice.start)]}'
            confirm_id = f'{f}:{ids[(pc.entry, pc.confirm.start)]}'
            where = f'{f}/{pc.entry} {choice_id} answer {pc.answer}'
            if len(sources.get(choice_id, [])) != 1:
                print(f'{where}: {len(sources.get(choice_id, []))} PSX boxes carry the choice - skipped')
                continue
            k = sources[choice_id][0]
            prompt = prompt_box(e, k, pc.choice.choice_id())
            if prompt is None:
                print(f'{where}: the PSX script asks no choice {pc.choice.choice_id()} '
                      f'after box {k} - skipped')
                continue
            twins = sources.get(confirm_id, [])
            if twins and twins != [prompt]:
                continue            # the PSX has this confirm
            out.append(Confirm(f, pc.entry, e.boxes[k][0], e.boxes[prompt][0], pc.answer,
                               escript.ADDED_BASE + pc.confirm.start, confirm_id,
                               pc.bust, pc.no))
    return out


def toolbelt_extracted(f: str) -> list[dict[str, str]]:
    import toolbelt
    return toolbelt.read_extracted('psp_us', f'pack/{f}')


def prompt_box(e: efile.Entry, k: int, choice_id: int | None) -> int | None:
    """The PSX box that asks choice `choice_id` for the line in box k: box k
    itself, or the next box the script shows after it, straight-line."""
    starts = {s: i for i, (s, _e) in enumerate(e.boxes)}

    def asks(i: int) -> bool:
        b = e.box_bytes(i)
        j = b.find(b'\xff\x0e')
        return j >= 0 and j + 2 < len(b) and b[j + 2] == choice_id
    if asks(k):
        return k
    said = escript.says(e.body, e.boxes[k][0])
    if len(said) != 1:
        return None
    at = said[0] + 8
    for _ in range(PROMPT_STEPS):
        c = command_at(e.body, at)
        if c is None or c.op in (escript.OP_ANSWER, 0x21):
            return None
        if c.op == escript.OP_SAY and c.target in starts:
            i = starts[c.target]
            return i if asks(i) else None
        at = c.target if c.op == escript.OP_JUMP and c.target is not None else at + len(c.raw)
    return None


def main() -> None:
    rows = plan()
    escript.write_plan(rows)
    for c in rows:
        print(f'{c.file}/{c.entry}: answer {c.answer} -> {c.psp} at {c.pos} '
              f'(choice {c.choice:#x}, prompt {c.prompt:#x}, '
              f'No: {"again" if c.no is None else "answer " + str(c.no)})')
    print(f'{len(rows)} confirms -> {os.path.relpath(escript.PLAN, toolpath.ROOT)}')


if __name__ == '__main__':
    main()
