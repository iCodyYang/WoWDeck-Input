import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const calls = [], listeners = new Map(), intervals = new Set(), waits = [], effects = [];
const toast = [], raw = [];
let menu = 0, config = {pluginEnabled:false, enabled:true, voiceWanted:true, adjust:{key:66,mods:[]}};
const manager = Object.freeze({
  IsShowingVirtualKeyboard:{Value:true},
  SetVirtualKeyboardVisible(){calls.push('force-show');},
  SetVirtualKeyboardHidden(){calls.push('hide');},
});
const panel = {};
const dom = {firstChild:panel, dataset:{}, style:{removeProperty(){}}, getClientRects:()=>[{}],
  __reactFiber$test:{child:{stateNode:{m_keyboardDiv:panel}}},
  querySelector:()=>null, querySelectorAll:()=>[], ownerDocument:{getElementById:()=>null}};
const owner = {
  MenuStore:{GetOpenSideMenu:()=>menu}, History:{location:{pathname:'/game'}},
  BrowserWindow:{document:{getElementById:()=>dom}}, VirtualKeyboardManager:manager,
  NavigateWithoutChangingFocus(route){calls.push('navigate');this.History.location.pathname=route;},
};
const window = {SteamUIStore:{ActiveWindowInstance:owner}};
let finishInitialRead;
const api = {
  callable:name=>async (...args)=>{
    calls.push([name,...args].join(' '));
    return name==='find_keyboards' ? true : {};
  },
  addEventListener:(name,fn)=>listeners.set(name,fn),
  removeEventListener:(name,fn)=>{if(listeners.get(name)===fn)listeners.delete(name);},
  definePlugin:fn=>fn,
  toaster:{toast:options=>{toast.push(options);return {dismiss(){}};}},
};
const modules = {
  '@decky/api':api, '@decky/ui':{staticClasses:{Title:''}},
  'react-icons/fa':{}, 'react/jsx-runtime':{jsx:()=>null,jsxs:()=>null},
  react:{useRef:v=>({current:v}),useEffect:fn=>effects.push(fn()),useState:initial=>[initial,()=>{}]},
  './WaveEditor':{},
  './keyboard-setup':{getKeyboardSetup:()=>({state:'enabled'})},
  './keyboard':{CreateRawKeyboardListener:()=> (...args)=>raw.push(args)},
  './wubi':{attachWubi:()=>{throw Error('Wubi must not load for normal input');}},
  './display':{SetCandidateDisplay:()=>{dom.dataset.codyPhysical='true';}},
};
modules['../config'] = modules['./config'] = {getConfig:()=>config, putConfig:value=>{config=value;},
  flushAppearance:async()=>{},api:{state:()=>new Promise(resolve=>{finishInitialRead=resolve;})}};

function load(file) {
  const source = readFileSync(new URL('../src/'+file,import.meta.url),'utf8');
  const code = ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2020,
    module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const exports = {};
  vm.runInNewContext(code,{exports,window,console,require:id=>{assert.ok(id in modules,id);return modules[id];},
    setTimeout:fn=>waits.push(fn), setInterval:fn=>{intervals.add(fn);return fn;},clearInterval:fn=>intervals.delete(fn)});
  return exports;
}
async function settle(){await new Promise(resolve=>setImmediate(resolve));}
async function tick(){for(const fn of waits.splice(0))fn();await settle();}
const context = modules['./utility/context'] = load('utility/context.ts');
modules['./Voice'] = load('Voice.tsx');
assert.equal(context.sideMenusClosed({}),false);
assert.equal(context.sideMenusClosed({MenuStore:{GetOpenSideMenu:()=>{throw Error();}}}),false);

const plugin = load('index.tsx').default();
const feedback = ()=>listeners.get('voice_feedback')({phase:'recording',message:'正在听',hideKeyboard:true});
const open = ()=>listeners.get('open_keyboard')();
const heartbeat = ()=>{for(const fn of intervals)fn();};
const preference = update=>listeners.get('preferences')({...config,...update});

open(); heartbeat(); feedback();
assert.deepEqual(calls,[],'disabled startup does not navigate, grab or send a heartbeat');
assert.equal(toast.length,0);
preference({pluginEnabled:true});
finishInitialRead({config:{...config,pluginEnabled:false}});
await settle();
assert.equal(config.pluginEnabled,true,'a late startup response must not overwrite newer preferences');

for(menu of [1,2,undefined]){
  calls.length=0; open(); feedback(); heartbeat();
  assert.deepEqual(calls,[menu===undefined?'voice_ui_state unknown':'voice_ui_state blocked']);
  assert.equal(toast.length,0);
}
menu=0; calls.length=0;
heartbeat();
assert.deepEqual(calls,['voice_ui_state game'],'native keyboard instance alone is never claimed');
open(); await tick(); heartbeat();
assert.ok(listeners.has('keyboard'));
assert.equal(dom.dataset.codyPhysical,'true');
assert.ok(calls.includes('voice_ui_state keyboard') && calls.includes('grab_keyboards'));
feedback();
assert.equal(toast.length,0,'normal dictation does not add a text notification');
assert.ok(calls.includes('hide'),'only explicitly opened, visible plugin keyboard may be hidden');

for(menu of [1,2]){
  calls.length=0;
  listeners.get('keyboard')?.(50,1);
  heartbeat(); feedback();
  assert.equal(listeners.has('keyboard'),false);
  assert.ok(calls.includes('ungrab_keyboards'));
  assert.equal(dom.dataset.codyPhysical,undefined);
  assert.equal(toast.length,0,'normal dictation does not add a text notification');
  assert.deepEqual(raw,[],'M never enters the plugin once a Steam menu is open');
  assert.ok(!calls.includes('hide'));
  menu=0; open(); await tick();
}
preference({pluginEnabled:false}); assert.equal(listeners.has('keyboard'),false);
preference({pluginEnabled:true});
open();menu=2;await tick();assert.equal(listeners.has('keyboard'),false,'late keyboard attach cannot reclaim the menu');
menu=0;open();owner.History.location.pathname='/library';await tick();
assert.equal(listeners.has('keyboard'),false,'leaving the keyboard route prevents attachment');
manager.IsShowingVirtualKeyboard.Value=false;
owner.History.location.pathname='/keyboard';
for(let i=0;i<16;i++)await tick();
assert.equal(listeners.has('keyboard'),false,'a hidden Steam keyboard is never forcibly shown or grabbed');
assert.ok(!calls.includes('force-show'));

calls.length=0;
modules['./Voice'].Voice({master:true,wanted:true});await settle();
assert.deepEqual(calls,['get_voice_state'],'opening the voice panel only reads status');
for(const cleanup of effects)cleanup?.();
plugin.onDismount();await settle();
assert.equal(listeners.size+intervals.size,0);
console.log('PASS: master off, native Steam menus, M pass-through, keyboard ownership, late callbacks, read-only panel');
