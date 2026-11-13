"""Bounded R3000 integer execution for assembled-code regression tests.

Loads become visible AFTER the following instruction reads its operands.
Branches execute one delay instruction. Unsupported instructions fail closed.
HI/LO results are functional (no cycle timing); GPU and BIOS are not emulated.
"""
MASK = 0xFFFFFFFF
REG = {name: i for i, name in enumerate(
    "zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra".split())}

# The registers a BIOS call may destroy. The real bzero at 0x800412FC returns
# with t0=0xBFC01ACC and t1=t2=0xA0 (observed on the console), and the BIOS is
# under no obligation to preserve any of these. Code that calls the BIOS must
# keep live state in callee-saved registers or memory, never across the call.
BIOS_CALLER_SAVED = ('v0', 'v1', 'a0', 'a1', 'a2', 'a3',
                     't0', 't1', 't2', 't3', 't4', 't5',
                     't6', 't7', 't8', 't9')


def clobber_bios_registers(cpu, pattern=0xDEAD0000):
    """Model the BIOS ABI: every caller-saved register is now garbage."""
    for name in BIOS_CALLER_SAVED:
        cpu.r[REG[name]] = pattern | (REG[name] & 0xFF)


def signed(x):
    return x - 0x100000000 if x & 0x80000000 else x


class CPU:
    def __init__(self):
        # 2 MB of main RAM, then the 1 KB data scratchpad (0x1F800000)
        self.mem = bytearray(0x200000 + 0x400)
        self.r = [0] * 32
        self.hi = self.lo = 0
        self.pc = self.next_pc = 0
        self.pending = None
        self.steps = 0
        self.trace = []
        # Opt-in write ledger: a test can prove the code under test touched
        # only the addresses it owns (and not, say, a walked copy's output).
        self.track_writes = False
        self.writes = []

    def offset(self, address, size=1):
        address &= MASK
        physical = address & 0x1FFFFFFF
        if 0x1F800000 <= physical <= 0x1F800400 - size:
            return 0x200000 + physical - 0x1F800000
        if not 0 <= physical <= 0x200000 - size:
            raise ValueError(f"RAM access {address:08x}+{size} at PC {self.pc:08x}")
        return physical

    def load(self, address, data):
        offset = self.offset(address, len(data))
        self.mem[offset:offset + len(data)] = data

    def read(self, address, size=4, sign=False):
        if address & (size - 1):
            raise ValueError(f"unaligned read {address:08x}/{size}")
        offset = self.offset(address, size)
        return int.from_bytes(self.mem[offset:offset + size], "little", signed=sign) & MASK

    def write(self, address, value, size=4):
        if address & (size - 1):
            raise ValueError(f"unaligned write {address:08x}/{size}")
        offset = self.offset(address, size)
        if self.track_writes:
            self.writes.append((address & MASK, size))
        self.mem[offset:offset + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, "little")

    def fill(self, value):
        """Poison all RAM. A test loads its code/data on top afterwards, so
        anything the code reads without writing is visibly garbage."""
        self.mem[:] = bytes([value]) * len(self.mem)

    def start(self, pc):
        self.pc, self.next_pc, self.pending = pc, pc + 4, None

    def step(self):
        pc = self.pc
        word = self.read(pc)
        op, rs, rt, rd, sh, fn = word >> 26, (word >> 21) & 31, (word >> 16) & 31, (word >> 11) & 31, (word >> 6) & 31, word & 63
        imm = word & 0xFFFF
        simm = imm - 0x10000 if imm & 0x8000 else imm
        a, b = self.r[rs], self.r[rt]
        dest = value = delayed = target = None
        old_pending = self.pending
        if op == 0:
            dest = rd
            if fn == 0: value = b << sh
            elif fn == 2: value = b >> sh
            elif fn == 3: value = signed(b) >> sh
            elif fn == 4: value = b << (a & 31)
            elif fn == 6: value = b >> (a & 31)
            elif fn == 7: value = signed(b) >> (a & 31)
            elif fn in (8, 9):
                target = a
                dest = rd if fn == 9 else None
                value = pc + 8
            elif fn == 16: value = self.hi
            elif fn == 18: value = self.lo
            elif fn in (24, 25):
                product = (signed(a) * signed(b)) if fn == 24 else a * b
                self.hi, self.lo = (product >> 32) & MASK, product & MASK
                dest = None
            elif fn in (26, 27):
                aa, bb = (signed(a), signed(b)) if fn == 26 else (a, b)
                if bb == 0:
                    self.lo = (1 if aa < 0 else MASK) if fn == 26 else MASK
                    self.hi = a
                else:
                    quotient = abs(aa) // abs(bb)
                    if (aa < 0) != (bb < 0): quotient = -quotient
                    self.lo, self.hi = quotient & MASK, (aa - quotient * bb) & MASK
                dest = None
            elif fn in (32, 33): value = a + b
            elif fn in (34, 35): value = a - b
            elif fn == 36: value = a & b
            elif fn == 37: value = a | b
            elif fn == 38: value = a ^ b
            elif fn == 39: value = ~(a | b)
            elif fn == 42: value = int(signed(a) < signed(b))
            elif fn == 43: value = int(a < b)
            else: raise ValueError(f"unsupported SPECIAL {word:08x} at {pc:08x}")
        elif op in (1, 4, 5, 6, 7):
            if op == 1:
                if rt not in (0, 1): raise ValueError("unsupported REGIMM")
                take = signed(a) >= 0 if rt == 1 else signed(a) < 0
            elif op == 4: take = a == b
            elif op == 5: take = a != b
            elif op == 6: take = signed(a) <= 0
            else: take = signed(a) > 0
            if take: target = (pc + 4 + (simm << 2)) & MASK
        elif op in (2, 3):
            target = ((pc + 4) & 0xF0000000) | ((word & 0x3FFFFFF) << 2)
            if op == 3: dest, value = 31, pc + 8
        elif op in (8, 9, 10, 11, 12, 13, 14, 15):
            dest = rt
            if op in (8, 9): value = a + simm
            elif op == 10: value = int(signed(a) < simm)
            elif op == 11: value = int(a < (simm & MASK))
            elif op == 12: value = a & imm
            elif op == 13: value = a | imm
            elif op == 14: value = a ^ imm
            else: value = imm << 16
        elif op in (32, 33, 35, 36, 37):
            size = {32: 1, 33: 2, 35: 4, 36: 1, 37: 2}[op]
            delayed = (rt, self.read((a + simm) & MASK, size, op in (32, 33)))
        elif op in (34, 38):  # little-endian LWL/LWR merge, including paired-load forwarding
            address = (a + simm) & MASK
            shift = (address & 3) * 8
            memory = self.read(address & ~3)
            merged = old_pending[1] if old_pending and old_pending[0] == rt else b
            if op == 34:
                keep = (1 << (24 - shift)) - 1
                merged = (merged & keep) | (memory << (24 - shift))
            else:
                keep = (MASK << (32 - shift)) & MASK
                merged = (merged & keep) | (memory >> shift)
            delayed = (rt, merged & MASK)
        elif op in (42, 46):  # little-endian SWL/SWR preserve neighboring bytes
            address = (a + simm) & MASK
            shift = (address & 3) * 8
            memory = self.read(address & ~3)
            if op == 42:
                mask = (1 << (shift + 8)) - 1
                merged = (memory & ~mask) | (b >> (24 - shift))
            else:
                mask = (MASK << shift) & MASK
                merged = (memory & ~mask) | ((b << shift) & mask)
            self.write(address & ~3, merged)
        elif op in (40, 41, 43):
            self.write((a + simm) & MASK, b, {40: 1, 41: 2, 43: 4}[op])
        else: raise ValueError(f"unsupported {word:08x} at {pc:08x}")
        # Execute using old operands, THEN finish the preceding load. An
        # instruction writing the same register takes precedence over that load.
        if old_pending and old_pending[0]: self.r[old_pending[0]] = old_pending[1]
        if dest: self.r[dest] = value & MASK
        self.r[0] = 0
        self.pending = delayed
        self.pc, self.next_pc = self.next_pc, (self.next_pc + 4) & MASK
        if target is not None: self.next_pc = target
        self.steps += 1
        self.trace.append(pc)
        if len(self.trace) > 16: del self.trace[0]

    def run(self, stop, limit=100000, intercept=None):
        for _ in range(limit):
            if self.pc == stop: return
            if intercept and intercept(self): continue
            self.step()
        raise AssertionError(f"instruction limit at {self.pc:08x}; trace={self.trace}")
