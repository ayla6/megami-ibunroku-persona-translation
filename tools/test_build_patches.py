"""The layer release (tools/build_patches.py): names and order, mod choices,
which mod pairs get a part for each other, the manifest, the CHD identity of
the original."""
import hashlib
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import build_patches as release  # noqa: E402
import modpack  # noqa: E402


class ReleaseNames(unittest.TestCase):
    def test_foundation_choice_keeps_original_disc_validation(self):
        class Source:
            entries = {'BTLP.BIN': None}

            def read(self, path, raw=False):
                return b'retail'

        source = Source()
        root = modpack.Pack('base', [modpack.Part('', []), modpack.Part(
            'base(negotiation-inset=off)', [modpack.FileEdit(
                'BTLP.BIN', False, 6, 6, spans=[modpack.Span(0, b'R')])])])
        dependent = modpack.Layer('latin-alphabet', [modpack.FileEdit(
            'BTLP.BIN', False, 6, 6, spans=[modpack.Span(1, b'E')])])
        release.guard_retail_inputs(source, root, dependent)
        selection = {'base': frozenset({'negotiation-inset=off'})}
        files, _ = modpack.merge(source, [root, dependent], selection)
        self.assertEqual(files['BTLP.BIN'], b'REtail')
        with unittest.mock.patch.object(Source, 'read', return_value=b'broken'):
            with self.assertRaisesRegex(ValueError, 'not the file'):
                modpack.merge(source, [root, dependent], selection)

    def test_tier_children_initialize_paths_before_importing_build_tools(self):
        code = """import sys
from pathlib import Path
sys.path.insert(0, 'tools')
import build_patches
import toolpath
assert build_patches.build.ENGINE_ONLY
assert Path(toolpath.TRANSLATION).resolve() == (build_patches.ROOT / 'build/engine-translation').resolve()
"""
        for flag in ('--base-only', '--engine-only'):
            with self.subTest(flag=flag):
                subprocess.run([sys.executable, '-c', code, flag], cwd=ROOT, check=True)

    def test_one_layer_per_mod_base_first(self):
        names = release.release_file_names()
        self.assertEqual(names[0], release.BASE_LAYER)
        self.assertEqual(names[:3], ['base.p1mod', 'latin-alphabet.p1mod',
                                    'english-translation.p1mod'])
        self.assertEqual(names[3:], [release.option_layer(label)
                                     for label in release.CHOICE_ORDER])

    def test_layer_files_are_named_after_the_option_names(self):
        self.assertEqual(release.slug('Save menu'), 'save-menu')
        self.assertEqual(release.slug('GAME END goes to the title screen'),
                         'game-end-goes-to-the-title-screen')
        release.check_choices()     # every option name makes its own file name

    def test_a_mod_folder_must_be_named_after_its_mod(self):
        import mods
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'not-its-name'
            folder.mkdir()
            (folder / 'mod.tsv').write_text(
                'name\tSome mod\ndescription\td\n'
                'default\tno\nalways\tno\nrelease\tyes\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'some-mod'):
                mods._read(str(folder))


class Choices(unittest.TestCase):
    """A mod's options and extras (mod.tsv), named on the mod in a build."""

    def test_english_font_group(self):
        import mods
        english = mods.by_label()['english-translation']
        self.assertEqual(english.defaults(), {'font=large', 'subtitles=on'})
        self.assertEqual(english.pick('font=small'), {'font=small', 'subtitles=on'})
        with self.assertRaisesRegex(ValueError, 'no choice'):
            english.pick('font=tiny')
        self.assertEqual(release.condition(english, {'font=small'}), 'english-translation(font=small)')
        self.assertEqual([(m.label, c.token) for m, c in release.other_choices()],
                         [('base', 'negotiation-inset=off'),
                          ('english-translation', 'font=small'),
                          ('english-translation', 'subtitles=off')])
        # one choice per group: the pairs are across groups
        self.assertEqual(len(release.choice_pairs()), 1)

    def test_a_marker_comes_with_what_requires_it(self):
        import mods
        english = mods.by_label()['english-translation']
        self.assertTrue(mods.by_label()['fmv-translation'].marker)
        self.assertNotIn('fmv-translation', [m.label for m in mods.pickable()])
        self.assertIn('fmv-translation', mods.with_needs([], {}))           # English's subtitles need it
        none = {'english-translation': english.pick('subtitles=off')}
        self.assertEqual(mods.with_needs(['black-mark'], none), ['black-mark'])   # Black Mark needs nothing
        self.assertIn('fmv-translation', mods.with_needs(['skip-movies'], none))      # its stub's home

    def test_a_mod_list_names_choices_in_parentheses(self):
        import mods
        self.assertEqual(mods.parse_mods('english-translation(font=small, x),60-fps'),
                         [('english-translation', 'font=small, x'), ('60-fps', '')])
        for bad in ('a(b', 'a)b', 'a(b(c))'):
            with self.assertRaises(ValueError, msg=bad):
                mods.parse_mods(bad)


class Requirements(unittest.TestCase):

    def test_a_requirement_is_a_label_without_a_version(self):
        import mods
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'some-mod'
            folder.mkdir()
            (folder / 'mod.tsv').write_text(
                'name\tSome mod\ndescription\td\n'
                'default\tno\nalways\tno\nrelease\tyes\nrequires\tbase\t1.0\n',
                encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'the release is the version'):
                mods._read(str(folder))

    def test_layers_only_require_mods_with_a_layer(self):
        import mods
        for mod in mods.load():
            for label in release.requirements(mod):
                self.assertTrue(mods.by_label()[label].release, label)
        self.assertEqual(release.requirements(mods.by_label()['unified-save-menu']), ['base'])

    def test_mods_come_after_what_they_require(self):
        import mods
        mod = lambda name, *needs: mods.Mod(name, '', needs, False, False, True, '')
        self.assertEqual([m.label for m in mods.ordered(
            [mod('a', 'c'), mod('b'), mod('c')])], ['b', 'c', 'a'])
        with self.assertRaisesRegex(ValueError, 'circle'):
            mods.ordered([mod('a', 'b'), mod('b', 'a')])
        with self.assertRaisesRegex(ValueError, 'not a mod'):
            mods.ordered([mod('a', 'x')])
        with self.assertRaisesRegex(ValueError, 'comes before it'):
            mods.check_requirements([mod('a', 'b'), mod('b')])


class OverlappingPairs(unittest.TestCase):
    """Only mods whose parts write the same bytes are built together."""

    def test_pairs_are_the_mods_writing_the_same_bytes(self):
        a, b, c = release.CHOICE_ORDER[:3]

        def pack(label, edits):
            return modpack.Pack(label, [modpack.Part('', [
                modpack.FileEdit(path, False, 100, 100, None, [modpack.Span(offset, b'x' * size)])
                for path, offset, size in edits])])
        packs = {label: pack(label, []) for label in release.CHOICE_ORDER}
        packs[a] = pack(a, [('BTLP.BIN', 10, 8)])
        packs[b] = pack(b, [('BTLP.BIN', 14, 4), ('DNG.BIN', 0, 4)])
        packs[c] = pack(c, [('BTLP.BIN', 18, 4), ('DNG.BIN', 4, 4)])   # touches, no overlap
        self.assertEqual(release.overlapping_pairs(packs), [(a, b)])

    def test_distinct_archive_entries_do_not_require_a_pair_build(self):
        from format_edits import EntryEdit
        a, b, c = release.CHOICE_ORDER[:3]
        packs = {label: modpack.Pack(label, []) for label in release.CHOICE_ORDER}
        for label, index in ((a, 3), (b, 8), (c, 3)):
            edit = modpack.FileEdit('ADV/MES.BIN', False, 2048, 4096,
                                    entries=[EntryEdit(index, b'prepared', 'source')])
            packs[label].parts = [modpack.Part('', [edit])]
        self.assertEqual(release.overlapping_pairs(packs), [(a, c)])


class Manifest(unittest.TestCase):

    def test_manifest_round_trips_and_an_xdelta_manifest_counts_as_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'manifest.tsv'
            rows = [{'layer': 'base.p1mod', 'kind': 'base', 'label': 'english-translation',
                     'state': 'verified',
                     'choices': 'font=large,font=small', 'requires': '', 'version': '',
                     'bytes': '1', 'sha1': 'ab', 'build_key': 'k', 'source_bytes': '2',
                     'source_chd_sha1': 'cd', 'release': ''}]
            release.write_manifest(path, rows)
            self.assertEqual(release.read_manifest(path), {'base.p1mod': rows[0]})
            path.write_text('patch\tadds\nrev0-to-base.xdelta\t\n', encoding='utf-8')
            self.assertEqual(release.read_manifest(path), {})


class ChdIdentity(unittest.TestCase):

    def test_raw_sha1_covers_frames_with_subcode_and_track_padding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'disc.bin'
            sectors = [bytes([n]) * 2352 for n in range(5)]
            path.write_bytes(b''.join(sectors))
            expect = hashlib.sha1()
            for sector in sectors:
                expect.update(sector + bytes(96))
            for _ in range(3):              # 5 frames pad to 8
                expect.update(bytes(2448))
            self.assertEqual(release.chd_raw_sha1(path), expect.hexdigest())




class SparseTrees(unittest.TestCase):
    def test_snapshot_reads_share_hard_links_and_invalidate_on_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, second = root / 'first', root / 'second'
            first.mkdir()
            second.mkdir()
            original = first / 'FILE.BIN'
            linked = second / original.name
            original.write_bytes(b'first')
            os.link(original, linked)
            source = unittest.mock.Mock(entries={'FILE.BIN': (0, 5)})

            self.assertEqual(release.kept_tree(source, first), {'FILE.BIN': b'first'})
            with unittest.mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('reread')):
                self.assertEqual(release.kept_tree(source, second), {'FILE.BIN': b'first'})

            stamp = original.stat().st_mtime_ns
            linked.write_bytes(b'other')
            os.utime(linked, ns=(stamp, stamp))
            self.assertEqual(release.kept_tree(source, first), {'FILE.BIN': b'other'})
            source.read.assert_not_called()

    def test_tree_read_cache_detects_edits_with_preserved_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            changed = root / 'changed.bin'
            retail = root / 'retail.bin'
            changed.write_bytes(b'edit')
            retail.write_bytes(b'orig')
            source = unittest.mock.Mock()
            source.read.return_value = b'orig'
            paths = {'CHANGED.BIN': str(changed), 'RETAIL.BIN': str(retail)}
            with unittest.mock.patch.object(release.modpack, 'tree', return_value=paths):
                self.assertEqual(release.tree_files(source, root), {'CHANGED.BIN': b'edit'})
                with unittest.mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('reread')):
                    self.assertEqual(release.tree_files(source, root), {'CHANGED.BIN': b'edit'})
                stamp = changed.stat().st_mtime_ns
                changed.write_bytes(b'next')
                os.utime(changed, ns=(stamp, stamp))
                self.assertEqual(release.tree_files(source, root), {'CHANGED.BIN': b'next'})

    def test_snapshots_share_only_immutable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / 'build/FILE.BIN'
            live.parent.mkdir()
            live.write_bytes(b'changed')
            source = unittest.mock.Mock()
            source.read.return_value = b'retail'
            with unittest.mock.patch.object(release, 'ROOT', root), \
                 unittest.mock.patch.object(release.modpack, 'tree',
                                            return_value={'FILE.BIN': str(live)}):
                first, second = root / 'first', root / 'second'
                release.save_tree(source, first)
                release.save_tree(source, second)
                a, b = first / 'FILE.BIN', second / 'FILE.BIN'
                self.assertEqual(a.stat().st_ino, b.stat().st_ino)
                self.assertNotEqual(a.stat().st_ino, live.stat().st_ino)
                live.write_bytes(b'new live output')
                self.assertEqual(a.read_bytes(), b'changed')
                self.assertEqual(b.read_bytes(), b'changed')


class NativeMetrics(unittest.TestCase):
    def test_untranslated_trait_keeps_native_position(self):
        import btlui
        import struct
        data = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        native = struct.unpack_from('<h', data, 0x800DEBF4 - btlui.B)[0]
        with unittest.mock.patch.object(btlui.strlib, 'glossary',
                                        return_value={'0x800dea3c': ''}), \
             unittest.mock.patch.object(btlui.smallfont_vwf, 'btl_orig_px',
                                        side_effect=AssertionError('font artifact read')):
            self.assertEqual(btlui.trait_line_x(data), native)

    def test_disabled_vwf_does_not_read_width_artifacts(self):
        import btlui
        with unittest.mock.patch.object(btlui.features, 'on', return_value=False), \
             unittest.mock.patch('builtins.open', side_effect=AssertionError('artifact read')):
            self.assertEqual(btlui.analyze_tiers(), [])

    def test_no_spills_replaces_the_previous_spill_file(self):
        import btlp
        stock = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'spills.asm'
            target.write_text('.org 0x80000000\n.byte 1\n')
            with unittest.mock.patch.object(btlp, 'MSG_OUT_SLPS', str(target)):
                btlp.msg_build(stock, {}, [])
            self.assertNotIn('.org', target.read_text())

    def test_dub_cache_uses_cue_timing_without_subtitle_wording(self):
        import fmv_dub
        with tempfile.TemporaryDirectory() as tmp:
            subtitles = Path(tmp) / 'subtitles.tsv'
            def rows(text, end):
                subtitles.write_text('movie\tstart_s\tend_s\ttext\n'
                                     f'clip\t0\t{end}\t{text}\n')
            with unittest.mock.patch.object(fmv_dub, 'SUBTITLES', str(subtitles)), \
                 unittest.mock.patch.object(fmv_dub, 'PSP_AUDIO', tmp + '/audio'), \
                 unittest.mock.patch.object(release.build_step_cache, 'fingerprint', return_value='code'):
                rows('wording', 1)
                first = fmv_dub.movie_key('retail', 'clip', [])
                rows('', 1)
                self.assertEqual(fmv_dub.movie_key('retail', 'clip', []), first)
                rows('', 2)
                self.assertNotEqual(fmv_dub.movie_key('retail', 'clip', []), first)


class MergeDiagnostics(unittest.TestCase):
    def test_byte_merge_matches_with_and_without_conflict_reports(self):
        import modpack
        source = unittest.mock.Mock()
        source.entries = {'FILE.BIN': (0, 8)}
        source.read.return_value = b'00000000'
        layers = [modpack.Layer('a', [modpack.FileEdit('FILE.BIN', False, 8, 8,
                        spans=[modpack.Span(2, b'abc')])]),
                  modpack.Layer('b', [modpack.FileEdit('FILE.BIN', False, 8, 8,
                        spans=[modpack.Span(3, b'bZ')])])]
        slow, reports = modpack.merge(source, layers, strict=False)
        fast, omitted = modpack.merge(source, layers, strict=False, track_clashes=False)
        self.assertEqual(slow, fast)
        self.assertEqual(reports, {('a', 'b', 'FILE.BIN'): 1})
        self.assertEqual(omitted, {})
        layers[0].files[0].spans = [modpack.Span(7, b'bad')]
        for tracking in (False, True):
            with self.assertRaisesRegex(ValueError, 'span outside'):
                modpack.merge(source, layers, strict=False, track_clashes=tracking)

    def test_voice_cache_is_independent_of_equivalent_map_locations(self):
        import battle_voice
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / 'a.tsv', Path(tmp) / 'b.tsv'
            first.write_text('identical map')
            second.write_text('identical map')
            with unittest.mock.patch.object(battle_voice, 'MAP', str(first)):
                key = battle_voice.cache_key()
            with unittest.mock.patch.object(battle_voice, 'MAP', str(second)):
                self.assertEqual(battle_voice.cache_key(), key)
                second.write_text('changed map')
                self.assertNotEqual(battle_voice.cache_key(), key)


if __name__ == '__main__':
    unittest.main()


class LayoutWorkspace(unittest.TestCase):
    def test_uses_ram_when_it_fits_and_disk_when_it_does_not(self):
        from types import SimpleNamespace
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ram = root / 'ram'
            ram.mkdir()
            image = root / 'disc.bin'
            image.write_bytes(bytes(100))
            for free, parent in ((300, ram), (299, root/'build')):
                with self.subTest(free=free), unittest.mock.patch.object(release, 'ROOT', root), \
                        unittest.mock.patch.object(release.shutil, 'disk_usage', return_value=SimpleNamespace(free=free)):
                    work = release.layout_workspace(image, ram)
                    try:
                        self.assertEqual(work.parent, parent)
                        self.assertTrue(work.is_dir())
                    finally:
                        shutil.rmtree(work)


class DubRenderInputs(unittest.TestCase):
    def test_equal_audio_inputs_share_key_across_translation_paths(self):
        import fmv_dub
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            keys = []
            for tier in ('engine', 'english'):
                folder = root/tier
                folder.mkdir()
                subtitles = folder/'subtitles.tsv'
                subtitles.write_text('movie\tstart_s\tend_s\ten\nclip\t1\t2\twords\n')
                audio = folder/'audio'
                audio.mkdir()
                jp = folder/'audio_jp'
                jp.mkdir()
                (audio/'clip.flac').write_bytes(b'English track')
                (jp/'clip.flac').write_bytes(b'Japanese track')
                with unittest.mock.patch.object(fmv_dub, 'SUBTITLES', str(subtitles)), \
                        unittest.mock.patch.object(fmv_dub, 'PSP_AUDIO', str(audio)):
                    keys.append(fmv_dub.movie_key('retail', 'clip', []))
            self.assertEqual(keys[0], keys[1])

class NativeVariantReuse(unittest.TestCase):
    def test_repeated_batches_skip_native_builds_and_mod_edit_only_rebuilds_consumers(self):
        from types import SimpleNamespace
        import variant_inputs
        import features
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generation = [0]
            current = [b'']
            built = []
            consumed = []
            variants = [release.Variant('run', ('run-in-dungeons',), 'option'),
                        release.Variant('battle', ('battle-speedup',), 'option'),
                        release.Variant('both', ('run-in-dungeons', 'battle-speedup'), 'check')]
            def key(labels):
                revision = generation[0] if 'run-in-dungeons' in labels else 0
                return hashlib.sha1(repr((labels, revision)).encode()).hexdigest()
            profile = SimpleNamespace(key=key)
            def native(variants_override, before_variant, after_variant):
                for labels, name in variants_override:
                    labels = release.mods.with_needs(labels, release.build.OPTIONS)
                    if not before_variant(labels, name):
                        continue
                    built.append(name)
                    current[0] = key(labels).encode()
                    after_variant(labels, name)
            def consume(variant, directory):
                consumed.append((variant.name, (directory/'DNG.BIN').read_bytes()))
            with unittest.mock.patch.object(release, 'ROOT', root), \
                    unittest.mock.patch.object(release.modpack, 'Source'), \
                    unittest.mock.patch.object(variant_inputs, 'VariantInputs', return_value=profile), \
                    unittest.mock.patch.object(release.build, 'main', side_effect=native), \
                    unittest.mock.patch.object(release.build, 'BASE_ONLY', False), \
                    unittest.mock.patch.object(release.build, 'ENGINE_ONLY', False), \
                    unittest.mock.patch.object(release, 'tree_files', side_effect=lambda source, directory: {'DNG.BIN': current[0]}):
                release.run_variants(root/'retail.bin', False, variants, consume)
                self.assertEqual(built, ['run', 'battle', 'both'])
                expected = list(consumed)
                built.clear(); consumed.clear()
                release.run_variants(root/'retail.bin', False, variants, consume)
                self.assertEqual(built, [])
                self.assertEqual(consumed, expected)
                generation[0] = 1
                built.clear(); consumed.clear()
                release.run_variants(root/'retail.bin', False, variants, consume)
                self.assertEqual(built, ['run', 'both'])
                self.assertEqual(consumed[1], expected[1])
                self.assertNotEqual(consumed[0][1], expected[0][1])
                self.assertNotEqual(consumed[2][1], expected[2][1])

class ProductionWithoutVerification(unittest.TestCase):
    def test_all_layers_are_written_untested_without_combined_verification(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            image = root/'retail.bin'
            image.write_bytes(bytes(2352))
            output = root/'patches'
            source = unittest.mock.Mock(entries={})
            stack.enter_context(unittest.mock.patch.object(release, 'ROOT', root))
            stack.enter_context(unittest.mock.patch.object(release, 'TREES', root/'trees'))
            stack.enter_context(unittest.mock.patch.object(release, 'BASE_TREE', root/'base-tree'))
            stack.enter_context(unittest.mock.patch.object(release.image_check, 'require'))
            stack.enter_context(unittest.mock.patch.object(release, 'release_fingerprint', return_value='inputs'))
            stack.enter_context(unittest.mock.patch.object(release.modpack, 'Source', return_value=source))
            stack.enter_context(unittest.mock.patch.object(release.modpack, 'cached_retail_twins', return_value=[]))
            stack.enter_context(unittest.mock.patch.object(release.modpack, 'source_version', return_value='fixture'))
            stack.enter_context(unittest.mock.patch.object(release.modpack, 'bind_ranges'))
            stack.enter_context(unittest.mock.patch.object(release, 'tree_files', return_value={}))
            stack.enter_context(unittest.mock.patch.object(release, 'kept_tree', return_value={}))
            stack.enter_context(unittest.mock.patch.object(release, 'variant_files', return_value={}))
            stack.enter_context(unittest.mock.patch.object(release, 'save_tree'))
            child = stack.enter_context(unittest.mock.patch.object(release, 'child_trees'))
            process = stack.enter_context(unittest.mock.patch.object(release.subprocess, 'run'))
            comparisons = stack.enter_context(unittest.mock.patch.object(release, 'check_combination'))
            browser = stack.enter_context(unittest.mock.patch.object(release, 'check_browser_layout'))
            names = []
            def native(image, port, variants, finished, **kwargs):
                for variant in variants:
                    names.append(variant.name)
                    finished(variant, root/'build')
            runs = stack.enter_context(unittest.mock.patch.object(release, 'run_variants', side_effect=native))
            release.build_release(str(image), str(output))
            self.assertEqual(set(p.name for p in output.glob('*.p1mod')),
                             set(release.release_file_names()))
            rows = release.read_manifest(output/release.MANIFEST)
            self.assertTrue(rows)
            self.assertEqual({r['state'] for r in rows.values()}, {'untested'})
            comparisons.assert_not_called()
            browser.assert_not_called()
            self.assertNotIn('all', names)
            self.assertTrue(all('--verify-tree' not in call.args[0] for call in process.call_args_list))
            for call in process.call_args_list:
                arguments = [arg for arg in call.args[0] if arg.startswith('--mods=')]
                if arguments:
                    release.build.selected_mods(arguments)
            count = runs.call_count
            release.build_release(str(image), str(output))
            self.assertEqual(runs.call_count, count, 'complete untested production was rebuilt')
