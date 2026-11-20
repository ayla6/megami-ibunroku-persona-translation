"""Deterministic greedy MES encoder with a decoder round-trip gate."""
import mescodec


def encode(blob: bytes) -> bytes:
    """Greedy encoder for the MES token stream (mescodec.decode round-trips it).

    Hash-chained back-references (distance <= 0x400, length <= 33; the 33/1
    combination would spell the 7F FF end marker and is clamped), zero runs,
    same-byte fills, 00,x pairs and literal runs; ends with 7F FF.
    """
    n = len(blob)
    out = bytearray()
    prev = [-1] * (n + 1)              # last position with the same 3 bytes
    last3 = {}
    for i in range(n - 2):
        k = bytes(blob[i:i + 3])
        prev[i] = last3.get(k, -1)
        last3[k] = i
    lit = bytearray()

    def flush() -> None:
        while lit:
            c = min(32, len(lit))
            out.append(0x80 | (c - 1))
            out.extend(lit[:c])
            del lit[:c]

    i = 0
    while i < n:
        z = 0
        while z < 0xFF + 0x20 and blob[i + z:i + z + 1] == b'\x00':
            z += 1
        r = 1
        while r < 33 and blob[i + r:i + r + 1] == blob[i:i + 1]:
            r += 1
        emit = None
        if z >= 2:
            emit = ('Z', z)
        elif r >= 3:
            emit = ('R', r)
        else:
            # Zero/fill tokens always win above, so matching them could not
            # affect the chosen output. Search only when a copy can win.
            best_len, best_dist = 0, 0
            if i + 2 < n - 2:
                j = prev[i]
                hops = 0
                cap = min(33, n - i)
                while 0 <= j and i - j <= 0x400 and hops < 16:
                    hops += 1
                    l = 3
                    while l < cap and blob[j + l] == blob[i + l]:
                        l += 1
                    if l > best_len:
                        best_len, best_dist = l, i - j
                    j = prev[j]
            if best_len == 33 and best_dist == 1:
                best_len = 32          # (33, 1) would encode as 7F FF
            if best_len >= 4:
                emit = ('B', best_len, best_dist)
            elif z == 1 and i + 3 < n:
                k = 0
                while k < 32 and i + 2 * k + 1 < n and blob[i + 2 * k:i + 2 * k + 1] == b'\x00':
                    k += 1
                if k >= 2:
                    emit = ('P', k)
        if emit is None:
            lit.append(blob[i])
            i += 1
            if len(lit) == 32:
                flush()
            continue
        flush()
        kind = emit[0]
        if kind == 'Z':
            L = emit[1]
            if L < 32:
                out.append(0xE0 | (L - 1))
            else:
                out += bytes((0xFF, L - 0x20))
            i += L
        elif kind == 'R':
            out += bytes((0xC0 | (emit[1] - 2), blob[i]))
            i += emit[1]
        elif kind == 'P':
            k = emit[1]
            out.append(0xA0 | (k - 1))
            out.extend(blob[i + 1:i + 2 * k:2])
            i += 2 * k
        else:
            L, d = emit[1], emit[2]
            f = 0x400 - d
            out.append(((L - 2) << 2) | (f >> 8))
            out.append(f & 0xFF)
            i += L
    flush()
    out += b'\x7f\xff'
    check, _ = mescodec.decode(bytes(out), n)
    if check != bytes(blob):
        raise SystemExit('MES encoder round-trip failed')
    return bytes(out)
