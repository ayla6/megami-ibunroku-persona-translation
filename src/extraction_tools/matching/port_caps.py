"""Destination capacities for the fixed text families.

Destination field capacity, not the source string's encoded length, limits
a name. Every family owns its field and answers for its own capacity here.  The constants and encoders are READ from the
builders; this module never invents a limit.

Units are the builder's own: bytes for the single-byte glyph tables
(items, demons), characters for the UI-limited fixed-cell tables (personas,
nicknames), and pixels for the VWF-rendered tables (skills, affinity) and the
one-line description bank.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
import affinity  # noqa: E402
import demons    # noqa: E402
import items     # noqa: E402
import nicknames  # noqa: E402
import personas  # noqa: E402
import skills    # noqa: E402
import smallfont_vwf  # noqa: E402
import toolbelt  # noqa: E402
import vwf_wrap  # noqa: E402

FAMILIES = ('items', 'demons', 'nicknames', 'skills', 'personas',
            'affinity', 'descs')

AFFINITY_ROW_PX = smallfont_vwf.ROW_PX   # the retail 25-cell affinity row's budget
DESCS_ROW_PX = 239                # descs.py's one-line string-bank slot


# ---------------------------------------------------------------------------
# The DESTINATION of every row: what the builder that writes it can hold.
# Every number here is READ from a builder - never from the Japanese line's
# length, which is no destination's capacity.
# ---------------------------------------------------------------------------

# Files whose rows are rendered in a textbox and may therefore be laid out
# again at a different width/line count. Fixed one-line tables (names,
# descriptions, card labels) are not here: their caps are screen cells or
# bytes, and re-wrapping them is not a fix.
TEXTBOX_RELS = ('ADV', 'BTLP', 'DNG', 'S2D', 'TALK',
                'D00', 'D01', 'D02')

BUDGET_PX = 239      # the layout width - the tightest shared budget
PEN_MAX = BUDGET_PX + 1  # a line may reach pen 240: the engine wraps only
                         # before the next glyph
BUDGET_LINES = vwf_wrap.PAGE_LINES  # 3 visible lines + the scroll (one place)


def is_name_field(rel):
    """A dungeon NAME pack (D0?M / D0?S), not a box file. The pack builder
    decides by exactly one property of the file's own name:
    `len(os.path.basename(rel)) == 3` is a boxes file. A name field is one
    line, not a textbox - re-wrapping it is never a fix."""
    if '/' not in (rel or ''):
        return False
    top, base = rel.split('/', 1)
    return top.startswith('D0') and len(base) != 3 and '/' not in base


def is_fixed_field(rel, pos):
    """The row is a fixed one-line field or slot, not a textbox: it cannot
    be laid out again, and a PSP-only UI marker has nowhere to show."""
    return is_name_field(rel) or dest_cap(rel, pos)[2] == 1


def is_textbox(rel):
    """A row rendered in a textbox: it may be laid out again at a different
    width/line count. Every D0* boxes file is one (the name packs beside
    them are not); so are the dialogue/event families."""
    rel = rel or ''
    if is_name_field(rel):
        return False
    if rel.startswith('D0'):
        return True
    return rel.startswith(TEXTBOX_RELS)


_LINE_BREAK = {}


def line_break(rel):
    """The line-break code this file's own text engine moves a line with.

    Not a family-name table: the code is read off the file's Japanese
    itself - whichever of <FFF6>/<FF03> its lines actually use, which is
    the same move the English must wrap with (a wrong code draws the
    break as a glyph or scrolls nothing). Computed once per file and
    cached."""
    rel = rel or ''
    if rel not in _LINE_BREAK:
        f6 = f3 = 0
        for t in toolbelt.psx_text_of(rel).values():
            f6 += t.count('<FFF6>')
            f3 += t.count('<FF03>')
        _LINE_BREAK[rel] = '<FFF6>' if f6 >= f3 else '<FF03>'
    return _LINE_BREAK[rel]


def ink_of(line):
    """A line's drawn characters: codes out, and out with each <FFFD>'s
    parameter character - a pause/branch parameter BYTE, not text."""
    return re.sub(r'<[^>]*>', '', re.sub(r'<FFFD>.', '', line))


def widest(en, ink=True):
    """(widest line in px, most lines on one page) of a wording, laid out
    the way the game breaks it. The BOX budget is ink (`ink=True`): a name
    insert is not ink when the layout engine has yet to place the line - it
    prices the insert itself. A row that is already laid out measures what
    it draws (`ink=False`), the same pixels the QA gate reads."""
    px = lines = 0
    for page in re.split(r'<FFFB><FFF7>|<FF04>|<FF02>', en):
        ls = [l for l in re.split(r'<FF03>|<FFF6>', page) if l.strip()]
        lines = max(lines, len(ls))
        for l in ls:
            px = max(px, vwf_wrap.text_width(ink_of(l) if ink else l))
    return px, lines


def _off(pos):
    """The file offset a row's `pos` names (its first, where a row merges a
    run of them), or None."""
    try:
        return int((pos or '').split(',')[0], 16)
    except ValueError:
        return None


def boot_plain(s):
    """A family record's Japanese key, matched the way boot_pairs keys it
    (undecoded code placeholders are not part of a name)."""
    return re.sub(r'<[0-9A-Fa-f]{4}>', '', s or '').strip()


_FAM = {}
_FW = {}
_BANK = {}


def _families():
    if not _FAM:
        import boot_pairs
        by, bypos = {}, {}
        for fam, slots in boot_pairs.family_slots().items():
            for k, pos, sj in slots:
                key = boot_pairs.plain(sj)
                by.setdefault(key, []).append((fam, k, pos))
                bypos[pos] = (fam, k, pos)
        _FAM['by'] = by
        _FAM['bypos'] = bypos
        us = boot_pairs.us_pointer()
        _FAM['us'] = us
        grids = {}
        for fam, slots in boot_pairs.family_slots().items():
            pts = [(k, us[pos]) for k, pos, _j in slots
                   if us.get(pos) is not None]
            g = boot_pairs.fit_grid(pts) if len(pts) >= 8 else None
            if g and len(g[2]) >= 0.8 * len(pts):
                grids[fam] = (g[0], g[1])
        _FAM['grid'] = grids
    return _FAM


def family_wording(ja, pos=''):
    """(psp pointer, en, family) where a SLPS family table names this unit.
    Cached: the port asks this once when it places a row and again when it
    measures the destination (family_row)."""
    key = ((pos or '').split(',')[0], boot_plain(ja))
    if key not in _FW:
        _FW[key] = _family_wording(ja, pos)
    return _FW[key]


def _family_wording(ja, pos=''):
    """(psp pointer, en, family) where a SLPS family table names this unit.

    Preferred key is the PSX POSITION - a family slot is a record at a
    known offset, so `family_slots()`'s slot for that offset IS this unit.
    That is identity, not similarity: a skill description is completely
    reworded between builds and no text match will ever find it. Falls
    back to the Japanese string where a position is not available - and
    then uniqueness is the proof."""
    fam = _families()
    hit = fam['bypos'].get((pos or '').split(',')[0])
    if hit is None:
        hits = fam['by'].get(boot_plain(ja), [])
        if len(hits) != 1:
            return '', '', ''
        hit = hits[0]
    fname, k, sp = hit
    off = fam['us'].get(sp)
    if off is None and fname in fam['grid']:
        base, stride = fam['grid'][fname]
        off = base + k * stride
    if off is not None:
        rows = toolbelt._extract('psp_us', 'EBOOT')
        best = None
        for r in rows:
            try:
                p = int(r['pos'], 16)
            except ValueError:
                continue
            if p <= off and (best is None or p > int(best['pos'], 16)):
                best = r
        if best is not None and best['text'].strip():
            return f'EBOOT:{best["pos"]}', best['text'], fname
    # the description families are not in EBOOT at all: their wording lives
    # in the boot description bank, addressed by slot index
    return '', _bank_wording(fname, k), fname


def _bank_wording(fam, k):
    """The PSP-US wording of a family slot out of the boot description
    bank - where skill/item descriptions actually live (port_descs). The
    map is slot-index -> bank-offset, so it is identity, not matching."""
    if fam != 'descs':
        return ''          # item slots are NAMES in EBOOT, never a bank row
    if not _BANK:
        import port_descs
        _BANK['map'] = port_descs.slot_map()
        _BANK['text'] = port_descs.bank_map()
    off = _BANK['map'].get(k)
    txt = _BANK['text'].get(off) if off is not None else None
    return txt or ''


def family_at(pos, rel=''):
    """The family whose fixed slot this position is, or ''. Positions are
    only unique inside one real disc file (an identical offset in an
    overlay is a different unit). Identity from the table structure."""
    if rel and rel != 'SLPS_005.00':
        return ''
    hit = _families()['bypos'].get((pos or '').split(',')[0])
    return hit[0] if hit else ''


def family_row(rel, pos, ja=''):
    """The port_caps family whose FIELD writes this row, or ''.

    Two identities, the same two place() proves: the position IS a family
    slot (SLPS_005.00's name/description tables), or the row's Japanese IS
    a family record (an item name on a battle banner, a demon's name in a
    negotiation line). A row whose wording is a family's own is measured by
    that family's builder; nothing else is."""
    fam = family_at(pos, rel)
    if fam in FAMILIES:
        return fam
    if not (ja or '').strip():
        return ''
    _ptr, text, ffam = family_wording(ja, pos)
    return ffam if (text.strip() and ffam in FAMILIES) else ''


_BTL = None
_ADV = None
_CAS = None


def _btl_caps():
    """{file offset: (cap, unit, lines)} for BTLP's four families.

    A BTLP row is a TEXTBOX: the builder packs (BPE for evt) and
    relocates (zone -> spill), so the in-place slot's length never caps the
    wording. Only a real buffer the unpacker writes through is a cap
    (NEG_BUF for the packed negotiation rows). banner: pool + spill, one
    line. Every number is READ from btlp."""
    global _BTL
    if _BTL is not None:
        return _BTL
    import btlp
    d = btlp.data()
    out = {}
    for a, _e in btlp.evt_messages(d):
        out[a - btlp.B] = (None, None, None)   # packed + relocated
    for a, _e in btlp.msg_messages(d):
        # BtlOpenMessage opens a one-row battle message viewport. The
        # re-packed storage is not a width limit, but its visible row is.
        out[a - btlp.B] = (PEN_MAX, 'px', 1)
    for i, (a, _q) in enumerate(btlp.neg_strings(d)):
        out[a - btlp.B] = ((btlp.NEG_BUF, 'B', None)
                           if i in btlp.NEG_PACK_IDX else (None, None, None))
    for _k, p, _ja in btlp.ban_records(d):
        out[p - btlp.B] = (None, None, 1)
    _BTL = out
    return out


def _adv_caps():
    """{file offset: (cap, unit, lines)} for ADV.BIN's text builders.

    sysmsg packs every translated message into the free space its zone has
    freed: the only space a message owns is its own in-place slot. scriptmsg
    moves an oversize embedded message into the surveyed ADV cave, whose
    whole extent is the row's limit. giftmsg rewrites the Persona-gift
    speech into the bytes its compact store sequence frees."""
    global _ADV
    if _ADV is not None:
        return _ADV
    import giftmsg
    import scriptmsg
    import sysmsg
    d = sysmsg.adv()
    out = {}
    for a, e in sysmsg.messages(d):
        out[a - sysmsg.B] = (e - a, 'B', None)
    _base, size = scriptmsg.CAVE['ADV']
    for ovl, ram, _keep in scriptmsg.MSGS:
        if ovl != 'ADV':
            continue
        s = ram - scriptmsg.B
        e = d.index(b'\xff\x01', s) + 2
        out[s] = (max(e - s, size), 'B', None)
    # giftmsg moves its store sequence out of this window, so the message owns
    # everything after the jump; the builder owns that number.
    out[giftmsg.OLD_A - giftmsg.B] = (giftmsg.ROOM, 'B', 3)
    _ADV = out
    return out


def _casino_cap(off):
    """Capacity of the complete prize line, including its bonus."""
    global _CAS
    if _CAS is None:
        import casinoprize
        src = open(toolbelt.bin_path('CASINO'), 'rb').read()
        _CAS = {}
        for o, _raw, ja in casinoprize.records(src):
            _CAS[o] = casinoprize.MAX_CELLS
    return _CAS.get(off, 19)


def dest_cap(rel, pos):
    """(cap, unit, lines) of the destination builder that writes this row.

    cap is None where the builder RELOCATES the wording (own slot -> free
    ranges -> a spill area): such a row is limited only by the box's
    layout. A cap is a real limit of the destination - a fixed slot or
    buffer, in the builder's own unit. `lines` is 1 for a one-line field,
    None for a textbox. Every number here comes from a builder."""
    rel = rel or ''
    if rel == 'BTLP':
        return _btl_caps().get(_off(pos), (None, None, None))
    if rel == 'S2D':
        import s2d
        off = _off(pos)
        if off is not None and s2d.NZONE[0] - s2d.B <= off < s2d.NZONE[1] - s2d.B:
            # A location slot's own row is the arrival/current-location
            # banner name (the 15x1 banner's strip). The 8x1 map labels are
            # a separate string the builder splits off, not this row.
            return s2d.BANNER_LIMIT, 'px', 1
        return None, None, None        # script box: own slot -> free -> spill
    if rel == 'ADV':
        import sysmsg
        off = _off(pos)
        if off is not None and sysmsg.ZONES[0][0] - sysmsg.B <= off < \
                sysmsg.ZONES[1][1] - sysmsg.B:
            # The message viewport is read from the code that opens it
            # (sysmsg.display_size). One visible row is a FIXED line: no
            # reflow, no invisible second line, and its width is the
            # layer's own (dest_line_px). A multi-row message scrolls
            # (PAGE_LINES), so its proven height is not a line cap.
            if sysmsg.is_one_line(off):
                return None, None, 1
            return None, None, None
        return _adv_caps().get(off, (None, None, None))
    if rel.startswith('ADV/'):
        return None, None, None        # efile.rebuild re-lays the image
    if rel == 'CASINO':
        return _casino_cap(_off(pos)), 'chars', 1
    if rel.startswith('TALK'):
        return None, None, None        # Talk.rebuild repacks units + table
    if is_name_field(rel):
        return None, None, 1           # map-title hook: one line
    if is_textbox(rel):
        return None, None, None        # dungeon boxes relocate (dngspill)
    return None, None, 1


def has_label_row(rel, pos):
    """Whether this destination can draw a speaker label at all.

    The ADV system-message bank is drawn by the message engine into the
    viewport its call site opens: there is no label row, and the Japanese
    carries no nameplate. A PSP-US `<FF1B>name<FF03>` there is PSP UI
    decoration, never wording - the label (and its break) is dropped."""
    if (rel or '') == 'ADV':
        import sysmsg
        off = _off(pos)
        if off is not None and sysmsg.ZONES[0][0] - sysmsg.B <= off < \
                sysmsg.ZONES[1][1] - sysmsg.B:
            return False
    return True


def dest_owned(rel):
    """A file whose destination this module models with a builder's own
    capacity (`dest_cap`). Anywhere else the fallback one-line field is
    not a statement about the row and must not withdraw anything."""
    rel = rel or ''
    return (rel in ('ADV', 'BTLP', 'S2D', 'CASINO')
            or rel.startswith('ADV/') or rel.startswith('TALK')
            or rel.startswith('D0'))


def _encoded_len(text, tail=2):
    """The bytes the destination builder writes for this wording: the
    encoded body plus the end code(s) that builder appends."""
    import etext
    try:
        b = etext.encode(text, end=None)
    except Exception:
        return len(text) + tail
    if tail > 2:
        return len(b) + tail
    return len(b) if b.endswith(b'\xff\x01') else len(b) + 2


def _taillen(rel, pos):
    """The end bytes the destination appends. An embedded script message
    re-emits its FF02 wait before FF01 (scriptmsg) - four; every other
    builder ends on the one end code."""
    if rel == 'ADV':
        import scriptmsg
        off = _off(pos)
        for ovl, ram, _keep in scriptmsg.MSGS:
            if ovl == 'ADV' and off == ram - scriptmsg.B:
                return 4
    return 2


def _measure(text, unit, tail=2):
    if unit == 'B':
        return _encoded_len(text, tail)
    if unit == 'chars':
        return len(re.sub(r'<[^>]*>', '', text))
    return widest(text)[0]


def _extra_codes(text, rel):
    """True when a fixed destination cannot interpret a source control."""
    import boot_pairs
    import port_derive
    if rel in ('ADV', 'BTLP'):
        return not port_derive.codes_match(text, interpreter='battle' if rel == 'BTLP' else 'dialogue')
    return any(c not in port_derive.REFLOW_CODES and c != 0xFF01
               for c in boot_pairs.skeleton(text)[0])


def dest_line_px(rel, pos):
    """The line width the destination itself proves, in px, or None where
    the box layout (`PEN_MAX`) is the only limit. An ADV system message is
    drawn into the map layer its code opens (sysmsg.display_size): that
    rectangle's width is what is visible, so it - not the 240 px default -
    bounds the line (the coin-shop notice is 11 cells, 176 px)."""
    if (rel or '') != 'ADV':
        return None
    import sysmsg
    off = _off(pos)
    if off is None or not (sysmsg.ZONES[0][0] - sysmsg.B <= off <
                           sysmsg.ZONES[1][1] - sysmsg.B):
        return None
    return sysmsg.line_px(off)


def dest_note(text, rel, pos, ja=''):
    """The reason this wording is over its DESTINATION's limit, or '' when
    it fits. ONE decision, shared by place() and redraft(), so the two can
    never disagree. A row that is a family's own field is measured by that
    family's builder; everything else by the builder that writes it: a
    real slot/buffer in the builder's own unit, or - where the builder
    relocates - the box layout alone. The Japanese line's byte length is
    never a cap."""
    fam = family_row(rel, pos, ja)
    if fam in FAMILIES:
        # port_caps speaks in full notes ('<reason>; <draft>'); every caller
        # composes the draft itself, so only the reason travels on.
        return note(fam, text).split(';', 1)[0]
    if is_fixed_field(rel, pos) and _extra_codes(text, rel):
        # a one-line field/slot has no interpreter to run a control code:
        # the Japanese carries exactly the codes its own build can show
        return 'unsupported destination control codes'
    cap, unit, lines = dest_cap(rel, pos)
    if lines == 1:
        # the destination draws one row: a line/page move is the space it
        # stood for, and the width is measured on the line that is drawn
        text = vwf_wrap.one_line(text)
    px, n = widest(text)
    limit = dest_line_px(rel, pos) or PEN_MAX
    if px > limit:
        return toolbelt.note_over(px, limit, 'px')
    if lines is not None and n > lines:
        return toolbelt.note_over(n, lines, 'lines')
    if n > BUDGET_LINES:
        return toolbelt.note_over(n, BUDGET_LINES, 'lines')
    if cap is None:
        return ''
    amount = _measure(text, unit, _taillen(rel, pos))
    if amount <= cap:
        return ''
    return toolbelt.note_over(amount, cap, unit)


def _strip(text):
    return (text or '').strip()


def _reason(exc):
    """The builder's reason only when the glyphs are the problem; an
    over-length refusal is the capacity check itself and needs no text."""
    return 'not in the small font' if 'not in the small font' in str(exc) else ''


def measure(fam, text):
    """(fits, amount, capacity, unit, reason) for one wording in one family.

    `amount` is in the family's own unit.  `reason` is '' when the builder
    accepts the wording, otherwise the builder's reason (an unsupported
    glyph) or '' when it is simply wider than the field.
    """
    t = _strip(text)
    if fam == 'items':
        try:
            b = items.encode(t)
        except (KeyError, SystemExit) as exc:
            return False, len(t), items.FIELD, 'B', _reason(exc)
        # The row's ten 8-px cells bound the drawn name, not its storage.
        # A name over the row uses the least aggressive condensed tier the
        # renderer can apply; only one no tier fits is over the destination
        # and returns to manual as a draft (never widened, never squeezed
        # past the tier's rules). The reported width is then the natural one.
        tier, px = items.name_fit(t)
        if tier is None:
            return False, px, items.ROW_PX, 'px', ''
        return len(b) <= items.MAXLEN, len(b), items.MAXLEN, 'B', ''
    if fam == 'demons':
        try:
            b = skills.encode_glyphs(0, t)
        except (KeyError, SystemExit) as exc:
            return False, len(t), demons.MAXLEN, 'B', _reason(exc)
        tier, px = demons.name_fit(t)
        if tier is None:
            return False, px, demons.ROW_PX, 'px', ''
        return len(b) <= demons.MAXLEN, len(b), demons.MAXLEN, 'B', ''
    if fam == 'nicknames':
        try:
            nicknames.encode(t)
        except (KeyError, SystemExit) as exc:
            return False, len(t), nicknames.MAXLEN, 'chars', _reason(exc)
        return len(t) <= nicknames.MAXLEN, len(t), nicknames.MAXLEN, 'chars', ''
    if fam == 'skills':
        # The battle skill menu renders these with the small-font VWF; its
        # two columns leave 144 px and the patch has always drawn 120 px.
        # Storage (MAXLEN) is only the 32-byte slot's bound, never the cap.
        try:
            skills.encode(0, t)
        except (KeyError, SystemExit) as exc:
            reason = _reason(exc)
            if reason:
                return False, len(t), skills.NAME_PX, 'px', reason
            return False, len(t), skills.MAXLEN, 'chars', ''
        px = smallfont_vwf.line_px(t)
        return px <= skills.NAME_PX, px, skills.NAME_PX, 'px', ''
    if fam == 'personas':
        if len(t) > personas.MAXLEN:
            return False, len(t), personas.MAXLEN, 'chars', ''
        try:
            skills.encode_glyphs(0, t)
        except (KeyError, SystemExit) as exc:
            return False, len(t), personas.MAXLEN, 'chars', _reason(exc)
        return True, len(t), personas.MAXLEN, 'chars', ''
    if fam == 'affinity':
        # The record carries the line's first 25 glyphs; a longer line
        # continues in the small-font pool and the recorder appends it
        # (affinity.LINE_MAX is one drawn row). Width, not the glyph count,
        # decides whether it crowds the retail 200 px footprint.
        if len(t) <= affinity.STRIDE:
            return True, len(t), affinity.STRIDE, 'chars', ''
        # control codes are no ink of their own, and a glyph the small font
        # cannot print is the builder's refusal - same shape as every other
        # family's answer
        body = re.sub(r'<[^>]*>', '', t)
        try:
            px = smallfont_vwf.field_line_px(body)
        except (KeyError, SystemExit) as exc:
            return False, len(body), affinity.STRIDE, 'chars', _reason(exc)
        return px <= AFFINITY_ROW_PX, px, AFFINITY_ROW_PX, 'px', ''
    if fam == 'descs':
        px = vwf_wrap.text_width(re.sub(r'<[^>]*>', '', t))
        lines = 1 + t.count(chr(10)) + t.count('<FF03>')
        return px <= DESCS_ROW_PX and lines == 1, px, DESCS_ROW_PX, 'px', ''
    raise KeyError(f'port_caps: unknown family {fam!r}')


def note(fam, text):
    """The canonical over-cap note for this family, or '' when it fits."""
    fits, amount, cap, unit, reason = measure(fam, text)
    if fits:
        return ''
    if reason:
        return toolbelt.over_note(reason, _strip(text))
    return toolbelt.over_note(toolbelt.note_over(amount, cap, unit),
                              _strip(text))


def fits(fam, text):
    return measure(fam, text)[0]
