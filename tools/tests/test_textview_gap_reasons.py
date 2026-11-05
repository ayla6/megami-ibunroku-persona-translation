"""Every gap classification is renderable and the source filter is accurate."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import textview

class GapReasons(unittest.TestCase):
 def test_all_reasons_display_and_proven_source_filter(self):
  notes=['over limit 3/2; ABC','characters not allowed; ?', 'leftover words',
         'psp lead; no proof','psp source; no fit','']
  items=[]
  for i,note in enumerate(notes):
   it=textview.Item('','');it.psx={'id':str(i),'pos':hex(i),'text':'test'}
   it.man={'id':str(i),'pos':hex(i),'note':note};items.append(it)
  known=textview.Item('','');known.psx={'id':'6','pos':'0x6','text':'test'}
  known.jp={'id':'6','pos':'0x6','text':'test'};items.append(known)
  context={'psx':'BTLP'}
  with patch.object(textview,'resolve',return_value=('BTLP',None)), \
       patch.object(textview,'missing_items',return_value=(items,context)), \
       redirect_stdout(StringIO()) as out:
   textview.cmd_missing('BTLP')
  text=out.getvalue()
  for reason in ('over-cap draft','unusable draft (bad characters)', 'empty unit (no Japanese)',
                 'lead - unverified match','source proven - no wording fits','no PSP source','source known'):
   self.assertIn(reason,text)
  with patch.object(textview,'cmd_missing') as command, patch.object(sys,'argv',['textview.py','missing','BTLP','--source']):
   textview.main()
  self.assertEqual(command.call_args.kwargs['pick'],{'source known','source proven - no wording fits'})

if __name__=='__main__':unittest.main()
