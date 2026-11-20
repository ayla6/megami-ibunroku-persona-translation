"""Preparation ownership, deferred QA and cache verification boundaries."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import toolpath
import preparation_cache
import translation_preparation as preparation


class TranslationPreparation(unittest.TestCase):
    def compile(self, *, verify=True, port=False, smallfont=True):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            preparation.prepare(
                Path(directory), 'python', lambda *args: calls.append(args[1:]),
                port=port, gates={'SF_VWF': smallfont}, verify=verify,
                tables=lambda: calls.append(('tables',)),
                font=lambda: calls.append(('font',)))
        return calls

    def test_production_retains_all_compilers_and_defers_only_source_checks(self):
        checked = self.compile()
        production = self.compile(verify=False)
        checks = [('tstatus.py', 'qa'), ('tstatus.py', 'status'), ('talktl.py', 'qa')]
        self.assertEqual(production, [call for call in checked if call not in checks])
        self.assertIn(('talk.py', 'build'), production)
        self.assertIn(('etext.py', 'build'), production)
        self.assertNotIn(('port.py',), production)

    def test_port_and_font_dependencies_keep_their_order(self):
        calls = self.compile(port=True)
        self.assertLess(calls.index(('tables',)), calls.index(('port.py',)))
        fonts = [i for i, call in enumerate(calls) if call == ('font',)]
        self.assertEqual(len(fonts), 2)
        self.assertLess(fonts[0], calls.index(('port.py',)))
        self.assertGreater(fonts[1], calls.index(('port.py',)))
        pools = [i for i, call in enumerate(calls) if call == ('smallfont_vwf.py', 'build')]
        self.assertEqual(len(pools), 2)
        self.assertLess(pools[0], calls.index(('affinity.py', 'build')))
        self.assertGreater(pools[1], calls.index(('affinity.py', 'build')))
        self.assertGreater(calls.index(('smallfont_pages.py',)), calls.index(('dngpacks.py', 'build')))
        self.assertNotIn(('smallfont_vwf.py', 'build'), self.compile(smallfont=False))

    def test_unverified_preparation_cannot_satisfy_verified_cache(self):
        contexts = []
        with patch.object(preparation_cache, 'inputs', return_value=[]), \
                patch.object(preparation_cache, 'versions', return_value=()), \
                patch.object(preparation_cache.materialized_cache, 'run',
                             side_effect=lambda *args, **kw: contexts.append(kw['context'])):
            for verify in (False, True):
                preparation_cache.prepare(lambda: None, 'large', {}, True, verify)
        self.assertNotEqual(contexts[0], contexts[1])

    def test_invalid_recipe_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'preparation.tsv'
            for row in ('always\trun\t../outside.py\t', 'always\tmkdir\t../outside\t',
                        'sometimes\tfont\t-\t', 'always\tfont\t-\targument'):
                path.write_text('when\taction\ttarget\targuments\n'+row+'\n')
                with self.subTest(row=row), self.assertRaises(ValueError):
                    preparation.steps(path)


if __name__ == '__main__':
    unittest.main()
