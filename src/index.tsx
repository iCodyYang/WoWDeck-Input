import {useEffect,useRef,useState} from 'react';
import {ButtonItem,DropdownItem,PanelSection,PanelSectionRow,SliderField,ToggleField,staticClasses} from '@decky/ui';
import {addEventListener,removeEventListener,definePlugin,toaster,callable} from '@decky/api';
import {Voice} from './Voice';
import {FaKeyboard} from 'react-icons/fa';
import {api,getConfig,putConfig,hotkeyLabel,State} from './config';
import {KeyboardContext,sideMenusClosed,sideMenuState} from './utility/context';
import {getKeyboardSetup,openKeyboardSettings,CHINESE_KEYBOARD_STEPS,KeyboardSetup} from './keyboard-setup';
let context:KeyboardContext|undefined;
function error(e:unknown){toaster.toast({title:'WoWDeck Input',body:String(e)});}
function Content(){
 const [setup,setSetup]=useState<KeyboardSetup>(()=>getKeyboardSetup());
 const [state,setState]=useState<State>();const [busy,setBusy]=useState(false);const [message,setMessage]=useState('');
 const [keyboardSettings,showKeyboardSettings]=useState(false);
 const pending=useRef(false),generation=useRef(0);
 const refresh=async()=>{if(pending.current)return;const request=++generation.current;const s=await api.state();if(request===generation.current){setSetup(getKeyboardSetup());setState(s);}};
 useEffect(()=>{void refresh().catch(error);const timer=setInterval(()=>void refresh().catch(()=>{}),3000);return ()=>{++generation.current;clearInterval(timer);};},[]);
 async function action(fn:()=>Promise<State>){pending.current=true;++generation.current;setBusy(true);try{const s=await fn();setState(s);setMessage('已保存');}catch(e){setMessage(String(e));error(e);}finally{pending.current=false;setBusy(false);}}
 if(!state)return <PanelSection><PanelSectionRow>正在读取设置…</PanelSectionRow></PanelSection>;
 const c=state.config,s=state.status;const row=(v:React.ReactNode)=><PanelSectionRow>{v}</PanelSectionRow>;
 return <>
 <PanelSection title="WoWDeck Input">
 {row(<ToggleField label="总开关" checked={c.pluginEnabled} disabled={busy} onChange={v=>void action(()=>api.master(v))}/>)}
 {message && message!=='已保存' && row(<div>{message}</div>)}
 {row(<div style={{fontSize:12}}>{c.pluginEnabled?'总开关已开启':'总开关已关闭，键盘与语音均不会启动'} · 键盘{c.pluginEnabled && c.enabled?'已开启':'已关闭'}</div>)}
 {row(<ButtonItem layout="below" disabled={busy} onClick={()=>void action(()=>api.inspect())}>重新检测键盘（不改变开关）</ButtonItem>)}
 {row(<div style={{fontSize:12,overflowWrap:'anywhere'}}>{s.inputStatus}{s.inputErrors?.map((item,i)=><div key={'e'+i}>{item}</div>)}{s.inputDetails?.map((item,i)=><div key={'d'+i}>{item}</div>)}</div>)}
 </PanelSection>
 <PanelSection title="外接键盘输入法">
 {row(<div style={{fontSize:12,opacity:.75}}>也支持掌机自带的实体键盘。</div>)}
 {row(<ToggleField label="启用外接键盘输入法" checked={c.pluginEnabled && c.enabled} disabled={!c.pluginEnabled||busy} onChange={v=>void action(()=>{if(v&&c.scheme!=='wubi86'&&(!s.engine||getKeyboardSetup().state==='disabled'))showKeyboardSettings(true);if(v&&c.scheme!=='wubi86'&&!s.engine)return Promise.reject('系统中文引擎未就绪，请在外接键盘设置中添加简体中文');if(v&&c.scheme!=='wubi86'&&getKeyboardSetup().state==='disabled')return Promise.reject(CHINESE_KEYBOARD_STEPS);if(v&&(window as any).DeckyPluginLoader?.plugins?.some((p:any)=>p.name==='Better Keyboard'))return Promise.reject('请先在 Decky 中停用 Better Keyboard，避免键盘被重复接管');return api.enabled(v);})}/>)}
 {row(<ButtonItem layout="below" disabled={!c.pluginEnabled} onClick={()=>showKeyboardSettings(!keyboardSettings)}>{keyboardSettings?'收起外接键盘设置':'外接键盘设置'}</ButtonItem>)}
 {c.pluginEnabled && keyboardSettings && <>
 {row(<div style={{fontSize:12}}>{c.scheme==='wubi86'?'五笔 86 使用内置词库，无需更改系统拼音。':<>{s.engine?'✓ 系统中文引擎已就绪':'未检测到系统中文拼音引擎'}<br/>{setup.state==='enabled'?'✓ Steam 已启用简体中文键盘':setup.state==='disabled'?'尚未启用 Steam 简体中文键盘':'当前 Steam 版本暂时无法读取键盘列表，请手动核对'}</>}</div>)}
 {c.scheme!=='wubi86'&&(setup.state!=='enabled'||!s.engine)&&<>
 {row(<div style={{fontSize:12}}>{CHINESE_KEYBOARD_STEPS}<br/>无需切换桌面模式或安装桌面输入法。若仍检测不到引擎，请检查 SteamOS 更新，不必修改系统只读分区。</div>)}
 {row(<ButtonItem layout="below" onClick={()=>{try{openKeyboardSettings();}catch(e){error(e);}}}>打开 Steam 键盘设置</ButtonItem>)}
 </>}
 {row(<ButtonItem layout="below" onClick={()=>void refresh().catch(error)}>重新检测</ButtonItem>)}

 {row(<DropdownItem label="中文输入方案" selectedOption={s.scheme} rgOptions={[{data:'keep',label:'保持系统当前方案'},{data:'full',label:'全拼'},{data:'xiaohe',label:'小鹤双拼'},{data:'wubi86',label:'五笔 86（试用）'}]} disabled={busy||s.grabbing} onChange={v=>{if(v.data!=='keep')void action(()=>api.scheme(v.data));}}/>)}
 {row(<div style={{fontSize:12,opacity:.75}}>全拼与小鹤需要先添加 Steam 简体中文键盘，使用系统 IBus 设置。五笔 86 使用插件内置词库，仅作用于此插件的实体键盘输入，不改系统拼音。短按 Shift 切换中英文；切换方案前先关闭输入界面。</div>)}
 {row(<strong>快捷键</strong>)}
 {(['wake','adjust'] as const).map(target=><PanelSectionRow key={target}><ButtonItem layout="below" disabled={busy||!!s.capturing||!c.enabled||s.keyboards.length===0} onClick={()=>void action(()=>api.capture(target))}>{target==='wake'?'唤醒输入界面':'调整候选框'}：{hotkeyLabel(c[target])} · 点击录制</ButtonItem></PanelSectionRow>)}
 {s.capturing&&<>
 {row(<div>请在机身或外接键盘上按下组合键后全部松开。Esc 取消，20 秒超时。</div>)}
 {row(<ButtonItem layout="below" onClick={()=>void action(()=>api.cancel())}>取消录制</ButtonItem>)}
 </>}
 {row(<ButtonItem layout="below" disabled={busy||!!s.capturing} onClick={()=>void action(async()=>{await api.hotkey('wake',{key:57,mods:['Ctrl']});return api.hotkey('adjust',{key:66,mods:[]});})}>恢复 Ctrl＋空格 / F8</ButtonItem>)}
 {row(<strong>候选框</strong>)}
 {row(<SliderField label="大小" min={65} max={125} step={5} value={Math.round(c.appearance.scale*100)} showValue valueSuffix="%" onChange={v=>{const a={...c.appearance,scale:v/100};putConfig({...getConfig(),appearance:a});setState({...state,config:getConfig()});void api.appearance(a).catch(error);}}/>)}
 {row(<SliderField label="透明度" min={0} max={80} step={5} value={Math.round((1-c.appearance.opacity)*100)} showValue valueSuffix="%" onChange={v=>{const a={...c.appearance,opacity:1-v/100};putConfig({...getConfig(),appearance:a});setState({...state,config:getConfig()});void api.appearance(a).catch(error);}}/>)}
 {row(<div style={{fontSize:12,opacity:.75}}>输入时按 {hotkeyLabel(c.adjust)} 调出拖动与大小/透明度控件；再按一次保存隐藏。无外接键盘时，Steam＋X 显示完整键盘。</div>)}
 {row(<ButtonItem layout="below" disabled={busy} onClick={()=>void action(async()=>{await api.appearance({x:12,y:80,scale:.85,opacity:.95});return api.state();})}>重置候选框位置和样式</ButtonItem>)}

 {row(<div style={{fontSize:12,overflowWrap:'anywhere'}}>{s.keyboards.length?'正在监听：'+s.keyboards.join('、'):s.inputStatus}<br/>{s.engine?'中文引擎可用':'缺少中文拼音引擎'}<br/>{s.error||message}<br/>v{s.version} · 设置自动保存</div>)}
 {row(<ButtonItem layout="below" disabled={busy||s.grabbing} onClick={()=>void action(()=>api.restore())}>恢复首次切换前的系统输入方案</ButtonItem>)}
 </>}
 </PanelSection>
 <Voice master={c.pluginEnabled} wanted={c.voiceWanted}/>
 </>;
}
export default definePlugin(()=>{
 context=new KeyboardContext(error);let alive=true,preferenceRevision=0,checkedLegacy=false;
 const tellUI=callable<[string],void>('voice_ui_state');
 let lastToast:ReturnType<typeof toaster.toast>|undefined;
 let timer:ReturnType<typeof setInterval>|undefined;
 const inGameUI=()=>sideMenusClosed((window as any).SteamUIStore?.ActiveWindowInstance);
 const heartbeat=()=>{
  if(!getConfig().pluginEnabled)return;
  context?.renew();
  if(!getConfig().voiceWanted)return;
  const menu=sideMenuState((window as any).SteamUIStore?.ActiveWindowInstance);
  const state=menu==='unknown'?'unknown':menu==='open'?'blocked':context?.ownedKeyboard()?'keyboard':'game';
  if(state==='blocked'){lastToast?.dismiss();lastToast=undefined;}
  void tellUI(state).catch(()=>{});
 };
 const feedback=(event:{phase:string;message:string;hideKeyboard:boolean})=>{
  if(!alive || !getConfig().pluginEnabled || !getConfig().voiceWanted || !inGameUI())return;
  if(event.hideKeyboard)context?.ownedKeyboard()?.SetVirtualKeyboardHidden();
  lastToast?.dismiss();
  lastToast=undefined;
  if(event.phase!=='error' && event.phase!=='wave_unavailable')return;
  const duration=1800;
  lastToast=toaster.toast({title:'语音输入',body:event.message,showToast:true,playSound:false,
      showNewIndicator:false,duration,expiration:duration});
 };
 const open=()=>{try{if(getConfig().pluginEnabled && getConfig().enabled && inGameUI()){
  if(getConfig().scheme!=='wubi86'&&getKeyboardSetup().state==='disabled')throw Error(CHINESE_KEYBOARD_STEPS);context?.open();
 }}catch(e){error(e);}};
 const preferences=(config:State['config'])=>{
  preferenceRevision++;
  if(!config.pluginEnabled || !config.enabled || config.scheme!==getConfig().scheme)context?.closeOwned();
  putConfig(config);
  if(config.pluginEnabled && (config.enabled || config.voiceWanted)){
   if(timer===undefined)timer=setInterval(heartbeat,250);
  }else if(timer!==undefined){clearInterval(timer);timer=undefined;}
  if(!config.pluginEnabled || !config.voiceWanted){lastToast?.dismiss();lastToast=undefined;}
  if(config.pluginEnabled && !config.appearance_migrated && !checkedLegacy){
   checkedLegacy=true;
   try{
    const old=JSON.parse(localStorage.getItem('bk.cody_candidate_position')||'null');
    const revision=preferenceRevision;
    if(old && Number.isFinite(old.x) && Number.isFinite(old.y))
     void api.migrate(old).then(c=>{if(alive && preferenceRevision===revision)putConfig(c);}).catch(()=>{});
   }catch{}
  }
 };
 const captureResult=(r:{error?:string})=>{
  if(!getConfig().pluginEnabled)return;
  if(r.error)error(r.error);else toaster.toast({title:'WoWDeck Input',body:'快捷键已保存'});
 };
 addEventListener('voice_feedback',feedback);
 addEventListener('open_keyboard',open);addEventListener('preferences',preferences);addEventListener('capture_result',captureResult);
 void api.state().then(s=>{
  if(alive && !preferenceRevision)preferences(s.config);
 }).catch(error);
 return {name:'WoWDeck Input',titleView:<div className={staticClasses.Title}>WoWDeck Input</div>,content:<Content/>,icon:<FaKeyboard/>,onDismount(){alive=false;clearInterval(timer);lastToast?.dismiss();void tellUI('blocked').catch(()=>{});removeEventListener('voice_feedback',feedback);removeEventListener('open_keyboard',open);removeEventListener('preferences',preferences);removeEventListener('capture_result',captureResult);context?.stop();context=undefined;}};
});
