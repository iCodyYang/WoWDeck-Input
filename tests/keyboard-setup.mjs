import ts from 'typescript';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const source=readFileSync(new URL('../src/keyboard-setup.ts',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
function load(options={}){
 let selected=options.selected??[0],current=options.current??0;
 const catalog=[{name:'qwerty',layout:0},{name:'schinese',layout:2,locToken:'#KeyboardLayout_Chinese_Simplified'}];
 function nativeGetter(){const settings={currentLayout:current,selectedLayouts:selected};return catalog.filter(layout=>settings.currentLayout===layout.layout||settings.selectedLayouts.length===0||settings.selectedLayouts.includes(layout.layout));}
 const exports={},navigation=[];
 vm.runInNewContext(code,{exports,require(){return {findModuleExport(filter){if(options.missing)return undefined;if(options.broken)return ()=>{throw Error('not ready')};assert.equal(filter(nativeGetter),true);return nativeGetter;},Navigation:{CloseSideMenus(){navigation.push('close')},Navigate(path){navigation.push(path)}}};}});
 return {exports,navigation};
}
assert.equal(load().exports.getKeyboardSetup().state,'disabled');
assert.equal(load({selected:[0,2]}).exports.getKeyboardSetup().state,'enabled');
assert.equal(load({selected:[0],current:2}).exports.getKeyboardSetup().state,'enabled');
assert.equal(load({selected:[]}).exports.getKeyboardSetup().state,'enabled','native empty list means all available layouts');
assert.equal(load({missing:true}).exports.getKeyboardSetup().state,'unknown');
assert.equal(load({broken:true}).exports.getKeyboardSetup().state,'unknown');
const example=load();example.exports.openKeyboardSettings();assert.deepEqual(example.navigation,['close','/settings/keyboard']);
console.log('PASS: native selected/current/empty layouts, unavailable API fallback, and keyboard-settings navigation');
