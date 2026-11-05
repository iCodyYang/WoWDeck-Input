import {callable} from '@decky/api';
import {EvdevToKey} from './utility/map';
export type Hotkey={key:number;mods:string[]};
export type Appearance={x:number;y:number;scale:number;opacity:number};
export type Config={enabled:boolean;scheme:string;wake:Hotkey;adjust:Hotkey;appearance:Appearance;appearance_migrated:boolean};
export type State={config:Config;status:{keyboards:string[];capturing:string|null;error:string;active:boolean;engine:boolean;scheme:string;grabbing:boolean}};
export const api={state:callable<[],State>('get_state'),enabled:callable<[boolean],State>('set_enabled'),scheme:callable<[string],State>('set_scheme'),hotkey:callable<[string,Hotkey],State>('set_hotkey'),capture:callable<[string],State>('begin_capture'),cancel:callable<[],State>('cancel_capture'),appearance:callable<[Appearance],Config>('set_appearance'),migrate:callable<[Appearance],Config>('migrate_appearance'),restore:callable<[],State>('restore_scheme')};
let config:Config={enabled:false,scheme:'full',wake:{key:57,mods:['Ctrl']},adjust:{key:66,mods:[]},appearance:{x:12,y:80,scale:.85,opacity:.95},appearance_migrated:false};
const subscribers=new Set<()=>void>();
export function getConfig(){return config;}
export function putConfig(value:Config){config=value;subscribers.forEach(fn=>fn());}
export function subscribe(fn:()=>void){subscribers.add(fn);return ()=>{subscribers.delete(fn);};}
let saveTimer:ReturnType<typeof setTimeout>|undefined;
let appearanceDirty=false;
function persistAppearance(){
 const value={...config.appearance};
 return api.appearance(value).then(result=>{if(JSON.stringify(config.appearance)===JSON.stringify(value))appearanceDirty=false;return result;});
}
export function saveAppearance(value:Appearance){config.appearance={...value};config.appearance_migrated=true;appearanceDirty=true;clearTimeout(saveTimer);saveTimer=setTimeout(()=>{void persistAppearance().catch(console.error);},100);}
export function flushAppearance(){clearTimeout(saveTimer);return appearanceDirty?persistAppearance():Promise.resolve(config);}
export function hotkeyLabel(value:Hotkey){let key=EvdevToKey[value.key as keyof typeof EvdevToKey]||String(value.key);if(key===' ')key='Space';return [...value.mods,key].join(' + ');}
