"""Decky-side supervisor. All browser, audio and X11 access runs as the session user."""
import asyncio
import contextlib
import json
import os
import signal
import time
from pathlib import Path
from voice.deck_hold import observe_press, report_stream
from host_session import GameSession

WORKER = Path(__file__).resolve().with_name('worker.py')


def initial(message='语音已关闭'):
    return dict(running=False, enabled=False, signed=False, auth='idle', qr='', message=message)


class VoiceControl:
    def __init__(self, user, on_notice=None, session=None):
        self.user = user
        self.on_notice = on_notice
        self.session = session or GameSession(user)
        self.retry_blocked = False
        self.stopping = False
        self.last_start = -999.0
        self.state = initial()
        self.proc = self.reader = None
        self.lock = asyncio.Lock()
        self.detector = None
        self.test_message = ''
        self.detected_key = ''
        self.hold_token = 0
        self.hold_task = None
        self.back_hold_available = report_stream() is not None

    async def observe_hold(self, token):
        if token == self.hold_token: return
        self.hold_token = token
        if self.hold_task:
            self.hold_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.hold_task
            self.hold_task = None
        if token:
            self.hold_task = asyncio.create_task(observe_press(token, self.signal))

    def signal(self, command):
        proc = self.proc
        if proc and proc.returncode is None and not proc.stdin.is_closing():
            try:
                proc.stdin.write((command + '\n').encode())
            except (BrokenPipeError, ConnectionResetError):
                pass

    def view(self, key):
        profile = Path(self.user.pw_dir) / '.local/share/wowdeck-input/doubao-browser/data'
        return dict(self.state, retryBlocked=self.retry_blocked, hasProfile=profile.is_dir(), hotkey=key, backHoldAvailable=self.back_hold_available,
                    r5HoldAvailable=self.back_hold_available,  # Retain the previous read-only API field.
                    testing=self.detector is not None and not self.detector.done(),
                    testMessage=self.test_message, detectedKey=self.detected_key)

    async def _detect(self):
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec('/usr/bin/python3', str(WORKER.with_name('game.py')),
                '--detect', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, **self.spawn_options())
            out, _ = await asyncio.wait_for(proc.communicate(), 24)
            key = out.decode().strip()
            if proc.returncode:
                self.test_message = '键盘检测不可用，请检查游戏模式'
            elif key in {f'F{i}' for i in range(1, 13)}:
                self.detected_key = key
                self.test_message = f'实际收到 {key}'
            else:
                self.test_message = '20 秒内未收到功能键，请检查游戏的 Steam Input 布局。'
        except (OSError, ValueError, asyncio.TimeoutError):
            self.test_message = '检测失败，请在游戏模式重试'
        finally:
            if proc and proc.returncode is None:
                with contextlib.suppress(ProcessLookupError): proc.kill()
                await proc.wait()

    async def cancel_detector(self):
        if self.detector and not self.detector.done():
            self.detector.cancel()
            with contextlib.suppress(asyncio.CancelledError): await self.detector
        self.detector = None

    async def _listening(self, enable, key):
        if not self.proc or self.proc.returncode is not None or not self.state['running']:
            if enable: raise ValueError('请先恢复豆包连接')
            return
        if enable and not self.state['signed']: raise ValueError('请等待官网验证登录')
        if self.state['enabled'] == enable: return
        self.proc.stdin.write((f'arm {key}\n' if enable else 'disarm\n').encode())
        await self.proc.stdin.drain()
        for _ in range(70):
            await asyncio.sleep(.05)
            if self.state['enabled'] == enable: return
            if not self.state['running']: break
        raise ValueError(self.state['message'] or '听写状态未更新')

    def spawn_options(self):
        user = self.user
        runtime = Path('/run/user') / str(user.pw_uid)
        env = dict(HOME=user.pw_dir, USER=user.pw_name, LOGNAME=user.pw_name,
                   PATH='/usr/bin:/bin', XDG_RUNTIME_DIR=str(runtime), LANG='C.UTF-8',
                   DBUS_SESSION_BUS_ADDRESS='unix:path='+str(runtime/'bus'),
                   PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
        for key in ('http_proxy','https_proxy','no_proxy','HTTP_PROXY','HTTPS_PROXY','NO_PROXY'):
            if key in os.environ: env[key] = os.environ[key]
        session = self.session.read()
        for key in ('DISPLAY','XAUTHORITY','PULSE_SERVER'):
            if session.get(key): env[key] = session[key]
        if not session or not env.get('DISPLAY'):
            raise ValueError('请在 Steam 游戏模式中连接豆包')
        options = dict(env=env, start_new_session=True, cwd=user.pw_dir, umask=0o077)
        if os.geteuid() == 0:
            options.update(user=user.pw_uid, group=user.pw_gid, extra_groups=os.getgrouplist(user.pw_name,user.pw_gid))
        return options

    async def read(self, proc):
        notice = 0
        try:
            async for line in proc.stdout:
                try:
                    data = json.loads(line)
                    if not isinstance(data, dict): continue
                    hold = data.get('hold', 0)
                    if type(hold) is int and hold >= 0:
                        await self.observe_hold(hold)
                    qr = data.get('qr', '')
                    metrics = data.get('diagnostics', {})
                    if not isinstance(metrics, dict): metrics = {}
                    self.state = dict(running=True, enabled=data.get('enabled') is True,
                        phase=data.get('phase','ready'), auth=data.get('auth','checking'), signed=data.get('signed') is True, message=str(data.get('message',''))[:200],
                        diagnostics={k:v for k,v in metrics.items()
                            if k in ('connect_ms','final_ms','audio_bytes','sent_bytes','responses','total_ms')
                            and type(v) is int and 0 <= v <= 2000000},
                        qr=qr if isinstance(qr,str) and qr.startswith('data:image/png;base64,iVBORw0KGgo') and len(qr)<250000 else '')
                    event = data.get('notice', 0)
                    if type(event) is int and event > notice:
                        notice = event
                        if self.on_notice:
                            # A disconnected Decky UI must not stop the worker status pipe.
                            with contextlib.suppress(RuntimeError, OSError, asyncio.TimeoutError):
                                await asyncio.wait_for(self.on_notice({'phase':self.state['phase'],
                                    'message':self.state['message'], 'hideKeyboard':data.get('hideKeyboard') is True}), 1)
                except (TypeError, ValueError, ConnectionError, OSError):
                    continue
        finally:
            await self.observe_hold(0)
            await proc.wait()
            if self.proc is proc:
                message = self.state.get('message', '') if self.state.get('phase')=='error' or not self.state['enabled'] else ''
                if not self.stopping:
                    self.retry_blocked = True
                self.state = dict(initial(message or '语音服务已断开，请点击重新连接账号。'),
                                  auth='error' if self.retry_blocked else 'idle')
                # If the helper crashed, reap any Qt/audio descendants in its private group.
                with contextlib.suppress(ProcessLookupError): os.killpg(proc.pid, signal.SIGTERM)

    async def _stop(self):
        self.stopping = True
        proc = self.proc
        if proc and proc.returncode is None:
            try:
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    proc.stdin.write(b'stop\n')
                    await asyncio.wait_for(proc.stdin.drain(), 1)
                await asyncio.wait_for(proc.wait(), 5)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError): os.killpg(proc.pid, signal.SIGKILL)
                await proc.wait()
        if self.reader:
            await self.reader
        self.reader = self.proc = None
        self.state = initial()
        self.stopping = False
        self.retry_blocked = False

    async def call(self, action, key='F7'):
        async with self.lock:
            if action == 'arm':
                if self.detector and not self.detector.done(): raise ValueError('请先完成按键检测')
                await self._listening(True, key)
            elif action == 'disarm':
                await self._listening(False, key)
            elif action == 'test':
                await self._listening(False, key)
                await self.cancel_detector()
                self.detected_key = ''
                self.test_message = '请返回游戏，在 20 秒内按住再松开背键，然后回来看结果。'
                self.detector = asyncio.create_task(self._detect())
            elif action in ('login','restore','refresh','stop','forget'):
                if action in ('restore','login') and self.state['running']:
                    return self.state
                if action == 'refresh' and self.state['signed']:
                    return self.state
                if action == 'refresh' and self.proc and self.proc.returncode is None:
                    self.signal('refresh_login')
                    self.state.update(qr='', message='正在重新获取官网二维码…')
                    return self.state
                if action in ('stop','forget'):
                    await self.cancel_detector()
                await self._stop()
                if action in ('login','restore','refresh'):
                    self.retry_blocked = False
                    self.last_start = time.monotonic()
                    try:
                        self.proc = await asyncio.create_subprocess_exec('/usr/bin/python3', str(WORKER),
                            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                            limit=1024*1024, **self.spawn_options())
                    except (OSError, ValueError):
                        self.retry_blocked = True
                        self.state = dict(initial('登录组件无法启动，请检查游戏模式和系统组件后重试'), auth='error')
                        raise
                    self.reader = asyncio.create_task(self.read(self.proc))
                    self.state = dict(initial('正在连接账号…'), running=True, auth='checking')
                elif action == 'forget':
                    p = await asyncio.create_subprocess_exec('/usr/bin/python3',str(WORKER),'forget',
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, **self.spawn_options())
                    out, _ = await p.communicate()
                    if p.returncode or out: raise ValueError('退出登录失败，请重试。')
                    self.state = initial('已退出登录')
            else:
                raise ValueError('未知语音操作')
            return self.state
