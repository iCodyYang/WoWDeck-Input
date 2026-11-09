import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const slots=[], writes=[];
let cursor=0, modal, closed=false;
function slot(make){const i=cursor++;if(!(i in slots))slots[i]=make();return i;}
const react={
 useState(initial){const i=slot(()=>initial);return [slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}];},
 useRef(value){return slots[slot(()=>({current:value}))];},
};
const jsx=(type,props)=>({type,props});
const ui={ModalRoot:'modal',SliderField:'slider',ButtonItem:'button',showModal:view=>{
 modal=view;return {Close:()=>{closed=true;}};
}};
const mods={'react':react,'react/jsx-runtime':{jsx,jsxs:jsx},'@decky/ui':ui,
 '@decky/api':{callable:key=>async value=>{assert.equal(key,'set_voice_bar');writes.push({...value});return value;}}};
const source=readFileSync(new URL('../src/WaveEditor.tsx',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const exports={};
vm.runInNewContext(code,{exports,require:id=>mods[id], window:{screen:{width:1280,height:800}}});
function render(){cursor=0;return modal.type(modal.props).props.children;}
exports.editWave(exports.defaultWave);
let children=render();
let preview=children[2];
const handle={getBoundingClientRect:()=>({left:50,top:40,width:20,height:8}), contains:()=>false};
preview.props.children.props.ref.current=handle;
const board={getBoundingClientRect:()=>({left:0,top:0,width:200,height:100}),setPointerCapture(){}};
const event=(x,y)=>({pointerId:1,currentTarget:board,target:board,clientX:x,clientY:y});
preview.props.onPointerDown(event(70,55));preview.props.onPointerMove(event(250,120));preview.props.onPointerUp(event(250,120));
children=render();
assert.equal(children[2].props.children.props.style.left,'100%');
assert.equal(children[2].props.children.props.style.top,'100%');
children[3][0].props.onChange(12);children[3][2].props.onChange(45);
children=render();
assert.equal(children[2].props.children.props.style.left,'12%');
assert.equal(children[2].props.children.props.style.opacity,.45);
assert.equal(writes.length,0,'editing is a preview until saved');
children.at(-1).props.onClick();await new Promise(resolve=>setImmediate(resolve));
assert.deepEqual(writes,[{x:.12,y:1,opacity:.45}]);assert.equal(closed,true);
console.log('PASS: waveform drag to corners, controller position, opacity preview and saved settings');
