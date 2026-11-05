import asyncio,copy,importlib.util,json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import AsyncMock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
# No real device, Decky service, or system dconf is used in these tests.
sys.modules.setdefault('decky',types.SimpleNamespace(emit=AsyncMock()))
spec=importlib.util.spec_from_file_location('wowdeck_backend',ROOT/'main.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
from model import DEFAULTS
class SchemeChanges(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.temp=tempfile.TemporaryDirectory();self.plugin=module.Plugin();p=self.plugin
  p.directory=Path(self.temp.name);p.path=p.directory/'settings.json';p.config=copy.deepcopy(DEFAULTS);p.grabbing=False;p.lock=asyncio.Lock();p.devices={}
  self.values={'DoublePinyin':'true','DoublePinyinSchema':'5'};self.original=self.values.copy();self.fail=False
  async def command(*args):
   action=args[1];key=args[2].split('/')[-1]
   if action=='read':return self.values[key]
   if action=='write':
    if self.fail and key=='DoublePinyin' and args[3]=='false':self.fail=False;raise ValueError('simulated write failure')
    self.values[key]=args[3]
   if action=='reset':self.values[key]=''
   return ''
  p.user_command=command;p.engine_available=lambda:True
  p.get_state=AsyncMock(return_value={})
 async def asyncTearDown(self):self.temp.cleanup()
 async def test_switch_full_then_xiaohe_and_restore(self):
  p=self.plugin;await p.set_scheme('full');self.assertEqual(self.values['DoublePinyin'],'false')
  self.assertEqual(json.loads((p.directory/'pinyin-before.json').read_text()),self.original)
  await p.set_scheme('xiaohe');self.assertEqual(self.values,self.original)
  await p.restore_scheme();self.assertEqual(self.values,self.original)
 async def test_failed_write_rolls_back_and_does_not_save_preference(self):
  self.fail=True
  with self.assertRaises(ValueError):await self.plugin.set_scheme('full')
  self.assertEqual(self.values,self.original);self.assertEqual(self.plugin.config['scheme'],'full')
 async def test_active_input_cannot_switch_scheme(self):
  self.plugin.grabbing=True
  with self.assertRaises(ValueError):await self.plugin.set_scheme('full')
  self.assertEqual(self.values,self.original)
 async def test_uninstall_keeps_later_user_changes(self):
  p=self.plugin;await p.set_scheme('full');self.values['DoublePinyinSchema']='3'
  await p._uninstall();self.assertEqual(self.values['DoublePinyinSchema'],'3')

 async def test_first_enable_applies_full_but_preserves_selected_xiaohe(self):
  p=self.plugin;await p.set_enabled(True);self.assertEqual(self.values['DoublePinyin'],'false')
  await p.set_enabled(False);await p.set_scheme('xiaohe');await p.set_enabled(True)
  self.assertEqual(self.values,self.original);self.assertEqual(p.config['scheme'],'xiaohe')
