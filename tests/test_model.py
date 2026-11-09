import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Chord,DEFAULTS,appearance,validate,validate_chord,effective_scheme
class InputPreferences(unittest.TestCase):
 def test_chord_release_both_orders(self):
  for events in [[(29,1),(57,1),(57,2),(57,0),(29,0)],[(97,1),(57,1),(97,0),(57,0)]]:
   chord=Chord();self.assertEqual(sum(chord.event(k,v,DEFAULTS['wake']) for k,v in events),1)
 def test_unwanted_modifiers_and_other_key(self):
  for events in [[(56,1),(29,1),(57,1),(57,0),(29,0),(56,0)],[(29,1),(57,1),(30,1),(30,0),(57,0),(29,0)]]:
   c=Chord();self.assertFalse(any(c.event(k,v,DEFAULTS['wake']) for k,v in events))
 def test_single_function_and_custom_combo(self):
  self.assertEqual(validate_chord({'key':67,'mods':[]}),{'key':67,'mods':[]})
  self.assertEqual(validate_chord({'key':57,'mods':['Shift','Ctrl']}),{'key':57,'mods':['Ctrl','Shift']})
 def test_unsafe_or_conflicting_keys_rejected(self):
  for value in [{'key':30,'mods':[]},{'key':57,'mods':['Super']},{'key':1,'mods':['Ctrl']},{'key':True,'mods':[]}]:
   with self.assertRaises(ValueError):validate_chord(value)
  c=copy.deepcopy(DEFAULTS);c['adjust']=c['wake']
  with self.assertRaises(ValueError):validate(c)
 def test_appearance_migration_and_validation(self):
  old={'x':100,'y':200,'locked':True,'scale':.65,'opacity':.95}
  self.assertEqual(appearance(old),{k:v for k,v in old.items() if k!='locked'})
  with self.assertRaises(ValueError):appearance({'x':float('nan')})
  self.assertEqual(appearance({'opacity':0,'scale':10})['opacity'],.2)
 def test_settings_disable_by_default(self):
  self.assertFalse(validate({})['enabled']);self.assertEqual(validate({})['scheme'],'full')
 def test_voice_defaults_independent_and_keep_explicit_choices(self):
  self.assertEqual(validate({})['voiceKey'],'F7')
  self.assertFalse(validate({'enabled':False})['voiceWanted'])
  self.assertFalse(validate({'voiceWanted':False})['voiceWanted'])
  self.assertEqual(validate({'voiceKey':'F11'})['voiceKey'],'F11')
 def test_default_engine_and_existing_xiaohe(self):
  self.assertEqual(effective_scheme({}),'full')
  self.assertEqual(effective_scheme({'DoublePinyin':'true','DoublePinyinSchema':'5'}),'xiaohe')
  c=copy.deepcopy(DEFAULTS);c['scheme']='xiaohe';self.assertEqual(validate(c)['scheme'],'xiaohe')
if __name__=='__main__':unittest.main()
