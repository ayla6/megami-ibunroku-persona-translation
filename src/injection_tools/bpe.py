"""Byte-pair packing of VWF message strings (same format as tools/btlevt.py; unpacker btlp/btlevt_unpack.asm).

pack(strings) -> (packed {key: bytes}, pairs [(left, right)])
  strings: {key: bytes} each = English VWF text (88..E9) and control codes (FF xx), ending FF F5 / FF EF.
  Format: FF xx = code copied as is (the FF F5 / FF EF end stops the unpacker), 88..E9 = a character,
  00 xx = the literal byte xx (a byte outside the character range: the
  game's two-byte glyph form, 80|hi,lo - '＞' is 87 26), 01..87 / EA..FE =
  pair code k (index into `pairs`, in CODES order); a pair's two bytes may
  be pair codes again.
unpack(packed, pairs) mirrors the unpacker (used by the build to verify every string).
"""
import collections
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'extraction_tools', 'psp'))
from codec import E_PARAM_UNITS  # noqa: E402

CODES = list(range(0x01, 0x88)) + list(range(0xEA, 0xFF))
ESCAPE = 0x00


def _runs(b):
    out, i = [], 0
    while i < len(b):
        if b[i] == 0xFF:
            c = b[i + 1]
            # a code's parameter bytes travel WITH it: <FF05><1000> is one
            # pause, and dropping the params would drop them from the
            # packed string as well
            n = 2 * E_PARAM_UNITS.get(c, 0)
            out.append((False, [b[i], b[i + 1]] + list(b[i + 2:i + 2 + n])))
            i += 2 + n
        else:
            # a byte outside the character range is not a character of its
            # own: it is the game's two-byte glyph form (80|hi,lo - '＞' is
            # 87 26) and it is ESCAPED, so the packed stream can carry any
            # byte a string holds and never mistake a glyph for a pair code.
            # It is ONE atom: a pair code must never split the escape from
            # its byte, so an atom takes no part in pairing at all.
            sy = ([b[i]] if 0x88 <= b[i] <= 0xE9
                  else [(ESCAPE, b[i])])
            if out and out[-1][0]:
                out[-1][1].extend(sy)
            else:
                out.append((True, sy))
            i += 1
    return out


def pack(strings, max_pairs=len(CODES), min_count=3):
    seqs = {k: _runs(b) for k, b in strings.items()}
    pairs = []

    def atom(s):
        return isinstance(s, tuple)         # an escaped byte: never paired

    while len(pairs) < max_pairs:
        cnt = collections.Counter()
        for rs in seqs.values():
            for txt, sy in rs:
                if txt:
                    for k in range(len(sy) - 1):
                        if atom(sy[k]) or atom(sy[k + 1]):
                            continue        # a pair code must never split
                        cnt[(sy[k], sy[k + 1])] += 1    # an escape from its byte
        if not cnt:
            break
        (x, y), n = cnt.most_common(1)[0]
        if n < min_count:
            break
        code = 0x100 + len(pairs)
        pairs.append((x, y))
        for rs in seqs.values():
            for txt, sy in rs:
                if txt:
                    k = 0
                    while k < len(sy) - 1:
                        if sy[k] == x and sy[k + 1] == y:
                            sy[k:k + 2] = [code]
                        k += 1

    def byte(sym):
        return CODES[sym - 0x100] if sym >= 0x100 else sym

    def sym_bytes(sym):
        return bytes(sym) if atom(sym) else bytes([byte(sym)])
    packed = {k: b''.join(sym_bytes(v) for txt, sy in rs for v in sy)
              for k, rs in seqs.items()}
    real = [(byte(x), byte(y)) for x, y in pairs]
    for k in packed:
        assert unpack(packed[k], real) == strings[k], f'bpe: round trip failed for {k}'
    return packed, real


def unpack(b, pairs):
    ix = {c: k for k, c in enumerate(CODES)}
    out, i = [], 0
    while True:
        c = b[i]
        i += 1
        if c == 0xFF:
            code = b[i]
            out += [c, code]
            i += 1
            for _ in range(2 * E_PARAM_UNITS.get(code, 0)):
                out.append(b[i]); i += 1
            if code in (0xF5, 0xEF):
                return bytes(out)
            continue
        if c == ESCAPE:
            out.append(b[i])            # the escaped byte, verbatim
            i += 1
            continue
        st = [c]
        while st:
            x = st.pop()
            if x == ESCAPE:
                out.append(st.pop())       # the escaped byte, verbatim
            elif x in ix:
                assert ix[x] < len(pairs), f'bpe: byte {x:#x} is a pair code with no pair'
                l, r = pairs[ix[x]]
                st += [r, l]
            else:
                out.append(x)
