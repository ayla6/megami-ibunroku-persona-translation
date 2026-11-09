"""Disc-byte verification (the QA evidence step): dist/Persona-TL.bin must
contain exactly the built files, and the built text must decode back to the
canonical translation rows.

  python tools/verify_disc.py [dist/Persona-TL.bin] [--original PATH]
      [--placement PATH] [--side-files DIR]

Level 0: the ISO tree and the game's own file tables are one consistent image,
and no sector changed outside the files, records and tables the builders own.
The baseline is normally the retail disc; a composed release passes the
variant's parent image instead, so each link is checked and the chain ends at
the base translation, which is checked against retail.
Level 1: every built disc file is byte-identical in the image.
Level 2: the text decoded from the DISC bytes equals the merged rows' en
(TALK units+answers, ADV story boxes, dng packs; compared round-trip
normalized and up to the end code - trailing stray bytes are dead data
the rebuild keeps by design). Any mismatch fails loud.

With --placement, the builder's record of every file it wrote (path, extent,
size, SHA-256) replaces the build/ tree walks, so a finished image can be
audited without the tree that produced it - safely in parallel with the
next build. --side-files points at the builder's small report files
(dng_spill.asm, the draft tables); it defaults to build/.
"""
import hashlib
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
import toolbelt          # noqa: E402
import etext             # noqa: E402
import talk as talkt     # noqa: E402
import efile             # noqa: E402
import dngpacks          # noqa: E402
import features          # noqa: E402

SECTOR = 2048
END_RE = re.compile(r'<FF(?:F5|EF)>')
fails = checks = 0


class Disc:
    def __init__(self, path):
        self.f = open(path, 'rb')
        self.f.seek(0, 2)
        self.sectors = self.f.tell() // 2352

    def user(self, lba):
        self.f.seek(lba * 2352)
        sec = self.f.read(2352)
        return sec[24:24 + 2048] if len(sec) == 2352 else sec

    def walk(self, lba, size, prefix=''):
        for path, ext, ext_size, *_rest in self.walk_records(prefix)[0]:
            yield path, ext, ext_size

    def walk_records(self, prefix='', problems=None):
        """Every file record plus the sectors its directory occupies.

        Validates record framing and both-endian duplicates while walking, so
        a corrupt tree cannot loop or point outside the image silently."""
        problems = [] if problems is None else problems
        files, dirs, dir_extents = [], [], []

        def walk(dir_lba, dir_size, where, stack):
            dir_extents.append((dir_lba, dir_size))
            if (dir_lba, dir_size) in stack:
                problems.append(f'directory loop at {where or "/"}')
                return
            stack = stack | {(dir_lba, dir_size)}
            for n in range((dir_size + 2047) // SECTOR):
                sector = dir_lba + n
                if sector >= self.sectors:
                    problems.append(f'directory {where or "/"} sector {sector} '
                                    f'is past the volume ({self.sectors})')
                    return
                dirs.append(sector)
                sec = self.user(sector)
                pos = 0
                while pos < 2048:
                    rec_len = sec[pos]
                    if rec_len == 0:
                        break
                    if rec_len < 34 or pos + rec_len > 2048:
                        problems.append(f'bad record length {rec_len} at '
                                        f'{where or "/"} sector {sector}+{pos}')
                        break
                    ext_lo, = struct.unpack_from('<I', sec, pos + 2)
                    ext_be, = struct.unpack_from('>I', sec, pos + 6)
                    size_lo, = struct.unpack_from('<I', sec, pos + 10)
                    size_be, = struct.unpack_from('>I', sec, pos + 14)
                    flags = sec[pos + 25]
                    name_len = sec[pos + 32]
                    if ext_lo != ext_be or size_lo != size_be:
                        problems.append(f'endian mismatch in record at '
                                        f'{where or "/"} sector {sector}+{pos}')
                    if 33 + name_len > rec_len:
                        problems.append(f'name runs past record at '
                                        f'{where or "/"} sector {sector}+{pos}')
                        break
                    name = sec[pos + 33:pos + 33 + name_len]
                    rec = (sector, pos, rec_len, ext_lo, size_lo, flags, name)
                    if name not in (b'\x00', b'\x01'):
                        try:
                            text = name.decode('ascii').split(';')[0]
                        except UnicodeDecodeError:
                            problems.append(f'non-ASCII name at '
                                            f'{where or "/"} sector {sector}+{pos}')
                            text = '?'
                        if flags & 2:
                            walk(ext_lo, size_lo, where + text + '/', stack)
                        else:
                            files.append((where + text, ext_lo, size_lo, rec))
                    pos += rec_len
                if pos == 0:
                    problems.append(f'empty directory sector {sector}')

        pvd = self.user(16)
        root_lba, = struct.unpack_from('<I', pvd, 156 + 2)
        root_size, = struct.unpack_from('<I', pvd, 156 + 10)
        walk(root_lba, root_size, prefix, frozenset())
        return files, dirs, dir_extents


def global_check(what, want, hay):
    """want must appear verbatim inside hay (the disc file bytes or the
    spill bytes) - the exact byte-level check the builders wrote."""
    global fails, checks
    checks += 1
    if want not in hay:
        fails += 1
        print(f'BACK-CHECK FAIL {what}: {len(want)}B text not found')


def check(what, want, got, *, end=None):
    global fails, checks
    checks += 1
    try:                     # normalize param bytes vs rendered glyphs
        # Compare the bytes the family's writer actually emits. ADV event
        # boxes append FF01 when the row omits it; TALK supplies its own end.
        want = etext.decode(etext.encode(want, end=end))
        got = etext.decode(etext.encode(got, end=None))
    except ValueError:
        pass
    for cut in ('got', 'want'):
        pass
    m = END_RE.search(got)
    if m:
        got = got[:m.end()]  # trailing strays are dead data (kept by rebuild)
    m = END_RE.search(want)
    if m:
        want = want[:m.end()]
    if want != got:
        fails += 1
        print(f'BACK-CHECK FAIL {what}:')
        print(f'  want {want[:90]!r}')
        print(f'  got  {got[:90]!r}')


def translation_rels():
    """Canonical disc-file tables, excluding registered wording inputs.

    Unknown/malformed tables remain candidates and fail canonical reading;
    their schema alone is never a reason to omit a translation from QA.
    """
    support = {os.path.abspath(path) for path in toolbelt.WORDING_TABLES}
    rels = set()
    for base in (toolbelt.GENERATED, toolbelt.MANUAL):
        for dirpath, _dirs, names in os.walk(base):
            for name in names:
                path = os.path.join(dirpath, name)
                if name.endswith('.tsv') and os.path.abspath(path) not in support:
                    rel = os.path.relpath(path, base)[:-4]
                    rels.add(rel.replace(os.sep, '/'))
    return rels


def _sectors(size):
    return (size + SECTOR - 1) // SECTOR


def _read_file(disc, ext, size):
    return b''.join(disc.user(ext + n) for n in range(_sectors(size)))[:size]


def _table_names(name):
    return name.lstrip('\\').split(';')[0].replace('\\', '/').upper()


def read_placement(path):
    """Parse the builder's placement TSV: (path, extent, size, sha256)."""
    rows = []
    with open(path, encoding='utf-8') as source:
        header = source.readline().rstrip('\n').split('\t')
        if header != ['path', 'extent', 'size', 'sha256']:
            raise ValueError(f'{path}: unrecognized placement header')
        for line in source:
            cells = line.rstrip('\n').split('\t')
            rows.append((cells[0], int(cells[1]), int(cells[2]), cells[3]))
    return rows


def audit_structure(disc, original, build, placed=None):
    """The ISO and game tables must describe one consistent image, and the
    patched disc may differ from the baseline only in the files and records
    the builders intentionally changed."""
    global fails, checks
    problems = []
    files, dir_sectors, dir_extents = disc.walk_records(problems=problems)
    orig_files, _orig_dirs, orig_dir_extents = original.walk_records(problems=problems)
    checks += 1
    if problems:
        fails += 1
        print(f'STRUCTURE FAIL: {len(problems)} malformed ISO record(s)')
        for problem in problems[:8]:
            print(f'    {problem}')
        return False
    entries = {path.upper(): (ext, size, rec) for path, ext, size, rec in files}
    orig_entries = {path.upper(): (ext, size, rec)
                    for path, ext, size, rec in orig_files}
    if len(entries) != len(files):
        fails += 1
        print(f'STRUCTURE FAIL: {len(files) - len(entries)} duplicate ISO path(s)')

    pvd = disc.user(16)
    volume, = struct.unpack_from('<I', pvd, 80)
    volume_be, = struct.unpack_from('>I', pvd, 84)
    checks += 1
    if volume != volume_be:
        fails += 1
        print(f'STRUCTURE FAIL: PVD volume is {volume} LE but {volume_be} BE')
    if volume != disc.sectors:
        fails += 1
        print(f'STRUCTURE FAIL: PVD volume {volume} != image length {disc.sectors} sectors')
    if volume > disc.sectors:
        return False

    # The disc builder updates the volume size, but owns no other PVD bytes.
    pvd_before = bytearray(original.user(16))
    pvd_before[80:88] = pvd[80:88]
    checks += 1
    if pvd_before != pvd:
        fails += 1
        print('STRUCTURE FAIL: PVD changed outside the volume size')

    checks += 1
    outside = [(path, ext, size) for path, ext, size, _rec in files
               if size and (ext + _sectors(size) > volume or ext < 16)]
    if outside:
        fails += 1
        print(f'STRUCTURE FAIL: {len(outside)} file extent(s) outside the volume')
        for path, ext, size in outside[:6]:
            print(f'    {path}: {ext}..{ext + _sectors(size)}')

    spans = [(ext, ext + _sectors(size), path) for path, ext, size, _rec in files if size]
    spans += [(lba, lba + _sectors(size), '<directory>') for lba, size in dir_extents]
    spans.sort()
    overlaps = [(a, b) for a, b in zip(spans, spans[1:]) if b[0] < a[1]]
    checks += 1
    if overlaps:
        fails += 1
        print(f'STRUCTURE FAIL: {len(overlaps)} overlapping extent(s)')
        for first, second in overlaps[:6]:
            print(f'    {first[2]} {first[0]}..{first[1]} overlaps '
                  f'{second[2]} {second[0]}..{second[1]}')

    # Directory records may change only their extent and size fields; the
    # directory tree itself (every extent and its length) is structural.
    checks += 1
    changed_records = []
    if sorted(dir_extents) != sorted(orig_dir_extents):
        changed_records.append('directory extents differ from retail')
    for lba in sorted(set(dir_sectors)):
        before = original.user(lba)
        after = disc.user(lba)
        if before == after:
            continue
        masked = bytearray(before)
        pos = 0
        while pos < SECTOR and before[pos]:
            rec_len = before[pos]
            if rec_len < 34 or pos + rec_len > SECTOR:
                break
            masked[pos + 2:pos + 18] = after[pos + 2:pos + 18]
            pos += rec_len
        if masked != after:
            changed_records.append(f'directory sector {lba} changed outside '
                                   f'record extents')
    for path in sorted(set(entries) & set(orig_entries)):
        rec_a, rec_b = orig_entries[path][2], entries[path][2]
        if rec_a[2] != rec_b[2]:
            changed_records.append(f'{path}: record length changed')
            continue
        before = original.user(rec_a[0])[rec_a[1]:rec_a[1] + rec_a[2]]
        after = disc.user(rec_b[0])[rec_b[1]:rec_b[1] + rec_b[2]]
        if before[:2] + before[18:] != after[:2] + after[18:]:
            changed_records.append(f'{path}: name/flags/record changed')
    if changed_records:
        fails += 1
        print(f'STRUCTURE FAIL: {len(changed_records)} directory record(s) changed '
              f'outside extent/size')
        for problem in changed_records[:6]:
            print(f'    {problem}')
    else:
        print(f'structure: {len(entries)} files, {len(dir_extents)} directories, '
              f'{len(spans)} extents, no duplicates or overlaps')

    # the game's own lookup tables must agree with the ISO tree
    checks += 1
    table_problems = []
    try:
        names = [n.decode('ascii') for n in _read_file(
            disc, *entries['FNAME.DAT'][:2]).split(b'\0') if n]
        # ISO file records carry whole-sector lengths, so a table's record
        # may include zero padding past its live entries. The name count
        # defines the table length; FSIZE.DAT itself already speaks sectors.
        count = len(names)
        fsect = _read_file(disc, *entries['FSECT.DAT'][:2])[:4 * count]
        fsize = _read_file(disc, *entries['FSIZE.DAT'][:2])[:4 * count]
        if not names or len(fsect) % 4 or len(fsize) % 4 or \
                len(fsect) != len(fsize) or len(fsect) // 4 != count:
            table_problems.append(f'{len(names)} names, {len(fsect) // 4} FSECT, '
                                  f'{len(fsize) // 4} FSIZE entries')
        seen = set()
        for i, name in enumerate(names):
            key = _table_names(name)
            if key in seen:
                table_problems.append(f'duplicate game name {name!r}')
            seen.add(key)
            if key not in entries:
                table_problems.append(f'{name!r} has no ISO record')
                continue
            lba, = struct.unpack_from('<I', fsect, i * 4)
            size, = struct.unpack_from('<I', fsize, i * 4)
            ext, iso_size, _rec = entries[key]
            if lba != ext or size != _sectors(iso_size) * SECTOR:
                table_problems.append(
                    f'{name!r}: table {lba}/{size}, ISO {ext}/{iso_size}')
        extra = set(entries) - seen
        if extra:
            table_problems.append(f'{len(extra)} ISO file(s) absent from FNAME.DAT')
    except KeyError as error:
        table_problems.append(f'missing table {error}')
    if table_problems:
        fails += 1
        print(f'STRUCTURE FAIL: {len(table_problems)} game-table mismatch(es)')
        for problem in table_problems[:8]:
            print(f'    {problem}')
    else:
        print(f'structure: {len(names)} FNAME/FSECT/FSIZE entries agree with the ISO tree')

    # Nothing outside the intentionally changed sectors may differ from the
    # baseline (retail, or this variant's parent image).
    allowed = {16}
    for lba, size in dir_extents + orig_dir_extents:
        allowed.update(range(lba, lba + _sectors(size)))
    for table in ('FSECT.DAT', 'FSIZE.DAT'):
        for source in (entries, orig_entries):
            if table in source:
                ext, size, _rec = source[table]
                allowed.update(range(ext, ext + _sectors(size)))
    changed_files = 0
    if placed is not None:
        # the builder's own record decides which sectors may differ; level 1
        # separately proves the disc bytes match the record's hashes
        placement_problems = []
        for path, ext, size, _sha in placed:
            entry = entries.get(path)
            if entry is None:
                placement_problems.append(f'{path} is not on the disc')
                continue
            if (entry[0], entry[1]) != (ext, size):
                placement_problems.append(
                    f'{path}: placement {ext}/{size}, ISO {entry[0]}/{entry[1]}')
                continue
            changed_files += 1
            allowed.update(range(ext, ext + _sectors(size)))
            if path in orig_entries:
                orig_ext, orig_size, _rec = orig_entries[path]
                allowed.update(range(orig_ext, orig_ext + _sectors(orig_size)))
        if placement_problems:
            fails += 1
            print(f'STRUCTURE FAIL: {len(placement_problems)} placement record '
                  f'mismatch(es)')
            for problem in placement_problems[:8]:
                print(f'    {problem}')
    else:
        for root, _dirs, names in os.walk(build):
            for name in sorted(names):
                local = os.path.join(root, name)
                rel = os.path.relpath(local, build).replace(os.sep, '/').upper()
                if rel not in entries or rel not in orig_entries:
                    continue
                with open(local, 'rb') as source:
                    data = source.read()
                ext, size, _rec = entries[rel]
                orig_ext, orig_size, _rec = orig_entries[rel]
                if data == _read_file(original, orig_ext, orig_size):
                    continue
                changed_files += 1
                allowed.update(range(ext, ext + _sectors(size)))
                allowed.update(range(orig_ext, orig_ext + _sectors(orig_size)))

    checks += 1
    unexpected = []
    for lba in range(min(original.sectors, disc.sectors)):
        if disc.user(lba) != original.user(lba) and lba not in allowed:
            unexpected.append(lba)
    # The volume may grow past retail. Appended bytes belong either to a
    # relocated file (already allowed) or to the builder's zeroed end padding.
    for lba in range(original.sectors, disc.sectors):
        if lba not in allowed and any(disc.user(lba)):
            unexpected.append(lba)
    if unexpected:
        fails += 1
        print(f'STRUCTURE FAIL: {len(unexpected)} sector(s) changed outside the '
              f'intended files/records')
        for lba in unexpected[:8]:
            print(f'    sector {lba} (0x{lba:x})')
    else:
        print(f'structure: {changed_files} changed file(s); every other sector in '
              f'the {disc.sectors}-sector image matches the baseline')
    return True


def level1(disc, build, entries, read_file, placed=None):
    """Every file the builder wrote must be byte-identical on the disc.

    With a placement record the image is checked against the hashes of the
    exact bytes the builder packed - no build tree involved, so the image
    stays auditable after the tree is gone or rewritten. Without one, the
    current build/ files are the reference."""
    bad = n = 0
    if placed is not None:
        for path, ext, size, sha in placed:
            data = _read_file(disc, ext, size)
            n += 1
            if hashlib.sha256(data).hexdigest() != sha:
                bad += 1
                print(f'MISMATCH {path}: disc bytes differ from the placement record')
        print(f'level 1: {n} placed files on the disc, {bad} byte mismatches')
    else:
        for r, _dirs, files in os.walk(build):
            for f in sorted(files):
                local = os.path.join(r, f)
                rel = os.path.relpath(local, build).replace(os.sep, '/').upper()
                if rel not in entries:
                    continue
                data = open(local, 'rb').read()
                got = read_file(rel)
                n += 1
                # ISO records carry whole-sector lengths; the build file
                # itself is exact. Pad the build bytes with the zero fill the
                # disc writer adds, then compare the recorded extent.
                if data.ljust(len(got), b'\0') != got:
                    bad += 1
                    print(f'MISMATCH {rel}: build {len(data)}B vs disc {len(got)}B')
        print(f'level 1: {n} built files on the disc, {bad} byte mismatches')
    return n, bad


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Verify a patched disc image.')
    parser.add_argument('image', nargs='?', default=os.path.join(ROOT, 'dist', 'Persona-TL.bin'))
    parser.add_argument('--original', default=os.path.join(
        ROOT, 'data', 'discs', 'Megami Ibunroku Persona - Be Your True Mind (Japan)',
        'Megami Ibunroku Persona - Be Your True Mind (Japan).bin'),
        help='baseline image to compare against: the retail disc, or the '
             'parent variant for a composed release image')
    parser.add_argument('--placement', default=None,
                        help='builder placement TSV; replaces the build/ tree walks')
    parser.add_argument('--side-files', default=None,
                        help='directory holding the builder report files '
                             '(dng_spill.asm, draft tables); default: build/')
    parser.add_argument('--no-text', action='store_true',
                        help='stop after the structure and level-1 byte checks; '
                             'the text read-back (levels 2 and 3) is identical for '
                             'every QoL combination, so a release proves it once')
    args = parser.parse_args()
    image = args.image
    build = os.path.join(ROOT, 'build')
    side_files = args.side_files or build
    placed = read_placement(args.placement) if args.placement else None
    disc = Disc(image)
    original = Disc(args.original)
    # Level 0: the ISO tree, the game's own tables and the baseline comparison
    # must all describe the same image before any text is read back.
    if not audit_structure(disc, original, build, placed):
        print('disc-byte verification FAILED: malformed or inconsistent ISO image')
        sys.exit(1)
    pvd = disc.user(16)
    root_lba, = struct.unpack_from('<I', pvd, 156 + 2)
    root_size, = struct.unpack_from('<I', pvd, 156 + 10)
    entries = {p.upper(): (e, s) for p, e, s in disc.walk(root_lba, root_size)}

    def read_file(path):
        ext, size = entries[path]
        return b''.join(disc.user(ext + n) for n in range((size + 2047) // SECTOR))[:size]

    _n, bad = level1(disc, build, entries, read_file, placed)
    if args.no_text:
        # Every release variant carries the same translated files; only the
        # QoL code overlays differ. The release therefore runs the text
        # read-back once (on the base translation) and uses this switch for
        # the combinations, which still get the full structure and level-1
        # checks above.
        print('level 2/3: skipped (--no-text); text is identical across QoL variants')
        if bad:
            sys.exit(1)
        print('disc-byte verification PASSED (structure and files)')
        return

    # level 2: decode the DISC bytes back to the canonical rows
    for name in sorted(os.listdir(os.path.join(ROOT, 'data', 'psx', 'TALK'))):
        if not name.endswith('.BIN'):
            continue
        rel = 'TALK/' + name[:-4]
        rows = {r['pos']: (r.get('en') or '') for r in toolbelt.merged_rows(rel)}
        dpath = ('TALK/' + name).upper()
        orig = talkt.Talk(name, open(os.path.join(ROOT, 'data', 'psx', 'TALK', name), 'rb').read())
        if not rows or not orig.ok or dpath not in entries:
            continue
        built = talkt.Talk(name, read_file(dpath))
        if not built.ok:
            continue
        for i, u in enumerate(built.units):
            pos = hex(orig.starts[i]) if i < len(orig.starts) else None
            if pos in rows:
                check(f'{rel} unit {i}', rows[pos], etext.decode(u))
        for k, (_v, sp) in enumerate(built.s1):
            # rows are keyed by the ORIGINAL string offsets; unit/answer
            # order is stable across rebuilds, byte offsets are not
            pos = hex(orig.hdr[1] + orig.s1[k][0]) if k < len(orig.s1) else None
            if pos in rows:
                check(f'{rel} answer {k}', rows[pos],
                      etext.decode(sp[:built.s1_text_len(sp)]))

    for n in ('E0', 'E1', 'E2', 'E3'):
        rel = f'ADV/{n}'
        rows = {r['pos']: (r.get('en') or '') for r in toolbelt.merged_rows(rel)}
        dpath = ('ADV/' + n + '.BIN').upper()
        orig = efile.load(os.path.join(ROOT, 'data', 'psx', 'ADV', n + '.BIN'))
        if not rows or dpath not in entries:
            continue
        built = efile.load_from(read_file(dpath)) if hasattr(efile, 'load_from') else None
        if built is None:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.BIN', delete=False) as t:
                t.write(read_file(dpath))
                tmp = t.name
            built = efile.load(tmp)
            os.remove(tmp)
        pmap = {}
        for e in orig.entries:
            for k, (s, _x) in enumerate(e.boxes):
                pmap[f'{e.index}:{s:#x}'] = (e.index, k)
        for pos, (ei, k) in pmap.items():
            if pos in rows and ei < len(built.entries) and k < len(built.entries[ei].boxes):
                s, x = built.entries[ei].boxes[k]
                check(f'{rel} {ei}/{k}', rows[pos],
                      etext.decode(built.entries[ei].body[s:x]), end=b'\xff\x01')

    # dng packs: in place when the row fits, otherwise the spill hook ships
    # the full text (build/dng_spill.asm) - boxes hold arbitrary text
    spill_path = os.path.join(side_files, 'dng_spill.asm')
    spill_bytes = b''
    if os.path.exists(spill_path):
        for line in open(spill_path, encoding='utf-8'):
            line = line.strip()
            if line.startswith('.byte '):
                spill_bytes += bytes(int(x, 16) for x in line[6:].split(','))
    for rel, fp in dngpacks.pack_files():
        if len(os.path.basename(rel)) != 3:
            continue
        rows = {r['pos']: (r.get('en') or '') for r in toolbelt.merged_rows(rel)}
        dpath = rel.upper() + '.BIN'
        if not rows or dpath not in entries:
            continue
        orig = open(fp, 'rb').read()
        dbytes = read_file(dpath)
        for off, ln, ja in dngpacks.boxes(orig):
            en = rows.get(hex(off), '')
            if not en:
                continue
            eb, cap, cand = dngpacks.place(en, ja, orig, off, ln)
            if eb is not None:
                global_check(f'{rel} box {hex(off)} in place', eb, dbytes)
            else:
                # the SAME end-code rule as the builder: encode appends one
                # only when the text does not already carry it (a dng row
                # ends with its own <FF01>), so adding one here unbounded
                # asks for a DOUBLE end code that can never be on the disc
                global_check(f'{rel} box {hex(off)} spill',
                             etext.encode(dngpacks.indent_en(en, ja),
                                          end=b'\xff\x01'), spill_bytes)

    # level 3: every filled canonical row ships (the general "translated
    # but not injected" detector): its bytes must be in the disc file it
    # belongs to, in whatever encoding its family renders. Families whose
    # text is packed on disc (BTLP evt/neg byte-pairs) are counted back
    # through the builders' own unpack round-trip instead.
    print(f'level 2: {checks} rows checked back from disc bytes, {fails} mismatches')
    level3(read_file, side_files)
    party_names(read_file)
    if bad or fails:
        sys.exit(1)
    print('disc-byte verification PASSED')


def _row_forms(r):
    """Candidate byte forms a row's shipped text can take (its family's
    encoding(s)); searched anywhere in the disc file - builders relocate
    text within their file and the check is presence, not placement.
    Returns (all-found, forms): all-found forms (choices rows) split at
    '|', every piece must be present."""
    import etext
    import toolbelt as tb
    t = (r.get('en') or '').strip()
    forms = []
    if '|' in t:                       # choice lists: each option is placed on its own
        forms.append(('pieces',
                      [re.escape(etext.encode(p.strip(), end=None))
                       for p in t.split('|') if p.strip()]))
        return True, forms
    try:
        if '<FF05>' in t:
            # FF05 carries 2 parameter bytes the builders copy from the
            # Japanese: search with those bytes free
            pat = b''
            for p in re.split(r'(<FF05>)', t):
                if p == '<FF05>':
                    pat += re.escape(b'\xff\x05') + b'.{0,2}'
                elif p:
                    pat += re.escape(etext.encode(p, end=None))
            forms.append(('etext+pauses', [pat]))
        else:
            forms.append(('etext', [re.escape(etext.encode(t, end=None))]))
            if '<FF0E>' in t:
                import sysmsg
                forms.append(('etext-choice-pages',
                              [re.escape(etext.encode(sysmsg.choice_pages(t), end=None))]))
    except ValueError:
        pass
    try:                       # small-font single-byte families
        sf = bytes(tb.smallfont_char(c) for c in t)
        forms.append(('smallfont', [re.escape(sf)]))
        if len(sf) > 10:
            forms.append(('smallfont10', [re.escape(sf[:10])]))
    except (SystemExit, ValueError):
        pass
    try:
        # the VWF small font's OWN code space (sf_glyphs.bin / the affinity
        # pool, incbin'd straight into the disc): a line the record's
        # single-byte slot cannot hold ships here, and this map knows
        # characters the game's own small-font map does not (',')
        import smallfont_vwf
        forms.append(('smallfont_vwf',
                      [re.escape(bytes(smallfont_vwf.char_code(c) for c in t))]))
    except (SystemExit, ValueError):
        pass
    try:                       # casino prize table: full-width SJIS cells,
                               # the builder's own row encoder ('+' is the
                               # retail prize separator tile, not '＋')
        import casinoprize
        forms.append(('fullwidth', [re.escape(casinoprize.encode_prize(t))]))
    except (SystemExit, ValueError):
        pass
    try:
        # an affinity row is drawn as its record head + the small-font pool
        # tail (two homes, two files): both halves must be on the disc
        import affinity
        import smallfont_vwf
        for _entry, off in tb.pos_offsets(r['pos']):
            if not smallfont_vwf.AFF_LO <= off < smallfont_vwf.AFF_HI:
                continue
            k = (off - smallfont_vwf.AFF_LO) // 0x19
            head = affinity.record_bytes(k, t)
            tail = affinity.tail_bytes(k, t)
            forms.append(('affinity',
                          [re.escape(head)] + ([re.escape(tail)] if tail else [])))
            break
    except (SystemExit, ValueError):
        pass
    try:                   # S2D name entries: 1-row VWF bytes + FF01
        vwf = bytes(etext.vwf_byte(c) for c in t) + b'\xff\x01'
        forms.append(('name', [re.escape(vwf)]))
    except ValueError:
        pass
    return False, forms


def party_names(read_file):
    """The STATUS header's table back from the disc: wording, case, every slot.

    It is the one translated table that is not a row in translation/ (its words
    come from the PSP US build's own party list - src/injection_tools/
    partynames.py), so level 3's row walk never sees it: this is its evidence."""
    global fails, checks
    import partynames
    rows = partynames.table()
    slps = read_file('SLPS_005.00')
    base = partynames.BASE - partynames.SLPS_BASE
    checks += 1
    bad = [(_i, t, etext.decode(slps[base + partynames.SLOT * _i:base + partynames.SLOT * _i + partynames.SLOT]))
           for _i, t in rows
           if slps[base + partynames.SLOT * _i:base + partynames.SLOT * _i + partynames.SLOT] != partynames.enc(t)]
    if bad:
        fails += 1
        print(f'PARTY NAMES FAIL: {len(bad)} of {len(rows)} slots on the disc differ from the tool')
        for i, want, got in bad[:8]:
            print(f'    slot {i}: want {want!r}, disc has {got!r}')
    else:
        print(f'party names: {len(rows)} slots read back from disc bytes, wording and case as derived '
              f'({", ".join(t for _i, t in rows)})')
    # ... and the STATUS page's name row reads the given name first (western
    # order, the PSP's), while the data keeps family / given in their own slots.
    checks += 1
    bad = []
    for rel in ('ADV.BIN', 'DNG.BIN', 'S2D.BIN'):
        try:
            d = read_file(rel)
        except KeyError:
            continue
        got = [m.group(0) for m in re.finditer(rb'\xff\x07(.)\xea\xff\x0f\1\xff\x01', d, re.S)]
        if len(got) != 1:
            bad.append(rel)
    if bad:
        fails += 1
        print(f'NAME ROW FAIL: no given-first status name row in {", ".join(bad)}')
    else:
        print('party names: the status name row reads the given name first in ADV/DNG/S2D')
    # its separator is ONE byte and must be half the retail full-width space:
    # the font's 8 px blank (make_vwf_font.WIDE_SPACE), not the 4 px word space.
    checks += 1
    widths = open(os.path.join(ROOT, 'src', 'asm', 'font', 'vwf_width.bin'), 'rb').read()
    adv = widths[0xEA - 0x88] if len(widths) > 0xEA - 0x88 else None
    if adv != 8:
        fails += 1
        print(f'NAME ROW FAIL: the separator byte 0xEA is {adv} px wide, want 8 (make_vwf_font WIDE_SPACE)')
    else:
        print('party names: the separator is the font\'s 8 px blank (half the 16 px glyph 0)')


def level3(read_file, side_files=None):
    global fails, checks
    side_files = side_files or os.path.join(ROOT, 'build')
    import collections
    import toolbelt as tb
    import btlp
    # A LINE THE AFFINITY SLOT REFUSES IS CARRIED BY THE SMALL-FONT POOL, and
    # that pool is part of the SF_VWF kit: with the gate off the builder drops
    # the line and the retail 25-cell record (one line, no wrap) cannot take
    # it, so the record keeps its Japanese. The builder names those rows
    # (build/affinity_gated.tsv, written by affinity.py) - count them apart so
    # the report says what the kit bought instead of "not found in disc bytes".
    gated = set()
    if not features.on('SF_VWF'):
        path = os.path.join(side_files, 'affinity_gated.tsv')
        if not os.path.exists(path):
            fails += 1
            print('LEVEL 3 FAIL: SF_VWF is off and build/affinity_gated.tsv is '
                  'missing - the affinity builder names the rows the pool '
                  'carries (rebuild: python src/injection_tools/affinity.py build)')
        else:
            for line in open(path, encoding='utf-8').read().split('\n')[1:]:
                if line.strip():
                    gated.add(line.split('\t')[1])
    gated_n = 0
    description_drafts = set()
    draft_path = os.path.join(side_files, 'descs_drafts.tsv')
    if os.path.exists(draft_path):
        with open(draft_path, encoding='utf-8') as source:
            description_drafts = {line.split('\t', 1)[0]
                                  for line in source.read().splitlines()[1:] if line.strip()}
    description_draft_n = 0
    board_unshipped = set()
    try:
        board_unshipped = btlp.board_unshipped(btlp.data(), tb.merged_rows('BTLP'))
    except (KeyError, ValueError) as error:
        fails += 1
        print(f'LEVEL 3 FAIL: battle-board ownership: {error}')
    board_unshipped_n = 0
    # BTLP: the story-battle dialogue is always byte-pair packed on disc;
    # negotiation strings are packed when they start with the pack marker
    # (NEG_PACK_IDX) - everything else is placed as plain bytes
    d = btlp.data()
    packed_pos = {hex(a - btlp.B) for a, _e in btlp.evt_messages(d)}
    for i, (a, _e) in enumerate(btlp.neg_strings(d)):
        if i in btlp.NEG_PACK_IDX:
            packed_pos.add(hex(a - btlp.B))
    rels = translation_rels()
    stat = collections.Counter()
    misses = collections.defaultdict(list)
    packed_n = 0
    slps = read_file('SLPS_005.00')     # the shared spill target (banner/msg/evt)
    pool_parts = []                     # the small-font pool's homes: the
    for _n in ('ADV.BIN', 'DNG.BIN', 'S2D.BIN', 'SLPS_005.00'):
        # SLPS carries the resident copy the renderer reads (vwf/sf_slps.asm)
        try:
            pool_parts.append(read_file(_n))
        except KeyError:
            pass
    pool_hay = b''.join(pool_parts)
    for rel in sorted(rels):
        # the rel keeps the DIRECTORY CASE it has on disk ('fmv/poems' is the
        # ending-poems SOURCE table, read by fmv_layout - not a position
        # table at all), so the family test is on the upper-cased name
        if rel.upper().startswith(('TALK/', 'ADV/E', 'D0')):
            continue                    # level 2 checks these exactly
        rows = [r for r in tb.merged_rows(rel) if (r.get('en') or '').strip()]
        if not rows:
            continue
        name = 'SLPS_005.00' if rel == 'SLPS_005.00' else rel.upper() + '.BIN'
        try:
            hay = read_file(name) + slps
        except KeyError:
            misses[rel].append((rows[0]['pos'], f'no disc file {name}'))
            continue
        for r in rows:
            if rel == 'SLPS_005.00' and r['pos'] in description_drafts:
                description_draft_n += 1
                continue
            if rel == 'BTLP' and r['pos'] in board_unshipped:
                board_unshipped_n += 1
                continue
            if r['pos'] in packed_pos:
                packed_n += 1
                continue
            if r['pos'] in gated:
                gated_n += 1
                continue
            # Battle message encoding maps a terminal PSP FF02 to the PSX
            # caller-controlled FFF5 end; check the destination spelling,
            # not the source-only control the PS1 cannot interpret.
            record = r
            if rel == 'SLPS_005.00':
                import partynames
                try:
                    party_offset = int(r['pos'], 16) - (partynames.BASE - partynames.SLPS_BASE)
                except ValueError:
                    party_offset = -1
                if (0 <= party_offset < partynames.SLOTS * partynames.SLOT
                        and party_offset % partynames.SLOT == 0):
                    record = dict(r, en=partynames.fit(r['en'], party_offset // partynames.SLOT))
            if rel == 'BTLP':
                try:
                    address = int(r['pos'], 16) + btlp.B
                except ValueError:
                    address = 0
                if btlp.MSG_ZONE[0] <= address < btlp.MSG_ZONE[1]:
                    record = dict(r, en=btlp.msg_script(r.get('en') or ''))
            _all, forms = _row_forms(record)
            for _what, pats in forms:
                # THE SMALL-FONT POOL IS IN ANOTHER FILE: its bytes are
                # incbin'd into the three overlays (ADV/DNG/S2D, see
                # src/asm/main.asm), because the row is composed by the
                # overlay's own VWF engine - so a pooled affinity line is
                # present on the disc, just not in the file its row names.
                # The record head sits in SLPS and the tail in the pool, so
                # that form searches the pool homes for both halves.
                if all(re.search(p, pool_hay if _what in ('smallfont_vwf', 'affinity')
                                 else hay) for p in pats):
                    stat[rel] += 1
                    break
            else:
                misses[rel].append((r['pos'], (r.get('en') or '')[:40]))
    missing = 0
    for rel in sorted(misses):
        fails += 1
        missing += len(misses[rel])
        print(f'LEVEL 3 FAIL {rel}: {len(misses[rel])} translated row(s) not found in disc bytes')
        for pos, en in misses[rel][:6]:
            print(f'    {pos}  {en!r}')
    print(f'level 3: {sum(stat.values())} translated rows found in disc bytes, '
          f'{missing} missing, {packed_n} byte-pair packed '
          f'(btlp.py unpack round-trip + level 1)'
          + (f', {gated_n} carried by the small-font pool - SF_VWF is OFF, so those '
             f'records keep their Japanese' if gated_n or gated else '')
          + (f', {description_draft_n} human description draft(s) retained unshipped'
             if description_draft_n else '')
          + (f', {board_unshipped_n} battle-board row(s) kept Japanese '
             f'(fit gate or no consumer)' if board_unshipped_n else ''))


if __name__ == '__main__':
    main()
