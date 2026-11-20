"""Entry edits compose across relocation and have identical browser semantics."""
from pathlib import Path
import hashlib
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import toolpath
import format_edits as fmt
import modpack
import persona_patch


def payload(count: int) -> bytes:
    return bytes(8) + b'\x80Z' * count + b'\x7f\xff'


def archive() -> bytes:
    blobs = {3: payload(3), 8: payload(4)}
    table = [1]
    body = bytearray()
    for index in range(256):
        data = blobs.get(index, b'')
        body.extend(data + bytes((-len(data)) % 2048))
        table.append(1 + len(body) // 2048)
    header = bytearray(2048)
    struct.pack_into('<257H', header, 0, *table)
    return bytes(header + body)

class ContainerEdits(unittest.TestCase):
    def edit(self, source: bytes, index: int, count: int) -> fmt.EntryEdit:
        return fmt.EntryEdit(index, payload(count), hashlib.sha1(fmt.mes_entry(source,index)).hexdigest())

    def test_different_entries_compose_even_when_the_first_relocates(self):
        source = archive()
        a, b = self.edit(source, 3, 1500), self.edit(source, 8, 7)
        first = fmt.replace_mes(fmt.replace_mes(source, [a]), [b])
        second = fmt.replace_mes(fmt.replace_mes(source, [b]), [a])
        self.assertEqual(first, second)
        self.assertEqual(fmt.mes_entry(first, 8)[:len(b.data)], b.data)
        with self.assertRaisesRegex(ValueError, 'source entry'):
            fmt.replace_mes(first, [a])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            fmt.replace_mes(source, [a,a])

    def test_layer_builder_uses_entry_identity_and_merge_composes(self):
        from types import SimpleNamespace
        source=archive()
        reader=SimpleNamespace(read=lambda _path,_raw: source,entries={'ADV/MES.BIN':(0,len(source))})
        a=fmt.replace_mes(source,[self.edit(source,3,1500)])
        b=fmt.replace_mes(source,[self.edit(source,8,7)])
        first=modpack.layer_from('a',reader,{}, {'ADV/MES.BIN':a})
        second=modpack.layer_from('b',reader,{}, {'ADV/MES.BIN':b})
        self.assertFalse(first.files[0].spans)
        self.assertEqual(first.files[0].entries[0].index,3)
        merged,clashes=modpack.merge(reader,[first,second])
        reverse,_=modpack.merge(reader,[second,first])
        self.assertEqual(merged,reverse)
        self.assertEqual(clashes,{})

    def test_python_standalone_and_browser_match(self):
        source=archive(); edits=[self.edit(source,3,1500),self.edit(source,8,7)]
        expected=fmt.replace_mes(source,edits)
        cli=[persona_patch.EntryEdit(e.index,e.data,e.source)for e in edits]
        self.assertEqual(persona_patch.replace_mes(source,cli),expected)
        pack=modpack.Pack('test',[modpack.Part('',[modpack.FileEdit('ADV/MES.BIN',False,len(source),len(expected),entries=edits)])])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'source').write_bytes(source)
            modpack.write_layer(str(root/'edit.p1mod'),pack)
            self.assertEqual(modpack.read_layer(str(root/'edit.p1mod')),pack)
            parsed=persona_patch.parse_layer((root/'edit.p1mod').read_bytes())
            self.assertEqual(parsed['parts'][0][1][0].entries,cli)
            script=r'''
require(process.argv[1]+'/webpatcher/lzma.js');require(process.argv[1]+'/webpatcher/modpack.js');
const fs=require('fs');
(async()=>{const root=process.argv[2];const p=MODPACK.parseLayer(new Uint8Array(fs.readFileSync(root+'/edit.p1mod')));
const original=new Uint8Array(fs.readFileSync(root+'/source'));
const disc={entries:async()=>new Map([['ADV/MES.BIN',[0,original.length]]]),readFile:async()=>original};
const merged=await MODPACK.merge(disc,MODPACK.selected([p],{test:[]}));
const data=merged.files.get('ADV/MES.BIN');
fs.writeFileSync(root+'/result',data);})().catch(e=>{console.error(e);process.exitCode=1;});'''
            subprocess.run(['node','-e',script,str(ROOT),str(root)],check=True)
            self.assertEqual((root/'result').read_bytes(),expected)
