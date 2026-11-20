"""Only variants consuming changed mod inputs are invalidated."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import unittest

import materialized_cache
import mods
import preparation_cache
from variant_inputs import VariantInputs


class VariantInputTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ('src/shared.py', 'tools/build_patches.py', 'tools/run_tests.py',
                     'armips', 'retail.bin', 'translation/sample.tsv', 'data/psx/DNG.BIN'):
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('initial')
        self.catalog = []
        for name, needs, always in (('Base', (), True), ('Alpha', ('base',), False),
                                   ('Beta', ('base',), False), ('Gamma', ('alpha',), False)):
            folder = self.root/'src/mods'/name.lower()
            folder.mkdir(parents=True)
            (folder/'code.asm').write_text('initial')
            self.catalog.append(mods.Mod(name, '', needs, False, always, True, str(folder)))
        self.product = self.root/'build/prepared.asm'
        self.product.parent.mkdir()
        self.set_prepared('prepared')
        stub = patch.object(preparation_cache, 'versions', return_value=('library=1',))
        stub.start()
        self.addCleanup(stub.stop)

    def set_prepared(self, text):
        self.product.write_text(text)
        path = self.root/'build/step_cache/preparation/active.tsv'
        path.parent.mkdir(parents=True, exist_ok=True)
        materialized_cache.write(path, [materialized_cache.Product(
            self.product, hashlib.sha1(self.product.read_bytes()).hexdigest(), 'blob')])

    def profile(self, **kwargs):
        return VariantInputs(self.root, self.root/'retail.bin', self.catalog,
                             kwargs.pop('options', {}), font='large', base_only=False,
                             engine_only=False, verify=kwargs.pop('verify', False),
                             movie_prepared=False, tool=self.root/'armips', gates={}, **kwargs)

    def test_mod_edit_only_invalidates_its_consumers_and_dependents(self):
        profile = self.profile()
        alpha, beta, gamma = (profile.key([label]) for label in ('alpha', 'beta', 'gamma'))
        (self.root/'src/mods/alpha/code.asm').write_text('changed')
        self.assertNotEqual(profile.key(['alpha']), alpha)
        self.assertNotEqual(profile.key(['gamma']), gamma)
        self.assertEqual(profile.key(['beta']), beta)
        (self.root/'src/shared.py').write_text('shared changed')
        self.assertNotEqual(profile.key(['beta']), beta)

    def test_shared_inventory_additions_and_removals_change_the_key(self):
        profile = self.profile()
        before = profile.key(['alpha'])
        added = self.root/'src/new_helper.py'
        added.write_text('new shared code')
        self.assertNotEqual(profile.key(['alpha']), before)
        added.unlink()
        self.assertEqual(profile.key(['alpha']), before)

    def test_preparation_coupling_and_declared_external_inputs_are_retained(self):
        alpha = self.profile().key(['alpha'])
        beta = self.profile().key(['beta'])
        self.set_prepared('different prepared bytes')
        self.assertNotEqual(self.profile().key(['alpha']), alpha)
        self.assertNotEqual(self.profile().key(['beta']), beta)
        manifest = self.root/'src/mods/alpha/inputs.tsv'
        manifest.write_text('path\ndata/external.bin\n')
        profile = self.profile()
        alpha, beta = profile.key(['alpha']), profile.key(['beta'])
        (self.root/'data/external.bin').write_bytes(b'new asset')
        self.assertNotEqual(profile.key(['alpha']), alpha)
        self.assertEqual(profile.key(['beta']), beta)

    def test_options_and_verification_scope_are_distinct(self):
        basic = self.profile().key(['alpha'])
        self.assertNotEqual(self.profile(options={'alpha': frozenset({'speed=3'})}).key(['alpha']), basic)
        self.assertNotEqual(self.profile(verify=True).key(['alpha']), basic)
        self.product.write_text('unverified preparation')
        with self.assertRaisesRegex(ValueError, 'verified product set'):
            self.profile()
