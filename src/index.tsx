import {useEffect,useState} from 'react';
import {ButtonItem,DropdownItem,PanelSection,PanelSectionRow,SliderField,ToggleField,staticClasses} from '@decky/ui';
import {addEventListener,removeEventListener,definePlugin,toaster} from '@decky/api';
import {FaKeyboard} from 'react-icons/fa';
import {api,getConfig,putConfig,hotkeyLabel,State} from './config';
import {KeyboardContext} from './utility/context';
import {getKeyboardSetup,openKeyboardSettings,CHINESE_KEYBOARD_STEPS,KeyboardSetup} from './keyboard-setup';
let context:KeyboardContext|undefined;
let recording=false;
function error(e:unknown){toaster.toast({title:'WoWDeck Input',body:String(e)});}
function Content(){
 const [setup,setSetup]=useState<KeyboardSetup>(()=>getKeyboardSetup());
 const [state,setState]=useState<State>();const [busy,setBusy]=useState(false);const [message,setMessage]=useState('');
 const refresh=()=>api.state().then(s=>{setSetup(getKeyboardSetup());putConfig(s.config);recording=!!s.status.capturing;setState(s);});
 useEffect(()=>{void refresh().catch(error);const timer=setInterval(()=>void refresh().catch(()=>{}),3000);return ()=>clearInterval(timer);},[]);
 async function action(fn:()=>Promise<State>){setBusy(true);try{const s=await fn();putConfig(s.config);recording=!!s.status.capturing;setState(s);setMessage('已保存');}catch(e){setMessage(String(e));error(e);}finally{setBusy(false);}}
 if(!state)return <PanelSection><PanelSectionRow>正在读取设置…</PanelSectionRow></PanelSection>;
 const c=state.config,s=state.status;const row=(v:React.ReactNode)=><PanelSectionRow>{v}</PanelSectionRow>;
 return <>
 <PanelSection title="首次使用检查">
 {row(<div style={{fontSize:12}}>{s.engine?'✓ 系统中文引擎已就绪':'未检测到系统中文拼音引擎'}<br/>{setup.state==='enabled'?'✓ Steam 已启用简体中文键盘':setup.state==='disabled'?'尚未启用 Steam 简体中文键盘':'当前 Steam 版本暂时无法读取键盘列表，请手动核对'}</div>)}
 {(setup.state!=='enabled'||!s.engine)&&<>
 {row(<div style={{fontSize:12}}>{CHINESE_KEYBOARD_STEPS}<br/>无需切换桌面模式或安装桌面输入法。若仍检测不到引擎，请检查 SteamOS 更新，不必修改系统只读分区。</div>)}
 {row(<ButtonItem layout="below" onClick={()=>{try{openKeyboardSettings();}catch(e){error(e);}}}>打开 Steam 键盘设置</ButtonItem>)}
 </>}
 {row(<ButtonItem layout="below" onClick={()=>void refresh().catch(error)}>重新检测</ButtonItem>)}
 </PanelSection>
 <PanelSection title="魔兽掌机输入法">
 {row(<ToggleField label="启用输入增强" checked={c.enabled} disabled={busy} onChange={v=>void action(()=>{if(v&&!s.engine)return Promise.reject('系统中文引擎未就绪，请按首次使用检查中的说明设置');if(v&&getKeyboardSetup().state==='disabled')return Promise.reject(CHINESE_KEYBOARD_STEPS);if(v&&(window as any).DeckyPluginLoader?.plugins?.some((p:any)=>p.name==='Better Keyboard'))return Promise.reject('请先在 Decky 中停用 Better Keyboard，避免键盘被重复接管');return api.enabled(v);})}/>)}
 {row(<DropdownItem label="中文输入方案" selectedOption={s.scheme} rgOptions={[{data:'keep',label:'保持系统当前方案'},{data:'full',label:'全拼'},{data:'xiaohe',label:'小鹤双拼'}]} disabled={busy||s.grabbing||!s.engine} onChange={v=>{if(v.data!=='keep')void action(()=>api.scheme(v.data));}}/>)}
 {row(<div style={{fontSize:12,opacity:.75}}>先在 Steam 键盘设置中添加简体中文。短按左右 Shift 切换中英文；切换全拼/双拼前请先关闭输入界面。方案使用系统 IBus，会影响其他使用该引擎的应用。</div>)}
 </PanelSection>
 <PanelSection title="快捷键">
 {(['wake','adjust'] as const).map(target=><PanelSectionRow key={target}><ButtonItem layout="below" disabled={busy||!!s.capturing||!c.enabled||s.keyboards.length===0} onClick={()=>void action(()=>api.capture(target))}>{target==='wake'?'唤醒输入界面':'调整候选框'}：{hotkeyLabel(c[target])} · 点击录制</ButtonItem></PanelSectionRow>)}
 {s.capturing&&<>
 {row(<div>请在外接键盘上按下组合键后全部松开。Esc 取消，20 秒超时。</div>)}
 {row(<ButtonItem layout="below" onClick={()=>void action(()=>api.cancel())}>取消录制</ButtonItem>)}
 </>}
 {row(<ButtonItem layout="below" disabled={busy||!!s.capturing} onClick={()=>void action(async()=>{await api.hotkey('wake',{key:57,mods:['Ctrl']});return api.hotkey('adjust',{key:66,mods:[]});})}>恢复 Ctrl＋空格 / F8</ButtonItem>)}
 </PanelSection>
 <PanelSection title="候选框">
 {row(<SliderField label="大小" min={65} max={125} step={5} value={Math.round(c.appearance.scale*100)} showValue valueSuffix="%" onChange={v=>{const a={...c.appearance,scale:v/100};putConfig({...c,appearance:a});setState({...state,config:getConfig()});void api.appearance(a).catch(error);}}/>)}
 {row(<SliderField label="透明度" min={0} max={80} step={5} value={Math.round((1-c.appearance.opacity)*100)} showValue valueSuffix="%" onChange={v=>{const a={...c.appearance,opacity:1-v/100};putConfig({...c,appearance:a});setState({...state,config:getConfig()});void api.appearance(a).catch(error);}}/>)}
 {row(<div style={{fontSize:12,opacity:.75}}>输入时按 {hotkeyLabel(c.adjust)} 调出拖动与大小/透明度控件；再按一次保存隐藏。无外接键盘时，Steam＋X 显示完整键盘。</div>)}
 {row(<ButtonItem layout="below" disabled={busy} onClick={()=>void action(async()=>{await api.appearance({x:12,y:80,scale:.85,opacity:.95});return api.state();})}>重置候选框位置和样式</ButtonItem>)}
 </PanelSection>
 <PanelSection title="状态与恢复">
 {row(<div style={{fontSize:12}}>{s.keyboards.length?'外接键盘：'+s.keyboards.join('、'):'尚未检测到外接键盘'}<br/>{s.engine?'中文引擎可用':'缺少中文拼音引擎'}<br/>{s.error||message}<br/>v0.1.3 · 设置自动保存</div>)}
 {row(<ButtonItem layout="below" disabled={busy||s.grabbing} onClick={()=>void action(()=>api.restore())}>恢复首次切换前的系统输入方案</ButtonItem>)}
 </PanelSection>
 </>;
}
export default definePlugin(()=>{
 context=new KeyboardContext();let alive=true;let captureWindow:Window|undefined;
 const open=()=>{try{if(getKeyboardSetup().state==='disabled')throw Error(CHINESE_KEYBOARD_STEPS);context?.open();}catch(e){error(e);}};
 const preferences=(config:any)=>{putConfig(config);if(!config.enabled){context?.stop();context=new KeyboardContext();}else context?.replace();};
 const captureResult=(r:{error?:string})=>{recording=false;if(r.error)error(r.error);else toaster.toast({title:'WoWDeck Input',body:'快捷键已保存'});void api.state().then(s=>putConfig(s.config));};
 addEventListener('open_keyboard',open);addEventListener('preferences',preferences);addEventListener('capture_result',captureResult);
 const guard=(event:KeyboardEvent)=>{if(recording){event.preventDefault();event.stopImmediatePropagation();}};
 const timer=setInterval(()=>{if(alive)context?.replace();},1000);
 const captureTimer=setInterval(()=>{if(recording)void api.state().then(s=>{recording=!!s.status.capturing;}).catch(()=>{});const w=(window as any).SteamUIStore?.ActiveWindowInstance?.BrowserWindow;if(w!==captureWindow){captureWindow?.removeEventListener('keydown',guard,true);captureWindow=w;captureWindow?.addEventListener('keydown',guard,true);}},500);
 void api.state().then(async s=>{
  if(!alive)return;
  if(!s.config.appearance_migrated){try{const old=JSON.parse(localStorage.getItem('bk.cody_candidate_position')||'null');if(old&&Number.isFinite(old.x)&&Number.isFinite(old.y))s.config=await api.migrate(old);}catch{}}
  if(!alive)return;putConfig(s.config);context?.replace();
 }).catch(error);
 return {name:'WoWDeck Input',titleView:<div className={staticClasses.Title}>WoWDeck Input</div>,content:<Content/>,icon:<FaKeyboard/>,onDismount(){alive=false;clearInterval(timer);clearInterval(captureTimer);captureWindow?.removeEventListener('keydown',guard,true);removeEventListener('open_keyboard',open);removeEventListener('preferences',preferences);removeEventListener('capture_result',captureResult);context?.stop();context=undefined;}};
});
