"""Find potential indexed runtime RAM users; candidates are not ownership proof.

Usage: python src/injection_tools/runtime_map.py [overlay [base]]
Scans the actual rev-0 instructions for LUI/ADDIU/ADDU/load-or-store sequences,
including scheduled instructions and a separate indexed-address register. It cannot establish array lengths, lifetimes,
indirect users, DMA, VRAM or SPU writes. Review candidates against the decomp
and live execution before adding a range to src/injection_tools/runtime-memory-map.tsv.
"""
import argparse
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / 'data/psx/BTLP.BIN'
BASE = 0x800643C4
MEMORY = {0x20: 'lb', 0x21: 'lh', 0x23: 'lw', 0x24: 'lbu', 0x25: 'lhu',
          0x28: 'sb', 0x29: 'sh', 0x2B: 'sw'}


def signed16(value):
    return value - 0x10000 if value & 0x8000 else value


def writes_register(word, reg):
    """Whether a common R3000 instruction replaces reg; fail closed on unknowns."""
    op, rs, rt, rd, fn = word >> 26, (word >> 21) & 31, (word >> 16) & 31, (word >> 11) & 31, word & 63
    if not word:
        return False
    if op == 0:
        if fn in (0x08, 0x0c, 0x0d, 0x11, 0x13, 0x18, 0x19, 0x1a, 0x1b):
            return False
        return rd == reg
    if op in (1, 2, 4, 5, 6, 7, 0x28, 0x29, 0x2a, 0x2b, 0x2e):
        return False
    if op == 3:
        return reg == 31
    if op in (8, 9, 10, 11, 12, 13, 14, 15, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26):
        return rt == reg
    # Coprocessor and uncommon instructions need explicit analysis.
    return True


def candidates(data, base=BASE):
    """Yield (instruction address, computed base, access, index register).

    A nonzero register holds the base; ADDU may place the indexed result in
    another register. Branches and replacement of tracked registers end the
    respective windows. No control-flow or index-bound proof is implied.
    """
    words = struct.unpack(f'<{len(data) // 4}I', data[:len(data) // 4 * 4])
    for i, lui in enumerate(words):
        if lui >> 26 != 15:
            continue
        reg = (lui >> 16) & 31
        if not reg:
            continue
        for j in range(i + 1, min(i + 5, len(words))):
            w = words[j]
            if (w >> 26 == 9 and (w >> 21) & 31 == reg and
                    (w >> 16) & 31 == reg):
                address = (((lui & 0xffff) << 16) + signed16(w & 0xffff)) & 0xffffffff
                if not 0x80000000 <= address < 0x80200000:
                    break
                for k in range(j + 1, min(j + 25, len(words))):
                    a = words[k]
                    if a >> 26 == 0 and a & 63 == 0x21:
                        rs, rt, dest = (a >> 21) & 31, (a >> 16) & 31, (a >> 11) & 31
                        if reg not in (rs, rt) or rs == rt:
                            if writes_register(a, reg):
                                break
                            continue
                        if not dest:
                            continue
                        index = rt if rs == reg else rs
                        for n in range(k + 1, min(k + 7, len(words))):
                            mem = words[n]
                            op = mem >> 26
                            if op in MEMORY and (mem >> 21) & 31 == dest:
                                yield base + n * 4, (address + signed16(mem & 0xffff)) & 0xffffffff, MEMORY[op], index
                                break
                            if op in (1, 2, 3, 4, 5, 6, 7):
                                break
                            if writes_register(mem, dest):
                                break
                        break
                    if a >> 26 in (1, 2, 3, 4, 5, 6, 7):
                        break
                    if writes_register(a, reg):
                        break
                break
            if w >> 26 in (1, 2, 3, 4, 5, 6, 7):
                break
            if writes_register(w, reg):
                break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('overlay', nargs='?', type=Path, default=DEFAULT)
    parser.add_argument('base', nargs='?', type=lambda x: int(x, 0), default=BASE)
    args = parser.parse_args()
    print('instruction\tbase\taccess\tindex_register')
    for pc, address, access, index in candidates(args.overlay.read_bytes(), args.base):
        print(f'{pc:#010x}\t{address:#010x}\t{access}\t${index}')


if __name__ == '__main__':
    main()
