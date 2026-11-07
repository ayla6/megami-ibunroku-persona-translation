"""Batch variants share preparation but assemble and verify independently."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import build
import features
import dngnames
sys.path.insert(0, str(ROOT / 'src/extraction_tools/matching'))
import mappings


class Variants(unittest.TestCase):
    def test_selection_and_distinct_output_paths(self):
        variants = build.build_variants(['--variants=base;saves;60fps,saves'])
        self.assertEqual([p for p, _ in variants], [[], ['saves'], ['saves', '60fps']])
        self.assertEqual([Path(path).name for _, path in variants],
                         ['Persona-TL-base.bin', 'Persona-TL-saves.bin', 'Persona-TL-saves-60fps.bin'])

    def test_invalid_and_ambiguous_combinations_fail(self):
        for args in (['--variants'], ['--variants='], ['--variants=base;'],
                     ['--variants=base;base'], ['--variants=saves;saves,saves'],
                     ['--variants=base', '--qol=saves'], ['--variants=base', '--no-disc'],
                     ['--variants=typo']):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                build.build_variants(args)

    def test_each_variant_assembles_verifies_and_writes_its_own_disc(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(build, 'run') as run, \
                patch.object(build, 'run_from') as assemble, \
                patch.object(features, 'on', return_value=True):
            base = str(Path(tmp) / 'base.bin')
            saves = str(Path(tmp) / 'saves.bin')
            build.assemble_variant(sys.executable, [], base)
            build.assemble_variant(sys.executable, ['saves'], saves)
        self.assertEqual(assemble.call_count, 2)
        self.assertNotIn('QOL_SAVES', assemble.call_args_list[0].args)
        self.assertIn('QOL_SAVES', assemble.call_args_list[1].args)
        commands = [call.args for call in run.call_args_list]
        # variant-independent outputs are generated once by main(), not per
        # variant; each variant still assembles and verifies its own outputs
        self.assertFalse(any('save_ui.py' in str(args) for args in commands))
        self.assertEqual(sum('dngspill.py' in str(args) and 'verify' in args for args in commands), 2)
        discs = [args for args in commands if 'build_disc.py' in str(args)]
        self.assertEqual([args[-3] for args in discs], [base, saves])
        # every variant image is published with its placement record, which is
        # what lets the release audit run without the build tree
        self.assertEqual([args[-1] for args in discs],
                         [path + '.placement.tsv' for path in (base, saves)])

    def test_mark_artwork_is_built_and_verified_without_a_callback(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(build, 'run') as run, \
                patch.object(build, 'run_from'), \
                patch.object(features, 'on', return_value=True):
            build.assemble_variant(sys.executable, ['mark'],
                                   str(Path(tmp) / 'mark.bin'), make_disc=False)
        commands = [str(call.args) for call in run.call_args_list]
        self.assertEqual(sum("mark.py', 'build'" in c for c in commands), 1)
        self.assertEqual(sum("mark.py', 'verify'" in c for c in commands), 1)

    def test_mark_callback_supplies_already_verified_artwork(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(build, 'run') as run, \
                patch.object(build, 'run_from'), \
                patch.object(features, 'on', return_value=True):
            callback = unittest.mock.Mock()
            build.assemble_variant(sys.executable, ['mark'],
                                   str(Path(tmp) / 'mark.bin'), make_disc=False,
                                   mark_builder=callback)
        callback.assert_called_once()
        commands = [str(call.args) for call in run.call_args_list]
        # the callback owns generation and verification; repeating the pixel
        # decode for byte-identical restored files would prove nothing new
        self.assertFalse(any("mark.py', 'verify'" in c for c in commands))

    def test_batch_prepares_once_then_assembles_each_variant(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(sys, 'argv', ['build.py', '--variants=base;saves']), \
                patch.object(build, 'ROOT', tmp), patch.object(build, 'ORIGINAL_DIR', tmp), \
                patch.object(build, 'ARMIPS', 'armips'), \
                patch.object(build.image_check, 'require'), \
                patch.object(build.disc_data, 'psx_complete', return_value=True), \
                patch.object(build.disc_data, 'ensure_psp'), \
                patch.object(features, 'from_argv', return_value={'SF_VWF': True}), \
                patch.object(features, 'write', return_value={'SF_VWF': True}), \
                patch.object(features, 'describe', return_value='test'), \
                patch.object(mappings, 'ensure'), \
                 patch.object(build, 'run') as run, \
                 patch.object(build, 'run_from'), \
                 patch.object(build, 'prepare_tables'), patch.object(build, 'prepare_vwf_font'), \
                 patch.object(build, 'prepare_fmv_data') as fmv, \
                patch.object(build, 'assemble_variant') as assemble:
            build.main()
        commands = [str(call.args) for call in run.call_args_list]
        self.assertEqual(sum('matching/port.py' in c for c in commands), 1)
        self.assertEqual(sum('dngpacks.py' in c and 'build' in c for c in commands), 1)
        self.assertEqual(sum('name_tails.py' in c and 'build' in c for c in commands), 1)
        # Shared (variant-independent) outputs are generated once. The tests
        # that execute assembled files run once too, but only after the first
        # variant exists (a clean build/ has no ADV.BIN or SLPS_005.00).
        for marker in ('save_ui.py', 'talktl.py',
                       "'injection_tools/talk.py', 'build'",
                       "'injection_tools/etctalk.py'", 'endtext.py',
                       'test_giftmsg_inventory.py', 'test_qol_saves.py'):
            self.assertEqual(sum(marker in c for c in commands), 1, marker)
        self.assertEqual(fmv.call_count, 1)
        self.assertEqual(assemble.call_count, 2)
        self.assertEqual([c.args[1] for c in assemble.call_args_list], [[], ['saves']])

    def test_no_port_still_builds_assembly_inputs(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(sys, 'argv', ['build.py', '--no-port', '--no-disc']), \
                patch.object(build, 'ROOT', tmp), patch.object(build, 'ORIGINAL_DIR', tmp), \
                patch.object(build, 'ARMIPS', 'armips'), \
                patch.object(build.disc_data, 'psx_complete', return_value=True), \
                patch.object(features, 'from_argv', return_value={'SF_VWF': True}), \
                patch.object(features, 'write', return_value={'SF_VWF': True}), \
                patch.object(features, 'describe', return_value='test'), \
                patch.object(build, 'run') as run, patch.object(build, 'run_from'), \
                patch.object(build, 'prepare_tables'), patch.object(build, 'prepare_vwf_font'), \
                patch.object(build, 'prepare_fmv_data'), patch.object(build, 'assemble_variant'):
            build.main()
        commands = [str(call.args) for call in run.call_args_list]
        self.assertTrue(any('name_tails.py' in c for c in commands))
        self.assertTrue(any('dngnames.py' in c for c in commands))
        self.assertFalse(any('matching/port.py' in c for c in commands))

    def test_dungeon_title_assets_are_generated_from_current_rows(self):
        rows, resolved = [object()], {'key': 'value'}
        with patch.object(dngnames, 'psx_floor_rows', return_value=[('rel', 1, 'ja')]), \
                patch.object(dngnames, 'resolved_en', return_value=resolved), \
                patch.object(dngnames, 'emit_titles') as emit, \
                patch.object(dngnames.glob, 'glob', return_value=[]):
            dngnames.main()
        emit.assert_called_once_with([('rel', 1, 'ja', '', '')], resolved)

    def test_assembly_can_be_written_onto_an_existing_image(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(build, 'run') as run, \
                patch.object(build, 'run_from'), \
                patch.object(features, 'on', return_value=True):
            build.assemble_variant(sys.executable, ['saves'],
                                   str(Path(tmp) / 'saves.bin'),
                                   source_image='/parent/saves.bin')
        discs = [call.args for call in run.call_args_list
                 if 'build_disc.py' in str(call.args)]
        self.assertEqual(len(discs), 1)
        self.assertEqual(discs[0][2], '/parent/saves.bin')

    def test_batch_asks_for_a_source_image_per_variant(self):
        variants = [([], 'base.bin'), (['mark'], 'mark.bin')]
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(sys, 'argv', ['build.py', '--no-port']), \
                patch.object(build, 'ROOT', tmp), patch.object(build, 'ORIGINAL_DIR', tmp), \
                patch.object(build, 'ARMIPS', 'armips'), \
                patch.object(build.image_check, 'require'), \
                patch.object(build.disc_data, 'psx_complete', return_value=True), \
                patch.object(features, 'from_argv', return_value={'SF_VWF': False}), \
                patch.object(features, 'write', return_value={'SF_VWF': False}), \
                patch.object(features, 'describe', return_value='test'), \
                patch.object(build, 'run'), patch.object(build, 'run_from'), \
                patch.object(build, 'prepare_tables'), patch.object(build, 'prepare_vwf_font'), \
                patch.object(build, 'prepare_fmv_data'), \
                patch.object(build, 'assemble_variant') as assemble:
            build.main(variants_override=variants,
                       source_image_for=lambda patches:
                       'base.bin' if not patches else 'from-' + '-'.join(patches))
        self.assertEqual([call.kwargs.get('source_image')
                          for call in assemble.call_args_list],
                         ['base.bin', 'from-mark'])

    def test_variant_callback_runs_after_each_assembly(self):
        variants = [([], 'base.bin'), (['mark'], 'mark.bin')]
        events = []
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(sys, 'argv', ['build.py', '--no-port']), \
                patch.object(build, 'ROOT', tmp), patch.object(build, 'ORIGINAL_DIR', tmp), \
                patch.object(build, 'ARMIPS', 'armips'), patch.object(build.image_check, 'require'), \
                patch.object(build.disc_data, 'psx_complete', return_value=True), \
                patch.object(features, 'from_argv', return_value={'SF_VWF': False}), \
                patch.object(features, 'write', return_value={'SF_VWF': False}), \
                patch.object(features, 'describe', return_value='test'), \
                patch.object(build, 'run'), patch.object(build, 'run_from'), \
                patch.object(build, 'prepare_tables'), patch.object(build, 'prepare_vwf_font'), \
                patch.object(build, 'prepare_fmv_data'), \
                patch.object(build, 'assemble_variant', side_effect=lambda _py, patches, path, **kw:
                             events.append(('build', tuple(patches), path))):
            build.main(variants_override=variants,
                       after_variant=lambda patches, path: events.append(('check', tuple(patches), path)))
        self.assertEqual(events, [('build', (), 'base.bin'), ('check', (), 'base.bin'),
                                  ('build', ('mark',), 'mark.bin'), ('check', ('mark',), 'mark.bin')])


if __name__ == '__main__':
    unittest.main()
