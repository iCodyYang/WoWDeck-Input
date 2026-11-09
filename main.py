"""WoWDeck Input: managed Decky lifecycle, evdev input, per-user IBus settings."""
import asyncio,copy,json,os,pathlib,pwd,struct,sys,time
import decky
sys.path.insert(0,str(pathlib.Path(__file__).parent/'py_modules'))
sys.path.insert(0,str(pathlib.Path(__file__).parent))
import evdev_mod as ev
from voice.control import VoiceControl
from voice.waveform import bar_settings
from host_session import GameSession, steam_processes
from model import FUNCTION_CODES,DEFAULTS,MODIFIERS,Chord,appearance,validate,validate_chord,effective_scheme

def is_external_keyboard(dev):
    if dev.info.vendor == 0x28de:
        return False
    if 'Steam Controller' in dev.name or 'Steam Deck' in dev.name:
        return False
    keys = dev.capabilities().get(ev.ecodes.EV_KEY, [])
    # Ignore joystick and gamepad endpoints, including those that also advertise keys.
    return keyboard_keys(keys)


def keyboard_keys(keys):
    # PS/2, I2C, SPI, USB and Bluetooth keyboards share EV_KEY capabilities.
    # A device may expose only right Ctrl. Do not identify keyboards by bus or model.
    return (30 in keys and 57 in keys and (29 in keys or 97 in keys)
            and not any(288 <= k < 320 or 544 <= k < 548 or 704 <= k < 744 for k in keys))


def keyboard_info(path, sysfs=pathlib.Path('/sys/class/input')):
    # Classify via sysfs before opening evdev. Even a short-lived controller
    # handle is unnecessary for either the wake shortcut or dictation.
    device = sysfs / pathlib.Path(path).name / 'device'
    try:
        vendor = int((device / 'id/vendor').read_text(), 16)
        name = (device / 'name').read_text(errors='replace').strip() if (device / 'name').exists() else pathlib.Path(path).name
        words = [int(w, 16) for w in (device / 'capabilities/key').read_text().split()]
        width = struct.calcsize('L') * 8
        bits = sum(word << (i * width) for i, word in enumerate(reversed(words)))
        keys = {k for k in range(bits.bit_length()) if bits & (1 << k)}
        if not keyboard_keys(keys) or vendor == 0x28de or 'Steam Controller' in name or 'Steam Deck' in name:
            return None
        virtual = '/devices/virtual/input/' in str(device.resolve())
        return {'name':name[:120], 'virtual':virtual, 'path':str(path)}
    except (OSError, ValueError):
        return None


def keyboard_endpoint(path, sysfs=pathlib.Path('/sys/class/input')):
    info = keyboard_info(path, sysfs)
    return bool(info and not info['virtual'])


def keyboard_inventory(sysfs=pathlib.Path('/sys/class/input'), inputs=pathlib.Path('/dev/input')):
    # Metadata only: this also explains remapped/hidden devices without opening
    # or stealing them from InputPlumber, HHD, Steam or another input handler.
    rows = []
    entries = sorted(sysfs.glob('event*'))
    for entry in entries:
        node = inputs/entry.name
        info = keyboard_info(node, sysfs)
        if not info:
            continue
        hidden = not node.exists() and (inputs/'.hidden'/entry.name).exists()
        kind = '系统映射键盘（未接管）' if info['virtual'] else '实体键盘'
        state = '被系统映射工具隐藏' if hidden else '设备节点不可见' if not node.exists() else kind
        rows.append(f"{info['name']}：{state}")
    return [f'系统输入设备 {len(entries)} 个，键盘候选 {len(rows)} 个'] + rows[:20]

class Plugin:
    async def _main(self):
        self.directory=pathlib.Path(decky.DECKY_PLUGIN_SETTINGS_DIR);self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/'settings.json'
        try:
            saved = json.loads(self.path.read_text())
            self.config = validate(saved)
        except (OSError, ValueError):
            self.config = copy.deepcopy(DEFAULTS)
        else:
            if isinstance(saved, dict) and saved.get('version', 1) in (1, 2, 3):
                try:
                    self.persist()
                except OSError:
                    # Keep validated preferences in use; retry on the next save.
                    pass
        self.user = self.session_user()
        self.session = GameSession(self.user)
        self.voice = VoiceControl(self.user, self._voice_notice, session=self.session)
        self.version = json.loads(pathlib.Path(__file__).with_name('package.json').read_text())['version']
        self.voice_keys_down = set()
        self.grab_timeout = None
        self.devices={};self.grabbing=False;self.capture=None;self.error='';self.last_open=0;self.stopping=False
        self.input_status = '插件已关闭'
        self.input_errors = {}
        self.input_details = []
        self.last_scan = 0
        self.game_active = False
        self.lock=asyncio.Lock();self.task=asyncio.create_task(self.watch())
        self.voice_task = asyncio.create_task(self.watch_voice())
    @staticmethod
    def session_user():
        # Decky exports the actual session home. Older loaders can be identified by their runtime dir.
        for path in (getattr(decky, 'DECKY_USER_HOME', None), os.environ.get('DECKY_USER_HOME'), os.environ.get('XDG_RUNTIME_DIR')):
            if not path:
                continue
            try:
                uid = pathlib.Path(path).stat().st_uid
                if uid:
                    return pwd.getpwuid(uid)
            except (OSError, KeyError):
                continue
        if os.geteuid():
            return pwd.getpwuid(os.geteuid())
        # Older Decky installations on other handhelds need not have a deck account.
        owners = {uid for _, uid in steam_processes() if uid}
        if len(owners) == 1:
            return pwd.getpwuid(owners.pop())
        # Legacy Decky installs on stock SteamOS use the deck account.
        return pwd.getpwnam('deck')

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
        scheme = 'keep'
        if self.config['scheme']=='wubi86':
            scheme = 'wubi86'
        elif self.config['pluginEnabled']:
            try: scheme = effective_scheme(await self.scheme_values())
            except Exception: pass
        if not self.config['pluginEnabled']:
            status = '总开关已关闭，未监听键盘'
        elif not self.config['enabled'] and not self.voice.state['enabled']:
            status = '键盘输入法已关闭；需要打字请打开键盘开关'
        elif not self.last_scan:
            status = '正在初始化键盘检测，请稍候或点击重新检测键盘'
        else:
            status = self.input_status
        return {'config':self.config,'status':{'version':self.version,'keyboards':[item['device'].name for item in self.devices.values()],'inputStatus':status,'inputDetails':self.input_details,'inputErrors':list(self.input_errors.values()),'capturing':self.capture['target'] if self.capture else None,'error':self.error,'active':self.session_active(),'engine':self.engine_available(),'scheme':scheme,'grabbing':self.grabbing}}

    async def inspect_keyboards(self):
        # Explicit diagnosis works even when the switches or session gate are off.
        try:
            self.input_details = keyboard_inventory()
            self.scan_keyboards()
        except Exception as exc:
            self.input_status = '键盘检测遇到异常，将自动重试'
            self.input_errors['scan'] = f'检测异常：{type(exc).__name__}'
        if not self.stopping and self.task.done():
            if not self.task.cancelled(): self.task.exception()
            self.task = asyncio.create_task(self.watch())
        return await self.get_state()
    def session_active(self):
        return self.game_active
    def require_master(self):
        if self.stopping or not self.config['pluginEnabled']:
            raise ValueError('请先打开插件总开关')

    async def set_master(self, value):
        if type(value) is not bool:
            raise ValueError('插件总开关设置无效')
        async with self.lock:
            if value:
                self.save_voice_option('pluginEnabled', True)
                self.last_scan = 0
            else:
                # Cut off new input before the first await. Persist the off switch before
                # shutting down children; always release them even if writing fails.
                self.config['pluginEnabled'] = False
                self.capture = None
                self.input_status = '插件已关闭'
                self.input_errors = {}
                self.game_active = False
                self.voice_keys_down.clear()
                self.voice.signal('ui blocked')
                try:
                    self.persist()
                finally:
                    await self.ungrab_keyboards()
                    for path in list(self.devices):
                        self.close_device(path)
                    await self.voice.call('stop')
        await decky.emit('preferences', self.config)
        return await self.get_state()

    async def set_enabled(self,value):
        self.require_master()
        c=copy.deepcopy(self.config);c['enabled']=value;validate(c)
        # New users default to full pinyin. Existing users retain their chosen scheme.
        if value and not self.config['enabled'] and self.config['scheme'] in {'full','xiaohe'} and self.engine_available():
            await self.set_scheme(self.config['scheme'])
        self.require_master()
        self.config['enabled']=value;self.persist()
        self.last_scan = 0
        if not value:
            self.capture = None
            for item in self.devices.values(): item['chord'].clear()
            await self.ungrab_keyboards()
        await decky.emit('preferences',self.config);return await self.get_state()
    async def set_appearance(self,value):
        self.config['appearance']=appearance(value);self.config['appearance_migrated']=True;self.persist();return self.config
    async def migrate_appearance(self,value):
        async with self.lock:
            self.require_master()
            if self.config['appearance_migrated']:return self.config
            # Importing the old candidate settings means this is an existing user.
            if self.config['scheme']!='wubi86':
                try:self.config['scheme']=effective_scheme(await self.scheme_values())
                except Exception:self.config['scheme']='keep'
            await self.set_appearance(value)
        return self.config
    async def set_hotkey(self,target,value):
        self.require_master()
        if target not in {'wake','adjust'}:raise ValueError('无效快捷键类型')
        chord = validate_chord(value)
        if chord['key'] == FUNCTION_CODES[self.config['voiceKey']] and self.config['voiceWanted']:
            raise ValueError(f"听写正在使用 {self.config['voiceKey']}，请先更换听写键")
        c=copy.deepcopy(self.config);c[target]=chord;self.config=validate(c);self.persist()
        for item in self.devices.values():item['chord'].clear()
        await decky.emit('preferences',self.config);return await self.get_state()
    async def begin_capture(self,target):
        self.require_master()
        if not self.config['enabled']:raise ValueError('请先启用外接键盘输入法')
        if target not in {'wake','adjust'}:raise ValueError('无效快捷键类型')
        if self.grabbing:raise ValueError('请先用 Esc 关闭输入界面，再录制快捷键')
        self.capture={'target':target,'expires':time.monotonic()+20,'down':set(),'chord':None};self.error=''
        return await self.get_state()
    async def cancel_capture(self):self.capture=None;return await self.get_state()
    async def get_wubi_table(self):
        self.require_master()
        if self.config['scheme']!='wubi86':raise ValueError('请先选择五笔 86')
        from wubi import table
        return await asyncio.to_thread(table)

    async def set_scheme(self,scheme):
        if scheme not in {'full','xiaohe','wubi86'}:raise ValueError('支持全拼、小鹤双拼或五笔 86')
        if self.grabbing:raise ValueError('请先选词或取消并关闭输入界面，再切换方案')
        if scheme=='wubi86':
            async with self.lock:
                self.require_master()
                from wubi import table
                await asyncio.to_thread(table)
                self.require_master()
                self.config['scheme']=scheme;self.persist()
            await decky.emit('preferences',self.config)
            return await self.get_state()
        if not self.engine_available():raise ValueError('系统缺少中文拼音引擎，请先添加 Steam 简体中文键盘')
        async with self.lock:
            self.require_master()
            before=await self.scheme_values();backup=self.directory/'pinyin-before.json'
            if not backup.exists():backup.write_text(json.dumps(before));backup.chmod(0o600)
            base='/desktop/ibus/engine/pinyin/'
            try:
                if scheme=='xiaohe':await self.user_command('/usr/bin/dconf','write',base+'DoublePinyinSchema','5')
                await self.user_command('/usr/bin/dconf','write',base+'DoublePinyin','true' if scheme=='xiaohe' else 'false')
            except Exception:
                await self.restore_values(before);raise
            self.config['scheme']=scheme;self.persist();(self.directory/'pinyin-last-applied.json').write_text(json.dumps(await self.scheme_values()))
        await decky.emit('preferences',self.config)
        return await self.get_state()
    async def restore_values(self,values):
        for key,value in values.items():
            args=['/usr/bin/dconf','write','/desktop/ibus/engine/pinyin/'+key,value] if value else ['/usr/bin/dconf','reset','/desktop/ibus/engine/pinyin/'+key]
            await self.user_command(*args)
    async def restore_scheme(self):
        if self.grabbing:raise ValueError('请先关闭输入界面')
        p=self.directory/'pinyin-before.json'
        if p.exists():await self.restore_values(json.loads(p.read_text()))
        self.config['scheme']='keep';self.persist();await decky.emit('preferences',self.config);return await self.get_state()

    def update_voice_key_down(self, path, down):
        was_down = bool(self.voice_keys_down)
        if down:
            self.voice_keys_down.add(path)
        else:
            self.voice_keys_down.discard(path)
        is_down = bool(self.voice_keys_down)
        if was_down != is_down:
            self.voice.signal(f'physical {int(is_down)}')
    def close_device(self,path):
        item=self.devices.pop(path,None)
        if not item:return
        self.update_voice_key_down(path, False)
        dev=item['device'];asyncio.get_running_loop().remove_reader(dev.fd)
        try:
            if item['grabbed']:dev.ungrab()
        except OSError:pass
        dev.close()
    async def watch(self):
        try:
            while not self.stopping:
                if not self.config['pluginEnabled']:
                    await asyncio.sleep(1)
                    continue
                try:
                    if self.capture and time.monotonic()>self.capture['expires']:
                        self.capture=None;await decky.emit('capture_result',{'error':'录制已超时，请重试'})
                    self.scan_keyboards()
                except Exception as exc:
                    # One incompatible device must not kill all keyboard monitoring.
                    self.last_scan = time.monotonic()
                    self.input_status = '键盘检测遇到异常，将自动重试'
                    self.input_errors['scan'] = f'检测异常：{type(exc).__name__}'
                    self._release_grab()
                await asyncio.sleep(2)
        except asyncio.CancelledError:pass
        finally:
            for path in list(self.devices):self.close_device(path)

    def scan_keyboards(self):
        self.last_scan = time.monotonic()
        wanted = self.config['pluginEnabled'] and (self.config['enabled'] or self.voice.state['enabled'])
        self.game_active = bool(self.session.read()) if wanted else False
        # Do not use evdev.list_devices(): it silently drops read-only or
        # permission-denied nodes, hiding the reason from the user.
        paths = {str(p) for p in pathlib.Path('/dev/input').glob('event*')} if wanted and self.game_active else set()
        self.input_errors = {}
        if not self.game_active:
            self._release_grab()
        for path,item in list(self.devices.items()):
            try:st=os.stat(path);identity=(st.st_ino,st.st_ctime_ns)
            except OSError:identity=None
            if path not in paths or item['identity']!=identity:self.close_device(path)
        for path in paths-self.devices.keys():
            dev=None
            try:
                if not keyboard_endpoint(path):continue
                dev=ev.InputDevice(path)
                if not is_external_keyboard(dev): dev.close();continue
                st=os.stat(path);item={'device':dev,'identity':(st.st_ino,st.st_ctime_ns),'chord':Chord(),'grabbed':False}
                self.devices[path]=item;asyncio.get_running_loop().add_reader(dev.fd,self.read_device,path)
                if self.grabbing:
                    dev.grab();item['grabbed']=True
            except Exception as exc:
                self.input_errors[path] = (f'{pathlib.Path(path).name}：没有读取键盘的权限，请检查 Decky 安装'
                    if isinstance(exc, PermissionError) else f'{pathlib.Path(path).name}：读取失败（{type(exc).__name__}），将自动重试')
                if path in self.devices:self.close_device(path)
                elif dev:dev.close()
        if not self.config['pluginEnabled']:
            self.input_status = '插件已关闭'
        elif not wanted:
            self.input_status = '实体键盘监听已关闭'
        elif not self.game_active:
            self.input_status = '未识别到 Steam 游戏模式；若已在游戏模式，请反馈系统与插件版本'
        elif self.devices:
            self.input_status = '实体键盘监听已就绪；快捷键需按下后全部松开'
        else:
            self.input_status = '游戏模式已识别，但未找到可读取的实体键盘'
    def read_device(self,path):
        if not self.config['pluginEnabled'] or self.stopping: return
        item=self.devices.get(path)
        if not item:return
        try:
            for event in item['device'].read():
                if event.type==ev.ecodes.EV_SYN and event.code==ev.ecodes.SYN_DROPPED:
                    item['chord'].clear()
                    self.update_voice_key_down(path, False)
                    continue
                if event.type!=ev.ecodes.EV_KEY:continue
                if self.capture:
                    self.capture_event(event.code,event.value);continue
                if self.voice.state['enabled'] and event.code == FUNCTION_CODES[self.config['voiceKey']]:
                    if event.value in (0, 1):
                        self.update_voice_key_down(path, bool(event.value))
                    continue
                if not self.config['enabled']: continue
                if self.grabbing:
                    if event.code<ev.ecodes.KEY_MACRO:asyncio.create_task(decky.emit('keyboard',event.code,event.value))
                elif item['chord'].event(event.code,event.value,self.config['wake']) and time.monotonic()-self.last_open>1:
                    self.last_open=time.monotonic();asyncio.create_task(decky.emit('open_keyboard'))
        except BlockingIOError:pass
        except Exception as exc:
            self.input_errors[path] = f'{pathlib.Path(path).name}：按键读取异常（{type(exc).__name__}），将自动重试'
            self.close_device(path)
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
    async def find_keyboards(self):return self.config['pluginEnabled'] and bool(self.devices)
    async def grab_keyboards(self):
        if not self.config['pluginEnabled'] or not self.config['enabled'] or self.stopping: return
        if self.grab_timeout: self.grab_timeout.cancel()
        self.grab_timeout = asyncio.get_running_loop().call_later(0.9, self._release_grab)
        self.grabbing=True
        for path,item in list(self.devices.items()):
            if not item['grabbed']:
                try:item['device'].grab();item['grabbed']=True;item['chord'].clear()
                except OSError:self.close_device(path)
    async def ungrab_keyboards(self):
        self._release_grab()

    def _release_grab(self):
        if self.grab_timeout:
            self.grab_timeout.cancel()
            self.grab_timeout = None
        self.grabbing=False
        for item in list(self.devices.values()):
            if item['grabbed']:
                try:item['device'].ungrab()
                except OSError:pass
                item['grabbed']=False;item['chord'].clear()
    async def _voice_notice(self, notice):
        if self.config['pluginEnabled'] and self.config['voiceWanted'] and not self.stopping:
            await decky.emit('voice_feedback', notice)

    async def voice_ui_state(self, state):
        if self.config['pluginEnabled'] and self.config['voiceWanted'] and state in ('blocked','keyboard','game','unknown'):
            self.voice.signal('ui ' + state)

    async def reconcile_voice(self):
        if self.stopping or not self.config['pluginEnabled'] or not self.config['voiceWanted']:
            return
        async with self.lock:
            # Recheck opt-in under the same lock as both switches.
            if self.stopping or not self.config['pluginEnabled'] or not self.config['voiceWanted']:
                return
            state = await self.get_voice_state()
            if state['testing'] or state.get('retryBlocked'):
                return
            if not state['running'] and time.monotonic()-self.voice.last_start >= 30:
                await self.voice.call('restore')
            elif state['signed'] and not state['enabled']:
                self.check_voice_key(self.config['voiceKey'])
                await self.arm_voice()

    async def watch_voice(self):
        # The enabled voice service prepares the account and trigger independently of the keyboard.
        while not self.stopping:
            try:
                await self.reconcile_voice()
            except (OSError, ValueError, RuntimeError, ConnectionError) as exc:
                self.voice.state['message'] = str(exc)[:200]
            await asyncio.sleep(2)

    async def arm_voice(self):
        self.voice_keys_down.clear()
        self.voice.signal('bar ' + json.dumps(self.config['voiceBar']))
        await self.voice.call('arm', self.config['voiceKey'])

    def save_voice_option(self, field, value):
        old = self.config[field]
        self.config[field] = value
        try: self.persist()
        except OSError:
            self.config[field] = old
            raise

    async def get_voice_state(self):
        return dict(self.voice.view(self.config['voiceKey']), wanted=self.config['voiceWanted'], bar=self.config['voiceBar'])

    async def install_chat_draft(self):
        self.require_master()
        helper = pathlib.Path(__file__).resolve().parent / 'voice' / 'draft_install.py'
        return await self.user_command('/usr/bin/python3', '-I', str(helper))

    async def set_voice_bar(self, value):
        async with self.lock:
            self.require_master()
            style = bar_settings(value)
            self.save_voice_option('voiceBar', style)
            self.voice.signal('bar ' + json.dumps(style))
            return style

    def check_voice_key(self, key):
        if not isinstance(key, str) or key not in FUNCTION_CODES:
            raise ValueError('请选择 F1 至 F12')
        for name, label in [('wake','唤醒键盘'), ('adjust','调整候选框')]:
            if self.config[name]['key'] == FUNCTION_CODES[key]:
                raise ValueError(f'{key} 已用于{label}，请改用其他功能键')

    async def set_voice_key(self, key):
        async with self.lock:
            self.require_master()
            self.check_voice_key(key)
            if self.config['voiceKey'] != key:
                await self.voice.call('disarm')
                self.save_voice_option('voiceKey', key)
            return await self.get_voice_state()

    async def voice_action(self, action):
        async with self.lock:
            if action not in ('stop','disarm','forget'): self.require_master()
            key = self.config['voiceKey']
            if action == 'arm':
                self.check_voice_key(key)
                self.save_voice_option('voiceWanted', True)
                await decky.emit('preferences',self.config)
                if not self.voice.state['running']:
                    await self.voice.call('restore')
                if self.voice.state['signed']:
                    await self.arm_voice()
            else:
                if action in ('stop','forget','logout','disarm'):
                    self.save_voice_option('voiceWanted', False)
                    self.voice_keys_down.clear()
                    await decky.emit('preferences',self.config)
                command = {'disarm':'stop','logout':'forget'}.get(action,action)
                await self.voice.call(command, key)
            return await self.get_voice_state()

    async def _unload(self):
        self.stopping = True
        self.capture = None
        self.voice.signal('ui blocked')
        self._release_grab()
        for path in list(self.devices):
            self.close_device(path)
        self.task.cancel()
        self.voice_task.cancel()
        try: await asyncio.gather(self.task, self.voice_task, return_exceptions=True)
        finally: await self.voice.call('stop')
    async def _uninstall(self):
        before=self.directory/'pinyin-before.json';last=self.directory/'pinyin-last-applied.json'
        if before.exists() and last.exists() and await self.scheme_values()==json.loads(last.read_text()):await self.restore_values(json.loads(before.read_text()))
