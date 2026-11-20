"""Mod declarations own lifecycle commands, cleanup and parameter binding."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import toolpath
import mods
import mod_build


class ModBuild(unittest.TestCase):
    def test_verification_is_opt_in_and_ordered_with_its_builder(self):
        mod=mods.by_label()['english-dub']
        enabled=mod_build.commands(mod,True,Mock())
        disabled=mod_build.commands(mod,False,Mock())
        self.assertEqual([c[1]for c in enabled],['build','verify','build','verify'])
        self.assertEqual([c[1]for c in disabled],['build','build'])
        self.assertTrue(all(Path(c[0]).parent==Path(mod.folder) for c in enabled))

    def test_numeric_values_come_from_the_selected_mod_options(self):
        mod=mods.by_label()['softer-menu-sounds']
        value=Mock(return_value='73')
        commands=mod_build.commands(mod,False,value)
        self.assertEqual(commands[0][1:],('build','--percent','73'))
        value.assert_called_once_with(mod.label,'level')

    def test_ending_options_only_come_from_selected_mods(self):
        dub = mods.by_label()['english-dub']
        value = Mock()
        self.assertEqual(mod_build.arguments([], 'ending', value), ())
        self.assertEqual(mod_build.arguments([dub], 'ending', value), ('--dub',))
        value.assert_not_called()

    def test_cleanup_runs_independently_of_which_mod_is_selected(self):
        mod=mods.by_label()['softer-menu-sounds']
        cleanup=Mock()
        module=SimpleNamespace(__file__=str(Path(mod.folder)/'menu_sounds.py'),retail=cleanup)
        with patch.object(mods,'load',return_value=[mod]),patch.object(mod_build.importlib,'import_module',return_value=module):
            mod_build.restore()
        cleanup.assert_called_once_with()

    def test_disabled_only_cleanup_keeps_enabled_mod_outputs(self):
        mod = mods.by_label()['english-dub']
        movie_cleanup, voice_cleanup = Mock(), Mock()
        modules = {
            'fmv_dub': SimpleNamespace(__file__=str(Path(mod.folder)/'fmv_dub.py'), retail=movie_cleanup),
            'battle_voice': SimpleNamespace(__file__=str(Path(mod.folder)/'battle_voice.py'), retail=voice_cleanup),
        }
        with patch.object(mods, 'load', return_value=[mod]), patch.object(
                mod_build.importlib, 'import_module', side_effect=modules.__getitem__):
            mod_build.restore(enabled=frozenset({mod.label}))
            movie_cleanup.assert_not_called()
            voice_cleanup.assert_called_once_with()
            mod_build.restore(enabled=frozenset())
            movie_cleanup.assert_called_once_with()
            self.assertEqual(voice_cleanup.call_count, 2)

    def test_tools_cannot_escape_the_mod_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'mod';folder.mkdir()
            (root/'outside.py').write_text('')
            (folder/'build.tsv').write_text('phase\taction\ttarget\targuments\nbuild\trun\t../outside.py\tbuild\n')
            with self.assertRaisesRegex(ValueError,'inside its mod'):
                mod_build.hooks(SimpleNamespace(folder=str(folder)))
