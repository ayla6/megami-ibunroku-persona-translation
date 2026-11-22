"""Find the PSP's retry fragments the PSX lacks: translation/generated_mappings/retry_port_plan.tsv.

  python src/porting/retry_port_plan.py           write the plan, print it

The shape (src/injection/formats/escript.py has the commands and the plan's
columns): a PSP flag-test chain whose fail jump leads into code that shows
at least one box no PSX box carries, where the PSX has a chain with the same
flags. The fragment is every command reachable from that fail target until
control comes back to the chain ('chain') or to another PSP chain with the
same flags ('retest': the same tests with the PSX's own outcomes). Its boxes
are PSX boxes where one carries the PSP box's English, else added boxes
(port_story writes their rows); its jumps are steps of the fragment.
"""
from __future__ import annotations

import os
import sys
from typing import Final

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import escript   # noqa: E402
import efile     # noqa: E402
import etext     # noqa: E402
from escript import Command, RetryStep, ScriptError, command, command_at  # noqa: E402
from confirm_port_plan import FILES, toolbelt_extracted  # noqa: E402

# what a fragment may do besides show boxes, branch and set or clear flags
KEEPS: Final = escript.PRESENTATION | {escript.OP_FLAG_SET, escript.OP_FLAG_CLEAR}
# how many commands a fragment may hold
MAX_COMMANDS: Final = 96


def fragment(body: bytes, start: int, exits: dict[int, str]) -> dict[int, Command]:
    """{offset: command} reachable from `start` until an exit."""
    seen: dict[int, Command] = {}
    todo = [start]
    while todo:
        at = todo.pop()
        if at in seen or at in exits:
            continue
        c = command_at(body, at, 0)
        if c is None:
            raise ScriptError(f'{at:#x}: not a command')
        if c.op not in KEEPS | escript.BRANCHING:
            raise ScriptError(f'{at:#x}: op {c.op:02X} is not carried')
        seen[at] = c
        if len(seen) > MAX_COMMANDS:
            raise ScriptError('fragment runs on')
        if c.op in (escript.OP_JUMP, escript.OP_ANSWER, escript.OP_IF_FLAG):
            if c.target is None:
                raise ScriptError(f'{at:#x}: jump outside the image')
            todo.append(c.target)
        if c.op != escript.OP_JUMP:
            todo.append(at + len(c.raw))
    return seen


def plan() -> list[RetryStep]:
    import port_story
    sys.path.insert(0, os.path.join(HERE, '..', 'extraction', 'psp'))
    import text as psp_text
    out: list[RetryStep] = []
    for f in FILES:
        psp_of = port_story.psp_lookup(f)
        ids = {(int(r['entry']), int(r['pos'].split(':')[1], 16)): r['id']
               for r in toolbelt_extracted(f)}
        psx = efile.load(etext.path(f)).entries
        for entry in psp_text.load_psp(f, 'us').entries:
            if entry.index >= len(psx):
                continue
            body = entry.body
            pc = escript.chains(body, 0)
            if not pc:
                continue
            e = psx[entry.index]
            px = escript.chains(e.body)
            sources: dict[str, list[int]] = {}
            for k in range(len(e.boxes)):
                sources.setdefault(psp_of(entry.index, k), []).append(k)
            boxes = {s for s, _e in entry.boxes}
            for c in pc:
                if [x for x in px if x.flags == c.flags] == [] or c.fail in boxes:
                    continue
                exits = {c.start: 'chain'}
                exits.update({o.start: 'retest' for o in pc if o.flags == c.flags and o is not c})
                where = f'{f}/{entry.index} chain {",".join(f"{x:x}" for x in c.flags)}'
                try:
                    cmds = fragment(body, c.fail, exits)
                except ScriptError:
                    continue        # not a fragment this carries (it leaves the room, ...)
                said = [x.target for x in cmds.values() if x.op == escript.OP_SAY]
                if any(t not in boxes for t in said):
                    print(f'{where}: a 55 shows no box - skipped')
                    continue
                own = [t for t in said if len(sources.get(f'{f}:{ids[(entry.index, t)]}', [])) == 0]
                if not own:
                    continue        # the PSX has every box of it: not PSP-only
                if len([x for x in px if x.flags == c.flags]) != 1:
                    print(f'{where}: the PSX has the chain more than once - skipped')
                    continue
                out += steps(f, entry.index, c.flags, cmds, exits, ids, sources, where)
    return out


def steps(f: str, entry: int, flags: tuple[int, ...], cmds: dict[int, Command],
          exits: dict[int, str], ids: dict[tuple[int, int], str],
          sources: dict[str, list[int]], where: str) -> list[RetryStep]:
    """The fragment as block commands, in PSP order, with a jump wherever the
    next command is not the fall-through."""
    order = sorted(cmds)
    psx = efile.load(etext.path(f)).entries[entry]
    out: list[tuple[bytes, str, str]] = []
    index: dict[int, int] = {}

    def to(at: int) -> str:
        return exits[at] if at in exits else f'@{at}'

    for i, at in enumerate(order):
        c = cmds[at]
        index[at] = len(out)
        head = c.raw[:4]
        if c.op == escript.OP_SAY:
            pid = f'{f}:{ids[(entry, c.target)]}'
            twins = sources.get(pid, [])
            if len(twins) > 1:
                raise ScriptError(f'{where}: {pid} is carried by {len(twins)} PSX boxes')
            if twins:
                out.append((head, f'box:{entry}:{psx.boxes[twins[0]][0]:#x}', ''))
            else:
                out.append((head, f'box:{entry}:{escript.ADDED_BASE + c.target:#x}', pid))
        elif c.op in (escript.OP_JUMP, escript.OP_ANSWER, escript.OP_IF_FLAG):
            out.append((head, to(c.target), ''))
        else:
            out.append((c.raw, '', ''))
        nxt = at + len(c.raw)
        if c.op != escript.OP_JUMP and (i + 1 == len(order) or order[i + 1] != nxt):
            out.append((command(escript.OP_JUMP)[:4], to(nxt), ''))
    result = []
    for n, (raw, target, psp) in enumerate(out):
        if target.startswith('@'):
            target = f'step:{index[int(target[1:])]}'
        result.append(RetryStep(f, entry, flags, n, raw, target, psp))
    return result


def main() -> None:
    rows = plan()
    escript.write_retry_plan(rows)
    for t in rows:
        print(f'{t.file}/{t.entry} {t.step:3d} {t.raw.hex()} {t.target} {t.psp}')
    print(f'{len(rows)} steps -> {os.path.relpath(escript.RETRY_PLAN, toolpath.ROOT)}')


if __name__ == '__main__':
    main()
