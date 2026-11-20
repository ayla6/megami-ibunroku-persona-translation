"""Dependency priority cannot be overridden by numeric row order."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import toolpath
from asm_main import Row, dependency_rows


def row(mod: str, order: int) -> Row:
    return Row(mod,'ADV',order,f'{mod}:{order}','','','')


class AssemblyDependencies(unittest.TestCase):
    def test_every_prerequisite_row_precedes_a_dependent(self):
        rows=[row('base',80),row('base',900),row('language',1),row('option',0)]
        result=dependency_rows(rows,{'language':{'base'},'option':{'language'}},
                               {'base':0,'language':1,'option':2})
        self.assertEqual([r.mod for r in result],['base','base','language','option'])

    def test_unrelated_rows_keep_numeric_priority(self):
        rows=[row('one',20),row('two',10),row('one',5),row('two',30)]
        result=dependency_rows(rows,{}, {'one':0,'two':1})
        self.assertEqual([r.line for r in result],['one:5','two:10','one:20','two:30'])

    def test_nodes_without_rows_still_carry_transitive_requirements(self):
        rows=[row('root',100),row('leaf',1)]
        result=dependency_rows(rows,{'middle':{'root'},'leaf':{'middle'}}, {'root':0,'leaf':1})
        self.assertEqual([r.mod for r in result],['root','leaf'])

    def test_dependency_cycles_fail(self):
        with self.assertRaisesRegex(ValueError,'cyclic'):
            dependency_rows([row('a',0)],{'a':{'b'},'b':{'a'}},{'a':0})
