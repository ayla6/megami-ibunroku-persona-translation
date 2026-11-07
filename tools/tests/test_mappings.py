"""Hermetic correspondence preparation regressions: python -m unittest discover -s tools/tests."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/extraction_tools/matching'))
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import mappings
import toolbelt


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / 'source'
        self.source.mkdir()
        for name in mappings.SOURCE_MAPS:
            (self.source / name).write_text('source input', encoding='utf-8')
        self.glyph = self.base / 'glyph.tsv'
        self.glyph.write_text('0000\t \n', encoding='utf-8')
        self.glossary = self.base / 'glossary.tsv'
        self.glossary.write_text('domain\tkey\ten\tnote\n', encoding='utf-8')
        self.cache = self.base / 'cache'
        changes = dict(MAPPINGS=str(self.cache), SOURCE_MAPPINGS=str(self.source),
                       PSP_GLYPHS=str(self.glyph), GLOSSARY=str(self.glossary))
        for key, value in changes.items():
            p = patch.object(toolbelt, key, value)
            p.start()
            self.addCleanup(p.stop)

    def content(self, name):
        examples = {
            'align.tsv': ('E0', '0', '0', '0', '0', 'ok', '', '', ''),
            'map_jp_psx.tsv': ('E0', '0', '0', '0', 'ok'),
            'map_us_jp.tsv': ('E0', '0', '0', '0', 'ok', '', '', ''),
            'psp_pairs.tsv': ('EBOOT', '0x10', '0x20', 'read'),
            'labels.tsv': ('Source label',),
        }
        return '\t'.join(mappings.HEADERS[name]) + '\n' + '\t'.join(examples[name]) + '\n'

    def write(self, name, content=None):
        self.cache.mkdir(exist_ok=True)
        (self.cache / name).write_text(content or self.content(name), encoding='utf-8')

    def generate(self, script, flag, name, directory):
        self.assertEqual(flag, '--generate')
        (Path(directory) / name).write_text(self.content(name), encoding='utf-8')
        if name.startswith('map_'):
            sibling = 'map_us_jp.tsv' if name == 'map_jp_psx.tsv' else 'map_jp_psx.tsv'
            (Path(directory) / sibling).write_text('must not overwrite sibling', encoding='utf-8')

    def test_populated_cache_starts_no_processes(self):
        for name in mappings.HEADERS:
            self.write(name)
        with patch.object(mappings, '_run') as run:
            self.assertEqual(mappings.ensure(), ())
            run.assert_not_called()

    def test_missing_maps_generated_once_in_dependency_order(self):
        with patch.object(mappings, '_run', side_effect=self.generate) as run, \
                patch.object(mappings, '_prepare_pairs') as prepare:
            made = mappings.ensure()
            self.assertEqual(made, tuple(mappings.HEADERS))
            self.assertEqual(run.call_count, 5)
            prepare.assert_called_once()
            self.assertEqual(mappings.ensure(), ())
            self.assertEqual(run.call_count, 5)
        self.assertFalse(list(self.cache.glob('.prepare-*')))

    def test_split_dependency_does_not_overwrite_existing_sibling(self):
        original = self.content('map_us_jp.tsv')
        self.write('map_us_jp.tsv', original)
        with patch.object(mappings, '_run', side_effect=self.generate):
            self.assertEqual(mappings.ensure(['map_jp_psx.tsv']),
                             ('align.tsv', 'map_jp_psx.tsv'))
        self.assertEqual((self.cache / 'map_us_jp.tsv').read_text(), original)

    def test_failed_generator_leaves_no_partial_cache(self):
        def fail(script, flag, name, directory):
            (Path(directory) / name).write_text('partial', encoding='utf-8')
            raise subprocess.CalledProcessError(7, ['generator'])
        with patch.object(mappings, '_run', side_effect=fail):
            with self.assertRaises(subprocess.CalledProcessError):
                mappings.ensure(['labels.tsv'])
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_bad_generated_output_not_published(self):
        def bad(script, flag, name, directory):
            (Path(directory) / name).write_text('label\n', encoding='utf-8')
        with patch.object(mappings, '_run', side_effect=bad):
            with self.assertRaisesRegex(ValueError, 'no rows'):
                mappings.ensure(['labels.tsv'])
        self.assertFalse((self.cache / 'labels.tsv').exists())

    def test_corrupt_existing_cache_fails_without_replacing_it(self):
        self.write('labels.tsv', 'wrong header\n')
        with patch.object(mappings, '_run') as run:
            with self.assertRaisesRegex(ValueError, 'expected header'):
                mappings.ensure(['labels.tsv'])
            run.assert_not_called()
        self.assertEqual((self.cache / 'labels.tsv').read_text(), 'wrong header\n')

    def test_malformed_rows_rejected(self):
        self.write('psp_pairs.tsv', 'file\tus_pos\tjp_pos\thow\nEBOOT\t0x10\n')
        with self.assertRaisesRegex(ValueError, 'malformed mapping row'):
            mappings.ensure(['psp_pairs.tsv'])

    def test_missing_authored_input_never_fabricated(self):
        self.glyph.unlink()
        with patch.object(mappings, '_run') as run:
            with self.assertRaisesRegex(FileNotFoundError, 'nothing was fabricated'):
                mappings.ensure(['labels.tsv'])
            run.assert_not_called()
        self.assertFalse(self.cache.exists())

    def test_unknown_cache_name_rejected_before_writes(self):
        with self.assertRaisesRegex(ValueError, 'unknown generated'):
            mappings.ensure(['typo.tsv'])
        self.assertFalse(self.cache.exists())

    def test_invalid_pair_offsets_rejected(self):
        self.write('psp_pairs.tsv', 'file\tus_pos\tjp_pos\thow\nEBOOT\tgarbage\t0x20\tread\n')
        with self.assertRaisesRegex(ValueError, 'invalid pair offset'):
            mappings.ensure(['psp_pairs.tsv'])

    def test_duplicate_pair_keys_rejected(self):
        self.write('psp_pairs.tsv', self.content('psp_pairs.tsv') +
                   'EBOOT\t0x10\t0x30\tread\n')
        with self.assertRaisesRegex(ValueError, 'duplicate mapping key'):
            mappings.ensure(['psp_pairs.tsv'])

    def test_pair_preparation_rejects_missing_provenance(self):
        with patch.object(mappings, '_require'), \
                patch.object(toolbelt, 'read_generated', return_value=[]), \
                patch.object(mappings, '_run') as run:
            with self.assertRaisesRegex(ValueError, 'missing independently ported'):
                mappings._prepare_pairs()
            run.assert_not_called()

    def test_pair_preparation_refreshes_corpus_without_worklists(self):
        with patch.object(mappings, '_require') as require, \
                patch.object(toolbelt, 'read_generated',
                             return_value=[{'en': 'source', 'psp': 'EBOOT:10'}]), \
                patch.object(mappings, '_run') as run:
            mappings._prepare_pairs()
        require.assert_called_once()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[-1], '--no-worklists')

    def test_port_prepares_before_font_or_any_porter(self):
        import port
        with patch.object(mappings, 'ensure', side_effect=RuntimeError('prepare first')), \
                patch.object(port, 'must') as must, patch.object(port, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'prepare first'):
                port.port_all()
            must.assert_not_called()
            run.assert_not_called()

    def test_build_ports_before_consuming_generated_translations(self):
        import build
        import features
        commands = []
        def capture(*args):
            commands.append(args)
            if str(args[1]).endswith('make_vwf_font.py'):
                raise RuntimeError('stop after port')
        with patch.object(build, 'ARMIPS', '/fake/armips'), \
                patch.object(build.os.path, 'isdir', return_value=True), \
                patch.object(build.image_check, 'require'), \
                patch.object(build.disc_data, 'psx_complete', return_value=True), \
                patch.object(build.disc_data, 'ensure_psp'), \
                patch.object(features, 'write', return_value={}), \
                patch.object(features, 'describe', return_value='test'), \
                patch.object(mappings, 'ensure'), patch.object(build, 'run', side_effect=capture):
            with self.assertRaisesRegex(RuntimeError, 'stop after port'):
                build.main()
        self.assertEqual([Path(c[1]).name for c in commands],
                         ['make_tbl.py', 'port.py', 'make_vwf_font.py'])

    def test_build_prepares_before_table_and_font_builders(self):
        import build
        import features
        with patch.object(build, 'ARMIPS', '/fake/armips'), \
                patch.object(build.os.path, 'isdir', return_value=True), \
                patch.object(build.image_check, 'require'), \
                patch.object(build.disc_data, 'psx_complete', return_value=True), \
                patch.object(build.disc_data, 'ensure_psp'), \
                patch.object(features, 'write', return_value={}), \
                patch.object(features, 'describe', return_value='test'), \
                patch.object(mappings, 'ensure', side_effect=RuntimeError('prepare first')), \
                patch.object(build, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'prepare first'):
                build.main()
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
