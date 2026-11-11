import {useEffect,useRef,useState} from 'react';
import {ButtonItem,DropdownItem,PanelSection,PanelSectionRow,ToggleField} from '@decky/ui';
import {callable} from '@decky/api';
import {editWave,defaultWave,WaveStyle} from './WaveEditor';

type VoiceState = {
  wanted:boolean; running:boolean; enabled:boolean; signed:boolean; auth:string; hasProfile:boolean;
  bar:WaveStyle; qr:string; message:string; hotkey:string; testing:boolean; testMessage:string; detectedKey:string; retryBlocked:boolean;
};
const getVoice=callable<[],VoiceState>('get_voice_state');
const changeVoice=callable<[string],VoiceState>('voice_action');
const setVoiceKey=callable<[string],VoiceState>('set_voice_key');
const installChatDraft=callable<[],string>('install_chat_draft');
const keys=Array.from({length:12},(_,i)=>({data:`F${i+1}`,label:`F${i+1}`}));

export function Voice({master,wanted}:{master:boolean;wanted:boolean}){
 const [state,setState]=useState<VoiceState>();
 const [show,setShow]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [confirmLogout,setConfirmLogout]=useState(false);
 const [draftMessage,setDraftMessage]=useState('');
 const revision=useRef(0),editing=useRef(false);
 useEffect(()=>{
  if(!master){setState(undefined);setShow(false);setConfirmLogout(false);setDraftMessage('');setError('');return;}
  let mounted=true,loading=false;
  async function refresh(){
   if(loading || editing.current)return;
   const start=revision.current;
   loading=true;
   try{const s=await getVoice();if(mounted && start===revision.current)setState(s);}
   catch{if(mounted)setError('无法读取语音状态');}
   finally{loading=false;}
  }
  void refresh();
  const timer=setInterval(refresh,1000);
  return ()=>{mounted=false;clearInterval(timer);};
 },[master]);
 async function run(fn:()=>Promise<VoiceState>){
  editing.current=true;revision.current++;setBusy(true);setError('');
  try{setState(await fn());}
  catch(e){setError(String(e));}
  finally{editing.current=false;setBusy(false);}
 }
 async function installDraft(){
  if(busy)return;
  setBusy(true);setDraftMessage('');setError('');
  try{setDraftMessage(await installChatDraft());}
  catch(e){setDraftMessage(String(e));}
  finally{setBusy(false);}
 }
 const key=state?.hotkey || 'F7';
 const on=master && (state?.wanted ?? wanted);
 const row=(v:React.ReactNode)=><PanelSectionRow>{v}</PanelSectionRow>;
 const button=(label:string,action:string)=>row(<ButtonItem layout="below" disabled={busy} onClick={()=>void run(()=>changeVoice(action))}>{label}</ButtonItem>);
 const summary=!on?'':state?.retryBlocked?'连接已暂停，请打开语音设置查看原因并重试':state?.testing?'正在检测按键':state?.enabled?`就绪 · 按住 ${key} 说话，松开转写`:
     state?.auth==='guest'?'请在语音设置中扫码登录':state?.running?'正在连接语音服务…':'正在准备语音输入…';
 return <PanelSection title="语音输入">
  {row(<ToggleField label="启用语音输入" description={summary} checked={on} disabled={!master||busy} onChange={v=>{
    if(v && !state?.signed)setShow(true);
    void run(()=>changeVoice(v?'arm':'disarm'));
  }}/>)}
  {row(<ButtonItem layout="below" disabled={!master} onClick={()=>setShow(!show)}>{show?'收起语音设置':'语音设置'}</ButtonItem>)}
  {master && error && row(<div>{error}</div>)}
  {master && show && <>
   {row(<div>{state?.signed?'账号已登录':state?.retryBlocked?'连接失败，已停止自动重试':state?.auth==='guest'?'等待扫码登录':state?.running?'正在连接账号…':state?.hasProfile?'账号未连接':'未登录'}</div>)}
   {state && !confirmLogout && (state.signed || (state.hasProfile && state.auth!=='guest')) &&
    row(<ButtonItem layout="below" disabled={busy} onClick={()=>setConfirmLogout(true)}>退出登录</ButtonItem>)}
   {confirmLogout && <>
    {row(<div>退出当前账号并关闭听写？下次可以重新扫码登录。</div>)}
    {row(<ButtonItem layout="below" disabled={busy} onClick={()=>{
      setConfirmLogout(false);void run(()=>changeVoice('logout'));
    }}>确认退出</ButtonItem>)}
    {row(<ButtonItem layout="below" onClick={()=>setConfirmLogout(false)}>取消</ButtonItem>)}
   </>}
   {state?.qr && row(<img alt="语音服务登录二维码" src={state.qr} style={{display:'block',width:'min(220px, 100%)',height:'auto',aspectRatio:'1',objectFit:'contain',boxSizing:'border-box',
      padding:8,background:'#fff',margin:'0 auto',imageRendering:'pixelated'}}/>)}
   {state && !state.running && button(state.retryBlocked||state.hasProfile?'重新连接账号':'扫码登录','restore')}
   {state?.running && !state.signed && button('重新获取二维码','refresh')}
   {state?.message && row(<div style={{fontSize:13,overflowWrap:'anywhere'}}>{state.message}</div>)}
   {row(<DropdownItem label="听写快捷键" selectedOption={key} rgOptions={keys} disabled={busy||!!state?.testing}
      onChange={v=>void run(()=>setVoiceKey(v.data))}/>)}
   {row(<div style={{fontSize:12}}>按住 {key} 说话，松开转写；转写中再按一次取消。文字填入魔兽聊天框后，快速点两下同一个键可清空草稿。</div>)}
   {state && !state.testing && button('检测背键映射','test')}
   {state?.testMessage && row(<div>{state.testMessage}</div>)}
   {state?.detectedKey && state.detectedKey!==key && row(<ButtonItem layout="below" disabled={busy}
      onClick={()=>void run(()=>setVoiceKey(state.detectedKey))}>使用检测到的 {state.detectedKey}</ButtonItem>)}
   {state && row(<ButtonItem layout="below" onClick={()=>editWave(state.bar || defaultWave)}>调整波形位置和透明度</ButtonItem>)}
   {row(<ButtonItem layout="below" disabled={busy} onClick={()=>void installDraft()}>安装或更新魔兽双击清空组件</ButtonItem>)}
   {row(<div style={{fontSize:12}}>{draftMessage || '双击清空需要此组件。进入《魔兽世界：无限》后点这里安装，再重新打开游戏。'}</div>)}
   {row(<div style={{fontSize:12}}>游戏画面不再显示清空或拖动按钮。保留双击听写键清空刚填入草稿的功能。</div>)}
   {row(<div style={{fontSize:12}}>在游戏的 Steam Input 布局中把 L4、L5、R4、R5 中任意一颗背键映射为 {key}（普通按压）。选中聊天输入框，按住背键说话，松开后文字填入草稿。录音中打开 Steam 或“…”菜单会取消这次听写。</div>)}

  </>}
 </PanelSection>;
}
