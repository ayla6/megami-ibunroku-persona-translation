"""Renderer keys follow helpers/constants while ignoring unrelated command code."""
from pathlib import Path
from tempfile import TemporaryDirectory
import types
import unittest

import render_inputs


class RenderInputs(unittest.TestCase):
    def test_helpers_nested_calls_constants_and_dynamic_fallback(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'renderer.py'
            template = '''AMOUNT = {amount}
DATA = [2]
def helper(value):
    return value {operator} AMOUNT
def render(values):
    return list(map(lambda value: helper(value), values))
def dynamic():
    return globals()['AMOUNT']
def mutable():
    return DATA[0]
def driver():
    return {driver}
'''
            def key(amount=2, operator='+', driver=1, root='render'):
                source = template.format(amount=amount, operator=operator, driver=driver)
                path.write_text(source)
                module = types.ModuleType('renderer')
                module.__file__ = str(path)
                # inspect resolves function modules through sys.modules.
                import sys
                from unittest.mock import patch
                with patch.dict(sys.modules, {'renderer': module}):
                    exec(compile(source, str(path), 'exec'), module.__dict__)
                    return render_inputs.fingerprint(getattr(module, root))
            first = key()
            self.assertEqual(key(driver=9), first)
            self.assertNotEqual(key(amount=3), first)
            self.assertNotEqual(key(operator='*'), first)
            self.assertNotEqual(key(root='dynamic'), key(root='dynamic', driver=9))
            self.assertNotEqual(key(root='mutable'), key(root='mutable', driver=9))
