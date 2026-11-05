"""Find the local game discs and extract the trees the build reads.

Every disc is recognized from its own bytes; no path, title or game name is
assumed:

* a PSX image by the size and CRC32 checked in image_check.py;
* a PSP image by its ISO9660 volume and the DISC_ID in
  PSP_GAME/PARAM.SFO. The region letter in that ID chooses data/psp_jp or
  data/psp_us, and the SFO title is only used for the human-readable report.

Discs live anywhere under data/discs/ (any file name, any subdirectory).
`build.py` asks this module for the PSX image and for the PSP-US tree when it
needs them; `tools/prepare_data.py` is the standalone command that extracts
whatever it finds.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import struct
import subprocess
import sys

import image_check

ROOT = Path(__file__).resolve().parents[2]
DISCS = ROOT / 'data' / 'discs'
PSX_DIR = ROOT / 'data' / 'psx'
PSX_REV1_DIR = ROOT / 'data' / 'psx_rev1'
PSP_DIRS = {'jp': ROOT / 'data' / 'psp_jp', 'us': ROOT / 'data' / 'psp_us'}
PSX_EXTRACT = ROOT / 'src' / 'extraction_tools' / 'psx' / 'extract.py'

ISO_SECTOR = 2048
PSX_REQUIRED = (
    'SLPS_005.00', 'ADV.BIN', 'BTLP.BIN', 'CASINO.BIN', 'DNG.BIN',
    'OPEN.BIN', 'S2D.BIN', 'EXE/MOVIE.EXE', 'ADV/MES.BIN', 'NAME.BIN',
    'NAMEDT.BIN', 'FONT.BIN',
)

# Sony title IDs: a UMD's first four characters carry the region (ULUS,
# ULJM, ULES, ULKS, ...); a PSN title puts it third (NPUG, NPJH, NPEB, ...).
UMD_REGIONS = {
    'ULUS': 'us', 'UCUS': 'us',
    'ULJM': 'jp', 'ULJS': 'jp', 'ULJN': 'jp',
    'ULES': 'eu', 'UCES': 'eu',
    'ULKS': 'korea', 'ULAS': 'asia',
}
PSN_REGIONS = {'U': 'us', 'J': 'jp', 'E': 'eu', 'H': 'asia', 'A': 'asia'}


def _show(path):
    """A path for logs: relative to the repo when it lives inside it."""
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return str(path)


@dataclass(frozen=True)
class Disc:
    """A recognized image under data/discs/."""
    path: Path
    kind: str                 # psx | psx-rev1 | psp-jp | psp-us | psp-<other>
    label: str
    disc_id: str = ''
    title: str = ''


def _read(f, offset, size):
    f.seek(offset)
    out = bytearray()
    while len(out) < size:
        chunk = f.read(size - len(out))
        if not chunk:
            raise EOFError(f'image ends after {len(out)} of {size} bytes')
        out += chunk
    return bytes(out)


def _iso_name(raw):
    """The usable name of a directory record, or None for . / .. / junk."""
    if raw in (b'\0', b'\1'):
        return None
    try:
        name = raw.split(b';', 1)[0].decode('ascii')
    except UnicodeDecodeError:
        return None
    name = name.rstrip('.')
    if (not name or name in ('.', '..') or '/' in name or '\\' in name
            or any(ord(ch) < 32 for ch in name)):
        return None
    return name


def _iso_entries(f, lba, size):
    """(name, extent_lba, extent_size, is_directory) for one directory."""
    data = _read(f, lba * ISO_SECTOR, size)
    pos = 0
    while pos < len(data):
        rec_len = data[pos]
        if rec_len == 0:
            pos = (pos // ISO_SECTOR + 1) * ISO_SECTOR
            continue
        if pos + rec_len > len(data) or rec_len < 34:
            break
        ext_lba, = struct.unpack_from('<I', data, pos + 2)
        ext_size, = struct.unpack_from('<I', data, pos + 10)
        flags = data[pos + 25]
        name_len = data[pos + 32]
        name = _iso_name(data[pos + 33:pos + 33 + name_len])
        pos += rec_len
        if name is not None:
            yield name, ext_lba, ext_size, bool(flags & 2)


def _pvd(f):
    pvd = _read(f, 16 * ISO_SECTOR, ISO_SECTOR)
    if pvd[1:6] != b'CD001':
        return None
    return (struct.unpack_from('<I', pvd, 156 + 2)[0],
            struct.unpack_from('<I', pvd, 156 + 10)[0])


def _lookup_file(f, root_lba, root_size, parts):
    """(lba, size) of an exact path in the ISO9660 tree, or None."""
    lba, size, is_dir = root_lba, root_size, True
    for part in parts:
        if not is_dir:
            return None
        hit = next(((n, l, s, d) for n, l, s, d in _iso_entries(f, lba, size)
                    if n.upper() == part.upper()), None)
        if hit is None:
            return None
        _name, lba, size, is_dir = hit
    return None if is_dir else (lba, size)


def _sfo_fields(data):
    """The string and 32-bit fields of a PARAM.SFO."""
    if len(data) < 20 or data[:4] != b'\0PSF':
        return {}
    _magic, _version, key_start, data_start, count = struct.unpack_from(
        '<4sIIII', data, 0)
    fields = {}
    for i in range(min(count, 4096)):
        pos = 20 + i * 16
        if pos + 16 > len(data):
            break
        key_off, fmt, length, _max_len, data_off = struct.unpack_from(
            '<HHIII', data, pos)
        key_pos = key_start + key_off
        key_end = data.find(b'\0', key_pos)
        if key_end < 0:
            continue
        key = data[key_pos:key_end].decode('ascii', 'replace')
        start = data_start + data_off
        value = data[start:start + length]
        if fmt == 0x0204:            # UTF-8 string
            fields[key] = value.rstrip(b'\0').decode('utf-8', 'replace')
        elif fmt == 0x0404 and len(value) == 4:  # unsigned/bit field
            fields[key] = struct.unpack('<I', value)[0]
    return fields


def psp_region(disc_id):
    """The data/psp_<region> key for a Sony title ID, or None."""
    disc_id = ''.join(ch for ch in disc_id.upper() if ch.isalnum())
    if len(disc_id) >= 4 and disc_id[:4] in UMD_REGIONS:
        return UMD_REGIONS[disc_id[:4]]
    if disc_id.startswith('NP') and len(disc_id) >= 3:
        return PSN_REGIONS.get(disc_id[2])
    return None


def _psp_disc(path):
    try:
        with path.open('rb') as f:
            volume = _pvd(f)
            if volume is None:
                return None
            root_lba, root_size = volume
            param = _lookup_file(f, root_lba, root_size, ('PSP_GAME', 'PARAM.SFO'))
            if param is None:
                return None
            fields = _sfo_fields(_read(f, param[0] * ISO_SECTOR, param[1]))
    except (OSError, EOFError, struct.error):
        return None
    disc_id = str(fields.get('DISC_ID', '')).strip()
    region = psp_region(disc_id)
    if region is None:
        return None
    title = str(fields.get('TITLE', '')).strip()
    label = f'PSP {region.upper()}'
    if disc_id:
        label += f' ({disc_id})'
    if title:
        label += f' "{title}"'
    return Disc(path, f'psp-{region}', label, disc_id, title)


def identify(path):
    """Recognize one image, or return None if it is not a disc we support."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size == image_check.SIZE:
        if image_check.crc32(str(path)) == image_check.CRC32:
            return Disc(path, 'psx', 'PSX Rev 0 (SLPS-00500)')
        return None
    if size == image_check.REV1_SIZE:
        if image_check.crc32(str(path)) == image_check.REV1_CRC32:
            return Disc(path, 'psx-rev1', 'PSX Rev 1')
        return None
    if size >= 17 * ISO_SECTOR and size % ISO_SECTOR == 0:
        return _psp_disc(path)
    return None


def candidates(discs_dir=DISCS):
    """Files under discs_dir that could be a supported disc, sorted."""
    root = Path(discs_dir)
    if not root.is_dir():
        return []
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix.lower() == '.cue':
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if (size in (image_check.SIZE, image_check.REV1_SIZE)
                    or (size >= 17 * ISO_SECTOR and size % ISO_SECTOR == 0)):
                out.append(path)
    return out


def discover(discs_dir=DISCS):
    """Every recognized disc under discs_dir, in stable path order."""
    return [disc for disc in (identify(path) for path in candidates(discs_dir))
            if disc is not None]


def find(kind, discs_dir=DISCS):
    """The first disc of a kind, or None."""
    return next((disc for disc in discover(discs_dir) if disc.kind == kind), None)


def psx_complete(out_dir=PSX_DIR):
    """True when the extracted PSX tree has every file the build reads."""
    out_dir = Path(out_dir)
    return (all((out_dir / name).is_file() for name in PSX_REQUIRED)
            and any((out_dir / 'TALK').glob('*.BIN')))


def psp_complete(region, out_dir=None):
    """True when the extracted PSP tree has the files the build reads."""
    out_dir = Path(out_dir or PSP_DIRS[region])
    boot = 'EBOOT.BIN' if region == 'us' else 'BOOT.BIN'
    return ((out_dir / 'PSP_GAME' / 'SYSDIR' / boot).is_file()
            and any((out_dir / 'PSP_GAME' / 'USRDIR' / 'pack' / 'talk').glob('*.BIN')))


def resolve_psx(preferred=None, discs_dir=DISCS):
    """The PSX Rev 0 image to build from.

    An explicit/default path wins when it exists. Otherwise the first Rev 0
    image anywhere under data/discs/ is used, so a fresh checkout only has
    to drop its dump in that folder.
    """
    if preferred and Path(preferred).is_file():
        return str(Path(preferred))
    found = find('psx', discs_dir)
    if found is not None:
        return str(found.path)
    rev1 = find('psx-rev1', discs_dir)
    if rev1 is not None:
        raise SystemExit(
            f'build.py: only the Rev 1 PSX image was found ({rev1.path}).\n'
            'The translation is built from Rev 0; convert the disc first '
            '(the release\'s rev1-to-rev0 patch, or the web patcher).')
    raise SystemExit(
        f'build.py: no PSX Rev 0 image found under {discs_dir}.\n'
        'Put a single-track .bin of SLPS-00500 (either revision is fine as '
        'input to the web patcher, but builds need Rev 0) in that folder, '
        'or pass --image PATH.')


def extract_psx(image, out_dir=PSX_DIR, rev1=False, force=False, log=print):
    """Extract the PSX tree with the one existing PSX extractor."""
    out_dir = Path(out_dir)
    if not force and psx_complete(out_dir):
        log(f'prepare_data: {_show(out_dir)} already extracted')
        return out_dir
    label = 'Rev 1' if rev1 else 'Rev 0'
    log(f'prepare_data: extracting PSX {label} -> {_show(out_dir)}')
    command = [sys.executable, str(PSX_EXTRACT), str(image), str(out_dir)]
    if rev1:
        command.append('--rev1')
    subprocess.run(command, cwd=ROOT, check=True,
                   env={**os.environ, 'PYTHONHASHSEED': '0'})
    return out_dir


def iso_index(image):
    """Every file in an ISO9660 image: (relative path, lba, size)."""
    files = []
    with open(image, 'rb') as f:
        volume = _pvd(f)
        if volume is None:
            raise ValueError(f'{image}: no ISO9660 volume descriptor')
        _walk_iso(f, *volume, '', files, set())
    return files


def _walk_iso(f, lba, size, prefix, files, seen):
    key = (lba, size)
    if key in seen:
        return
    seen.add(key)
    for name, ext_lba, ext_size, is_dir in _iso_entries(f, lba, size):
        rel = prefix + name
        if is_dir:
            _walk_iso(f, ext_lba, ext_size, rel + '/', files, seen)
        else:
            files.append((rel, ext_lba, ext_size))


def _copy_extent(f, lba, size, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    f.seek(lba * ISO_SECTOR)
    remaining = size
    with dest.open('wb') as out:
        while remaining:
            chunk = f.read(min(remaining, 4 << 20))
            if not chunk:
                raise EOFError(f'{dest}: image ends before the recorded size')
            out.write(chunk)
            remaining -= len(chunk)


def extract_psp(image, region, out_dir=None, force=False, log=print):
    """Extract a PSP ISO to data/psp_jp or data/psp_us."""
    image = Path(image)
    target = Path(out_dir or PSP_DIRS[region])
    if not force and psp_complete(region, target):
        log(f'prepare_data: {_show(target)} already extracted')
        return target
    disc = identify(image)
    if disc is None or disc.kind != f'psp-{region}':
        raise SystemExit(f'{image} is not a PSP {region.upper()} disc')
    files = iso_index(image)
    total = sum(size for _rel, _lba, size in files)
    log(f'prepare_data: extracting {disc.label} -> {_show(target)} '
        f'({len(files)} files, {total / (1 << 20):.0f} MiB)')
    with image.open('rb') as f:
        for rel, lba, size in files:
            _copy_extent(f, lba, size, target / rel)
    return target


def ensure_psp(region='us', discs_dir=DISCS, force=False, log=print):
    """Extract a PSP tree on demand, for a build that needs it."""
    if not force and psp_complete(region):
        return PSP_DIRS[region]
    disc = find(f'psp-{region}', discs_dir)
    if disc is None:
        raise SystemExit(
            f'build.py: no PSP {region.upper()} image found under {discs_dir}.\n'
            'Extracting the PSP text needs the game image there (or use '
            '--no-port to build from the checked-in translations).')
    return extract_psp(disc.path, region, force=force, log=log)


def prepare(discs_dir=DISCS, only=None, force=False, log=print):
    """Extract every requested disc whose target tree is missing.

    `only` is a set of kinds (psx, psx-rev1, psp-jp, psp-us). A requested
    kind that has no disc is an error; without `only`, whatever is present
    is extracted and anything absent is simply skipped.
    """
    wanted = set(only or ())
    unknown = wanted - {'psx', 'psx-rev1', 'psp-jp', 'psp-us'}
    if unknown:
        raise SystemExit(f'prepare_data: unknown kind(s): {", ".join(sorted(unknown))}')
    discs = discover(discs_dir)
    prepared = []
    for kind in ('psx', 'psx-rev1', 'psp-jp', 'psp-us'):
        if wanted and kind not in wanted:
            continue
        found = [disc for disc in discs if disc.kind == kind]
        if not found:
            if wanted:
                raise SystemExit(f'prepare_data: no {kind} disc found under {discs_dir}')
            continue
        if len(found) > 1:
            log(f'prepare_data: {len(found)} {kind} discs found; using {found[0].path}')
        disc = found[0]
        if kind == 'psx':
            extract_psx(disc.path, PSX_DIR, rev1=False, force=force, log=log)
        elif kind == 'psx-rev1':
            extract_psx(disc.path, PSX_REV1_DIR, rev1=True, force=force, log=log)
        else:
            region = kind.split('-', 1)[1]
            extract_psp(disc.path, region, force=force, log=log)
        prepared.append(disc)
    if not prepared:
        log(f'prepare_data: no supported discs found under {discs_dir}')
    return prepared
