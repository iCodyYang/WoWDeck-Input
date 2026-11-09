import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
function load(file,modules={}){
 const exports={};
 vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/utility/'+file,import.meta.url),'utf8'),{
  compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText,
  {exports,require:name=>modules[name]});return exports;
}
const map=load('map.ts'),{WubiComposer,attachWubi}=load('wubi.ts',{'./map':map});
const table={wq:['你'],vbg:['好','㛅'],abcd:['测试'],abce:['一','二','三','四','五','六','七'],q:['我']};
let output=[],fallback=[],clock=0,fail=false,changes=0;
const c=new WubiComposer(table,text=>{if(fail)throw Error();output.push(text);},(...args)=>fallback.push(args),()=>changes++,()=>clock);
const key=(code,value=1)=>c.key(code,value),tap=code=>{key(code);key(code,0);};
const letters=text=>{for(const char of text)tap(Number(Object.keys(map.EvdevToKey).find(code=>map.EvdevToKey[code]==='Key'+char.toUpperCase())));};
letters('wq');tap(57);letters('vbg');tap(2);assert.deepEqual(output,['你','好']);
letters('abcd');assert.equal(output.at(-1),'测试','unique fourth code commits automatically');
letters('abce');assert.equal(c.code,'abce');tap(109);tap(2);assert.equal(output.at(-1),'六');
letters('abce');tap(13);tap(3);assert.equal(output.at(-1),'七');
letters('wq');tap(14);assert.equal(c.code,'w');tap(1);assert.equal(c.code,'');
letters('zz');assert.equal(c.code,'');assert.ok(c.error);c.reset();
letters('qqqq');const before=output.length;tap(57);assert.equal(output.length,before,'invalid code cannot reuse old candidate');tap(1);
letters('wq');fail=true;tap(57);assert.equal(c.code,'wq','failed commit retains code');fail=false;tap(57);assert.equal(output.at(-1),'你');
letters('wq');tap(28);assert.equal(output.at(-1),'wq','Enter confirms raw code without sending chat');
tap(42);assert.equal(c.english,true);letters('ab');assert.deepEqual(output.slice(-2),['a','b']);tap(42);assert.equal(c.english,false);
key(42);letters('q');key(42,0);assert.equal(c.english,false);assert.equal(output.at(-1),'Q');
key(42);clock+=300;key(42,0);assert.equal(c.english,false,'long Shift is not language toggle');
tap(58);letters('q');assert.equal(output.at(-1),'Q');tap(58);
letters('q');key(29);tap(30);key(29,0);assert.equal(c.code,'');assert.ok(fallback.some(([code])=>code===30),'Ctrl combinations pass through');
tap(51);assert.equal(output.at(-1),'，');tap(14);assert.equal(output.at(-1),'Backspace');tap(1);assert.equal(output.at(-1),'VKClose');
assert.throws(()=>attachWubi({ownedKeyboard:()=>({})},table,()=>{}),/Steam/);
assert.ok(changes>0);
console.log('PASS: Wubi words, auto commit, pagination, invalid code, failed delivery, Shift, English, Ctrl, editing and API guard');
