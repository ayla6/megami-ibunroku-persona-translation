"""Compile a mod's images.tsv through shared TIM and archive handlers.

A mod declares source image slots and PNG assets; it supplies no Python builder.
Expensive PNG mapping and MES encoding happen here, never in the patcher.
"""
from __future__ import annotations
import argparse
import csv
from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
import sys
from typing import Final
from concurrent.futures import ProcessPoolExecutor
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import toolpath
import tim
import pngpage
import mescodec
import mes_encode
import mods
import build_step_cache as cache
from format_edits import mes_table, SECTOR
from pngpage import rgba_to_page, pixels, rgb15

ROOT: Final = Path(toolpath.ROOT)
RETAIL: Final = ROOT / 'data/psx'
BUILD: Final = ROOT / 'build'
COLUMNS: Final = ('file', 'format', 'entry', 'member', 'image', 'mode', 'width', 'height')

@dataclass(frozen=True)
class ImageRule:
    file: str
    format: str
    entry: int
    member: int
    image: Path
    mode: str
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class MappedPage:
    colors: tuple[int, ...]
    indices: bytes


def rules(mod: mods.Mod, art: Path | None = None) -> list[ImageRule]:
    with (Path(mod.folder) / 'images.tsv').open(newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if reader.fieldnames != list(COLUMNS): raise ValueError('invalid image replacement manifest')
        result = []
        for row in reader:
            file = row['file']
            if Path(file).is_absolute() or '..' in Path(file).parts: raise ValueError('invalid image target path')
            asset = (art or Path(mod.folder) / 'assets') / row['image']
            if '..' in Path(row['image']).parts or Path(row['image']).is_absolute(): raise ValueError('invalid image asset path')
            if row['format'] not in ('bst','battle','tim','mes','mes-image') or row['mode'] not in ('indexed','black-matte'):
                raise ValueError('unsupported image replacement format or mode')
            rule = ImageRule(file,row['format'],int(row['entry'],0),int(row['member'],0),asset,row['mode'],int(row['width']),int(row['height']))
            if min(rule.entry, rule.member, rule.width, rule.height) < 0:
                raise ValueError('negative image replacement index or dimension')
            if rule.format == 'mes' and (rule.entry >= 256 or rule.member >= 8):
                raise ValueError('MES image index outside container')
            if rule.format == 'mes-image' and (rule.mode != 'indexed' or not rule.width or not rule.height):
                raise ValueError('compressed images require indexed mode and dimensions')
            result.append(rule)
    for file in {r.file for r in result}:
        formats = {r.format for r in result if r.file == file}
        if 'mes' in formats and len(formats) != 1:
            raise ValueError('MES archive and flat image rules cannot share a file')
    return result


def battle_table(data: bytes, sectors: int) -> tuple[int, ...]:
    found = []
    for at in range(0,len(data)-43,2):
        values = struct.unpack_from('<22H',data,at)
        if values[0] <= 3 and values[20] == sectors and values[21] == 0 and all(5 <= b-a <= 60 for a,b in zip(values[:20],values[1:21])):
            found.append(values[:21])
    if len(found)!=1: raise ValueError('battle sprite member table is ambiguous')
    return found[0]


def offset(rule: ImageRule, original: bytes, tree: Path | None = None) -> int:
    if rule.format=='tim': return rule.entry
    if rule.format=='bst': return 0x808+rule.entry*0x2800
    if rule.format=='battle':
        table=battle_table(((tree or RETAIL)/'BTLP.BIN').read_bytes(),len(original)//SECTOR)
        if not 0 <= rule.entry < len(table)-1: raise ValueError('battle member outside table')
        return table[rule.entry]*SECTOR+12
    raise ValueError('compressed images need their container handler')


def indexed_image(palette: tuple[int, ...], indices: bytes, width: int, height: int) -> Image.Image:
    """Decode indexed PS1 art without losing its transparent key."""
    if len(indices) != width * height:
        raise ValueError('indexed image dimensions mismatch')
    rgba = bytearray()
    for index in indices:
        color = palette[index]
        channels = [((color >> shift) & 31) for shift in (0, 5, 10)]
        rgba.extend([(value << 3) | (value >> 2) for value in channels])
        rgba.append(0 if index == 0 else 255)
    return Image.frombytes('RGBA', (width, height), bytes(rgba))


def tim_image(data: bytes, at: int) -> Image.Image:
    image_ranges(data, at)
    info = tim.parse(data, at)
    raw = data[info['at']:info['end']]
    if info['bpp'] == 16:
        rgb = bytearray()
        for (color,) in struct.iter_unpack('<H', raw):
            for shift in (0, 5, 10):
                value = (color >> shift) & 31
                rgb.append((value << 3) | (value >> 2))
        return Image.frombytes('RGB', (info['px_w'], info['h']), bytes(rgb))
    clut = info['clut']
    if not clut:
        raise ValueError('indexed TIM lacks a palette')
    palette = struct.unpack_from(f"<{clut['n']}H", data, clut['at'])
    indices = raw if info['bpp'] == 8 else bytes(v for b in raw for v in (b & 15, b >> 4))
    return indexed_image(palette, indices, info['px_w'], info['h'])


def source_image(rule: ImageRule, tree: Path) -> Image.Image:
    data = (tree / rule.file).read_bytes()
    if rule.format == 'mes':
        table = mes_table(data)
        blob = mescodec.decode(data[table[rule.entry]*SECTOR+8:table[rule.entry+1]*SECTOR])[0]
        return tim_image(blob, members(blob)[rule.member])
    if rule.format == 'mes-image':
        raw = mescodec.decode(data[rule.entry:], 512+rule.width*rule.height)[0]
        return indexed_image(struct.unpack_from('<256H', raw), raw[512:], rule.width, rule.height)
    return tim_image(data, offset(rule, data, tree))


def export_images(mod: mods.Mod, tree: Path, out: Path, suffix: str = '') -> None:
    """Explicit reference export, using the same declarations as the build."""
    selected = rules(mod)
    targets = [out / (r.image.stem + suffix + '.png') for r in selected]
    if len(set(targets)) != len(targets):
        raise ValueError('image declarations have duplicate export names')
    if any(path.exists() for path in targets):
        raise ValueError('image export refuses to overwrite existing files')
    out.mkdir(parents=True, exist_ok=True)
    for rule, target in zip(selected, targets):
        source_image(rule, tree).save(target)
    print(f'images: exported {len(targets)} reference images to {out}')


def image_ranges(data: bytes, at: int) -> list[tuple[int,int]]:
    if at<0 or at+8>len(data) or struct.unpack_from('<H',data,at)[0]!=0x10: raise ValueError('missing TIM header')
    info=tim.parse(data,at)
    if info['end'] > len(data): raise ValueError('TIM exceeds container')
    ranges=[(info['at'],info['end'])]
    if info['clut']: ranges.append((info['clut']['at'],info['clut']['at']+info['clut']['n']*2))
    return ranges


def replace_image(data: bytes, at: int, image: Image.Image, mode: str,
                  mapped_pages: dict[tuple[int,tuple[int,...]],MappedPage] | None = None) -> bytes:
    if at<0 or at+8>len(data) or struct.unpack_from('<H',data,at)[0]!=0x10: raise ValueError('missing TIM header')
    info=tim.parse(data,at)
    if info['end']>len(data) or image.size!=(info['px_w'],info['h']): raise ValueError('image dimensions do not match TIM')
    result=bytearray(data)
    if mode=='indexed':
        if info['bpp']!=8 or not info['clut'] or info['clut']['n']!=256: raise ValueError('expected an indexed 8bpp TIM')
        clut=info['clut'];palette=list(struct.unpack_from('<256H',data,clut['at']))
        key=(id(image),tuple(palette))
        mapped=mapped_pages.get(key) if mapped_pages is not None else None
        if mapped is None:
            colors,indices=rgba_to_page(image,palette,name='declared image',tool='images')
            mapped=MappedPage(tuple(colors),indices)
            if mapped_pages is not None: mapped_pages[key]=mapped
        colors,indices=mapped.colors,mapped.indices
        if len(indices)!=info['end']-info['at']: raise ValueError('image data size mismatch')
        struct.pack_into('<256H',result,clut['at'],*colors)
        result[info['at']:info['end']]=indices
    else:
        if info['bpp']!=16: raise ValueError('black-matte images require a 16bpp TIM')
        original=struct.unpack_from(f'<{image.width*image.height}H',data,info['at'])
        values=[]
        for old,(r,g,b,a) in zip(original,pixels(image)):
            if a!=255: raise ValueError('black-matte art must be opaque')
            value=rgb15(r,g,b)
            if value==0 and (r,g,b)!=(0,0,0): value=0x421
            values.append((old&0x8000)|value)
        struct.pack_into(f'<{len(values)}H',result,info['at'],*values)
    return bytes(result)


def members(blob: bytes) -> list[int]:
    result=[]
    for index in range(8):
        at=struct.unpack_from('<I',blob,index*4)[0]
        if not at or at>=len(blob): break
        if tim.parse(blob,at)['bpp']==8: result.append(at)
    return result


def page_key(blob: bytes, at: int) -> str:
    info=tim.parse(blob,at)
    return hashlib.sha1(blob[info['at']:info['end']]).hexdigest()


def mes_images(current: bytes, original: bytes, selected: list[ImageRule]) -> bytes:
    targets: dict[str, tuple[Image.Image,str]] = {}
    source_table=mes_table(original)
    for rule in selected:
        a,b=source_table[rule.entry:rule.entry+2]
        blob=mescodec.decode(original[a*SECTOR+8:b*SECTOR])[0]
        at=members(blob)[rule.member]
        with Image.open(rule.image) as art: targets[page_key(blob,at)]=(art.convert('RGBA'),rule.mode)
    table=mes_table(current)
    pieces=[];indexes=[];blobs=[]
    mapped_pages: dict[tuple[int,tuple[int,...]],MappedPage] = {}
    for index in range(256):
        raw=current[table[index]*SECTOR:table[index+1]*SECTOR]
        blob=mescodec.decode(raw[8:])[0]
        updated=blob
        for at in members(blob):
            target=targets.get(page_key(blob,at))
            if target: updated=replace_image(updated,at,*target,mapped_pages=mapped_pages)
        if updated!=blob:
            indexes.append(index);blobs.append(updated);pieces.append(raw[:8])
        else: pieces.append(raw)
    if not indexes: raise ValueError('no source images matched the replacement declarations')
    with ProcessPoolExecutor(max_workers=min(4,len(indexes))) as pool:
        for index,encoded in zip(indexes,pool.map(mes_encode.encode,blobs)):
            pieces[index]+=encoded
    if all(len(pieces[i]) <= (table[i+1]-table[i])*SECTOR for i in indexes):
        return current[:table[0]*SECTOR]+b''.join(piece+bytes((table[i+1]-table[i])*SECTOR-len(piece))for i,piece in enumerate(pieces))
    starts=[table[0]]
    for piece in pieces: starts.append(starts[-1]+(len(piece)+SECTOR-1)//SECTOR)
    if starts[-1]>65535: raise ValueError('MES sector table overflow')
    head=bytearray(current[:table[0]*SECTOR]);struct.pack_into('<257H',head,0,*starts)
    return bytes(head)+b''.join(piece+bytes((-len(piece))%SECTOR)for piece in pieces)


def replace_compressed_image(data: bytes, rule: ImageRule) -> bytes:
    if rule.width<=0 or rule.height<=0: raise ValueError('compressed image dimensions are required')
    size=512+rule.width*rule.height
    raw,capacity=mescodec.decode(data[rule.entry:],size)
    if len(raw)!=size: raise ValueError('compressed image has wrong size')
    with Image.open(rule.image) as image:
        if image.size!=(rule.width,rule.height): raise ValueError('compressed image dimensions mismatch')
        palette=list(struct.unpack_from('<256H',raw))
        colors,indices=rgba_to_page(image.convert('RGBA'),palette,name='declared image',tool='images')
    decoded=struct.pack('<256H',*(c&0x7fff for c in colors))+indices
    encoded=mescodec.encode_opt(decoded)
    if len(encoded)>capacity: raise ValueError('compressed image exceeds its reserved space')
    if mescodec.decode(encoded,size)[0]!=decoded: raise ValueError('compressed image round-trip failed')
    return data[:rule.entry]+encoded+data[rule.entry+len(encoded):]


def registered() -> list[mods.Mod]:
    return [mod for mod in mods.load() if (Path(mod.folder)/'images.tsv').is_file()]


def write_changed(dest: Path, data: bytes) -> None:
    if dest.is_file() and dest.read_bytes()==data: return
    dest.parent.mkdir(parents=True,exist_ok=True)
    temporary=dest.with_suffix(dest.suffix+'.tmp')
    temporary.write_bytes(data);temporary.replace(dest)


def restore(selected_mods: list[mods.Mod] | None = None) -> None:
    """Reset declared image regions before assembling another variant."""
    grouped: dict[str,list[ImageRule]]={}
    for mod in registered() if selected_mods is None else selected_mods:
        for rule in rules(mod):
            if rule.format!='mes': grouped.setdefault(rule.file,[]).append(rule)
    for file,selected in grouped.items():
        dest=BUILD/file
        if not dest.exists(): continue
        original=(RETAIL/file).read_bytes();data=bytearray(dest.read_bytes())
        for rule in selected:
            spans=image_ranges(original,offset(rule,original)) if rule.format!='mes-image' else [(rule.entry,rule.entry+mescodec.decode(original[rule.entry:],512+rule.width*rule.height)[1])]
            for first,last in spans:
                if last>len(data): raise ValueError('built image file is truncated')
                data[first:last]=original[first:last]
        write_changed(dest,bytes(data))


def build_images(mod: mods.Mod, art: Path | None = None) -> None:
    selected=rules(mod,art);grouped: dict[str,list[ImageRule]]={}
    for rule in selected: grouped.setdefault(rule.file,[]).append(rule)
    for file,group in grouped.items():
        original=(RETAIL/file).read_bytes();dest=BUILD/file
        current=dest.read_bytes() if dest.exists() else original
        if group[0].format=='mes':
            cached=BUILD/'step_cache/images'/mod.slug/'MES.BIN'
            source_copy=cached.with_suffix('.source.bin')
            if cached.is_file() and source_copy.is_file() and current==cached.read_bytes():
                current=source_copy.read_bytes()
            write_changed(source_copy,current)
            inputs=[source_copy,Path(mod.folder)/'images.tsv',RETAIL/file,Path(__file__),Path(mes_encode.__file__),Path(mescodec.__file__),Path(pngpage.__file__),Path(tim.__file__),*(r.image for r in group)]
            def generate() -> None:
                cached.parent.mkdir(parents=True,exist_ok=True)
                cached.write_bytes(mes_images(current,original,group))
            cache.run('declared archive images',inputs,[cached],generate,cached.with_suffix('.tsv'),context=(hashlib.sha1(current).hexdigest(),))
            if not dest.is_file() or cache._digest(cached) != cache._digest(dest):
                cache.clone(cached,dest)
        else:
            for rule in group:
                if rule.format=='mes-image': current=replace_compressed_image(current,rule)
                else:
                    with Image.open(rule.image) as image: current=replace_image(current,offset(rule,original),image.convert('RGBA'),rule.mode)
            write_changed(dest,current)
    print(f'images: {mod.slug}: {len(selected)} declarations, {len(grouped)} files')


def verify_images(mod: mods.Mod, art: Path | None = None) -> None:
    for rule in rules(mod,art):
        if rule.format=='mes':
            cached=BUILD/'step_cache/images'/mod.slug/'MES.BIN'
            if not cached.is_file() or cache._digest(cached)!=cache._digest(BUILD/rule.file): raise ValueError('built archive differs from validated image cache')
        elif rule.format=='mes-image':
            current=(BUILD/rule.file).read_bytes()
            expected=replace_compressed_image((RETAIL/rule.file).read_bytes(),rule)
            size=512+rule.width*rule.height
            if mescodec.decode(current[rule.entry:],size)[0]!=mescodec.decode(expected[rule.entry:],size)[0]: raise ValueError('compressed image readback differs')
        else:
            original=(RETAIL/rule.file).read_bytes();current=(BUILD/rule.file).read_bytes()
            with Image.open(rule.image) as image: expected=replace_image(original,offset(rule,original),image.convert('RGBA'),rule.mode)
            for first,last in image_ranges(original,offset(rule,original)):
                if current[first:last]!=expected[first:last]: raise ValueError(f'{rule.file}: declared image readback differs')
    print(f'images: {mod.slug}: all declared images verified')


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('build','verify','retail','export'))
    parser.add_argument('mod',nargs='?')
    parser.add_argument('--art',type=Path)
    parser.add_argument('--tree',type=Path,default=RETAIL)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--suffix',default='')
    args=parser.parse_args()
    if args.command=='retail': restore();return
    if not args.mod: parser.error('a mod label is required')
    mod=mods.by_label()[args.mod]
    if args.command=='export':
        if args.output is None: parser.error('export requires --output')
        export_images(mod,args.tree,args.output,args.suffix)
        return
    if args.command=='build': build_images(mod,args.art)
    else: verify_images(mod,args.art)

if __name__=='__main__': main()
