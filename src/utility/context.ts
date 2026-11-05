// @ts-nocheck
// Steam private UI hooks are checked at runtime. Only native keyboard presentation is changed.
import {addEventListener,removeEventListener,callable} from '@decky/api';
import {getConfig,flushAppearance} from '../config';
import {CreateRawKeyboardListener} from './keyboard';
import {SetCandidateDisplay} from './display';
const find=callable('find_keyboards'),grab=callable('grab_keyboards'),ungrab=callable('ungrab_keyboards');
const modifiers={29:'Ctrl',97:'Ctrl',42:'Shift',54:'Shift',56:'Alt',100:'Alt',125:'Super',126:'Super'};
export function componentFor(dom){
 if(!dom)return null;const child=dom.firstChild;
 let current=dom[Object.keys(dom).find(k=>k.startsWith('__reactFiber$'))];
 while(current&&current.stateNode!==child){if(current.stateNode?.m_keyboardDiv===child)return current.stateNode;current=current.child;}
 return null;
}
export class KeyboardContext {
 dom=null;component=null;rawListener=null;generation=0;managers=new Set();active=true;
 open=()=>{
  if(!getConfig().enabled||!this.active)return;
  const active=window.SteamUIStore?.ActiveWindowInstance;
  if(!active?.NavigateWithoutChangingFocus)throw Error('当前 Steam 版本的键盘入口不可用');
  this.replace();window.__wowdeckPhysicalRequestUntil=Date.now()+5000;
  active.NavigateWithoutChangingFocus('/keyboard',true,true);
  setTimeout(()=>{if(this.active&&!active.VirtualKeyboardManager.IsShowingVirtualKeyboard.Value)active.VirtualKeyboardManager.SetVirtualKeyboardVisible();},100);
 };
 replace(){
  if(!getConfig().enabled||!this.active)return;
  const manager=window.SteamUIStore?.ActiveWindowInstance?.VirtualKeyboardManager;
  if(!manager||this.managers.has(manager))return;
  if(manager.__wowdeckOriginalShow)return;
  manager.__wowdeckOriginalShow=manager.SetVirtualKeyboardVisible;
  manager.__wowdeckOriginalHide=manager.SetVirtualKeyboardHidden;
  this.managers.add(manager);
  manager.SetVirtualKeyboardVisible=()=>{
   const physical=Date.now()<(window.__wowdeckPhysicalRequestUntil||0);window.__wowdeckPhysicalRequestUntil=0;
   manager.__wowdeckOriginalShow();
   if(!getConfig().enabled)return;
   const generation=++this.generation;
   const poll=async(count=0)=>{
    if(!this.active||generation!==this.generation)return;
    const dom=window.SteamUIStore?.ActiveWindowInstance?.BrowserWindow.document.getElementById('virtual keyboard');
    if(!dom){if(count<15)setTimeout(()=>void poll(count+1),100);return;}
    this.dom=dom;this.component=componentFor(dom);
    const has=await find();if(!this.active||generation!==this.generation)return;
    SetCandidateDisplay(dom,!!has&&physical,()=>this.component?.UpdateWindowSize?.());
    this.removeRaw();
    if(!has){await ungrab();return;}
    const raw=CreateRawKeyboardListener(this),down=new Set(),consumed=new Set();
    this.rawListener=(code,value)=>{
     if(value===1)down.add(code);
     const hk=getConfig().adjust;
     const current=[...new Set([...down].map(c=>modifiers[c]).filter(Boolean))].sort();
     if(dom.dataset.codyPhysical==='true'&&code===hk.key&&value===1&&JSON.stringify(current)===JSON.stringify([...hk.mods].sort())){
      this.shortClickShiftCode=null;consumed.add(code);dom.__codyToggleAdjustment?.();return;
     }
     if(value===0)down.delete(code);
     if(consumed.has(code)){if(value===0)consumed.delete(code);return;}
     raw(code,value);
    };
    addEventListener('keyboard',this.rawListener);await grab();
   };
   void poll().catch(console.error);
  };
  manager.SetVirtualKeyboardHidden=()=>{
   this.generation++;this.removeRaw();void ungrab();
   this.dom?.__codyCandidateObserver?.disconnect();
   manager.__wowdeckOriginalHide();
  };
 }
 removeRaw(){if(this.rawListener){removeEventListener('keyboard',this.rawListener);this.rawListener=null;}}
 stop(){
  this.active=false;this.generation++;this.removeRaw();void ungrab().catch(console.error);void flushAppearance().catch(console.error);
  this.dom?.__codyCandidateObserver?.disconnect();
  if(this.dom){delete this.dom.dataset.codyPhysical;delete this.dom.dataset.codyCandidates;this.dom.querySelector('.cody-candidate-handle')?.remove();this.dom.ownerDocument.getElementById('cody-keyboard-display-style')?.remove();}
  for(const manager of this.managers){manager.SetVirtualKeyboardVisible=manager.__wowdeckOriginalShow;manager.SetVirtualKeyboardHidden=manager.__wowdeckOriginalHide;delete manager.__wowdeckOriginalShow;delete manager.__wowdeckOriginalHide;}
  this.managers.clear();
 }
}
