"""WoWDeck Input: managed Decky lifecycle, evdev input, per-user IBus settings."""
import asyncio,copy,json,os,pathlib,pwd,shutil,sys,time
import decky
sys.path.insert(0,str(pathlib.Path(__file__).parent/'py_modules'))
sys.path.insert(0,str(pathlib.Path(__file__).parent))
import evdev_mod as ev
from model import DEFAULTS,MODIFIERS,Chord,appearance,validate,validate_chord,effective_scheme

class Plugin:
    async def _main(self):
        self.directory=pathlib.Path(decky.DECKY_PLUGIN_SETTINGS_DIR);self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/'settings.json'
        try:self.config=validate(json.loads(self.path.read_text()))
        except (OSError,ValueError):self.config=copy.deepcopy(DEFAULTS)
        user_home=getattr(decky,'DECKY_USER_HOME','/home/deck')
        try:self.user=pwd.getpwuid(pathlib.Path(user_home).stat().st_uid)
        except (OSError,KeyError):self.user=pwd.getpwnam('deck')
        self.devices={};self.grabbing=False;self.capture=None;self.error='';self.last_open=0;self.stopping=False;self.game_active=False
        self.lock=asyncio.Lock();self.task=asyncio.create_task(self.watch())
    def persist(self):
        p=self.path.with_suffix('.tmp');p.write_text(json.dumps(self.config,ensure_ascii=False,indent=2)+'\n');p.chmod(0o600);p.replace(self.path)
    async def user_command(self,*args):
        env=dict(os.environ,HOME=self.user.pw_dir,USER=self.user.pw_name,LOGNAME=self.user.pw_name,XDG_RUNTIME_DIR=f'/run/user/{self.user.pw_uid}',DBUS_SESSION_BUS_ADDRESS=f'unix:path=/run/user/{self.user.pw_uid}/bus')
        for key in ['LD_LIBRARY_PATH','LD_PRELOAD','PYTHONPATH','PYTHONHOME']:env.pop(key,None)
        options={}
        if os.geteuid()==0:options=dict(user=self.user.pw_uid,group=self.user.pw_gid,extra_groups=os.getgrouplist(self.user.pw_name,self.user.pw_gid))
        p=await asyncio.create_subprocess_exec(*args,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env,**options)
        try:out,err=await asyncio.wait_for(p.communicate(),5)
        except asyncio.TimeoutError:p.kill();await p.wait();raise ValueError('输入引擎响应超时')
        if p.returncode:raise ValueError(err.decode(errors='replace').strip() or '输入引擎操作失败')
        return out.decode().strip()
    async def scheme_values(self):
        base='/desktop/ibus/engine/pinyin/'
        return {k:await self.user_command('/usr/bin/dconf','read',base+k) for k in ['DoublePinyin','DoublePinyinSchema']}
    def engine_available(self):return pathlib.Path('/usr/lib/ibus/ibus-engine-pinyin').exists()
    async def get_state(self):
        try:
            values=await self.scheme_values()
            scheme=effective_scheme(values)
        except Exception:scheme='keep'
        return {'config':self.config,'status':{'keyboards':[item['device'].name for item in self.devices.values()],'capturing':self.capture['target'] if self.capture else None,'error':self.error,'active':self.session_active(),'engine':self.engine_available(),'scheme':scheme,'grabbing':self.grabbing}}
    def session_active(self):
        try:return 'XDG_CURRENT_DESKTOP=gamescope' in pathlib.Path(f'/run/user/{self.user.pw_uid}/gamescope-environment').read_text().splitlines() and self.game_active
        except OSError:return False
    async def set_enabled(self,value):
        c=copy.deepcopy(self.config);c['enabled']=value;validate(c)
        # New users default to full pinyin. Existing users retain their chosen scheme.
        if value and not self.config['enabled'] and self.config['scheme'] in {'full','xiaohe'} and self.engine_available():
            await self.set_scheme(self.config['scheme'])
        self.config['enabled']=value;self.persist()
        if not value:await self.ungrab_keyboards()
        await decky.emit('preferences',self.config);return await self.get_state()
    async def set_appearance(self,value):
        self.config['appearance']=appearance(value);self.config['appearance_migrated']=True;self.persist();return self.config
    async def migrate_appearance(self,value):
        if not self.config['appearance_migrated']:
            # Importing the old candidate settings means this is an existing user.
            try:self.config['scheme']=effective_scheme(await self.scheme_values())
            except Exception:self.config['scheme']='keep'
            await self.set_appearance(value)
        return self.config
    async def set_hotkey(self,target,value):
        if target not in {'wake','adjust'}:raise ValueError('无效快捷键类型')
        c=copy.deepcopy(self.config);c[target]=validate_chord(value);self.config=validate(c);self.persist()
        for item in self.devices.values():item['chord'].clear()
        await decky.emit('preferences',self.config);return await self.get_state()
    async def begin_capture(self,target):
        if target not in {'wake','adjust'}:raise ValueError('无效快捷键类型')
        if self.grabbing:raise ValueError('请先用 Esc 关闭输入界面，再录制快捷键')
        self.capture={'target':target,'expires':time.monotonic()+20,'down':set(),'chord':None};self.error=''
        return await self.get_state()
    async def cancel_capture(self):self.capture=None;return await self.get_state()
    async def set_scheme(self,scheme):
        if scheme not in {'full','xiaohe'}:raise ValueError('支持全拼或小鹤双拼')
        if self.grabbing:raise ValueError('请先选词或取消并关闭输入界面，再切换方案')
        if not self.engine_available():raise ValueError('系统缺少中文拼音引擎，请先添加 Steam 简体中文键盘')
        async with self.lock:
            before=await self.scheme_values();backup=self.directory/'pinyin-before.json'
            if not backup.exists():backup.write_text(json.dumps(before));backup.chmod(0o600)
            base='/desktop/ibus/engine/pinyin/'
            try:
                if scheme=='xiaohe':await self.user_command('/usr/bin/dconf','write',base+'DoublePinyinSchema','5')
                await self.user_command('/usr/bin/dconf','write',base+'DoublePinyin','true' if scheme=='xiaohe' else 'false')
            except Exception:
                await self.restore_values(before);raise
            self.config['scheme']=scheme;self.persist();(self.directory/'pinyin-last-applied.json').write_text(json.dumps(await self.scheme_values()))
        return await self.get_state()
    async def restore_values(self,values):
        for key,value in values.items():
            args=['/usr/bin/dconf','write','/desktop/ibus/engine/pinyin/'+key,value] if value else ['/usr/bin/dconf','reset','/desktop/ibus/engine/pinyin/'+key]
            await self.user_command(*args)
    async def restore_scheme(self):
        if self.grabbing:raise ValueError('请先关闭输入界面')
        p=self.directory/'pinyin-before.json'
        if p.exists():await self.restore_values(json.loads(p.read_text()))
        self.config['scheme']='keep';self.persist();return await self.get_state()
    def close_device(self,path):
        item=self.devices.pop(path,None)
        if not item:return
        dev=item['device'];asyncio.get_running_loop().remove_reader(dev.fd)
        try:
            if item['grabbed']:dev.ungrab()
        except OSError:pass
        dev.close()
    async def watch(self):
        try:
            while not self.stopping:
                if self.capture and time.monotonic()>self.capture['expires']:
                    self.capture=None;await decky.emit('capture_result',{'error':'录制已超时，请重试'})
                try:self.game_active=await self.user_command('/usr/bin/systemctl','--user','is-active','ibus-gamescope.service')=='active'
                except Exception:self.game_active=False
                paths=set(ev.list_devices()) if self.config['enabled'] and self.session_active() else set()
                for path,item in list(self.devices.items()):
                    try:st=os.stat(path);identity=(st.st_ino,st.st_ctime_ns)
                    except OSError:identity=None
                    if path not in paths or item['identity']!=identity:self.close_device(path)
                for path in paths-self.devices.keys():
                    dev=None
                    try:
                        if '/devices/virtual/' in os.path.realpath('/sys/class/input/'+os.path.basename(path)+'/device'):continue
                        dev=ev.InputDevice(path)
                        if dev.name=='AT Translated Set 2 keyboard' or 'Steam Controller' in dev.name or 'Steam Deck' in dev.name:dev.close();continue
                        keys=dev.capabilities().get(ev.ecodes.EV_KEY,[])
                        if not all(k in keys for k in [30,57,29]):dev.close();continue
                        st=os.stat(path);item={'device':dev,'identity':(st.st_ino,st.st_ctime_ns),'chord':Chord(),'grabbed':False}
                        self.devices[path]=item;asyncio.get_running_loop().add_reader(dev.fd,self.read_device,path)
                        if self.grabbing:
                            dev.grab();item['grabbed']=True
                    except OSError:
                        if path in self.devices:self.close_device(path)
                        elif dev:dev.close()
                await asyncio.sleep(2)
        except asyncio.CancelledError:pass
        finally:
            for path in list(self.devices):self.close_device(path)
    def read_device(self,path):
        item=self.devices.get(path)
        if not item:return
        try:
            for event in item['device'].read():
                if event.type==ev.ecodes.EV_SYN and event.code==ev.ecodes.SYN_DROPPED:item['chord'].clear();continue
                if event.type!=ev.ecodes.EV_KEY:continue
                if self.capture:
                    self.capture_event(event.code,event.value);continue
                if self.grabbing:
                    if event.code<ev.ecodes.KEY_MACRO:asyncio.create_task(decky.emit('keyboard',event.code,event.value))
                elif item['chord'].event(event.code,event.value,self.config['wake']) and time.monotonic()-self.last_open>1:
                    self.last_open=time.monotonic();asyncio.create_task(decky.emit('open_keyboard'))
        except BlockingIOError:pass
        except OSError:self.close_device(path)
    def capture_event(self,code,value):
        c=self.capture
        if not c:return
        if code==1 and value==1:self.capture=None;asyncio.create_task(decky.emit('capture_result',{'error':'已取消录制'}));return
        if value==1:
            c['down'].add(code)
            if code not in MODIFIERS:c['chord']={'key':code,'mods':sorted({MODIFIERS[x] for x in c['down'] if x in MODIFIERS})}
        elif value==0:
            c['down'].discard(code)
            if not c['down'] and c['chord']:
                self.capture=None;asyncio.create_task(self.finish_capture(c['target'],c['chord']))
    async def finish_capture(self,target,chord):
        try:await self.set_hotkey(target,chord);await decky.emit('capture_result',{'ok':True})
        except Exception as e:self.error=str(e);await decky.emit('capture_result',{'error':str(e)})
    async def find_keyboards(self):return bool(self.devices)
    async def grab_keyboards(self):
        if not self.config['enabled']:return
        self.grabbing=True
        for path,item in list(self.devices.items()):
            if not item['grabbed']:
                try:item['device'].grab();item['grabbed']=True;item['chord'].clear()
                except OSError:self.close_device(path)
    async def ungrab_keyboards(self):
        self.grabbing=False
        for item in list(self.devices.values()):
            if item['grabbed']:
                try:item['device'].ungrab()
                except OSError:pass
                item['grabbed']=False;item['chord'].clear()
    async def _unload(self):
        self.stopping=True;await self.ungrab_keyboards();self.task.cancel();await self.task
    async def _uninstall(self):
        before=self.directory/'pinyin-before.json';last=self.directory/'pinyin-last-applied.json'
        if before.exists() and last.exists() and await self.scheme_values()==json.loads(last.read_text()):await self.restore_values(json.loads(before.read_text()))
