import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/utility/context.ts',import.meta.url),'utf8'),{
 compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.CommonJS}}).outputText;
function create(){
 let menu=0,resolveTable,rejectTable,attaches=0,disposes=0;
 const config={scheme:'wubi86',pluginEnabled:true,enabled:true,adjust:{key:66,mods:[]}};
 const calls=[],events=new Map(),timers=[],typed=[],errors=[];
 const manager={IsShowingVirtualKeyboard:{Value:true},SetVirtualKeyboardHidden(){calls.push('hide');}};
 const panel={},component={m_keyboardDiv:panel};
 const dom={firstChild:panel,__reactFiber$test:{child:{stateNode:component}},dataset:{},
  style:{removeProperty(){}},getClientRects:()=>[{}],querySelector:()=>null,querySelectorAll:()=>[],
  ownerDocument:{getElementById:()=>null}};
 const owner={MenuStore:{GetOpenSideMenu:()=>menu},History:{location:{pathname:'/game'}},
  VirtualKeyboardManager:manager,BrowserWindow:{document:{getElementById:()=>dom}},
  NavigateWithoutChangingFocus(path){this.History.location.pathname=path;}};
 const modules={
  '@decky/api':{
   callable:name=>async()=>{calls.push(name);if(name==='get_wubi_table')return await new Promise((resolve,reject)=>{resolveTable=resolve;rejectTable=reject;});return true;},
   addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:name=>events.delete(name)},
  '../config':{getConfig:()=>config,flushAppearance:async()=>{}},
  './keyboard':{CreateRawKeyboardListener:()=> (...args)=>typed.push(['native',...args])},
  './display':{SetCandidateDisplay:()=>{}},
  './wubi':{attachWubi:()=>{attaches++;return {key:(...args)=>typed.push(['wubi',...args]),dispose(){disposes++;}};}}
 };
 const exports={};vm.runInNewContext(code,{exports,require:id=>modules[id],setTimeout:fn=>timers.push(fn),window:{SteamUIStore:{ActiveWindowInstance:owner}}});
 const ctx=new exports.KeyboardContext(error=>errors.push(String(error)));
 return {ctx,calls,typed,events,config,errors,menu:value=>menu=value,
  resolve:()=>resolveTable({}),reject:()=>rejectTable(Error('table unavailable')),
  counts:()=>[attaches,disposes],tick:async()=>{for(const fn of timers.splice(0))fn();await settle();}};
}
async function settle(){await new Promise(resolve=>setImmediate(resolve));}
for(const stop of ['close','menu','disable']){
 const x=create();x.ctx.open();await x.tick();x.ctx.renew();
 assert.ok(x.calls.includes('get_wubi_table'));assert.ok(!x.calls.includes('grab_keyboards'),'loading never grabs keys without a listener');
 if(stop==='close')x.ctx.closeOwned();
 if(stop==='menu'){x.menu(1);x.ctx.renew();}
 if(stop==='disable'){x.config.pluginEnabled=false;x.ctx.renew();}
 x.resolve();await settle();assert.deepEqual(x.counts(),[0,0]);assert.equal(x.events.size,0,'late table callback cannot capture the keyboard');
}
const x=create();x.ctx.open();await x.tick();x.resolve();await settle();
assert.deepEqual(x.counts(),[1,0]);assert.ok(x.calls.includes('grab_keyboards'));
x.events.get('keyboard')(30,1);assert.equal(x.typed[0][0],'wubi');
x.menu(2);x.events.get('keyboard')(50,1);assert.equal(x.typed.length,1,'M cannot be consumed once a Steam menu is open');
assert.deepEqual(x.counts(),[1,1]);assert.equal(x.events.size,0);
const failed=create();failed.ctx.open();await failed.tick();failed.reject();await settle();
assert.equal(failed.errors.length,1);assert.equal(failed.events.size,0);assert.ok(!failed.calls.includes('grab_keyboards'));
const pinyin=create();pinyin.config.scheme='xiaohe';pinyin.ctx.open();await pinyin.tick();
assert.ok(!pinyin.calls.includes('get_wubi_table'));pinyin.events.get('keyboard')(30,1);assert.equal(pinyin.typed[0][0],'native');
pinyin.ctx.stop();assert.equal(pinyin.events.size,0);
console.log('PASS: Wubi loading, stale callbacks, menu priority, ownership cleanup, failure release and unchanged Xiaohe route');
