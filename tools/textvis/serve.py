#!/usr/bin/env python3
"""Serve the textbox visualiser: the page plus the real rows, read live.

  python tools/textvis/serve.py          http://127.0.0.1:8765/
  python tools/textvis/serve.py 9000     another port

No build step and no baked dump: /rows, /row, /psp and /save read
translation/{generated,manual}/*.tsv and extracted_text/{psx,psp_us,psp_jp}
through toolbelt whenever a file changes, so what you see is the table as it
is on disk right now. A saved draft is the human's override and goes to
translation/manual/ with the row's psp and note kept.

  GET  /rows?q=&fam=&limit=   [rel, id, pos, text, state, note] per row
  GET  /row?rel=&pos=         one row: manual, generated, PSP-US, PSX-JA,
                              and the choice grid when the row is an <FF0E>
                              option table entry (a queued over-limit row
                              starts from the draft in its note)
  POST /reload                the project's modules imported afresh and every
                              cache dropped (the page's reload button)
  POST /errata {rel,pos,rows} the row's PSP line's errata, replaced in
                              translation/psp_errata.tsv (the port applies them)
  POST /errata/preview {rel,pos,rows}  the row as those errata would make
                              it: the stored English re-edited and each box
                              laid out by the porter's flow (a picture; the
                              port writes the row)
  POST /save {rel,pos,en}     the human's manual override (Ctrl+S in the page);
                              a choice row is laid out first, so the save
                              cannot write a grid the build would refuse
  POST /phrases {phrase,note} words read as one thing, appended to
                              translation/phrases.tsv (a break inside them
                              costs what a name split does)
  GET  /psp?q=&region=&limit= search the PSP-US and PSP-JP extracts
  GET  /psp/unit?region=&rel=&id=  one PSP unit, its neighbours, its twin
  GET  /font?edition=          a font edition's VWF font (large by default) + the retail FONT.BIN and
                              its glyph map (the missing-character fallback)
  GET  /count                 how many rows the tables hold
  POST /render {rel,text,flow,edition} the text as the game draws it in a font
                               edition (a row carrying every edition's layout is
                               read as that one's), page by page:
                              vwf_render's compositor model (ink, shadow,
                              inserts, the engine's own wrap) and
                              vwf_wrap.shape_report's findings - the porter's
                              rules, never a copy of them. flow=1 lays typed
                              text out with vwf_wrap.flow_lines first
                              (a newline is a break, a blank line a new box)
  GET  /changed?ref=HEAD      [rel, pos] of every row whose shipped English
                              (manual wins) differs from the git ref's
  GET  /close                 the close calls the port weighed
                              (build/close_calls.tsv, close_calls.py):
                              {rows: [rel, pos, margin], missing}
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import base64
import csv
import glob
import importlib
import json
import re
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
GEN = os.path.join(ROOT, "translation", "generated")
MAN = os.path.join(ROOT, "translation", "manual")
PAGE = os.path.join(HERE, "index.html")
FONT_DIR = os.path.join(ROOT, "src", "mods", "latin-alphabet", "assets", "fonts")
# THE RETAIL JAPANESE FONT: the textbox's own 16x16 1-bpp FONT.BIN and the
# glyph map that names each slot. The page uses it for every character the
# English VWF font has no cell for.
ORIG_FONT = os.path.join(ROOT, "data", "psx", "FONT.BIN")
FONT_MAP = os.path.join(ROOT, "src", "injection", "formats", "font_map.tsv")

_font = {"stamp": None, "json": None}
_orig = {"stamp": None, "data": None}
_cache = {"stamp": None, "rows": []}
_psp = {}
_align = {"key": None, "map": {}}
_choices = {"stamp": None, "map": {}}


def font_payload(edition: str) -> bytes:
    """The built face and its exact character-to-code and spelling maps."""
    font_builder = importlib.import_module("make_vwf_font")
    fb = toolpath.font_path("font", edition)
    wb = toolpath.font_path("width", edition)
    paths = (fb, wb, ORIG_FONT, FONT_MAP, font_builder.SHEET_CHARACTERS,
             font_builder.RECLAIMED_KANJI, os.path.join(FONT_DIR, font_builder.EDITIONS[edition][0]))
    stamp = (edition, *tuple(
        (os.stat(p).st_mtime_ns, os.stat(p).st_size) if os.path.exists(p) else None
        for p in paths
    ))
    if _font["stamp"] == stamp:
        return _font["json"]
    with open(fb, "rb") as source:
        rows = source.read()
    with open(wb, "rb") as source:
        widths = source.read()
    if len(widths) != font_builder.TOP - font_builder.FIRST + 1 or len(rows) != 16 * len(widths):
        raise ValueError("Font tables do not match the sheet character list. Build the fonts and reload Textvis.")
    extra = font_builder.EXTRA_CODE
    atlas = font_builder.atlas_glyphs(edition)
    custom = {ch: [atlas[slot][-1], list(atlas[slot][:16])]
              for ch, slot in font_builder.ATLAS_CODE.items()}
    drawn = extra.keys() | custom.keys()
    folds = {ch: dest for ch, dest in font_builder.SPELL.items() if ch not in drawn}
    folds.update({ch: dest for ch, dest in (("＞", ">"), ("＜", "<")) if ch not in drawn})
    data = {"font": base64.b64encode(rows).decode(),
            "widths": base64.b64encode(widths).decode(),
            "extra": extra, "custom": custom, "spell": folds, "sheet_error": font_builder.SHEET_ERROR}
    try:
        ofont, gmap = orig_font()
        data["orig"] = base64.b64encode(ofont).decode()
        data["map"] = gmap
    except OSError:
        pass
    result = json.dumps(data, ensure_ascii=False).encode()
    _font.update(stamp=stamp, json=result)
    return result


def tb():
    """toolbelt, imported once: it is the only reader/writer of the tables."""
    if "toolbelt" not in globals():
        globals()["toolbelt"] = importlib.import_module("toolbelt")
    return globals()["toolbelt"]


def reload_all():
    """The reload button: the project's own modules (the porter's rules, the
    readers) imported afresh and every cache dropped, so the page shows the
    code and tables on disk now without restarting the server."""
    srcs = (os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"))
    mods = [m for m in list(sys.modules.values())
            if getattr(m, "__file__", None) and m.__name__ != __name__
            and os.path.abspath(m.__file__).startswith(srcs)]
    for m in mods:
        sys.modules.pop(m.__name__, None)
    globals().pop("toolbelt", None)
    _font.update(stamp=None, json=None)
    _orig.update(stamp=None, data=None)
    _cache.update(stamp=None, rows=[])
    _psp.clear()
    _align.update(key=None, map={})
    _choices.update(stamp=None, map={})
    _errata_targets.clear()
    _renders.clear()
    tb()
    return len(mods)


def tables(base, cols):
    """[(rel, path)] of the tables under <base> whose header is <cols>.

    A manual tree also holds source tables with their own schema (fmv/,
    terms.tsv); the viewer lists row tables only, so it checks the header
    before handing a path to toolbelt.
    """
    out = []
    for path in sorted(glob.glob(os.path.join(base, "**", "*.tsv"), recursive=True)):
        try:
            with open(path, encoding="utf-8") as f:
                head = f.readline().rstrip("\r\n").split("\t")
        except OSError:
            continue
        if tuple(head) == tuple(cols):
            out.append((os.path.relpath(path, base)[:-4], path))
    return out


def row_tables():
    """Both row-table trees, parsed once per mtime change."""
    tb_ = tb()
    found = [(GEN, rel, path) for rel, path in tables(GEN, tb_.GEN_COLS)]
    found += [(MAN, rel, path) for rel, path in tables(MAN, tb_.MAN_COLS)]
    stamp = tuple(sorted((path, os.stat(path).st_mtime_ns, os.stat(path).st_size)
                         for _b, _r, path in found))
    return found, stamp


def ja_text(ja_map, pos):
    """The Japanese at a row's pos. A multi-spot row ('0x1,0x2') takes the
    first spot that has an extract - the same identity the build uses."""
    for p in [pos] + [x.strip() for x in str(pos).split(",") if x.strip()]:
        if p in ja_map:
            return ja_map[p]
    return ""


def orig_font():
    """(FONT.BIN bytes, {character: glyph index}) of the retail Japanese font.

    The map is font_map.tsv: the slot each character printed from in the
    retail game (etext.char2g takes the first spelling, so do we). 16x16
    1-bpp glyphs, 32 bytes each, glyph g at FONT.BIN + g*32.
    """
    stamp = (os.path.getmtime(ORIG_FONT), os.path.getsize(ORIG_FONT),
             os.path.getmtime(FONT_MAP), os.path.getsize(FONT_MAP))
    if _orig["stamp"] == stamp:
        return _orig["data"]
    font = open(ORIG_FONT, "rb").read()
    gmap = {}
    with open(FONT_MAP, encoding="utf-8") as f:
        for line in f:
            fld = line.rstrip("\r\n").split("\t")
            if len(fld) < 2 or not fld[1]:
                continue
            try:
                g = int(fld[0], 16)
            except ValueError:
                continue
            gmap.setdefault(fld[1], g)
    _orig.update(stamp=stamp, data=(font, gmap))
    return font, gmap


def rows():
    """[rel, id, pos, text, state, note, man] for every row either table holds.

    generated + manual merged by pos (the row identity): manual's en wins
    where a human filled it, generated's en is what ships otherwise, and a
    row with no English at all shows the PSX Japanese it still has. state is
    manual / generated / queue (manual row, no en yet) / empty; man is 1
    when a manual row exists even if its en is still empty.
    """
    found, stamp = row_tables()
    if stamp == _cache["stamp"]:
        return _cache["rows"]
    tb_ = tb()
    rels = {rel for _base, rel, _path in found}
    out = []
    for rel in sorted(rels):
        gen = {r["pos"]: r for r in tb_._raw_generated(rel, optional=True)}
        man = {r["pos"]: r for r in tb_._raw_manual(rel, optional=True)}
        order = list(gen)
        order += [p for p in man if p not in gen]
        ja = None
        for pos in order:
            g, m = gen.get(pos), man.get(pos)
            gen_en = (g.get("en") or "") if g else ""
            man_en = (m.get("en") or "") if m else ""
            en = man_en if man_en.strip() else gen_en
            if not en.strip():
                # A queue row whose note parks an over-limit draft IS that
                # draft, so the list shows the wording the human has to
                # shorten instead of an empty cell (row_detail starts the
                # editor from the same draft).
                note = (m.get("note") or "") if m else ""
                if note.startswith("over limit"):
                    en = note.partition(";")[2].strip()
            if not en.strip():
                if ja is None:
                    ja = tb_.psx_text_of(rel)
                en = ja_text(ja, pos)
            state = ("manual" if man_en.strip() else
                     "generated" if gen_en.strip() else
                     "queue" if m else "empty")
            out.append([rel, (g or m)["id"], pos, en, state,
                        (m.get("note") or "") if m else "", 1 if m else 0])
    _cache.update(stamp=stamp, rows=out)
    return out


def psp_text(toolbelt, loc):
    """The PSP-US wording a row's `psp` names, as the PSP has it (the
    psp_errata.tsv corrections not applied: the row shows those).

    Two spellings: a unit locator ("pack/talk/KEMONO:0xd118", "BASKET:49" -
    an answer slot - resolved by toolbelt.psp_wording) and a FAMILY locator
    ("E0:149" - the ADV porter's own box index, which is the row's id in
    that extract).
    """
    w = toolbelt.psp_wording(loc, errata=False)
    if w:
        return w.strip()
    if ":" not in loc:
        return ""
    name, num = loc.split(":", 1)
    try:
        for row in toolbelt.read_extracted("psp_us", toolbelt.psp_rel(name),
                                           errata=False):
            if str(row.get("id")) == num.strip():
                return (row.get("text") or "").strip()
    except Exception:
        return ""
    return ""


def slim(toolbelt, r, with_note=False):
    if not r:
        return None
    out = {"id": r.get("id", ""), "pos": r.get("pos", ""),
           "psp": r.get("psp", ""), "en": r.get("en", ""),
           "psp_text": psp_text(toolbelt, r.get("psp", ""))}
    if with_note:
        out["note"] = r.get("note", "")
    return out


def row_detail(rel, pos):
    """Everything the page may read about one row, and the draft it starts
    with: manual's en, else generated's en, else the PSX Japanese.

    A manual row whose note parks an over-limit draft starts from that draft,
    not from the Japanese: the note's wording is the PSP text the human has to
    shorten, and retyping it before editing is work the viewer can spare them.
    The row keeps its `queue` state (manual en is still empty)."""
    tb_ = tb()
    gen = next((r for r in tb_._raw_generated(rel, optional=True)
                if r["pos"] == pos), None)
    man = next((r for r in tb_._raw_manual(rel, optional=True)
                if r["pos"] == pos), None)
    ja = ja_text(tb_.psx_text_of(rel), pos)
    man_en = (man or {}).get("en", "")
    gen_en = (gen or {}).get("en", "")
    note = (man or {}).get("note", "") or ""
    if man_en.strip():
        initial, state = man_en, "manual"
    elif gen_en.strip():
        initial, state = gen_en, "generated"
    else:
        draft = note.partition(";")[2].strip()
        over = note.startswith("over limit") and bool(draft)
        initial = draft if over else ja
        state = "queue" if man else "empty"
    try:
        head = shipped_at("HEAD").get((rel, pos))
    except ValueError:
        head = None
    try:
        errata = errata_for((gen or {}).get("psp", ""))
    except Exception:
        errata = None
    return {"rel": rel, "pos": pos, "ja": ja, "state": state,
            "initial": initial, "head": head, "gen": slim(tb_, gen),
            "man": slim(tb_, man, with_note=True),
            "choice": choice_grid(rel, pos), "errata": errata}


def choice_grid(rel, pos):
    """The dialogue-choice shape at <pos>, or None for an ordinary row.

    The choice table owns rows/cols/width (choices.py reads it from the
    disc); the page only needs the shape so it can draw `<FF0E>` option cells
    as the grid the build will produce and gate the same 239 px / two-row
    limits choices.layout applies."""
    if rel != "SLPS_005.00":
        return None
    path = os.path.join(ROOT, "data", "psx", "SLPS_005.00")
    if not os.path.exists(path):
        return None
    stamp = (os.stat(path).st_mtime_ns, os.stat(path).st_size)
    if _choices["stamp"] != stamp:
        import choices
        orig = choices.original()
        _choices["rows"] = {hex(r["ptr"] - choices.BASE): r for r in orig}
        _choices["map"] = {
            hex(r["ptr"] - choices.BASE):
                {"rows": r["params"][0], "cols": r["params"][1],
                 "width": r["params"][2]}
            for r in orig}
        _choices["stamp"] = stamp
    return _choices["map"].get(pos)


def validate_choice(rel, pos, en):
    """The choice grid's own owner checks a human's draft before it is saved.

    choices.layout is what the build runs; calling it here means the Save
    button refuses a grid the build would refuse (wrong cell count) or one
    still over the box limit, with the same message the porter would emit -
    instead of writing a row that stops the next build."""
    if not choice_grid(rel, pos):
        return
    import choices
    row = _choices["rows"][pos]
    try:
        choices.layout(row, en)
    except choices.OverLimit as exc:
        raise ValueError(f"{exc} - shorten the choice wording until the "
                         f"grid fits the box") from None
    except AssertionError as exc:
        raise ValueError(f"{pos}: {exc}") from None


def valid_rel(rel):
    return rel in {r[0] for r in rows()}


# ---------------------------------------------------------------------------
# PSP extracts: search both, and compare the two regions unit by unit
# ---------------------------------------------------------------------------

def psp_files(region):
    """{'stamp':..., 'files': {rel: rows}, 'lower': {rel: [text.lower()]}}
    for 'us' or 'jp', rebuilt when a file changes."""
    tb_ = tb()
    key = "psp_us" if region == "us" else "psp_jp"
    base = os.path.join(tb_.EXTRACTED, key)
    found = tables(base, tb_.EXT_COLS)
    stamp = tuple((path, os.stat(path).st_mtime_ns, os.stat(path).st_size)
                  for _rel, path in found)
    cached = _psp.get(region)
    if cached and cached["stamp"] == stamp:
        return cached
    # the PSP text as the PSP has it: psp_errata.tsv corrections are the
    # rows', not the source's
    files = {rel: tb_.read_extracted(key, rel, optional=True, errata=False)
             for rel, _path in found}
    cached = {"stamp": stamp, "files": files,
              "lower": {rel: [r["text"].lower() for r in rs]
                        for rel, rs in files.items()}}
    _psp[region] = cached
    return cached


def psp_glyphs():
    """The PSP's glyph table, so a parameter decoded as a character can be
    turned back into the bytes it stands for (match.Glyphs)."""
    if "glyphs" not in globals():
        from codec import jp_map
        import match
        globals()["match"] = match
        globals()["glyphs"] = match.Glyphs(jp_map())
    return globals()["glyphs"]


def psp_codes(region):
    """{rel: [canonical code signature]} next to the extracts, built once
    per table change. A signature is 'ff05:1000|ff03|ff01' - the codes by
    meaning, so the PSP's spelling of a parameter does not matter."""
    idx = psp_files(region)
    if "codes" not in idx:
        g = psp_glyphs()
        idx["codes"] = {rel: ["|".join(match.canon_codes(r["text"], g))
                              for r in rs]
                        for rel, rs in idx["files"].items()}
    return idx["codes"]


def align_map():
    """{rel: True} where the US and JP extracts line up unit for unit.

    The twin is only offered where the (entry, box) sequence is identical in
    both regions - 69 of the 72 shared files. EBOOT and E3 do not align, so
    they get no twin instead of a guessed one.
    """
    us, jp = psp_files("us"), psp_files("jp")
    key = (us["stamp"], jp["stamp"])
    if _align["key"] != key:
        out = {}
        for rel, ours in us["files"].items():
            theirs = jp["files"].get(rel)
            out[rel] = bool(theirs) and (
                [(r["entry"], r["box"]) for r in ours] ==
                [(r["entry"], r["box"]) for r in theirs])
        _align.update(key=key, map=out)
    return _align["map"]


def psp_search(q, region, limit):
    """Matches in US + JP, interleaved so one region cannot fill the limit
    and hide the other (an English word matches US only, a Japanese one JP
    only - then the other side simply ends)."""
    needle = q.lower()
    if not needle:
        return []

    def hits(reg):
        idx = psp_files(reg)
        for rel in sorted(idx["files"]):
            rows_ = idx["files"][rel]
            for i, low in enumerate(idx["lower"][rel]):
                if needle in low:
                    r = rows_[i]
                    yield [reg, rel, r["id"], r["pos"], r["text"]]

    regs = ("us", "jp") if region == "both" else (region,)
    alive = [hits(reg) for reg in regs]
    out = []
    while alive and len(out) < limit:
        nxt = []
        for g in alive:
            try:
                out.append(next(g))
                nxt.append(g)
            except StopIteration:
                pass
        alive = nxt
    return out[:limit]


def prefer_rel(rel):
    """The PSP extract a PSX table's rows most likely come from, for
    breaking an exact tie ('ADV/E0' -> 'pack/E0', 'TALK/SLIME' -> ...)."""
    name = rel.split("/")[-1]
    try:
        return tb().psp_rel(name)
    except Exception:
        return None


def psp_match(text, region, limit, prefer):
    """Ranked PSP matches for a row's text, with the import form of each.

    The search itself is match.py's; this only hands it the extracts the
    server already holds and adds the converted draft + its warnings.
    """
    m = psp_glyphs()
    import match as _m
    files = {"us": psp_files("us")["files"], "jp": psp_files("jp")["files"]}
    codes = {"us": psp_codes("us"), "jp": psp_codes("jp")}
    res = _m.match(text, files, codes, m, region=region, limit=limit,
                   prefer_rel=prefer)
    for h in res["hits"]:
        if h["region"] == "us":
            h["import_text"], h["flags"] = _m.convert_us(h["text"], m)
        else:
            h["import_text"], h["flags"] = _m.convert_jp(h["text"])
    res["text"] = text
    res["prefer"] = prefer
    return res


def psp_unit(region, rel, rid):
    idx = psp_files(region)
    rows_ = idx["files"].get(rel)
    if not rows_:
        return None
    i = next((k for k, r in enumerate(rows_) if str(r["id"]) == str(rid)), None)
    if i is None:
        return None
    cur = rows_[i]

    def unit(r):
        return [r["id"], r["pos"], r["text"]]

    out = {"region": region, "rel": rel, "id": cur["id"], "pos": cur["pos"],
           "text": cur["text"], "prev": [unit(r) for r in rows_[max(0, i - 2):i]],
           "next": [unit(r) for r in rows_[i + 1:i + 3]], "twin": None}
    if align_map().get(rel):
        other = "jp" if region == "us" else "us"
        tr = psp_files(other)["files"][rel][i]
        out["twin"] = {"region": other, "id": tr["id"], "pos": tr["pos"],
                       "text": tr["text"]}
    return out


# ---------------------------------------------------------------------------
# the human's save
# ---------------------------------------------------------------------------

def save_manual(rel, pos, en):
    """Write the human's draft to translation/manual/<rel>.tsv.

    This is the editor's Save button, not a porter: the human's keystroke is
    the one writer allowed to fill or change manual's `en`, so it calls
    toolbelt's table writer directly instead of toolbelt.write_manual (that
    gate exists to keep scripts out of a human's wording). Every other row,
    its psp and its note stay exactly as they are; toolbelt._write applies
    the same canonical column set and end-code rule every writer uses.
    """
    tb_ = tb()
    rows_ = [dict(r) for r in tb_._raw_manual(rel, optional=True)]
    row = next((r for r in rows_ if r["pos"] == pos), None)
    if row is None:
        gen = next((r for r in tb_._raw_generated(rel, optional=True)
                    if r["pos"] == pos), None)
        used = {r["id"] for r in rows_ if str(r["id"]).isdigit()}
        n = 0
        while str(n) in used:
            n += 1
        row = {"id": str(n), "pos": pos, "psp": (gen or {}).get("psp", ""),
               "en": "", "note": ""}
        rows_.append(row)
    validate_choice(rel, pos, en)
    row["en"] = en
    tb_._write(tb_.man_path(rel), tb_.MAN_COLS, rows_)
    return row_detail(rel, pos)


# ---------------------------------------------------------------------------
# the row's PSP errata (translation/psp_errata.tsv): read, previewed, saved
# ---------------------------------------------------------------------------

def errata_target(psp):
    """(rel, pos) of the one PSP-US line a row's `psp` pointer names - the
    line its errata rows correct - or None (no pointer, a merged row)."""
    tb_ = tb()
    parts = [x.strip() for x in (psp or "").split(",") if x.strip()]
    if len(parts) != 1 or ":" not in parts[0]:
        return None
    name, loc = parts[0].split(":", 1)
    rel = tb_.psp_rel(name)
    rows_ = tb_.read_extracted("psp_us", rel, optional=True, errata=False)
    if re.fullmatch(r"pack/E\d", rel):
        hit = next((r for r in rows_ if str(r["id"]) == loc), None)
    elif rel.startswith("pack/talk/") and loc.isdigit():
        hit = next((r for r in rows_ if r.get("entry") == "1"
                    and r["box"] == loc), None)
    else:
        want = tb_.psp_loc(loc)
        hit = next((r for r in rows_ if tb_.psp_loc(r["pos"]) == want), None)
    return (rel, hit["pos"], hit["text"]) if hit else None


def _errata_line_target(psp):
    """errata_target for an errata row's own pointer (cached per file)."""
    if psp not in _errata_targets:
        t = errata_target(psp)
        _errata_targets[psp] = t[:2] if t else None
    return _errata_targets[psp]


_errata_targets = {}


def errata_for(psp):
    """{target, raw, rows} of the errata naming the row's PSP line: `raw` is
    the line as the PSP has it, `rows` [{psp, find, replace, note}] in file
    order (the order they apply)."""
    t = errata_target(psp)
    if not t:
        return None
    rel, pos, raw = t
    rows_ = [r for r in read_errata()
             if _errata_line_target(r["psp"]) == (rel, pos)]
    return {"rel": rel, "pos": pos, "raw": raw, "rows": rows_}


def read_errata():
    with open(tb().ERRATA, encoding="utf-8") as f:
        lines = f.read().split("\n")
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[1:] if l.strip()]


def errata_apply(raw, rows_):
    """The PSP line with `rows_` applied in order, as the readers apply them:
    each `find` must be there exactly once when its turn comes."""
    text = raw
    for i, r in enumerate(rows_):
        if not r["find"]:
            raise ValueError(f"errata {i + 1}: find is empty")
        if text.count(r["find"]) != 1:
            raise ValueError(f"errata {i + 1}: {r['find']!r} is not in the "
                             f"PSP line exactly once")
        text = text.replace(r["find"], r["replace"])
    return text


def _loose(s):
    """A regex for s that ignores where the lines break: the porter rewraps
    the PSP line, so a space, a line move or a speaker-label break of the
    PSP side may be any of them in the row."""
    out = []
    for tok in re.split(r"(\s+|<FF03>|<FFF6>)", s):
        if not tok:
            continue
        out.append(r"(?:\s|<FF03>|<FFF6>)+" if re.fullmatch(r"\s+|<FF03>|<FFF6>", tok)
                   else re.escape(tok))
    return "".join(out)


def errata_preview(rel, pos, rows_):
    """What the row would be with `rows_` as its PSP line's errata: the
    stored English with the old errata taken back and the new ones put in
    (break-insensitive), each box laid out again by the porter's flow. The
    port writes the real row; this is its picture, not its write."""
    d = row_detail(rel, pos)
    gen = d["gen"]
    info = errata_for(gen["psp"] if gen else "")
    if not info:
        raise ValueError("this row names no single PSP-US line")
    for r in rows_:
        if any(c in r["find"] + r["replace"] + r.get("note", "")
               for c in "\t\n\r"):
            raise ValueError("no tab or newline in an errata field")
    applied = errata_apply(info["raw"], rows_)
    en = gen["en"]
    missed = []
    edits = [(r["replace"], r["find"]) for r in reversed(info["rows"])]
    edits += [(r["find"], r["replace"]) for r in rows_]
    for find, replace in edits:
        if find == replace:
            continue
        pat = _loose(find)
        if not re.search(pat, en):
            missed.append(find)
            continue
        en = re.sub(pat, lambda _m: replace, en, count=1)
    return {"applied": applied, "en": reflow(rel, en, gen["en"]), "missed": missed,
            "manual": d["state"] == "manual"}


_BOX_SPLIT = re.compile(r"((?:<FF02>)?<FF04>|(?:<FFFB>)?<FFF7>)")
_TAIL = re.compile(r"(?:<FF02>|<FF01>|<FFF5>|<FFEF>|<FFFB>|<FFF1>|<FFFD>.)*$")


def reflow(rel, en, before):
    """Each box of en whose words differ from `before`'s laid out again by
    vwf_wrap's flow (the porter's), its own codes kept; the other boxes and a
    choice table stay as stored. A box the edit makes too long for the
    flow's box is the port's to page."""
    vw, measure = inj("vwf_wrap"), measure_for(rel)
    parts = _BOX_SPLIT.split(en)
    old = _BOX_SPLIT.split(before)
    words_of = lambda b: re.sub(r"<FF03>|<FFF6>", " ", b).split()
    for i in range(0, len(parts), 2):
        box = parts[i]
        if "<FF0E>" in box or (i < len(old) and words_of(old[i]) == words_of(box)):
            continue
        tail = _TAIL.search(box).group(0)
        body = box[:len(box) - len(tail)]
        brk = "<FFF6>" if "<FFF6>" in body or rel.startswith(("BTLP", "TALK")) else "<FF03>"
        words = re.sub(r"<FF03>|<FFF6>", " ", body).split()
        if len(words) < 2:
            continue
        ranked = vw.weigh(words, measure=measure)
        if ranked:
            parts[i] = brk.join(ranked[0][1]) + tail
    return "".join(parts)


def add_phrase(text, note=""):
    """Append a phrase to translation/phrases.tsv: words the flow reads as
    one thing, so a break inside them costs what a name split does
    (docs/TEXT_LAYOUT_SPEC.md rule 3). Codes in the selection are word
    gaps. Returns the phrase as written; one already listed is not added
    twice."""
    vw = inj("vwf_wrap")
    phrase = " ".join(re.sub(r"<[^>]+>", " ", text).split())
    note = " ".join(note.split())
    seq = tuple(vw._phrase_word(w) for w in phrase.split())
    if len([w for w in seq if w]) < 2:
        raise ValueError("a phrase is two words or more")
    if seq in vw.phrases():
        return phrase
    path = vw.PHRASES_PATH
    fresh = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        if fresh:
            f.write("phrase\tnote\n")
        elif not open(path, "rb").read().endswith(b"\n"):
            f.write("\n")
        f.write(f"{phrase}\t{note}\n")
    return phrase


def save_errata(rel, pos, rows_):
    """Replace the errata of the row's PSP line with `rows_` in
    translation/psp_errata.tsv (in place of the old ones, else at the end);
    every other errata row stays exactly as it is."""
    d = row_detail(rel, pos)
    gen = d["gen"]
    info = errata_for(gen["psp"] if gen else "")
    if not info:
        raise ValueError("this row names no single PSP-US line")
    errata_apply(info["raw"], rows_)
    tb_ = tb()
    target = (info["rel"], info["pos"])
    if info["rows"]:
        spell = info["rows"][0]["psp"]
    elif re.fullmatch(r"pack/E\d", info["rel"]):
        spell = gen["psp"]
    else:
        spell = f"{tb_.psp_name(info['rel'])}:{info['pos']}"
    with open(tb_.ERRATA, encoding="utf-8") as f:
        lines = f.read().rstrip("\n").split("\n")
    new = ["\t".join((spell, r["find"], r["replace"], r.get("note", "")))
           for r in rows_]
    out, placed = [lines[0]], False
    for l in lines[1:]:
        psp = l.split("\t", 1)[0]
        if l.strip() and _errata_line_target(psp) == target:
            if not placed:
                out += new
                placed = True
            continue
        out.append(l)
    if not placed:
        out += new
    with open(tb_.ERRATA, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    # the readers cache the corrected lines
    for cache in ("_PSP_INDEX", "_EXTRACT_CACHE"):
        getattr(tb_, cache).clear()
    for k in [k for k in tb_._ERRATA_CACHE if k not in ("table", "resolved")]:
        del tb_._ERRATA_CACHE[k]
    return errata_for(gen["psp"])


def inj(name):
    """A tool module by name (the porter's own code; src/toolpath.py)."""
    tb()
    return importlib.import_module(name)


def cc():
    """close_calls (src/porting): the page weighing the
    port writes build/close_calls.tsv with - the open row is weighed with the
    same code."""
    tb()
    return importlib.import_module("close_calls")


def measure_for(rel):
    return cc().measure_for(rel)


def flow_text(text):
    """Typed text (no row) laid out by the porter's flow: a newline is a
    break you asked for, a blank line starts a new box."""
    vw = inj("vwf_wrap")
    items = []
    for bi, box in enumerate(t for t in text.replace("\r", "").split("\n\n")):
        if not box.strip():
            continue
        if items:
            items.append(("b", "<FF04>"))
        for li, line in enumerate(box.split("\n")):
            if li:
                items.append(("b", "<FF03>"))
            items += [("w", w) for w in line.split(" ") if w]
    return "".join(v for _k, v in vw.flow_lines(items))


_renders = {}


def render(rel, text, flow=False, weigh=True, edition=None):
    """The page model the viewer draws (see /render), cached per input: the
    page asks again for every keystroke and for the HEAD column. `weigh`
    adds the close calls (the main box only). `edition` is the font edition
    to lay the text out and draw it in (a row carrying every edition's
    layout is read as that one's; docs/TEXT_LAYOUT_SPEC.md "Font editions")."""
    vw = inj("vwf_wrap")
    edition = edition or toolpath.FONT_EDITION
    if edition not in toolpath.FONT_EDITIONS:
        raise ValueError(f'edition is one of {", ".join(toolpath.FONT_EDITIONS)}')
    key = (rel, text, flow, weigh, edition, row_tables()[1], vw.phrases_stamp())
    if key not in _renders:
        if len(_renders) > 256:
            _renders.clear()
        with vw.measured_as(edition):
            _renders[key] = dict(_render(rel, vw.edition_text(text, edition), flow, weigh),
                                 edition=edition)
    return _renders[key]


def _render(rel, text, flow, weigh):
    shape = importlib.import_module("textshape")
    vr = inj("vwf_render")
    measure = measure_for(rel)
    en = flow_text(text) if flow else text
    # A BOX, NOT A PAGE: a wait followed by a line move (<FF02><FF03>, battle
    # <FF02><FFF6>) scrolls the SAME box to its next line, so the pages
    # textshape reads (a wait ends one for the shape findings) are drawn
    # together until a real box move.
    boxes = []
    for k, chunk in enumerate(re.split(r"<FF02>(?=<FF03>|<FFF6>)", en)):
        pages = shape.pages(chunk)
        if k and pages and boxes:
            boxes[-1].append(pages.pop(0))
        boxes += [[p] for p in pages]
    out = []
    for box in boxes:
        lines, planes, missing, found, weighs = [], bytearray(), [], [], []
        for page in box:
            for stored in page:
                phys, lost = vr.render_line(stored, measure)
                missing += lost
                lines.append({"text": stored, "width": measure(stored),
                              "engine_wraps": len(phys) - 1})
                for ln in phys:
                    for row in ln.px:
                        planes += bytes(row)
            found += shape.findings_for(page)[1]
            weighs.append(cc().weigh_page(page, measure)
                          if weigh and "<FF0E>" not in en else None)
        out.append({"lines": lines, "h": len(planes) // vr.BOX_PX // 16,
                    "weighs": weighs,
                    "planes": base64.b64encode(bytes(planes)).decode(),
                    "findings": found, "missing": sorted(set(missing))})
    return {"en": en, "pages": out, "box": vr.BOX_PX}


_git = {}


def git(*args):
    return subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True,
                          check=False).stdout


def shipped_at(ref):
    """{(rel, pos): en} of what a git ref ships (manual's en wins), cached
    per commit."""
    sha = git("rev-parse", "--verify", "-q", ref).decode().strip()
    if not sha:
        raise ValueError(f"no such git ref: {ref}")
    if _git.get("sha") == sha:
        return _git["rows"]
    out = {}
    for tree in ("generated", "manual"):
        names = git("ls-tree", "-r", "--name-only", sha, f"translation/{tree}").decode().split("\n")
        for name in names:
            if not name.endswith(".tsv"):
                continue
            body = git("show", f"{sha}:{name}").decode("utf-8", "replace")
            head = body.split("\n", 1)[0].rstrip("\r").split("\t")
            if "pos" not in head or "en" not in head:
                continue                    # a source table (fmv/, terms.tsv)
            rel = name[len(f"translation/{tree}/"):-4]
            for r in csv.DictReader(body.splitlines(), delimiter="\t",
                                    quoting=csv.QUOTE_NONE):
                en = r.get("en") or ""
                if tree == "generated" or en.strip():
                    out[(rel, r.get("pos") or "")] = en
    _git.update(sha=sha, rows=out)
    return out


def changed(ref):
    """[rel, pos] of every row whose shipped English differs from ref's."""
    old = shipped_at(ref)
    hit = []
    for r in rows():
        rel, pos, state = r[0], r[2], r[4]
        now = r[3] if state in ("manual", "generated") else ""
        if old.get((rel, pos), "") != now:
            hit.append([rel, pos])
    return hit


def close_rows():
    """[rel, pos, margin] of build/close_calls.tsv's close calls (the port
    writes it; run the port to refresh it)."""
    path = cc().OUT
    if not os.path.exists(path):
        return None
    out = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if r["close"] == "1":
                key = (r["rel"], r["pos"])
                out[key] = min(out.get(key, 99.0), float(r["margin"]))
    return [[rel, pos, m] for (rel, pos), m in out.items()]


# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query)
        one = lambda k, d="": (q.get(k, [d])[0] or d)
        try:
            if url.path in ("/", "/index.html"):
                self.send(200, "text/html; charset=utf-8",
                          open(PAGE, "rb").read())
            elif url.path == "/app.js":
                self.send(200, "text/javascript; charset=utf-8",
                          open(os.path.join(HERE, "app.js"), "rb").read())
            elif url.path == "/rows":
                needle = one("q").lower()
                limit = int(one("limit", "300") or 300)
                fam = one("fam", "ALL") or "ALL"
                hit = [r for r in rows()
                       if (fam == "ALL" or r[0].startswith(fam))
                       and (not needle or needle in r[3].lower()
                            or needle in r[0].lower()
                            or needle in r[5].lower())]
                self.send(200, "application/json",
                          json.dumps(hit[:limit], ensure_ascii=False).encode())
            elif url.path == "/row":
                rel, pos = one("rel").strip(), one("pos").strip()
                if not valid_rel(rel):
                    self.send(404, "text/plain", b"no such table")
                else:
                    self.send(200, "application/json",
                              json.dumps(row_detail(rel, pos),
                                         ensure_ascii=False).encode())
            elif url.path == "/psp":
                region = one("region", "both")
                if region not in ("us", "jp", "both"):
                    region = "both"
                limit = min(2000, int(one("limit", "300") or 300))
                self.send(200, "application/json",
                          json.dumps(psp_search(one("q"), region, limit),
                                     ensure_ascii=False).encode())
            elif url.path == "/match":
                # "find psp": the row's own text (or the draft the page
                # sends) against both extracts, best first, each hit with
                # the PSX draft it would import as.
                try:
                    rel = one("rel").strip()
                    pos = one("pos").strip()
                    text = one("text")
                    limit = min(50, int(one("limit", "12") or 12))
                    region = one("region", "auto")
                    if region not in ("us", "jp"):
                        region = None
                    if not text.strip() and rel and pos:
                        if not valid_rel(rel):
                            raise ValueError("no such table")
                        text = row_detail(rel, pos)["initial"]
                    if not text.strip():
                        raise ValueError("nothing to search for")
                    prefer = prefer_rel(rel) if rel else None
                    self.send(200, "application/json",
                              json.dumps(psp_match(text, region, limit, prefer),
                                         ensure_ascii=False).encode())
                except ValueError as exc:
                    self.send(400, "application/json",
                              json.dumps({"error": str(exc)}).encode())
            elif url.path == "/psp/unit":
                region = one("region", "us")
                if region not in ("us", "jp"):
                    region = "us"
                unit = psp_unit(region, one("rel").strip(), one("id").strip())
                if unit is None:
                    self.send(404, "text/plain", b"no such PSP unit")
                else:
                    self.send(200, "application/json",
                              json.dumps(unit, ensure_ascii=False).encode())
            elif url.path == "/font":
                edition = (q.get("edition") or [toolpath.FONT_EDITION])[0]
                if edition not in toolpath.FONT_EDITIONS:
                    edition = toolpath.FONT_EDITION
                self.send(200, "application/json", font_payload(edition))
            elif url.path == "/changed":
                try:
                    hit = changed(one("ref", "HEAD"))
                    self.send(200, "application/json", json.dumps(hit).encode())
                except ValueError as exc:
                    self.send(400, "application/json",
                              json.dumps({"error": str(exc)}).encode())
            elif url.path == "/close":
                got = close_rows()
                self.send(200, "application/json", json.dumps(
                    {"rows": got or [], "missing": got is None}).encode())
            elif url.path == "/count":
                self.send(200, "application/json",
                          json.dumps({"rows": len(rows())}).encode())
            else:
                self.send(404, "text/plain", b"no")
        except Exception as exc:                  # never kill the page silently
            self.send(500, "text/plain", str(exc).encode())

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/render":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8"))
                self.send(200, "application/json", json.dumps(
                    render(str(body.get("rel") or ""), str(body.get("text") or ""),
                           bool(body.get("flow")), body.get("weigh", True) is not False,
                           body.get("edition") or None),
                    ensure_ascii=False).encode())
            except Exception as exc:
                self.send(400, "application/json",
                          json.dumps({"error": str(exc)}).encode())
            return
        if url.path == "/reload":
            try:
                n = reload_all()
                self.send(200, "application/json",
                          json.dumps({"modules": n, "rows": len(rows())}).encode())
            except Exception as exc:
                self.send(500, "application/json",
                          json.dumps({"error": str(exc)}).encode())
            return
        if url.path in ("/errata", "/errata/preview"):
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n <= 0 or n > 1_000_000:
                    raise ValueError("bad Content-Length")
                body = json.loads(self.rfile.read(n).decode("utf-8"))
                rel = str(body.get("rel") or "").strip()
                pos = str(body.get("pos") or "").strip()
                if not valid_rel(rel):
                    raise ValueError("no such table")
                rows_ = [{"find": str(r.get("find") or ""),
                          "replace": str(r.get("replace") or ""),
                          "note": str(r.get("note") or "")}
                         for r in body.get("rows") or []]
                if url.path == "/errata":
                    out = {"errata": save_errata(rel, pos, rows_)}
                else:
                    out = errata_preview(rel, pos, rows_)
                self.send(200, "application/json",
                          json.dumps(out, ensure_ascii=False).encode())
            except (ValueError, SystemExit) as exc:
                self.send(400, "application/json",
                          json.dumps({"error": str(exc)}).encode())
            return
        if url.path == "/phrases":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n <= 0 or n > 10_000:
                    raise ValueError("bad Content-Length")
                body = json.loads(self.rfile.read(n).decode("utf-8"))
                phrase = add_phrase(str(body.get("phrase") or ""), str(body.get("note") or ""))
                self.send(200, "application/json",
                          json.dumps({"phrase": phrase}, ensure_ascii=False).encode())
            except ValueError as exc:
                self.send(400, "application/json",
                          json.dumps({"error": str(exc)}).encode())
            return
        if url.path != "/save":
            self.send(404, "text/plain", b"no")
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 1_000_000:
                raise ValueError("bad Content-Length")
            body = json.loads(self.rfile.read(n).decode("utf-8"))
            rel = str(body.get("rel") or "").strip()
            pos = str(body.get("pos") or "").strip()
            en = str(body.get("en") or "")
            if not valid_rel(rel):
                raise ValueError("no such table")
            if not pos:
                raise ValueError("no pos")
            if any(c in en for c in "\n\r\t"):
                raise ValueError("one row is one TSV line: no newline or tab; "
                                 "use <FF03> (dialogue) or <FFF6> (battle) "
                                 "for a line break")
            if not en.strip():
                raise ValueError("the draft is empty")
            detail = row_detail(rel, pos)
            if detail["state"] in ("queue", "empty") and en == detail["ja"]:
                raise ValueError("still the Japanese original - translate it "
                                 "before saving")
            self.send(200, "application/json",
                      json.dumps(save_manual(rel, pos, en),
                                 ensure_ascii=False).encode())
        except SystemExit as exc:                 # toolbelt.fail()
            self.send(400, "application/json",
                      json.dumps({"error": str(exc)}).encode())
        except Exception as exc:
            self.send(400, "application/json",
                      json.dumps({"error": str(exc)}).encode())

    def send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"textbox visualiser: http://127.0.0.1:{port}/  "
          f"({len(rows())} rows from translation/generated + translation/manual)",
          flush=True)
    srv.serve_forever()
