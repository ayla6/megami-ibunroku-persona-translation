"""Preparation owns text/font sources; declared image inputs have their own cache."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import toolpath
import preparation_cache as cache


class PreparationInputs(unittest.TestCase):
    def test_image_edits_and_tests_do_not_invalidate_text_but_font_inputs_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                'src/mods/example/images.tsv': 'file\timage\nADV/MES.BIN\twalk.png\n',
                'src/mods/example/assets/walk.png': 'image',
                'src/mods/example/assets/walk.psd': 'authoring source',
                'src/mods/latin-alphabet/assets/font.png': 'font',
                'src/pipeline/test_example.py': 'test',
                'src/injection/producer.py': 'producer',
                'src/mods/example/code.asm': 'assembly',
            }
            for name, data in files.items():
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(data)
            with patch.object(cache, 'ROOT', root), patch.object(cache, 'GENERATED', ()):
                actual = {str(p.relative_to(root)) for p in cache.source_inputs()}
            self.assertNotIn('src/mods/example/assets/walk.png', actual)
            self.assertNotIn('src/mods/example/images.tsv', actual)
            self.assertNotIn('src/pipeline/test_example.py', actual)
            self.assertIn('src/mods/latin-alphabet/assets/font.png', actual)
            self.assertIn('src/injection/producer.py', actual)
            self.assertIn('src/mods/example/code.asm', actual)
