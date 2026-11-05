"""PSP text codecs: the glyph map + box decoder (E/TALK/dng).

ONE glyph table - the PSP has a single charset, there is no US/JP split
(src/extraction_tools/psp_glyphs.tsv; the codes are in SHIFT-JIS ORDER). Every decoder and builder loads it from here. 8140 = space inside
BOOT.BIN tables, 0000 = space inside E/TALK boxes and terminator in BOOT.
"""
import os
import sys

# this module is imported from many places; it finds toolbelt itself
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), 'injection_tools'))
import toolbelt  # noqa: E402
import struct
# The glyph table lives in src/extraction_tools/psp_glyphs.tsv; reference:
# references/persona1psptable.tbl (DISCOVERED BY Gabriulio: the codes are in
# SHIFT-JIS ORDER). ONE table: the PSP has a single charset - there is no
# US/JP split and no hand-solved map. The loader is below.
# Pass-through (copy raw, never translate): icons/params/digits etc.
# 0001 0002 0029 0006 002a 0044 0055 00d0 00d1 001e 001f 0200-0207 ...
#
# Control parameter units: the control CONSUMES the next unit(s), so every
# decoder consumes them (decoding one as a glyph corrupts the text):
# FF05/FF06/FF0E/FF18/FF19/FF1A take one unit, FF1B takes two on intro
# cards (0200/0300 0044) and none in dialogue, FF0D one parameter byte
# (rendered '<FFFD>#' - talktl replaces the per-unit character with '#').
# Keys are the control's op BYTE (the FF prefix is the code marker).
E_PARAM_UNITS = {0x05: 1, 0x06: 1, 0x0E: 1, 0x18: 1, 0x19: 1, 0x1A: 1}
INTRO_CARD_HEAD = (0x0200, 0x0300)

# THE parameter rule - one place, every decoder calls param_take and
# nothing re-derives it. A control code's parameter units are part of the
# CODE, never text. Two kinds of parameter:
#
#   an ID   (the name spans FF18/FF19/FF1A, the intro card FF1B): the
#           unit is whatever the id happens to be - 0x0200 reads 'beta',
#           0x0500 reads as a kanji - and the code eats it always.
#   a NUMBER (FF05 pause, FF06 colour, FF0E choice): a number is never a
#           letter, so where the next unit is a glyph the map solves, it
#           is text and the code does not eat it. (A name record's field
#           separator reads as 'FF0E' and sits right before the name -
#           eating the 'S' of 'Self-Destruct' for it is how a name loses
#           its first letter.)
#
# Reading an id as its glyph is what made a name span print 'beta' in the
# middle of a sentence; reading a separator's next letter as a parameter
# is what ate a name. Neither is a per-row special case: it is which kind
# of parameter the code takes.
EAT_ID = (0x18, 0x19, 0x1A)


def param_take(op, peek=None, peek2=None):
    """(count, is_id) of the parameter units control code `op` takes.
    `is_id` says the units are an id: eaten whatever they look like. The
    peeks are the next one or two units, for the intro-card FF1B form
    (FF1B 0200/0300 0044 - a two-unit id)."""
    if op == 0xFD:
        return 1, True
    if op == 0x1B and peek in INTRO_CARD_HEAD and peek2 == 0x0044:
        return 2, True
    return E_PARAM_UNITS.get(op, 0), op in EAT_ID

_JP = None
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))


def jp_map():
    """{unit: char} - THE PSP glyph table (src/extraction_tools/psp_glyphs.tsv,
    reference: references/persona1psptable.tbl). One table: the PSP
    has a single charset and no US/JP split. The one loader."""
    global _JP
    if _JP is None:
        import strlib
        _JP = {}
        for u, ch in strlib.tsv_fields(
                toolbelt.PSP_GLYPHS, 2):
            if u:
                _JP[int(u, 16)] = ch
    return _JP


US_MAP = jp_map()          # the same table: there is only one


def glyphs(region):
    """The shared glyph map for either region; the PSP has a single charset."""
    return US_MAP


def decode_box(raw, glyph_map=US_MAP, stop_at_end=False, holes=None):
    """Render a raw PSP box as text: controls as <FFxx>, their parameter
    units as <xxxx>, glyphs from the map.

    A word that is neither a glyph nor a parameter is a glyph-map hole (or
    scanner noise): recorded in `holes` as (offset, word) when a collector
    is given - the cache keeps it visible as [xxxx] - and RAISED otherwise.
    Nothing is ever dropped or invented silently."""
    import struct
    out = []
    i, n = 0, len(raw)
    while i + 1 < n:
        if raw[i] == 0xFF:
            op = raw[i + 1]
            i += 2
            out.append('<FF%02X>' % op)
            if stop_at_end and op in (0xF5, 0xEF):
                break
            if op == 0xFD:  # one parameter byte
                if i < n:
                    out.append('#')
                    i += 1
                continue
            units, is_id = param_take(
                op,
                struct.unpack_from('>H', raw, i)[0] if i + 1 < n else None,
                struct.unpack_from('>H', raw, i + 2)[0] if i + 3 < n else None)
            for _ in range(units):
                if i + 1 >= n:
                    break
                u = struct.unpack_from('>H', raw, i)[0]
                if not is_id and u in glyph_map:
                    break          # a number parameter is never a letter
                out.append('<%04X>' % u)
                i += 2
            continue
        u = struct.unpack_from('>H', raw, i)[0]
        i += 2
        ch = glyph_map.get(u)
        if ch is not None:
            out.append(ch)
        else:
            out.append('[%04x]' % u)
            if holes is None:
                raise LookupError('glyph-map hole: word 0x%04x at box+0x%x '
                                  '(fix the glyph map; nothing is dropped '
                                  'silently)' % (u, i - 2))
            holes.append((i - 2, u))
    if i < n:
        out.append('[%02x]' % raw[i])
    return ''.join(out)
