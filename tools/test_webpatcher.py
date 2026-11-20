"""Web patcher integrity: the release option wording, and the P1MOD layer
format read the same way by Python (src/pipeline/modpack.py) and the
browser (webpatcher/modpack.js).

Full disc parity - the browser applier laying a disc out byte for byte like
build_disc.py - is checked by every release build (tools/build_patches.py,
check_browser_layout) on the real disc."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)


class InPlaceLayerTest(unittest.TestCase):
    def test_in_place_edit_preserves_file_shortened_by_an_earlier_layer(self):
        import modpack

        class Source:
            entries = {'OPEN.EXE': None}

            def read(self, path, raw=False):
                return b'original'

        shrink = modpack.Layer('short', [modpack.FileEdit('OPEN.EXE', False, 8, 4)])
        edit = modpack.Layer('in-place', [
            modpack.FileEdit('OPEN.EXE', False, 8, 8, spans=[modpack.Span(0, b'O')]),
        ])
        files, _ = modpack.merge(Source(), [shrink, edit])
        self.assertEqual(files['OPEN.EXE'], b'Orig')

        if shutil.which('node'):
            js = """
require(process.argv[1]);
const disc = {
  async entries() { return new Map([['OPEN.EXE', [0, 8]]]); },
  async readFile() { return new TextEncoder().encode('original'); },
};
const base = {path: 'OPEN.EXE', raw: false, before: 8};
const layers = [
  {name: 'short', files: [{...base, length: 4, spans: []}]},
  {name: 'in-place', files: [{
    ...base, length: 8, spans: [{offset: 0, bytes: Uint8Array.of(79)}],
  }]},
];
MODPACK.merge(disc, layers).then(({files}) => {
  if (new TextDecoder().decode(files.get('OPEN.EXE')) !== 'Orig') process.exitCode = 1;
}).catch(err => { console.error(err); process.exitCode = 1; });
"""
            subprocess.run(['node', '-e', js, str(ROOT / 'webpatcher' / 'modpack.js')],
                           check=True)


@unittest.skipIf(shutil.which('node') is None, 'node not installed')
class DiscStreamComparison(unittest.TestCase):
    def test_comparison_checks_contents_and_length_without_replacing_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'worker.js').write_text(
                "self.onmessage = () => postMessage({type:'done', blob: new Blob(['disc bytes'])});\n")
            source = folder / 'source.bin'
            source.write_bytes(b'source')
            expected = folder / 'expected.bin'
            for contents, accepted in ((b'disc bytes', True), (b'disc byte!', False), (b'disc', False)):
                with self.subTest(contents=contents):
                    expected.write_bytes(contents)
                    stamp = expected.stat().st_mtime_ns
                    done = subprocess.run([
                        'node', str(ROOT / 'tools/tests/webpatcher_modpack.js'),
                        str(folder / 'modpack.js'), str(source), str(expected), '--compare'],
                        capture_output=True, text=True)
                    self.assertEqual(done.returncode == 0, accepted, done.stderr)
                    self.assertEqual(expected.read_bytes(), contents)
                    self.assertEqual(expected.stat().st_mtime_ns, stamp)


class FeatureWordingTest(unittest.TestCase):
    """Mod wording lives in each mod's src/mods/<mod>/mod.tsv (mods.py reads
    it; the release README, the layers and the generated webpatcher
    features.js all come from it). Every released mod must be named and
    explained there, and the generated file must match."""

    def test_every_released_mod_is_named_and_explained(self):
        import mods
        released = mods.released()
        self.assertTrue(released)
        for mod in released:
            self.assertTrue(mod.name.strip(), mod.label)
            self.assertTrue(mod.description.strip(), mod.label)
            self.assertEqual(Path(mod.folder).name, mods.slug(mod.name))

    def test_generated_features_file_matches_the_mods(self):
        import generate_features
        import mods

        with tempfile.TemporaryDirectory() as tmp:
            target = generate_features.generate(target=Path(tmp) / 'features.js')
            generated = target.read_text(encoding='utf-8')
        payload = generated.split('globalThis.FEATURES = ', 1)[1]
        features = json.loads(payload.split(';\nglobalThis.FEATURE_RENAMES', 1)[0])
        shown = mods.released() + [mod for mod in mods.load()
                                   if mod.always and mod.release]
        self.assertEqual(
            features,
            {mod.label: {'name': mod.name, 'description': mod.description,
                         **({'author': mod.author} if mod.author else {}),
                         **({'default': True} if mod.default else {}),
                         **({'always': True} if mod.always else {}),
                         **({'warning': mod.warning} if mod.warning else {}),
                         **({'integrates': [{'with': i.other, 'text': i.text}
                                            for i in mod.integrates]} if mod.integrates else {}),
                         **({'ranges': [{'key': r.key, 'minimum': r.minimum, 'maximum': r.maximum,
                                        'step': r.step, 'default': r.default, 'name': r.name}
                                       for r in mod.ranges]} if mod.ranges else {}),
                         **({'choices': [{'token': c.token, 'group': c.group, 'name': c.name,
                                          'description': c.description}
                                         for c in mod.choices]} if mod.choices else {})}
             for mod in shown})
        # always-on components first, then by name
        self.assertEqual(list(features), [mod.label for mod in sorted(
            shown, key=lambda mod: (not mod.always, mod.name.lower()))])


READER = r"""
require(require('path').join(require('path').dirname(process.argv[1]), 'lzma.js'));
require(process.argv[1]);
const fs = require('fs');
try {
  const pack = MODPACK.parseLayer(new Uint8Array(fs.readFileSync(process.argv[2])));
  const files = list => list.map(f => ({
    path: f.path, raw: f.raw, before: f.before, length: f.length, source: f.source,
    spans: f.spans.map(s => [s.offset, Buffer.from(s.bytes).toString('hex')])}));
  console.log(JSON.stringify({
    name: pack.name, author: pack.author, choices: pack.choices.map(c => [c.token, c.name]),
    requires: pack.requires,
    parts: pack.parts.map(p => ({when: p.when, files: files(p.files)})),
    picked: JSON.parse(process.argv[3]).map(sel => MODPACK.selected([pack], sel).map(l => l.name))}));
} catch (err) { console.error(err.message); process.exit(1); }
"""

# selections both sides pick parts for: {label: [tokens]}
SELECTIONS = [{}, {'test': ['font=small']}, {'test': ['font=small'], 'other': []},
              {'test': ['font=large', 'extra']}]


@unittest.skipIf(shutil.which('node') is None, 'node not installed')
class LayerFormatTest(unittest.TestCase):
    """A layer written by modpack.py parses identically in modpack.js, and
    both refuse a layout-owned file."""

    def layer(self):
        import modpack
        return modpack.Pack('test', [
            modpack.Part('test(font=large)', [
                modpack.FileEdit('ADV.BIN', False, 32, 40, 'ab' * 20,
                                 [modpack.Span(0, b'\x01\x02'), modpack.Span(30, b'\xff' * 10)])]),
            modpack.Part('test(font=small)', [
                modpack.FileEdit('ADV.BIN', False, 32, 40, 'ab' * 20,
                                 [modpack.Span(0, b'\x03\x04')])]),
            modpack.Part('other', [
                modpack.FileEdit('STR1/MV00.STR', True, 2352, 2352, None,
                                 [modpack.Span(24, bytes(range(16)))])]),
            modpack.Part('test(extra)', []),
        ], 'Test', 'about it', author='Example creator', requires=['base'],
            choices=[('font=large', 'Large'), ('font=small', 'Small'), ('extra', 'Extra')])

    def read_js(self, path):
        done = subprocess.run(['node', '-e', READER, str(ROOT / 'webpatcher' / 'modpack.js'),
                               str(path), json.dumps(SELECTIONS)], capture_output=True, text=True)
        return done

    def test_python_and_browser_read_the_same_layer(self):
        import modpack
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.p1mod'
            modpack.write_layer(str(path), self.layer())
            self.assertEqual(modpack.read_layer(str(path)), self.layer())
            import persona_patch
            self.assertEqual(persona_patch.parse_layer(path.read_bytes())['name'], 'test')
            done = self.read_js(path)
            self.assertEqual(done.returncode, 0, done.stderr)
            parsed = json.loads(done.stdout)
            picked = [[layer.name for layer in modpack.selected(
                [str(path)], {label: frozenset(tokens) for label, tokens in sel.items()})]
                for sel in SELECTIONS]
        self.assertEqual(picked, [['test[test(font=large)]'],
                                  ['test[test(font=small)]'],
                                  ['test[test(font=small)]', 'test[other]'],
                                  ['test[test(font=large)]', 'test[test(extra)]']])
        self.assertEqual(parsed, {
            'name': 'test', 'author': self.layer().author, 'choices': [list(c) for c in self.layer().choices],
            'requires': ['base'],
            'parts': [{'when': part.when, 'files': [
                {'path': f.path, 'raw': f.raw, 'before': f.before, 'length': f.length,
                 'source': f.source, 'spans': [[s.offset, s.data.hex()] for s in f.spans]}
                for f in part.files]} for part in self.layer().parts],
            'picked': picked})

    def test_only_current_format_is_accepted_by_all_readers(self):
        import modpack
        import persona_patch
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.p1mod'
            modpack.write_layer(str(path), self.layer())
            blob = path.read_bytes()
            self.assertTrue(blob.startswith(b'P1MOD\t1\n'))
            for version in (2, 3, 4, 5):
                changed = f'P1MOD\t{version}\n'.encode() + blob[len(modpack.MAGIC):]
                path.write_bytes(changed)
                with self.assertRaises(ValueError):
                    modpack.read_layer(str(path))
                with self.assertRaises(SystemExit):
                    persona_patch.parse_layer(changed)
                self.assertNotEqual(self.read_js(path).returncode, 0)

    def test_layer_written_twice_is_identical(self):
        import modpack
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / 'a.p1mod', Path(tmp) / 'b.p1mod'
            modpack.write_layer(str(a), self.layer())
            modpack.write_layer(str(b), self.layer())
            self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_layout_files_are_refused(self):
        import modpack
        layer = modpack.Layer('bad', [modpack.FileEdit('FSECT.DAT', False, 4, 4, None,
                                                       [modpack.Span(0, b'\0\0\0\0')])])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                modpack.write_layer(str(Path(tmp) / 'bad.p1mod'), layer)




class DependencyControls(unittest.TestCase):
    def test_dependencies_lock_and_release_without_turning_dependents_off(self):
        app = (ROOT / 'webpatcher/app.js').read_text()
        functions = app[app.index('function neededOptions('):app.index('const releaseStamp')]
        script = r"""
const assert = require('assert');
const requirementsOf = row => (row.requires || '').split(',').filter(Boolean);
const state = {labels: ['alphabet', 'english', 'mod'], rows: [
  {kind: 'option', label: 'alphabet'},
  {kind: 'option', label: 'english', requires: 'alphabet'},
  {kind: 'option', label: 'mod', requires: 'english'},
], ownMods: []};
const boxes = state.labels.map(value => ({value, checked: false, disabled: false,
  dataset: {}, classList: {contains: () => true},
  closest: () => ({classList: {toggle: () => {}}})}));
const document = {querySelectorAll: selector => selector.startsWith('#choices') ? boxes : []};
const refreshSettings = () => {};
""" + functions + r"""
const [alphabet, english, mod] = boxes;
mod.checked = true;
followRequirements(mod);
assert(alphabet.checked && alphabet.disabled);
assert(english.checked && english.disabled);
assert(mod.checked && !mod.disabled);
mod.checked = false;
followRequirements(mod);
assert(!alphabet.checked && !alphabet.disabled);
assert(!english.checked && !english.disabled);
// A dependency selected by hand remains enabled when its dependent goes off.
english.checked = true;
followRequirements(english);
mod.checked = true;
followRequirements(mod);
assert(english.disabled);
mod.checked = false;
followRequirements(mod);
assert(english.checked && !english.disabled);
assert(alphabet.checked && alphabet.disabled);
english.checked = false;
followRequirements(english);
// Uploaded mods lock their release dependencies too.
state.ownMods = [{name: 'uploaded', on: true, requires: ['english']}];
followRequirements(null);
assert(english.checked && english.disabled);
assert(alphabet.checked && alphabet.disabled);
state.ownMods[0].on = false;
followRequirements(null);
assert(!english.checked && !english.disabled);
assert(!alphabet.checked && !alphabet.disabled);
// The same graph applies between uploaded mods, including transitive needs.
state.ownMods = [
  {name: 'parent', on: true, requires: ['child']},
  {name: 'child', on: false, requires: ['english']},
];
followRequirements(null);
assert(state.ownMods[1].on && state.ownMods[1].required);
assert(english.checked && english.disabled && alphabet.disabled);
state.ownMods[0].on = false;
followRequirements(null);
assert(!state.ownMods[1].on && !state.ownMods[1].required);
assert(!english.checked && !english.disabled && !alphabet.disabled);
"""
        subprocess.run(['node', '-e', script], check=True, cwd=ROOT)


if __name__ == '__main__':
    unittest.main()
