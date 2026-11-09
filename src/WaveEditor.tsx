import {useRef,useState} from 'react';
import {ButtonItem,ModalRoot,SliderField,showModal} from '@decky/ui';
import {callable} from '@decky/api';

export type WaveStyle = {x:number; y:number; opacity:number};
export const defaultWave:WaveStyle = {x:.5,y:.82,opacity:.90};
const saveBar = callable<[WaveStyle],WaveStyle>('set_voice_bar');
const heights = [9,16,24,38,50,68,86,72,59,77,94,72,52,38,26,16,9];
const clamp=(n:number)=>Math.max(0,Math.min(1,n));

function Editor({initial,close}:{initial:WaveStyle;close:()=>void}){
 const [bar,setBar]=useState(initial),[saving,setSaving]=useState(false),[error,setError]=useState('');
 const handle=useRef<HTMLDivElement>(null);
 const grab=useRef<{id:number;x:number;y:number}|null>(null);
 const ratio=window.screen.width/window.screen.height || 1.6;
 function point(e:React.PointerEvent<HTMLDivElement>){
  const offset=grab.current;
  if(!offset || offset.id!==e.pointerId || !handle.current)return;
  const rect=e.currentTarget.getBoundingClientRect(),box=handle.current.getBoundingClientRect();
  const x=clamp((e.clientX-rect.left-offset.x)/Math.max(1,rect.width-box.width));
  const y=clamp((e.clientY-rect.top-offset.y)/Math.max(1,rect.height-box.height));
  setBar(current=>({...current,x,y}));
 }
 async function save(){
  setSaving(true);
  try{await saveBar(bar);close();}catch(e){setError(String(e));setSaving(false);}
 }
 return <ModalRoot closeModal={close} onCancel={close}>
  <div style={{fontSize:20,marginBottom:6}}>听写波形</div>
  <div style={{fontSize:13,marginBottom:10}}>拖动波形到游戏画面中的目标位置，也可以用摇杆调节下方滑块。</div>
  <div aria-label="游戏画面位置预览" style={{width:'100%',maxWidth:`min(62vw, ${ratio*34}vh)`,aspectRatio:ratio,
    margin:'0 auto 8px',background:'linear-gradient(120deg,#354552,#141c25)',outline:'1px solid #687885',
    position:'relative',touchAction:'none',cursor:'crosshair'}}
    onPointerDown={e=>{
      if(saving || !handle.current || grab.current)return;
      const rect=handle.current.getBoundingClientRect();
      const hit=handle.current.contains(e.target as Node);
      grab.current={id:e.pointerId,x:hit?e.clientX-rect.left:rect.width/2,y:hit?e.clientY-rect.top:rect.height/2};
      e.currentTarget.setPointerCapture(e.pointerId);point(e);
    }}
    onPointerMove={point} onPointerUp={e=>{point(e);grab.current=null;}}
    onPointerCancel={()=>{grab.current=null;}} onLostPointerCapture={()=>{grab.current=null;}}>
    <div ref={handle} style={{position:'absolute',width:'14.5%',aspectRatio:'4 / 1',left:(bar.x*100)+'%',top:(bar.y*100)+'%',
      transform:`translate(${-bar.x*100}%,${-bar.y*100}%)`,opacity:bar.opacity,cursor:'grab',display:'flex',
      alignItems:'center',justifyContent:'space-evenly',boxSizing:'border-box',padding:'0 2.3%',background:'#101317',border:'1px solid #b8c4c7',borderRadius:99}}>
      {heights.map((height,i)=><i key={i} style={{width:'3%',height:Math.max(10,height*.62)+'%',borderRadius:5,
        background:height>=70?'#acf6ef':'#f6fbff'}}/>)}
    </div>
  </div>
  {([['x','水平位置'],['y','垂直位置'],['opacity','不透明度']] as const).map(([key,label])=>
    <SliderField key={key} label={label} min={key==='opacity'?20:0} max={100} step={1}
      value={Math.round(bar[key]*100)} showValue valueSuffix="%" disabled={saving}
      onChange={v=>setBar(current=>({...current,[key]:v/100}))}/>)}
  {error && <div>{error}</div>}
  <ButtonItem layout="below" disabled={saving} onClick={()=>void save()}>保存位置和透明度</ButtonItem>
 </ModalRoot>;
}

export function editWave(initial:WaveStyle){
 const dialog=showModal(<Editor initial={{...initial}} close={()=>dialog.Close()}/>,undefined,
    {strTitle:'听写波形',bNeverPopOut:true});
}
