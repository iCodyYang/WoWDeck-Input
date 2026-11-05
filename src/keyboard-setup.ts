import {findModuleExport,Navigation} from '@decky/ui';
export type KeyboardSetup={state:'enabled'|'disabled'|'unknown';names:string[]};
type Layout={name:string;layout:number;locToken?:string};
let nativeGetter:(()=>Layout[])|undefined;
// Steam's native enabled-layout getter (Qe in the tracked client) filters selectedLayouts
// and currentLayout through its IBus-aware catalog. Do not infer from engine files.
export function getKeyboardSetup():KeyboardSetup{
 try{
  if(!nativeGetter)nativeGetter=findModuleExport((value:unknown)=>{
   if(typeof value!=='function'||value.length!==0)return false;
   const source=Function.prototype.toString.call(value);
   return source.includes('selectedLayouts.includes')&&source.includes('currentLayout')&&source.includes('.filter(');
  });
  if(!nativeGetter)return {state:'unknown',names:[]};
  const layouts=nativeGetter();
  if(!Array.isArray(layouts)||layouts.length===0||layouts.some(l=>!l||typeof l.name!=='string'||typeof l.layout!=='number'))return {state:'unknown',names:[]};
  const enabled=layouts.some(l=>l.name==='schinese'||l.locToken==='#KeyboardLayout_Chinese_Simplified');
  return {state:enabled?'enabled':'disabled',names:layouts.map(l=>l.name)};
 }catch{return {state:'unknown',names:[]};}
}
export const CHINESE_KEYBOARD_STEPS='游戏模式：Steam → 设置 → 键盘 → 当前键盘/启用的键盘 → 编辑，勾选“简体中文（拼音）”，确认后返回插件。';
export function openKeyboardSettings(){Navigation.CloseSideMenus();Navigation.Navigate('/settings/keyboard');}
