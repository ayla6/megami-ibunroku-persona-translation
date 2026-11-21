"""System messages of ADV.BIN (shop / Persona exchange / memory card and save messages), dialogue-box format.

  python tools/sysmsg.py dump     write/refresh translation/strings/SYSMSG.tsv (keeps the `en` column)
  python tools/sysmsg.py build    QA + generate build/sysmsg.asm (included in the ADV section of main.asm)

The messages live in ADV.BIN at RAM 0x800BB0E8-0x800BB517 (file offset = RAM - 0x800643C4), in the same encoding as the
event boxes (FF01 end, FF02 wait, FF03 newline, FF04 new page, FF0E choice ...) and are shown by the dialogue engine,
so English goes through the dialogue VWF. Every message is reached either through a pointer table (RAM 0x800BB518,
11 words) or through `lui a0,0x800C ; addiu a0,a0,imm` pairs in the ADV code (found by scanning). Because both kinds of
reference are patched (only the addiu immediate changes, the lui stays 0x800C), the English strings are re-packed freely
inside the two zones below. Messages with no reference found are left where they are.
The small-font label block 0x800BB115-0x800BB153 (TOTAL COIN ...) is not touched; 0x800BB154 is the Velvet Room
fusion prompt (message 24, own zone so the older message indices stay put).

`en` syntax = the event TSVs (`<FF03>` newline, `<FF02>` wait, ...; no trailing <FF01>, the build adds it); checked with
tools/tstatus.check (control codes identical to the Japanese, 239 px lines, <= 3 lines per page, ASCII).
A confirmation prompt ships the row's own layout - the warning, then the question and its options on a
fresh page (`<FF02><FF04>`): a question on the box's second-to-last row would scroll the options in
without a press. The build ships the row as written, never re-laid-out after the gate.
A message whose own call site proves a one-row viewport (`display_size`) is one line of the width that viewport shows,
with no line/page move: `tstatus.ship_errors(..., line_px=...)` measures it against the proven width.
A message with more lines on a page than its call site's multi-row viewport shows gets that viewport's height
raised to its lines (at most 3): the `ori` that feeds the height store is rewritten, provided that constant feeds
no other store, and the frame drawn around it (TileMapDrawWindow / TileMapDrawBox, 8 px tiles) grows with it.
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import toolbelt  # noqa: E402
import etext                  # noqa: E402
import strlib                  # noqa: E402
import tstatus    # noqa: E402
import vwf_wrap   # noqa: E402

ROOT = etext.ROOT
B = 0x800643C4                       # RAM address of ADV.BIN file offset 0
ZONES = [(0x800BB0E8, 0x800BB115), (0x800BB166, 0x800BB518),
         (0x800BB154, 0x800BB166)]     # Velvet Room 'add an item?' prompt; listed last to keep the older indices
TABLE = 0x800BB518
PROTECT = [(0x800BB1CC, 0x800BB1D2)]   # tile label "BUTTON" (6 small-font cells) inside message 8's slot: drawn by ADV 0x800A5290 (Velvet Room hint line)
DEAD = {3}                           # unreferenced duplicate of message 7 (0x56da2 vs 0x56df2, which
                                     # ships the wording); its slot is reused as free space, so the
                                     # manual row stays an empty queue row by design
# Spill strings use the ADV extension partition defined in addresses.inc.
# References use lui 0x800C + addiu, reaching 0x800B8000-0x800C7FFF.
# The build checks the finite window; verify reads the assembled bytes back
# to detect overlapping claims.
ADV_SPILL_ADDR = toolbelt.asm_equ('ADV_SYSMSG_SPILL_ADDR')
ADV_SPILL_END = toolbelt.asm_equ('ADV_SYSMSG_SPILL_END')
ADV_SPILL_SIZE = ADV_SPILL_END - ADV_SPILL_ADDR   # the partition's window, from its boundaries
assert 0 < ADV_SPILL_SIZE, 'sysmsg spill window is empty - check the ADV extension partition in addresses.inc'
TSV = os.path.join(toolpath.TRANSLATION, 'manual', 'strings', 'SYSMSG.tsv')
OUT = os.path.join(ROOT, 'build', 'sysmsg.asm')
PLACED = os.path.join(ROOT, 'build', 'sysmsg_placed.json')
DRAFT_OUT = os.path.join(ROOT, 'build', 'sysmsg_drafts.tsv')
NL = chr(10)


def adv():
    return open(os.path.join(ROOT, 'data', 'psx', 'ADV.BIN'), 'rb').read()


def messages(d):
    out = []
    for a, b in ZONES:
        p = a
        while p < b:
            e = d.index(b'\xff\x01', p - B) + 2 + B
            out.append((p, e))
            p = e
            while p < b and d[p - B] == 0 and False:
                p += 1
    return out


def refs(d, msgs):
    """-> (table_slots, code_refs) as {msg_index: [(kind, ram_address_of_patch, old_value)]}"""
    found = {i: [] for i in range(len(msgs))}

    def which(v):
        for i, (a, e) in enumerate(msgs):
            if a <= v < e:
                return i

    t = TABLE
    while True:
        v = struct.unpack_from('<I', d, t - B)[0]
        i = which(v) if B <= v < 0x80100000 else None
        if i is None:
            break
        found[i].append(('ptr', t, v))
        t += 4
    nwords = (0x800BB000 - B) // 4
    end = (len(d)) // 4
    for k in range(end - 9):
        w = struct.unpack_from('<I', d, 4 * k)[0]
        if (w >> 26) == 0xF and (w & 0xFFFF) in (0x800B, 0x800C):
            rt = (w >> 16) & 31
            for j in range(1, 9):
                x = struct.unpack_from('<I', d, 4 * (k + j))[0]
                op, imm = x >> 26, x & 0xFFFF
                if op in (9, 0xD) and ((x >> 21) & 31) == rt:
                    v = ((w & 0xFFFF) << 16) + (imm - 0x10000 if (imm & 0x8000 and op == 9) else imm)
                    i = which(v)
                    if any(pa <= v < pe for pa, pe in PROTECT):
                        i = None                    # label inside a message slot that must stay where it is
                    if i is not None and (w & 0xFFFF) == 0x800C and op == 9:
                        found[i].append(('code', B + 4 * (k + j), v))
                if ((x >> 16) & 31 == rt and op in (*range(8, 16), *range(0x20, 0x27))) \
                        or (op == 0 and (x >> 11) & 31 == rt):
                    break                           # rt rewritten: the lui reaches no further
    return found


# --- the message VIEWPORT, read from the code that opens it -----------------
# Every ADV system message is drawn through BgMapInit (0x800666DC in ADV.BIN).
# The same straight-line block writes g_bg_layers[4] - the map layer the
# message is drawn through - so the call site itself proves the visible
# rectangle: w px across, h / 16 rows down (16 px cells). That rectangle is a
# property of the CALL SITE, not of the wording: a message whose block proves
# h == 0x10 has ONE visible row, and its line is w px wide, so a break or a
# second line is not shown. A call site that proves no local geometry
# inherits whatever the previous screen left - unknown is never guessed, and
# the message stays an ordinary textbox.
BG_INIT = 0x800666DC             # BgMapInit entry
# The frame around the text: TileMapDrawWindow (outer) and TileMapDrawBox
# (inner), (dst, w, h, stride) in 8 px tiles, called just before BgMapInit by
# the block that opens the message.
FRAME_CALLS = (0x8007AC30, 0x8007AF1C)
_FRAME_SETUP = 24                # instructions searched back from BgMapInit
BG_LAYER4 = {0x800B8EFC: 'x', 0x800B8EFE: 'y',
             0x800B8F00: 'w', 0x800B8F02: 'h'}   # GsBG x/y/w/h in ADV.BIN
_MAX_SETUP = 160                 # instructions searched around one call
_MAX_WIDTH = 240                 # the map is 15 x 16 px cells across
_MAX_ROWS = 3                    # a page's lines (tstatus.check)
_DISPLAY = None
_HEIGHT_AT = None


def _ins(md, d, addr):
    off = addr - B
    if off < 0 or off + 4 > len(d):
        return None
    return next(md.disasm(d[off:off + 4], addr), None)


def _mem_addr(md, d, ins):
    """The absolute destination address of a store, or None."""
    import capstone
    if ins is None or ins.mnemonic not in ('sh', 'sw') or len(ins.operands) != 2:
        return None
    mem = ins.operands[1]
    if mem.type != capstone.mips.MIPS_OP_MEM:
        return None
    base = ins.reg_name(mem.mem.base)
    for k in range(1, 8):
        prev = _ins(md, d, ins.address - 4 * k)
        if prev is None:
            break
        if prev.mnemonic == 'lui' and prev.operands and \
                prev.reg_name(prev.operands[0].reg) == base:
            return ((prev.operands[1].imm << 16) + mem.mem.disp) & 0xFFFFFFFF
        if prev.operands and prev.operands[0].type == capstone.mips.MIPS_OP_REG \
                and prev.reg_name(prev.operands[0].reg) == base \
                and prev.mnemonic not in ('sb', 'sh', 'sw', 'swl', 'swr') \
                and not prev.mnemonic.startswith(('b', 'j')):
            return None                     # base rewritten after any earlier lui
    return None


def _const_reg(md, d, addr, reg):
    """The constant a register holds at `addr` (nearest writer only)."""
    w = _const_writer(md, d, addr, reg)
    return w[0] if w else None


def _const_writer(md, d, addr, reg):
    """(constant, address of the `ori/addiu reg, zero, imm` that wrote it)
    for the register at `addr` (nearest writer only), or None."""
    import capstone
    for k in range(1, 12):
        ins = _ins(md, d, addr - 4 * k)
        if ins is None:
            return None
        if not ins.operands or ins.mnemonic in (
                'sb', 'sh', 'sw', 'swl', 'swr', 'sc'):
            continue                  # a store reads the register, never writes it
        dst = ins.operands[0]
        if dst.type == capstone.mips.MIPS_OP_REG and \
                ins.reg_name(dst.reg) == reg:
            if ins.mnemonic in ('ori', 'addiu') and len(ins.operands) == 3 \
                    and ins.operands[1].type == capstone.mips.MIPS_OP_REG \
                    and ins.operands[1].reg == capstone.mips.MIPS_REG_ZERO:
                return ins.operands[2].imm & 0xFFFF, ins.address
            return None
    return None


def _sole_use(md, d, writer, store, reg):
    """True when the constant `writer` puts in `reg` is stored only by
    `store` before the register is written again: rewriting the writer's
    immediate then changes that one field and nothing else."""
    import capstone
    addr = writer + 4
    while addr < store + 4 * 24:
        ins = _ins(md, d, addr)
        if ins is None:
            return False
        if addr == store and ins.mnemonic == 'jal':
            return True               # the call's argument: the callee is its one reader
        if ins.mnemonic.startswith(('j', 'b')):
            return addr > store       # control flow past the store ends the walk
        if ins.operands and addr != store:
            regs = [ins.reg_name(o.reg) for o in ins.operands
                    if o.type == capstone.mips.MIPS_OP_REG]
            regs += [ins.reg_name(o.mem.base) for o in ins.operands
                     if o.type == capstone.mips.MIPS_OP_MEM]
            writes = ins.mnemonic not in ('sb', 'sh', 'sw', 'swl', 'swr') \
                and regs and regs[0] == reg
            if reg in (regs[1:] if writes else regs):
                return False          # read by something else
            if writes:
                return addr > store
        addr += 4
    return False


def _find_call(md, d, start):
    """The BgMapInit call this message reference reaches, following the
    compiler's own unconditional jump (a shared draw block). A conditional
    path has no single local answer, so it returns None."""
    addr = start
    for _ in range(40):
        ins = _ins(md, d, addr)
        if ins is None:
            return None
        if ins.mnemonic == 'jal' and ins.operands and \
                ins.operands[0].imm == BG_INIT:
            return addr
        if ins.mnemonic in ('j', 'b') and ins.operands:
            addr = ins.operands[0].imm
            continue
        if ins.mnemonic.startswith('b'):
            return None
        addr += 4
    return None


def _viewport(md, d, start, end):
    """{field: value} of the first g_bg_layers[4] write per field in a walk
    from `start` to `end` (exclusive). The geometry is one tight block of
    stores; after the height it is read for a few more instructions so the
    width that follows it (a call site may write w after h) is still seen."""
    step = 4 if end > start else -4
    vals = {}
    left = None
    addr = start
    while (addr < end) if step > 0 else (addr > end):
        ins = _ins(md, d, addr)
        if ins is not None and ins.mnemonic == 'sh':
            field = BG_LAYER4.get(_mem_addr(md, d, ins))
            if field is not None and field not in vals:
                reg = ins.reg_name(ins.operands[0].reg)
                w = _const_writer(md, d, addr, reg)
                if w is not None:
                    vals[field] = w[0]
                    if field == 'h':
                        if _sole_use(md, d, w[1], addr, reg):
                            vals['h_at'] = w[1]
                        if left is None:
                            left = 20     # the width sits beside the height
        if left is not None:
            left -= 1
            if left < 0:
                break
        addr += step
    return vals


def display_size():
    """{message file offset: (width px, height px)} of the viewport the
    message's own call site proves.

    Only messages with a code reference can be followed to a BgMapInit call;
    a pointer-table message drawn by a loop has no one call site and is not
    in the map. The numbers come from the block's own `g_bg_layers[4]`, so a
    message whose geometry is inherited from another screen stays unknown.
    Cached: the analysis reads the delivered ADV.BIN once."""
    global _DISPLAY, _HEIGHT_AT
    if _DISPLAY is not None:
        return _DISPLAY
    import capstone
    d = adv()
    msgs = messages(d)
    rf = refs(d, msgs)
    md = capstone.Cs(capstone.CS_ARCH_MIPS,
                     capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    calls = {}
    for i, (_a, _e) in enumerate(msgs):
        for kind, where, _old in rf[i]:
            if kind != 'code':
                continue
            call = _find_call(md, d, where)
            if call is not None:
                calls.setdefault(call, set()).add(i)
    order = sorted(calls)
    out = {}
    height_at = {}
    for k, call in enumerate(order):
        prev = order[k - 1] if k else call - 4 * _MAX_SETUP
        nxt = order[k + 1] if k + 1 < len(order) else call + 4 * _MAX_SETUP
        # The block that opens the message can set the geometry just before
        # the call (a shared setup) or just after it (the long draw block).
        # The FIRST write after the call belongs to this call; only when the
        # block has none does the nearest write before it apply.
        geo = _viewport(md, d, call + 4, min(nxt, call + 4 * _MAX_SETUP))
        if 'h' not in geo:
            geo = _viewport(md, d, call - 4, max(prev, call - 4 * _MAX_SETUP))
        h = geo.get('h')
        if not h or h % 16:
            continue                      # no proven viewport: stay a textbox
        w = geo.get('w')
        w = min(w, _MAX_WIDTH) if w else None
        frame = _frame_heights(md, d, call)
        for i in calls[call]:
            out[msgs[i][0] - B] = (w, h)
            height_at.setdefault(msgs[i][0] - B, []).append((geo.get('h_at'), frame))
    _DISPLAY = out
    _HEIGHT_AT = height_at
    return out


def _frame_heights(md, d, call):
    """[(address of the `ori a2, zero, rows`, rows)] of the frame calls
    (FRAME_CALLS) the block draws before its BgMapInit `call`, or None when
    a frame call's height is not a constant of its own."""
    out = []
    for k in range(1, _FRAME_SETUP):
        ins = _ins(md, d, call - 4 * k)
        if ins is None:
            break
        if ins.mnemonic in ('jr', 'j') or ins.mnemonic.startswith('b'):
            break                     # the block starts after other control flow
        if ins.mnemonic != 'jal' or not ins.operands \
                or ins.operands[0].imm not in FRAME_CALLS:
            continue
        w = _const_writer(md, d, ins.address + 8, 'a2')
        if w is None or not _sole_use(md, d, w[1], ins.address, 'a2'):
            return None
        out.append((w[1], w[0]))
    return out


def height_writers(off):
    """[(h_at, frame)] per call site of this message: h_at is the address of
    the `ori reg, zero, h` that sets its viewport height (None where the
    constant also feeds another store and so cannot be rewritten alone);
    frame is _frame_heights' list for the frame drawn around it (None when
    a frame height cannot be rewritten alone)."""
    display_size()
    return _HEIGHT_AT.get(off, [])


def display_rows():
    """{message file offset: visible rows its call site proves}."""
    return {off: h // 16 for off, (_w, h) in display_size().items()}


def line_px(off):
    """The proven width of this message's viewport, or None when the call
    site proves no local width (the box layout then bounds the line)."""
    size = display_size().get(off)
    return size[0] if size else None


def is_one_line(off):
    """True when this message's own call site proves a one-row viewport."""
    return display_size().get(off, (None, None))[1] == 16


def dec(d, a, e):
    return etext.decode(d[a - B:e - B])


def read_tsv():
    """{idx: merged row} from the canonical ADV table (pos = message file
    offset). The row keeps `psp` and `note`: an over-limit draft needs the
    locator it came from."""
    import toolbelt
    msgs = messages(d := open(os.path.join(ROOT, 'data', 'psx', 'ADV.BIN'), 'rb').read())
    by_pos = {r['pos']: r for r in toolbelt.merged_rows(toolbelt.rel_for(os.path.join(ROOT, 'data', 'psx', 'ADV.BIN')))}
    rows = {}
    for i, (a, e) in enumerate(msgs):
        r = by_pos.get(hex(a - B))
        if r and (r['en'] or '').strip():
            rows[i] = r
    return rows


def _widest_line(t):
    """The widest drawn line of `t`, measured the way the gate measures it
    (pages and lines split on the same codes as tstatus.check)."""
    return max((vwf_wrap.text_width(ln)
                for page in tstatus.segments(t) for ln in page), default=0)


def dump():
    d = adv()
    msgs = messages(d)
    import toolbelt
    toolbelt.route_gaps(toolbelt.rel_for(os.path.join(ROOT, 'data', 'psx', 'ADV.BIN')),
                        [hex(a - B) for i, (a, _e) in enumerate(msgs)
                         if i not in DEAD])
    print(f'sysmsg: {len(msgs)} rows queued in {toolbelt.man_path(toolbelt.rel_for(os.path.join(ROOT, 'data', 'psx', 'ADV.BIN')))}')


def cut(a, e):
    """[a, e) minus the PROTECT ranges -> list of (a, e)"""
    out = [(a, e)]
    for pa, pe in PROTECT:
        nxt = []
        for x, y in out:
            if pe <= x or pa >= y:
                nxt.append((x, y))
                continue
            if x < pa:
                nxt.append((x, pa))
            if pe < y:
                nxt.append((pe, y))
        out = nxt
    return out


# The mods that retire retail ADV code, with the file declaring the
# ranges and their label prefix.
MOD_RETIRING = (('MOD_UNIFIED_SAVE_MENU', 'unified-save-menu/saves.inc', 'MOD_ADV_RETIRED_'),
                ('MOD_SKIP_THE_AGASTYA_TREE_MENU', 'skip-the-agastya-tree-menu/agastya.inc', 'MOD_AGASTYA_RETIRED_'))


def mod_retired_ranges():
    """(start, end, define): assembly owns these retired functions, including
    their old text refs, when the define is on."""
    out = []
    for define, name, prefix in MOD_RETIRING:
        source = open(os.path.join(ROOT, 'src', 'mods', name)).read()
        labels = dict(re.findall(r'\.definelabel\s+(' + prefix + r'\w+),\s*(0x[0-9A-Fa-f]+)', source))
        out += [(int(value, 16), int(labels[label[:-6] + '_END'], 16), define)
                for label, value in labels.items() if label.endswith('_START')]
    return out


def build():
    d = adv()
    msgs = messages(d)
    rf = refs(d, msgs)
    en = read_tsv()
    rows = display_rows()
    tstatus.load_glossary()
    todo = {}
    grow = {}                           # {height `ori` address: new height (px, or frame tiles)}
    inplace = set()
    errors = []
    drafts = []
    for i, (a, e) in enumerate(msgs):
        r = en.get(i) or {}
        t = (r.get('en') or '').strip(' 	')
        if not t:
            continue
        if not rf[i]:
            inplace.add(i)                  # nothing points at it that we can patch: must fit its own slot
        ja = dec(d, a, e)
        ja = re.sub(r'^(<00>|　)+', '', ja)
        width = line_px(a - B)
        limit = width or vwf_wrap.BOX_WIDTH + 1
        if rows.get(a - B) == 1:
            # ONE VISIBLE ROW: the line/page move has nowhere to go; the
            # wording must fit the one line the viewport proves, with no
            # invisible line after a break. The width check measures it
            # against that proven width.
            t = vwf_wrap.one_line(t)
        px = _widest_line(t)
        bad = tstatus.ship_errors(ja, t, line_px=width)
        # Over the destination's line: a DRAFT, not a broken box. It never
        # reaches the disc (the Japanese ships); a tool's wording goes to
        # manual in the standard over-limit shape, a human's row is kept and
        # reported. Anything else the gate found still fails the build.
        if px > limit and not [x for x in bad
                               if not (x[0] == 'width' and 'px over ' in x[1])]:
            drafts.append((i, hex(a - B), px, limit, t, r.get('psp', '')))
            continue
        if bad:
            errors.extend(f'{i}: [{k}] {m}' for k, m in bad)
            continue
        todo[i] = etext.encode(t)        # + FF01
        # MORE LINES THAN THE VIEWPORT SHOWS: the call site's height grows
        # to the page's lines (at most the three a page holds), so no line
        # is drawn below the visible rectangle.
        need = max((len(page) for page in tstatus.segments(t)), default=1)
        have = rows.get(a - B)
        if have and 1 < have < need <= _MAX_ROWS:
            for at, frame in height_writers(a - B):
                if at is None or frame is None:
                    errors.append(f'{i}: [rows] {need} lines, the viewport shows'
                                  f' {have} and its height constant (or its'
                                  f' frame\'s) is shared')
                    continue
                grow[at] = max(grow.get(at, 0), need * 16)
                for f_at, f_rows in frame:  # 8 px tiles: two per text row
                    grow[f_at] = max(grow.get(f_at, 0),
                                     f_rows + 2 * (need - have))
    if errors:
        raise SystemExit('sysmsg:\n  ' + '\n  '.join(errors))
    routed = kept = 0
    man = {x['pos']: x for x in toolbelt.read_manual('ADV', optional=True)}
    with open(DRAFT_OUT, 'w', encoding='utf-8', newline=NL) as o:
        o.write('pos\twidth_px\tlimit_px\tdraft\n')
        for _i, pos, px, limit, t, psp in drafts:
            o.write(f'{pos}\t{px}\t{limit}\t{t}\n')
            if (man.get(pos, {}).get('en') or '').strip():
                kept += 1                   # the human's wording: kept, the Japanese ships
                continue
            toolbelt.route_over('ADV', pos, psp, t,
                                toolbelt.note_over(px, limit, 'px'))
            routed += 1
    if drafts:
        print(f'sysmsg: {len(drafts)} over the line, shipped as Japanese'
              f' ({routed} routed to manual, {kept} human draft(s) kept): '
              + ', '.join(f'{pos} {px}px/{limit}px'
                          for _i, pos, px, limit, _t, _p in drafts))
    # free space = the old slots of the translated messages (per zone)
    free = []
    for i in todo:
        a, e = msgs[i]
        if i in inplace:
            if len(todo[i]) > e - a:
                raise SystemExit(f'sysmsg: unreferenced message {i} needs {len(todo[i])} bytes, slot has {e - a}')
            continue
        free.extend(cut(a, e))
    for i in DEAD:
        free.extend(cut(*msgs[i]))
    free.append((ADV_SPILL_ADDR, ADV_SPILL_ADDR + ADV_SPILL_SIZE))
    free.sort()
    merged = []
    for a, e in free:
        if merged and merged[-1][1] == a:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((a, e))
    # share identical English between messages with identical content
    placed = {}
    addr_of = {}
    fixed = {}
    for i in sorted(todo, key=lambda i: -len(todo[i])):
        b = todo[i]
        if i in inplace:
            fixed[msgs[i][0]] = b
            continue
        if b in placed:
            addr_of[i] = placed[b]
            continue
        for k, (a, e) in enumerate(merged):
            if e - a >= len(b):
                placed[b] = a
                addr_of[i] = a
                merged[k] = (a + len(b), e)
                break
        else:
            raise SystemExit(f'sysmsg: out of space for message {i} ({len(b)} bytes); free {[(hex(a), e - a) for a, e in merged]}.\n'
                             f'  The extension window [{ADV_SPILL_ADDR:#x},{ADV_SPILL_END:#x}) is full: widening it means'
                             f' moving ADV_SYSMSG_SPILL_END up (and verifying the live ADV work area above it) in addresses.inc.')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # every byte this build places, as {addr: byte} - fills first, then the
    # strings and pointer patches that override them - collapsed into
    # contiguous ranges for verify to read back after armips
    net = {}
    conditional_net = {define: {} for define, _, _ in MOD_RETIRING}
    retired = mod_retired_ranges()
    def claim(a, b, define=None):
        target = conditional_net[define] if define else net
        for k, x in enumerate(b):
            target[a + k] = x
    manifest = []
    with open(OUT, 'w', newline=NL) as o:
        o.write(';; generated by tools/sysmsg.py build - do not edit' + NL)
        for i in list(todo) + sorted(DEAD - set(todo)):
            for a, e in cut(*msgs[i]):
                o.write(f'.org {a:#x}{NL}.fill {e - a}, 0{NL}')
                claim(a, bytes(e - a))
        for b, a in list(placed.items()) + [(b, a) for a, b in fixed.items()]:
            o.write(f'; {a:#x}{NL}.org {a:#x}{NL}    .byte ' + ', '.join(f'0x{x:02X}' for x in b) + NL)
            claim(a, b)
        for i in todo:
            for kind, where, old in rf[i]:
                new = addr_of[i]
                conditional = next((define for start, end, define in retired
                                    if start <= where < end), None)
                if conditional:
                    o.write(f'.ifndef {conditional}' + NL)
                if kind == 'ptr':
                    o.write(f'.org {where:#x}{NL}    .word {new:#x}{NL}')
                    claim(where, struct.pack('<I', new), conditional)
                else:
                    o.write(f'.org {where:#x}{NL}    .halfword {(new - 0x800C0000) & 0xFFFF:#x}{NL}')
                    claim(where, struct.pack('<H', (new - 0x800C0000) & 0xFFFF), conditional)
                if conditional:
                    o.write('.endif' + NL)
        for at, h in sorted(grow.items()):
            conditional = next((define for start, end, define in retired
                                if start <= at < end), None)
            if conditional:
                o.write(f'.ifndef {conditional}' + NL)
            o.write(f'.org {at:#x}{NL}    .halfword {h:#x}  ; viewport / frame height{NL}')
            claim(at, struct.pack('<H', h), conditional)
            if conditional:
                o.write('.endif' + NL)
    for cells, condition in [(net, None)] + [(cells, '!' + define)
                                             for define, cells in conditional_net.items()]:
        start = prev = None
        for a in sorted(cells) + [None]:
            if start is None:
                start = prev = a
            elif a != prev + 1:
                row = [start, bytes(cells[x] for x in range(start, prev + 1)).hex()]
                manifest.append(row + [condition] if condition else row)
                start = prev = a
            else:
                prev = a
    import json
    with open(PLACED, 'w', newline=NL) as o:
        json.dump(manifest, o)
    used = sum(len(b) for b in placed) + sum(len(b) for b in fixed.values())
    print(f'sysmsg: {len(todo)}/{len(msgs)} translated, {used} bytes -> {OUT}')


def verify():
    """Re-read the assembled ADV.BIN at every address this build placed bytes
    (build/sysmsg_placed.json) and require them back byte-for-byte. The
    companion of the extension partition: armips assembles overlapping .org
    claims in silence (last write wins), so 'the generator ran' proves
    nothing - the checker after armips is what turns a new claimant of these
    bytes into a failed build instead of garbage on the memory-card screen."""
    import json
    places = json.load(open(PLACED))
    d = open(os.path.join(ROOT, 'build', 'ADV.BIN'), 'rb').read()
    symbols = open(os.path.join(ROOT, 'build', 'persona.sym')).read()
    defined = {define for define, _, _ in MOD_RETIRING
               if re.search(r'^\S+\s+' + define + r'\s*$', symbols, re.MULTILINE | re.IGNORECASE)}
    bad = []
    for row in places:
        a, hx = row[:2]
        if len(row) > 2:
            if row[2][1:] not in {define for define, _, _ in MOD_RETIRING}:
                raise SystemExit(f'sysmsg: unknown placement condition {row[2]!r}')
            if row[2][1:] in defined:
                continue
        want = bytes.fromhex(hx)
        got = d[a - B:a - B + len(want)]
        if got != want:
            bad.append((a, want.hex(), got.hex()))
    if bad:
        a, want, got = bad[0]
        raise SystemExit(
            f'sysmsg: verify: {len(bad)}/{len(places)} placed ranges are not in the assembled ADV.BIN, '
            f'first at {a:#x}: want {want[:32]}{"..." if len(want) > 32 else ""}, got {got[:32]}. '
            f'Another build step is writing over the sysmsg strings - see addresses.inc\'s '
            f'ADV extension partition (the sysmsg window is '
            f'[{ADV_SPILL_ADDR:#x},{ADV_SPILL_END:#x})).')
    print(f'sysmsg: verify: {len(places)} placed ranges read back from build/ADV.BIN unchanged')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'dump': dump, 'build': build, 'verify': verify}[sys.argv[1] if len(sys.argv) > 1 else 'build']()
