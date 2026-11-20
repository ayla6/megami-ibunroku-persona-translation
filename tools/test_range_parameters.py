"""Range settings must produce identical bytes in every patcher, at every level."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import toolpath
import modpack
import mods
import persona_patch
from range_parameters import RangeSetting, Scale, apply_files

class RangeParameters(unittest.TestCase):
    def test_running_accepts_only_integer_speeds_two_through_four(self):
        mod = mods.by_label()['run-in-dungeons']
        self.assertEqual(mod.defaults(), frozenset({'speed=2'}))
        for value in (2, 3, 4):
            self.assertEqual(mod.pick(f'speed={value}'), frozenset({f'speed={value}'}))
        for value in ('1', '5', '2.5', '-3', 'nan'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                mod.pick(f'speed={value}')

    def test_native_byte_settings_match_layer_values_and_reject_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build = root / 'build'
            build.mkdir()
            target = build / 'DNG.BIN'
            target.write_bytes(b'\0\2\0')
            table = root / 'values.tsv'
            table.write_text('path\toffset\tparameter\toriginal\nDNG.BIN\t1\tspeed\t100\n')
            setting = RangeSetting('speed', 2, 4, 1, 2, 'Speed', 'values.tsv')
            for speed in (2, 3, 4):
                apply_files(root, build, [setting], lambda key: str(speed))
                self.assertEqual(target.read_bytes(), bytes([0, Scale(1, 'speed', 100).value(speed), 0]))
            table.write_text('path\toffset\tparameter\toriginal\n../outside\t1\tspeed\t100\n')
            with self.assertRaisesRegex(ValueError, 'escapes'):
                apply_files(root, build, [setting], lambda key: '4')

    def test_metadata_accepts_arbitrary_values_and_rejects_invalid_values(self):
        mod = mods.by_label()['softer-menu-sounds']
        for value in range(101):
            self.assertEqual(mod.pick(f'level={value}'), frozenset((f'level={value}',)))
        for value in ('-1', '101', '77.5', 'nan', '1e1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                mod.pick(f'level={value}')

    def test_all_values_match_python_standalone_and_browser_without_mutation(self):
        setting = RangeSetting('amount', 0, 100, 1, 80, 'Amount')
        edit = modpack.FileEdit('TEST.BIN', False, 3, 3, None,
                               [modpack.Span(1, b'P')], [Scale(1, 'amount', 100)])
        pack = modpack.Pack('test', [modpack.Part('', [edit])], ranges=[setting])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.p1mod'
            modpack.write_layer(str(path), pack)
            loaded = modpack.read_layer(str(path))
            self.assertEqual(loaded, pack)
            standalone = persona_patch.parse_layer(path.read_bytes())
            for percent in range(101):
                token = f'amount={percent}'
                py = modpack.selected([loaded], {'test': frozenset((token,))})
                cli = persona_patch.selected([standalone], {'test': [token]})
                self.assertEqual(py[0].files[0].spans[-1].data, bytes([percent]))
                self.assertEqual(cli[0][1][0].spans[-1][1], bytes([percent]))
            script = r'''
require(process.argv[1] + '/webpatcher/lzma.js');
require(process.argv[1] + '/webpatcher/modpack.js');
const fs = require('fs');
const pack = MODPACK.parseLayer(new Uint8Array(fs.readFileSync(process.argv[2])));
const values = Array.from({length: 101}, (_, p) =>
  [...MODPACK.selected([pack], {test: ['amount=' + p]})[0].files[0].spans.at(-1).bytes][0]);
for (const value of ['101', '-1', '1.2']) {
  let refused = false;
  try { MODPACK.selected([pack], {test: ['amount=' + value]}); } catch { refused = true; }
  if (!refused) throw Error('invalid value accepted');
}
console.log(JSON.stringify(values));
'''
            done = subprocess.run(['node', '-e', script, str(ROOT), str(path)],
                                  capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(done.stdout), list(range(101)))
            self.assertEqual(loaded, pack)
            self.assertEqual(edit.spans, [modpack.Span(1, b'P')])

    def test_browser_range_control_synchronizes_slider_and_number(self):
        app = (ROOT / 'webpatcher/app.js').read_text()
        sub = app[app.index('function subChoices('):app.index('/* Mods: one toggle', app.index('function subChoices('))]
        picked = app[app.index('function pickedTokens('):app.index('/* The selection as a build', app.index('function pickedTokens('))]
        script = r"""
const assert = require('assert');
const inputs = [];
function element(tag) {
 const result = {tag, dataset: {}, children: [], handlers: {}, append(...nodes) {this.children.push(...nodes);},
 setAttribute() {}, addEventListener(name, fn) {this.handlers[name] = fn;}};
 if (tag === 'input') inputs.push(result);
 return result;
}
const document = {createElement: element, querySelectorAll(selector) {
 return selector.endsWith('input:checked') ? inputs.filter(i => i.checked) : inputs.filter(i => i.dataset.parameter);
}};
const choicesOf = () => [];
const featureOf = () => ({ranges: [{key: 'level', minimum: 0, maximum: 100, step: 1, default: 80, name: 'Volume (%)'}]});
const defaultTokens = () => ['level=80'];
""" + sub + picked + r"""
subChoices('test');
const slider = inputs.find(i => i.type === 'range');
const number = inputs.find(i => i.type === 'number');
number.value = '63'; number.handlers.change();
assert.equal(slider.value, 63); assert.deepEqual(pickedTokens('test'), ['level=63']);
slider.value = '27'; slider.handlers.input();
assert.equal(number.value, '27'); assert.deepEqual(pickedTokens('test'), ['level=27']);
number.value = '0'; number.handlers.change();
assert.deepEqual(pickedTokens('test'), ['level=0']);
number.value = '101'; number.handlers.change();
assert.deepEqual(pickedTokens('test'), ['level=100']);
"""
        subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)
