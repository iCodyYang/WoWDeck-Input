// @ts-nocheck
// Steam private UI hooks are checked at runtime. Only native keyboard presentation is changed.
import {addEventListener,removeEventListener,callable} from '@decky/api';
import {getConfig,flushAppearance} from '../config';
import {CreateRawKeyboardListener} from './keyboard';
import {SetCandidateDisplay} from './display';
import {attachWubi} from './wubi';
const find=callable('find_keyboards'),grab=callable('grab_keyboards'),ungrab=callable('ungrab_keyboards');
const getWubiTable=callable('get_wubi_table');
let wubiTable;
const modifiers={29:'Ctrl',97:'Ctrl',42:'Shift',54:'Shift',56:'Alt',100:'Alt',125:'Super',126:'Super'};
export function componentFor(dom){
 if(!dom)return null;const child=dom.firstChild;
 let current=dom[Object.keys(dom).find(k=>k.startsWith('__reactFiber$'))];
 while(current&&current.stateNode!==child){if(current.stateNode?.m_keyboardDiv===child)return current.stateNode;current=current.child;}
 return null;
}
// Missing menu state is treated conservatively on an unrecognized Steam client.
export function sideMenuState(owner){
 try{
  const state=owner?.MenuStore?.GetOpenSideMenu?.();
  if(state===0)return 'closed';
  if(state===1 || state===2)return 'open';
 }catch{}
 return 'unknown';
}
export function sideMenusClosed(owner){
 return sideMenuState(owner)==='closed';
}
function keyboardEnabled(){
 const c=getConfig();return c.pluginEnabled && c.enabled;
}
export class KeyboardContext {
 dom=null;component=null;rawListener=null;generation=0;owner=null;active=true;
 wubi=null;
 constructor(reportError=(_error:unknown)=>{}){this.reportError=reportError;}

 sameView(owner){
  return this.active && keyboardEnabled() &&
   owner===window.SteamUIStore?.ActiveWindowInstance && sideMenusClosed(owner) &&
   owner.History?.location?.pathname==='/keyboard';
 }
 ownedKeyboard(){
  const owner=this.owner;
  if(!owner || !this.dom || !this.sameView(owner))return undefined;
  const manager=owner.VirtualKeyboardManager;
  if(manager?.IsShowingVirtualKeyboard?.Value &&
     owner.BrowserWindow?.document.getElementById('virtual keyboard')===this.dom &&
     (!this.component || componentFor(this.dom)===this.component) &&
     this.dom.getClientRects().length)return manager;
 }
 open=()=>{
  const owner=window.SteamUIStore?.ActiveWindowInstance;
  if(!this.active || !keyboardEnabled() || !sideMenusClosed(owner))return;
  if(!owner?.NavigateWithoutChangingFocus)throw Error('当前 Steam 版本的键盘入口不可用');
  this.release();
  const generation=this.generation;
  this.owner=owner;
  owner.NavigateWithoutChangingFocus('/keyboard',true,true);
  void this.attach(owner,generation).catch(error=>{
   if(generation===this.generation){
    if(getConfig().scheme==='wubi86'){this.closeOwned();this.reportError(error);}
    else this.release();
   }
  });
 };
 async attach(owner,generation){
  for(let i=0;i<15;i++){
   await new Promise(resolve=>setTimeout(resolve,100));
   if(generation!==this.generation || !this.active)return;
   if(!keyboardEnabled() || owner!==window.SteamUIStore?.ActiveWindowInstance || !sideMenusClosed(owner))break;
   if(!this.sameView(owner))continue;
   const manager=owner.VirtualKeyboardManager;
   if(!manager?.IsShowingVirtualKeyboard?.Value)continue;
   const dom=owner.BrowserWindow.document.getElementById('virtual keyboard');
   if(!dom?.getClientRects().length)continue;
   if(!await find())break;
   if(generation!==this.generation)return;
   this.dom=dom;
   if(!this.ownedKeyboard())break;
   this.component=componentFor(dom);
   if(!this.component)break;
   let raw=CreateRawKeyboardListener(this);
   if(getConfig().scheme==='wubi86'){
    const table=wubiTable??await getWubiTable();
    if(generation!==this.generation)return;
    if(!this.ownedKeyboard() || getConfig().scheme!=='wubi86')break;
    wubiTable=table;
    this.wubi=attachWubi(this,table,raw);raw=this.wubi.key;
   }
   SetCandidateDisplay(dom,true,()=>this.component?.UpdateWindowSize?.());
   const down=new Set(),consumed=new Set();
   this.rawListener=(code,value)=>{
    if(!this.ownedKeyboard()){this.release();return;}
    if(value===1)down.add(code);
    const hk=getConfig().adjust;
    const current=[...new Set([...down].map(c=>modifiers[c]).filter(Boolean))].sort();
    if(code===hk.key&&value===1&&JSON.stringify(current)===JSON.stringify([...hk.mods].sort())){
     this.shortClickShiftCode=null;consumed.add(code);dom.__codyToggleAdjustment?.();return;
    }
    if(value===0)down.delete(code);
    if(consumed.has(code)){if(value===0)consumed.delete(code);return;}
    raw(code,value);
   };
   addEventListener('keyboard',this.rawListener);
   await grab();
   return;
  }
  if(generation===this.generation)this.release();
 }
 renew(){
  if(!this.dom)return;
  if(this.ownedKeyboard()){
   // Optional table loading must finish before any key can be intercepted.
   if(this.rawListener)void grab().catch(()=>this.release());
  }
  else this.release();
 }
 release(){
  this.generation++;
  this.owner=null;
  if(this.rawListener){removeEventListener('keyboard',this.rawListener);this.rawListener=null;}
  this.wubi?.dispose();this.wubi=null;
  if(this.dom){
   void ungrab().catch(()=>{});
   this.dom.__codyCandidateObserver?.disconnect();
   delete this.dom.__codyCandidateObserver;
   delete this.dom.__codyCandidateRect;
   delete this.dom.__codyToggleAdjustment;
   delete this.dom.dataset.codyToolsBelow;
   delete this.dom.dataset.codyPhysical;
   delete this.dom.dataset.codyCandidates;
   delete this.dom.dataset.codyAdjusting;
   for(const name of ['candidate-x','candidate-y','candidate-scale','candidate-opacity','tools-x'])
    this.dom.style.removeProperty('--cody-'+name);
   for(const key of this.dom.querySelectorAll('[data-cody-number]'))delete key.dataset.codyNumber;
   this.dom.querySelector('.cody-candidate-handle')?.remove();
   this.dom.ownerDocument.getElementById('cody-keyboard-display-style')?.remove();
   this.dom=null;this.component=null;
  }
 }
 closeOwned(){
  try{this.ownedKeyboard()?.SetVirtualKeyboardHidden?.();}
  catch{/* Steam may already have disposed this keyboard. */}
  finally{this.release();}
 }
 stop(){
  this.closeOwned();this.active=false;
  void flushAppearance().catch(console.error);
 }
}
