import {EvdevToKey} from './map';

export type WubiTable = Record<string,string[]>;
const PAGE = 5;
const shifts = new Set([42,54]);
const modifiers = new Set([29,97,56,100,125,126]);
const punctuation:Record<number,string> = {12:'-_',13:'=+',26:'[{',27:']}',39:';:',40:'\'"',41:'`~',43:'\\|',51:',<',52:'.>',53:'/?',86:'\\|'};
const chinese:Record<string,string> = {',':'，','.':'。','?':'？','!':'！',':':'：',';':'；','(':'（',')':'）','[':'【',']':'】'};

// Pure state machine: a successful native commit is required before discarding code.
export class WubiComposer {
 code='';page=0;english=false;caps=false;error='';
 private down=new Set<number>();
 private shiftTap:{code:number;at:number}|undefined;
 constructor(private table:WubiTable, private commit:(text:string)=>void,
             private fallback:(code:number,value:number)=>void, private changed:()=>void,
             private now=()=>Date.now()){}
 get candidates(){return this.table[this.code]??[];}
 get visible(){return this.candidates.slice(this.page*PAGE,(this.page+1)*PAGE);}
 get pages(){return Math.max(1,Math.ceil(this.candidates.length/PAGE));}
 reset(){this.code='';this.page=0;this.error='';this.changed();}
 private send(text:string){
  try{this.commit(text);this.reset();return true;}
  catch{this.error='文字未能填入，请重新打开输入界面';this.changed();return false;}
 }
 select(index=0){const text=this.visible[index];return text ? this.send(text) : false;}
 turn(delta:number){this.page=(this.page+delta+this.pages)%this.pages;this.changed();}
 key(code:number,value:number){
  if(value===1){this.down.add(code);if(!shifts.has(code))this.shiftTap=undefined;}
  if(value===0)this.down.delete(code);
  if(shifts.has(code)){
   if(value===1)this.shiftTap=this.down.size===1?{code,at:this.now()}:undefined;
   if(value===0){
    if(this.shiftTap?.code===code && this.now()-this.shiftTap.at<250){this.english=!this.english;this.reset();}
    this.shiftTap=undefined;
   }
   return; // Do not switch Steam's system pinyin layout behind the optional composer.
  }
  if(modifiers.has(code)){if(value===1)this.reset();this.fallback(code,value);return;}
  if(code===58){if(value===1){this.caps=!this.caps;this.reset();}return;}
  if([...this.down].some(key=>modifiers.has(key))){this.fallback(code,value);return;}
  if(value===0)return;
  const shifted=[...this.down].some(key=>shifts.has(key));
  const name=EvdevToKey[code as keyof typeof EvdevToKey]??'';
  if(name.startsWith('Key')){
   const letter=name.slice(3).toLowerCase();
   if(this.english || shifted || this.caps){
    if(this.code && !this.select())return;
    this.send(shifted!==this.caps?letter.toUpperCase():letter);return;
   }
   if(letter==='z'){this.error='五笔 86 使用 A–Y 编码；短按 Shift 可输入英文';this.changed();return;}
   if(this.code.length===4 && !this.select()){this.error='无候选词，请退格修改或按 Esc 取消';this.changed();return;}
   this.code+=letter;this.page=0;this.error='';
   // Standard four-code unique-candidate commit; ambiguous codes wait for selection.
   if(this.code.length===4 && this.candidates.length===1)this.select();
   else this.changed();
   return;
  }
  if(this.code){
   if(code===14){this.code=this.code.slice(0,-1);this.page=0;this.error='';this.changed();return;}
   if(code===1){this.reset();return;}
   if(code===57){if(!this.select()){this.error='无候选词，请修改编码';this.changed();}return;}
   if(code===28){this.send(this.code);return;} // Enter explicitly commits raw code, not chat submission.
   if(code>=2 && code<=10 && !shifted){this.select(code-2);return;}
   if(code===104 || code===109 || (!shifted && (code===12 || code===13))){this.turn(code===104 || code===12?-1:1);return;}
   if(punctuation[code]){if(!this.select())return;}
   else return; // Navigation cannot silently discard or send an unfinished code.
  }
  let text:string|undefined;
  if(name.startsWith('Digit')){const n=Number(name.slice(5));text=shifted?')!@#$%^&*('[n]:String(n);}
  else if(punctuation[code])text=punctuation[code][shifted?1:0];
  else if(code===57)text=' ';
  if(text!==undefined){this.send(this.english || this.caps?text:(chinese[text]??text));return;}
  // Native editing keys must bypass pinyin too, so an old pinyin preedit cannot reappear.
  if(['Backspace','Delete','Enter','Tab','ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Escape'].includes(name)){
   this.send(name==='Escape'?'VKClose':name==='Delete'?'\x7f':name);return;
  }
  this.fallback(code,value);
 }
}

// Installed only for an explicitly selected Wubi context. It never mutates IBus settings.
export function attachWubi(ctx:any,table:WubiTable,fallback:(code:number,value:number)=>void){
 const manager=ctx.ownedKeyboard();
 if(typeof manager?.HandleVirtualKeyDown!=='function')throw Error('当前 Steam 版本尚不支持五笔文字填入，请切回全拼或小鹤');
 const dom=ctx.dom,doc=dom.ownerDocument,panel=dom.firstElementChild;
 const row=doc.createElement('div');row.className='Row_IME cody-wubi';
 row.style.cssText='flex-wrap:wrap;max-width:min(640px,calc(100vw - 24px));color:#eee;align-items:center;padding:6px';
 const style=doc.createElement('style');
 style.textContent='[data-cody-wubi="true"] .Row_IME:not(.cody-wubi){display:none!important}.cody-wubi button{color:inherit;background:#34383e;border:0;border-radius:4px;font:inherit;cursor:pointer}';
 dom.dataset.codyWubi='true';panel.append(style,row);
 const paint=()=>{
  row.replaceChildren();
  const label=doc.createElement('span');
  label.textContent=`${composer.english || composer.caps?'英文':'五笔 86'} · ${composer.code || 'Shift 中/英'}`;
  row.append(label);
  composer.visible.forEach((text,index)=>{
   const button=doc.createElement('button');button.type='button';button.textContent=`${index+1} ${text}`;
   button.onclick=(event:Event)=>{event.preventDefault();event.stopPropagation();if(ctx.ownedKeyboard())composer.select(index);};
   row.append(button);
  });
  if(composer.pages>1){const hint=doc.createElement('span');hint.textContent=`${composer.page+1}/${composer.pages} · −/+ 翻页`;row.append(hint);}
  if(composer.error || (composer.code && !composer.candidates.length)){
   const hint=doc.createElement('span');hint.textContent=composer.error || '继续编码 · 退格修改';row.append(hint);
  }
 };
 // Candidate clicks must not focus a new text target or trigger the hidden Steam keys.
 row.onpointerdown=(event:PointerEvent)=>{event.preventDefault();event.stopPropagation();};
 const composer=new WubiComposer(table,text=>{
  if(ctx.ownedKeyboard()!==manager)throw Error('keyboard ownership ended');
  manager.HandleVirtualKeyDown(text);
 },fallback,paint);
 composer.caps=!!ctx.component?.state?.toggleStates?.CapsLock;
 paint();
 return {key:(code:number,value:number)=>{
  // Keep native modifier state for Ctrl+Shift shortcuts, without toggling its IME.
  if(shifts.has(code)){
   if(value===0)ctx.shortClickShiftCode=null;
   fallback(code,value);
  }
  if(code===58)fallback(code,value);
  composer.key(code,value);
 },dispose(){row.remove();style.remove();delete dom.dataset.codyWubi;}};
}
