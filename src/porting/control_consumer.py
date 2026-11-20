"""Control-message twins proved by an independently anchored executable consumer.

No positional/table interpolation is emitted: every result needs its own unique
caller, an independently proven callee correspondence, and a bounded monotone
relocated-pointer path to that same independent anchor. Wording is read verbatim.
"""
import collections
import re
import struct
import match_jp
import notice_consumer as notice

SPAN = 19
MAX_PATH = 256
CONTROLS = re.compile(r'<[0-9A-Fa-f]{4}>|\[[0-9A-Fa-f]{4}\]')

def skeleton(text):
    return tuple(token.upper() for token in CONTROLS.findall(text))

def message_key(text, psx=False):
    # Presentation breaks/terminators differ between PSX and PSP; variables do not.
    controls = tuple(c for c in skeleton(text) if c not in ('<FF01>','<FF03>','<FFF6>'))
    return match_jp.norm(text, psx), controls

def pointer_rows(blob, segments, relocations, rows):
    by_position = collections.defaultdict(list)
    for row in rows:
        if row['text'].endswith('<FF01>'):
            by_position[int(row['pos'],16)].append(row)
    out = {}
    lo,hi = segments[1]
    for slot in relocations:
        ptr = lo + struct.unpack_from('<I',blob,slot)[0]
        if ptr < lo or ptr >= hi or ptr & 1:
            continue
        end = next((p for p in range(ptr,min(ptr+1024,hi-1),2)
                    if blob[p:p+2] == b'\xff\x01'),None)
        if end is None:
            continue
        possible = [row for pos in range(ptr-8,ptr+1,2) for row in by_position.get(pos,())]
        if not possible:
            continue
        try:
            text = notice.codec.decode_box(blob[ptr:end+2]).strip()
        except (LookupError,ValueError):
            continue
        possible = [row for row in possible if row['text'].strip() == text]
        if len(possible) == 1:
            out[slot] = (ptr,possible[0])
    return out

def consumers(blob, segments, pointed):
    by_fp = collections.defaultdict(list)
    by_row = collections.defaultdict(list)
    lo,hi = segments[0]
    for at in range(lo,hi-4*SPAN+1,4):
        first,call,load = struct.unpack_from('<III',blob,at)
        base_reg = (first >> 16) & 31
        if (first >> 26 != 15 or (first >> 21) & 31 or not base_reg
                or call >> 26 != 3 or load >> 26 != 35
                or (load >> 21) & 31 != base_reg or (load >> 16) & 31 != 4):
            continue
        slot = segments[1][0] + ((first & 0xffff)<<16) + struct.unpack('<h',struct.pack('<H',load & 0xffff))[0]
        if slot not in pointed:
            continue
        callee = lo + ((call & 0x3ffffff)<<2)
        if not lo <= callee < hi:
            continue
        words = list(struct.unpack_from(f'<{SPAN}I',blob,at))
        # Only the selected address load is normalized; other data operands stay exact.
        words[0] &= 0xffff0000
        words[2] &= 0xffff0000
        for i,word in enumerate(words):
            if word >> 26 in (2,3):
                words[i] = word & 0xfc000000
        site = (at,slot,callee,int(pointed[slot][1]['pos'],16))
        by_fp[tuple(words)].append(site)
        by_row[site[3]].append(site)
    return by_fp,by_row

def anchored_calls(jrows,urows,pairs):
    proposed = []
    for jp,values in pairs.items():
        if len(values) != 1 or len(jrows.get(jp,())) != 1:
            continue
        up = next(iter(values))
        if len(urows.get(up,())) == 1:
            proposed.append((jrows[jp][0],urows[up][0]))
    forward,reverse = collections.defaultdict(set),collections.defaultdict(set)
    for j,u in proposed:
        forward[j[2]].add(u[2]); reverse[u[2]].add(j[2])
    return [(j,u) for j,u in proposed if forward[j[2]] == {u[2]} and reverse[u[2]] == {j[2]}]

def pointer_path(jsite,usite,janchor,uanchor,jp,us,pairs):
    delta = jsite[1]-janchor[1]
    if delta != usite[1]-uanchor[1] or not delta or delta % 4 or abs(delta)//4 > MAX_PATH:
        return False
    step = 4 if delta > 0 else -4
    previous_j,previous_u = jp[janchor[1]][0],us[uanchor[1]][0]
    direction = None
    for offset in range(step,delta+step,step):
        js,uslot = janchor[1]+offset,uanchor[1]+offset
        if js not in jp or uslot not in us:
            return False
        jt,jrow = jp[js]; ut,urow = us[uslot]
        if not match_jp.jp_unit(jrow['text']) or not match_jp.us_unit(urow['text']):
            return False
        dj,du = jt-previous_j,ut-previous_u
        if not dj or not du or (dj>0) != (du>0):
            return False
        if direction is None: direction = dj>0
        if (dj>0) != direction or skeleton(jrow['text']) != skeleton(urow['text']):
            return False
        jpos,upos = int(jrow['pos'],16),int(urow['pos'],16)
        if jpos in pairs and pairs[jpos] != {upos}:
            return False
        previous_j,previous_u = jt,ut
    return True

def candidates(messages,jp_blob,us_blob,jp_rows,us_rows,pairs):
    js,jr = notice.elf(jp_blob); us,ur = notice.elf(us_blob)
    jp = pointer_rows(jp_blob,js,jr,jp_rows); up = pointer_rows(us_blob,us,ur,us_rows)
    jf,jby = consumers(jp_blob,js,jp); uf,uby = consumers(us_blob,us,up)
    anchors = anchored_calls(jby,uby,pairs)
    keys = collections.defaultdict(list)
    for row in jp_rows:
        if row['text'].endswith('<FF01>') and match_jp.jp_unit(row['text']):
            keys[message_key(row['text'])].append(row)
    counts = collections.Counter(message_key(text, psx=True) for _idx,text in messages)
    proven = {}
    for fp,sites in jf.items():
        if len(sites) != 1 or len(uf.get(fp,())) != 1:
            continue
        j,u = sites[0],uf[fp][0]
        if len(jby[j[3]]) != 1 or len(uby[u[3]]) != 1:
            continue
        if any(j[2] == a[2] and u[2] == b[2] and pointer_path(j,u,a,b,jp,up,pairs)
               for a,b in anchors):
            proven[j[3]] = up[u[1]][1]
    result = []
    for idx,text in messages:
        key = message_key(text, psx=True)
        if counts[key] == 1 and len(keys.get(key,())) == 1:
            pos = int(keys[key][0]['pos'],16)
            if pos in proven:
                result.append((idx,proven[pos]))
    return result

def derive(messages):
    import tables
    import toolbelt
    return candidates(messages,tables.jp_boot(),tables.us_boot(),
                      toolbelt.read_extracted('psp_jp','EBOOT'),
                      toolbelt.read_extracted('psp_us','EBOOT'),notice.proven_pairs())
