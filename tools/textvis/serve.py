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
  POST /save {rel,pos,en}     the human's manual override (Ctrl+S in the page);
                              a choice row is laid out first, so the save
                              cannot write a grid the build would refuse
  GET  /psp?q=&region=&limit= search the PSP-US and PSP-JP extracts
  GET  /psp/unit?region=&rel=&id=  one PSP unit, its neighbours, its twin
  GET  /font                  the build's VWF font + the retail FONT.BIN and
                              its glyph map (the missing-character fallback)
  GET  /count                 how many rows the tables hold
"""
import base64
import glob
import importlib
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
GEN = os.path.join(ROOT, "translation", "generated")
MAN = os.path.join(ROOT, "translation", "manual")
PAGE = os.path.join(HERE, "index.html")
FONT_DIR = os.path.join(ROOT, "src", "asm", "font")
# THE RETAIL JAPANESE FONT: the textbox's own 16x16 1-bpp FONT.BIN and the
# glyph map that names each slot. The page uses it for every character the
# English VWF font has no cell for.
ORIG_FONT = os.path.join(ROOT, "data", "psx", "FONT.BIN")
FONT_MAP = os.path.join(ROOT, "src", "injection_tools", "font_map.tsv")

_font = {"stamp": None, "json": None}
_orig = {"stamp": None, "data": None}
_cache = {"stamp": None, "rows": []}
_psp = {}
_align = {"key": None, "map": {}}
_choices = {"stamp": None, "map": {}}


def tb():
    """toolbelt, imported once: it is the only reader/writer of the tables."""
    if "toolbelt" not in globals():
        sys.path.insert(0, os.path.join(ROOT, "src", "injection_tools"))
        globals()["toolbelt"] = importlib.import_module("toolbelt")
    return globals()["toolbelt"]


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
        gen = {r["pos"]: r for r in tb_.read_generated(rel, optional=True)}
        man = {r["pos"]: r for r in tb_.read_manual(rel, optional=True)}
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
    """The PSP-US wording a row's `psp` names.

    Two spellings: a unit locator ("pack/talk/KEMONO:0xd118", resolved by
    toolbelt.psp_wording) and a FAMILY locator ("E0:149" - the ADV porter's
    own box index, which is the row's id in that extract).
    """
    w = toolbelt.psp_wording(loc)
    if w:
        return w.strip()
    if ":" not in loc:
        return ""
    name, num = loc.split(":", 1)
    try:
        for row in toolbelt.read_extracted("psp_us", toolbelt.psp_rel(name)):
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
    gen = next((r for r in tb_.read_generated(rel, optional=True)
                if r["pos"] == pos), None)
    man = next((r for r in tb_.read_manual(rel, optional=True)
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
    return {"rel": rel, "pos": pos, "ja": ja, "state": state,
            "initial": initial, "gen": slim(tb_, gen),
            "man": slim(tb_, man, with_note=True),
            "choice": choice_grid(rel, pos)}


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
        sys.path.insert(0, os.path.join(ROOT, "src", "injection_tools"))
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
    files = {rel: tb_.read_extracted(key, rel, optional=True)
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
        sys.path.insert(0, os.path.join(ROOT, "src", "extraction_tools", "psp"))
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
    rows_ = [dict(r) for r in tb_.read_manual(rel, optional=True)]
    row = next((r for r in rows_ if r["pos"] == pos), None)
    if row is None:
        gen = next((r for r in tb_.read_generated(rel, optional=True)
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
                # THE FONT COMES FROM THE DISC BUILD, LIVE: the page draws the
                # real 1-bpp glyphs, so it asks for the current vwf_font.bin
                # and vwf_width.bin instead of trusting a copy baked into the
                # page. The retail 16x16 FONT.BIN and its glyph map ride along
                # as the fallback for every character the English font lacks.
                fb = os.path.join(FONT_DIR, "vwf_font.bin")
                wb = os.path.join(FONT_DIR, "vwf_width.bin")
                stamp = [os.path.getmtime(fb), os.path.getsize(fb),
                         os.path.getmtime(wb), os.path.getsize(wb)]
                for p in (ORIG_FONT, FONT_MAP):
                    try:
                        st = os.stat(p)
                        stamp += [st.st_mtime, st.st_size]
                    except OSError:
                        stamp += [0, 0]
                stamp = tuple(stamp)
                if _font["stamp"] != stamp:
                    data = {
                        "font": base64.b64encode(open(fb, "rb").read()).decode(),
                        "widths": base64.b64encode(open(wb, "rb").read()).decode(),
                    }
                    try:
                        ofont, gmap = orig_font()
                        data["orig"] = base64.b64encode(ofont).decode()
                        data["map"] = gmap
                    except OSError:
                        pass                       # no retail font: boxes only
                    _font["json"] = json.dumps(data, ensure_ascii=False).encode()
                    _font["stamp"] = stamp
                self.send(200, "application/json", _font["json"])
            elif url.path == "/count":
                self.send(200, "application/json",
                          json.dumps({"rows": len(rows())}).encode())
            else:
                self.send(404, "text/plain", b"no")
        except Exception as exc:                  # never kill the page silently
            self.send(500, "text/plain", str(exc).encode())

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
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
