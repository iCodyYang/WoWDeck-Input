"""Runs as the interactive user. The Decky parent receives only UI status and the official QR."""
import asyncio
import base64
import contextlib
from dataclasses import dataclass
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
import game
from game import FUNCTION_KEYS, VoiceKey, focused_game, wave_has_focus
from waveform import DEFAULT_BAR, WaveMeter, bar_settings, error_label

HERE = Path(__file__).resolve().parent
PROFILE = Path.home() / '.local' / 'share' / 'wowdeck-input' / 'doubao-browser'
RATE = 32000   # 16 kHz, signed 16-bit mono
MAX_SECONDS = 20
UI_HEARTBEAT_TTL = 2  # Allow Steam's background UI timer to tick at 1 Hz.
HOLD_SECONDS = .28
DOUBLE_TAP_GAP = .36
R5_DISCOVERY = .40  # A mapped key-up can precede the physical hold report.
R5_HEARTBEAT = .40


def paste_error(reply):
    return {
        b'error:focus_changed':'游戏窗口已切换，本次文字未填入。',
        b'error:clipboard_changed':'剪贴板内容被替换，本次文字未填入。',
        b'error:clipboard_timeout':'剪贴板读取超时，本次文字未填入，请重试。',
        b'error:clipboard_init':'剪贴板组件启动失败，请重新启用语音。',
        b'error:key_send':'游戏粘贴按键未能发送，请重试。',
        b'error:invalid_text':'识别文字为空或过长，本次未填入。',
    }.get(reply, '粘贴组件未能完成操作，请重试。')


@dataclass
class Press:
    start: float
    delivery: object
    up: float | None = None
    long: bool = False


def qml_binary():
    for path in ('/usr/lib/qt6/bin/qml', '/usr/lib64/qt6/bin/qml', shutil.which('qml6')):
        if path and os.access(path, os.X_OK):
            return path
    raise RuntimeError('缺少 Qt 6 WebEngine 登录组件，请检查 SteamOS 版本')


def browser_failure(line):
    # Inspect locally but never forward Chromium logs, URLs, tokens or cookies.
    value = line.lower()
    if b'qtwebengine' in value and (b'is not installed' in value or b'unavailable' in value):
        return '系统缺少 Qt WebEngine 模块，请检查系统组件'
    if b'platform plugin' in value and (b'could not' in value or b'failed' in value):
        return 'Qt 离屏显示组件无法启动，已停止重试'
    if b'failed to create' in value and (b'opengl' in value or b'graphics' in value):
        return '登录组件的软件渲染初始化失败'
    return ''


def send(**state):
    print(json.dumps(state, ensure_ascii=True), flush=True)


def command_file(folder, **cmd):
    temp = folder / 'command.tmp'
    temp.write_text(json.dumps(cmd))
    temp.replace(folder / 'command.json')


async def terminate(proc):
    if proc and proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), 2)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()


class Session:
    def __init__(self, folder):
        self.folder = folder
        self.browser = self.recorder = self.capture = self.keys = None
        self.clipboard = None
        self.wave_window = None
        self.press_number = self.hold_token = 0
        self.r5_until = 0
        self.r5_confirmed = False
        self.bar = DEFAULT_BAR.copy()
        self.press_time = 0
        self.audio_bytes = 0
        self.target = None
        self.pending_id = None
        self.pending_until = 0
        self.seq = 1
        self.outbox = []
        self.diagnostics = {}
        self.enabled = self.signed = False
        self.auth = 'checking'
        self.hotkey_name = 'F7'
        self.physical_down = self.key_level = False
        self.external_until = 0.0
        self.press = self.first_tap = None
        self.delivery = self.clear_due = None
        self.start_due = self.beginning = self.finish_due = self.committing = False
        self.accept_cancel = self.discard_requested = False
        self.cancel_on_repress = False
        self.input_lock = asyncio.Lock()
        self.ui_until = self.keyboard_until = 0
        self.ui_epoch = self.target_epoch = 0
        self.phase = 'ready'
        self.notice_id = 0
        self.hide_keyboard = False
        self.qr = self.last_qr = ''
        self.connect_until = time.monotonic() + 120
        self.login_deadline = time.monotonic() + 45
        self.login_stage = 'starting'
        self.credit = None

    def status(self, message=None, phase=None, hide_keyboard=False):
        if message is not None:
            self.credit = message
        if phase is not None:
            self.phase = phase
            self.notice_id += 1
            self.hide_keyboard = hide_keyboard
            if phase in ('error','done','cancelled'):
                self.accept_cancel = False
            if phase in ('error','recognizing','done','cancelled'):
                self.wave_status(phase)
        state = dict(phase=self.phase, notice=self.notice_id, hold=self.hold_token, hideKeyboard=self.hide_keyboard, enabled=self.enabled, signed=self.signed, auth=self.auth, qr=self.qr, message=self.credit or '', diagnostics=self.diagnostics)
        if state != getattr(self, 'last_state', None):
            self.last_state = state
            send(**state)

    def flush_commands(self):
        if len(self.outbox) == 1:
            command_file(self.folder, **self.outbox[0])
        elif self.outbox:
            command_file(self.folder, seq=self.seq, commands=self.outbox)
        else:
            command_file(self.folder, seq=self.seq, action='idle')

    def issue(self, action, **fields):
        self.seq += 1
        if action == 'cancel':
            self.outbox.clear()  # Never send unacknowledged audio after cancellation.
        self.outbox.append(dict(seq=self.seq, action=action, **fields))
        self.flush_commands()

    def acknowledge(self, seq):
        if type(seq) is not int or not 0 <= seq <= self.seq:
            return
        remaining = [cmd for cmd in self.outbox if cmd['seq'] > seq]
        if len(remaining) != len(self.outbox):
            self.outbox = remaining
            self.flush_commands()

    def start_stream(self):
        self.diagnostics = {}
        self.pending_id = self.seq + 1
        self.pending_until = time.monotonic() + MAX_SECONDS + 8
        self.issue('start', id=self.pending_id)

    def cancel_stream(self):
        if self.pending_id is not None:
            self.pending_id = None
            self.issue('cancel')

    async def connect(self):
        browser = qml_binary()
        PROFILE.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in ('Browser.qml', 'site.js'):
            shutil.copyfile(HERE / name, self.folder / name)
        self.issue('restore')
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                   QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu', QML_XHR_ALLOW_FILE_READ='1',
                   QT_SCALE_FACTOR='1', QT_AUTO_SCREEN_SCALE_FACTOR='0',
                   QT_FORCE_STDERR_LOGGING='1', XDG_DATA_HOME=str(PROFILE / 'data'),
                   XDG_CONFIG_HOME=str(PROFILE / 'config'), XDG_CACHE_HOME=str(self.folder / 'cache'))
        env.pop('WAYLAND_DISPLAY', None)
        env.pop('QT_SCREEN_SCALE_FACTORS', None)
        self.browser = await asyncio.create_subprocess_exec(
            browser, '-platform', 'offscreen', '-f', str(self.folder / 'Browser.qml'), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, stdin=asyncio.subprocess.DEVNULL, env=env, limit=1024*1024)
        self.status('正在连接账号…')

    async def browser_events(self):
        failure = ''
        async for line in self.browser.stdout:
            if b'WDI:' not in line:
                failure = browser_failure(line) or failure
                continue
            try:
                event = json.loads(line.split(b'WDI:', 1)[1])
                if event['kind'] == 'error':
                    # Only local QML publishes these fixed errors; page console is disabled.
                    raise RuntimeError(str(event.get('data', '登录组件失败'))[:160])
                if event['kind'] == 'stage':
                    self.login_stage = event.get('data')
                    self.status('正在等待官网登录二维码…' if self.login_stage == 'page_loaded' else '正在加载豆包登录页面…')
                    continue
                if event['kind'] != 'state':
                    continue
                state = json.loads(event['data'])
            except (ValueError, KeyError, TypeError):
                continue
            previous_auth = self.auth
            self.auth = state.get('auth', 'checking')
            self.signed = self.auth == 'signed'
            self.login_stage = 'signed' if self.signed else 'waiting_qr'
            qr = state.get('qr', '')
            self.qr = qr if isinstance(qr, str) and qr.startswith('data:image/png;base64,iVBORw0KGgo') and len(qr)<250000 else ''
            if self.auth != previous_auth and self.auth != 'signed':
                async with self.input_lock:
                    if self.auth == 'guest':
                        interrupted = self.recorder is not None or self.pending_id is not None
                        await self.disarm('登录已失效，请在语音设置中重新登录。' if interrupted else None)
                    elif self.recorder:
                        await self.finish(discard=True, reason='账号正在重新连接，请稍后再试。')
                self.connect_until = time.monotonic() + 120
                self.status('正在重新核验豆包登录' if self.auth == 'checking' else '请确认官网提供的登录方式')
            if self.signed and previous_auth != 'signed':
                self.connect_until = time.monotonic() + 180
                self.status('豆包已验证登录' + ('，听写已启用' if self.enabled else '，可启用按键听写'))
            elif self.qr and self.qr != self.last_qr:
                self.status('请使用豆包或飞书 App 扫码，并在手机上确认')
            self.last_qr = self.qr
            self.status()
            self.acknowledge(state.get('seq'))
            result = state.get('result')
            if isinstance(result, dict):
                async with self.input_lock:
                    if self.pending_id is None or result.get('id') != self.pending_id: continue
                    self.pending_id = None
                    stats = result.get('stats', {})
                    self.diagnostics = {key:value for key,value in stats.items()
                        if key in ('connect_ms','final_ms','audio_bytes','sent_bytes','responses','total_ms')
                        and type(value) is int and 0 <= value <= 2000000} if isinstance(stats, dict) else {}
                    if result.get('error') or not result.get('text'):
                        self.issue('cancel')
                        reason = result.get('error') or '没有识别到文字'
                        if self.recorder:
                            await self.finish(discard=True, reason=reason)
                        else:
                            self.status(reason, 'error')
                    elif self.recorder:
                        await self.finish(discard=True, reason='语音连接提前结束，请重新按住说话。')
                    else:
                        await self.paste(result['text'])
        raise RuntimeError(failure or '登录组件已退出，请检查 Qt WebEngine 后重新连接')

    def refresh_login(self):
        if self.signed:
            return
        self.qr = self.last_qr = ''
        self.login_deadline = time.monotonic() + 45
        self.connect_until = time.monotonic() + 120
        self.issue('login')
        self.status('正在重新获取官网二维码…')

    async def paste(self, text):
        target = self.target
        epoch = self.target_epoch
        if self.discard_requested:return
        if not self.enabled or not self.signed or not await self.can_deliver(target, epoch):
            if self.discard_requested:return
            self.status('已切离原游戏窗口，本次文字未填入。', 'error')
            return
        env = dict(os.environ, DISPLAY=target[0], WDI_ROOT_DISPLAY=os.environ['DISPLAY'], GDK_BACKEND='x11')
        p = await asyncio.create_subprocess_exec(sys.executable, str(HERE/'game.py'), '--guarded-paste', env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        async def boundary():
            return (await asyncio.wait_for(p.stdout.readline(), 4)).strip()

        sent = retained = False
        try:
            request = {'target':target, 'text':text, 'key':self.hotkey_name}
            p.stdin.write(json.dumps(request).encode() + b'\n')
            await p.stdin.drain()
            ready = await boundary()
            if self.discard_requested or not self.enabled or not self.signed or not self.target_active(target, epoch):
                return
            if ready != b'ready':
                self.status(paste_error(ready), 'error')
                return
            self.accept_cancel = False
            self.committing = True
            p.stdin.write(b'commit\n')
            await p.stdin.drain()
            outcome = await boundary()
            sent = outcome == b'sent'
            self.committing = False
            if sent:
                # Keep this one owner alive for delayed Wine clipboard reads.
                # The next owner replaces it; there is no previous-text restore.
                previous, self.clipboard = self.clipboard, p
                retained = True
            if sent and self.target_active(target, epoch):
                self.delivery = (target, epoch)
                self.status('已请求填入，请检查聊天草稿', 'done')
            elif not sent:
                self.status(paste_error(outcome), 'error')
            if sent and previous:
                previous.stdin.close()
                await terminate(previous)
        except (asyncio.TimeoutError, BrokenPipeError, ConnectionResetError):
            if not self.discard_requested and not sent:
                self.status('游戏粘贴未完成', 'error')
        finally:
            self.committing = False
            if not retained:
                p.stdin.close()
                await terminate(p)

    async def close_clipboard(self):
        previous, self.clipboard = self.clipboard, None
        if previous:
            previous.stdin.close()
            await terminate(previous)

    async def controls(self):
        reader = asyncio.StreamReader()
        transport, _ = await asyncio.get_running_loop().connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        try:
            async for line in reader:
                action = line.decode().strip()
                if action == 'refresh_login':
                    self.refresh_login()
                elif action.startswith('arm ') and self.signed and not self.enabled:
                    key = action[4:]
                    if key not in FUNCTION_KEYS:
                        raise RuntimeError('听写键无效')
                    if not all(shutil.which(c) for c in ('parec','xdotool','xprop')):
                        raise RuntimeError('缺少 parec、xdotool 或 xprop，语音未启用')
                    try:
                        import gi
                        gi.require_version('Gtk', '3.0')
                        gi.require_version('Gdk', '3.0')
                    except (ImportError, ValueError) as e:
                        raise RuntimeError('缺少 GTK 3 剪贴板组件，语音未启用') from e
                    async with self.input_lock:
                        self.keys = VoiceKey([key], watch_edges=True)
                        self.key_level = key in self.keys.pressed()
                        self.hotkey_name = key
                        self.enabled = True
                        self.connect_until = time.monotonic() + 180
                        self.status(f'已就绪。按住 {key} 说话，松开转写。')
                elif action in ('physical 1', 'physical 0'):
                    self.physical_event(action.endswith('1'), time.monotonic())
                elif action.startswith('r5 '):
                    _, token, value = action.split()
                    self.r5_event(int(token), value == '1', time.monotonic())
                elif action.startswith('bar '):
                    self.bar = bar_settings(json.loads(action[4:]))
                elif action in ('ui blocked','ui keyboard','ui game','ui unknown'):
                    await self.update_ui(action)
                elif action == 'disarm':
                    async with self.input_lock:
                        await self.disarm()
                    self.status('听写已暂停，豆包连接已保留')
                elif action == 'stop':
                    return
        finally:
            transport.close()

    async def update_ui(self, action):
        now = time.monotonic()
        # A temporarily missing Steam window is not a menu-open event. Only strict
        # game focus can authorize dictation until the frontend reports its state again.
        if action in ('ui blocked', 'ui unknown', 'ui keyboard'):
            self.forget_delivery()
        if action == 'ui unknown':
            self.keyboard_until = 0
            if self.ui_until: self.ui_until = min(self.ui_until, now)
            return
        blocked = action == 'ui blocked'
        interrupted = bool(self.ui_until) and blocked
        if interrupted:
            self.reset_press()
            self.ui_epoch += 1
        self.ui_until = 0 if blocked else now + UI_HEARTBEAT_TTL
        self.keyboard_until = self.ui_until if action == 'ui keyboard' else 0
        if interrupted:
            async with self.input_lock:
                await self.cancel_utterance()

    async def disarm(self, reason=None):
        self.enabled = False
        self.physical_down = False
        self.reset_press()
        self.forget_delivery()
        await self.cancel_utterance(reason)
        await self.close_clipboard()
        if self.keys:
            self.keys.close()
            self.keys = None

    async def cancel_utterance(self, reason=None):
        self.accept_cancel = False
        if self.recorder:
            await self.finish(discard=True, reason=reason)
        self.cancel_stream()
        if reason:
            self.status(reason, 'error')
        else:
            await self.close_wave()

    def request_cancel(self):
        # Invalidate synchronously, including while the recorder is draining or the
        # paste task is waiting for focus. A duplicate evdev/X11 edge is harmless.
        if not self.enabled or not self.accept_cancel:return
        self.discard_requested = True
        self.target = None
        self.cancel_stream()
        if self.recorder and self.recorder.returncode is None:
            with contextlib.suppress(ProcessLookupError):self.recorder.terminate()
        self.status('已取消本次听写', 'cancelled')

    def forget_delivery(self):
        self.delivery = self.first_tap = self.clear_due = None

    def reset_press(self):
        self.press = None
        self.start_due = self.finish_due = False
        self.end_observation()

    def end_observation(self):
        self.r5_confirmed = False
        self.r5_until = 0
        if self.hold_token:
            self.hold_token = 0
            self.status()

    def physical_event(self, down, now):
        # evdev supplies edges even when an entire tap falls between X11 polls.
        # Give those edges priority over the delayed mirror on the X display.
        self.physical_down = down
        self.external_until = now + .10
        self.key_edge(down, now, mapped=False)

    def r5_event(self, token, down, now):
        if not self.press or not self.hold_token or token != self.hold_token:
            return
        self.r5_confirmed = True
        self.r5_until = now + R5_HEARTBEAT if down else 0
        if not down:
            self.release_press(now)

    def key_edge(self, down, now, mapped):
        if down == self.key_level:
            return
        self.key_level = down
        if not self.enabled or not self.signed or not self.ui_until:
            return
        if not down:
            if self.press:
                self.press.up = now
                if not self.hold_token:
                    self.release_press(now)
            return
        if self.press is not None:
            # Repeated Steam Input pulses must not interrupt a confirmed hold.
            if self.press.up is None or (self.r5_confirmed and self.r5_until > now):
                return
            self.release_press(self.press.up)
        if self.cancel_on_repress and self.accept_cancel:
            self.request_cancel()
            return  # This entire press belongs to cancel, even if held.
        if self.beginning or self.recorder or self.pending_id is not None or self.committing:
            return
        self.press = Press(now, self.delivery)
        if mapped:
            self.press_number += 1
            self.hold_token = self.press_number
            self.status()

    def release_press(self, released):
        press, self.press = self.press, None
        self.end_observation()
        if not press:
            return
        if press.long:
            if self.recorder or self.beginning:
                self.finish_due = True
                self.cancel_on_repress = True
            self.start_due = False
            return
        # A missed long stroke is never reclassified as a short destructive tap.
        if released - press.start >= HOLD_SECONDS or press.delivery is None or press.delivery is not self.delivery:
            self.first_tap = None
            return
        if self.first_tap is not None and press.start - self.first_tap <= DOUBLE_TAP_GAP:
            self.clear_due = self.delivery
            self.first_tap = None
        else:
            self.first_tap = released

    def advance_press(self, now):
        press = self.press
        if not press:
            return
        if self.r5_confirmed:
            if self.r5_until <= now:
                self.release_press(now)
                return
        elif press.up is not None:
            # On the Deck a mapped F-key may pulse while R5 stays held. Keep
            # watching its token before deciding; an actual second edge resolves
            # the first tap immediately without waiting out this grace period.
            if now >= press.start + R5_DISCOVERY:
                self.release_press(press.up)
            return
        if not press.long and now - press.start >= HOLD_SECONDS:
            press.long = True
            self.forget_delivery()
            self.discard_requested = self.cancel_on_repress = False
            self.accept_cancel = self.start_due = True

    def read_key(self, now):
        if not self.keys:
            return
        edges = self.keys.edges(now)
        x_down = self.hotkey_name in self.keys.pressed()
        if not self.physical_down and now >= self.external_until:
            for when, down in edges:
                self.key_edge(down, when, mapped=True)
            self.key_edge(x_down, now, mapped=True)
        self.advance_press(now)

    async def sample_keys(self):
        # Keep observing while recording startup, focus verification or paste
        # owns input_lock. A press during transcription invalidates it at once.
        while True:
            if self.enabled and self.keys:
                self.read_key(time.monotonic())
            await asyncio.sleep(.022 if self.enabled else .15)

    async def clear_draft(self):
        delivery, self.clear_due = self.clear_due, None
        if delivery is None or delivery is not self.delivery:
            return
        target, epoch = delivery
        self.forget_delivery()
        if not self.enabled or not self.signed or not self.target_active(target, epoch):
            return
        if await asyncio.to_thread(focused_game) != target or not self.target_active(target, epoch):
            return
        if await asyncio.to_thread(game.signal_clear_draft, target, self.hotkey_name):
            self.status('已请求清空当前聊天草稿')

    async def read_audio(self, p):
        # Keep draining while the key is held; cap the utterance independently of UI timing.
        audio = bytearray()
        meter = WaveMeter()
        while True:
            chunk = await p.stdout.read(8192)
            if not chunk:
                break
            self.audio_bytes += len(chunk)
            remaining = RATE * MAX_SECONDS - len(audio)
            if remaining:
                audio.extend(chunk[:remaining])
                if self.pending_id is not None and not self.discard_requested and self.target_active(self.target, self.target_epoch):
                    self.issue('chunk', id=self.pending_id, audio=base64.b64encode(chunk[:remaining]).decode())
            levels = meter.feed(chunk)
            window = self.wave_window
            if levels and self.phase=='recording' and window and window.returncode is None and not window.stdin.is_closing():
                # Dropping a visual frame must never stall audio capture.
                if window.stdin.transport.get_write_buffer_size() < 4096:
                    with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                        window.stdin.write((json.dumps(levels)+'\n').encode())
            elif window and window.returncode is not None and self.phase == 'recording':
                self.status('正在听，当前画面无法显示波形', 'wave_unavailable')
        return bytes(audio)

    def wave_status(self, phase):
        window = self.wave_window
        if window and window.returncode is None and not window.stdin.is_closing():
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                window.stdin.write((json.dumps({'phase':phase, 'label':error_label(self.credit or '')})+'\n').encode())

    async def close_wave(self):
        window, self.wave_window = self.wave_window, None
        if window:
            window.stdin.close()
            await terminate(window)

    def target_active(self, target, epoch):
        return (target is not None and self.target == target and self.ui_epoch == epoch
                and self.ui_until > 0)

    async def can_deliver(self, target, epoch):
        # Hide only a verified Steam keyboard above the original game. Paste itself still requires strict focus.
        requested_hide = self.hide_keyboard
        for attempt in range(20):
            if not self.target_active(target, epoch):
                return False
            foreground = await asyncio.to_thread(focused_game)
            if foreground == target:
                return self.target_active(target, epoch)
            if foreground is not None:
                return False
            if attempt == 2 and self.wave_window and await asyncio.to_thread(wave_has_focus, target[0]):
                # On clients that briefly focus the decoration, let the game
                # regain focus naturally. Never redirect keyboard input ourselves.
                self.wave_status('yield')
            is_keyboard = time.monotonic() < self.keyboard_until
            if is_keyboard and await asyncio.to_thread(focused_game, True) == target and self.target_active(target, epoch):
                if not requested_hide:
                    self.status('正在返回原游戏聊天框', 'handoff', True)
                    requested_hide = True
            # Closing the wave or keyboard can leave XWayland briefly without focus.
            # Wait for the same window; paste_draft checks it again at injection time.
            await asyncio.sleep(.05)
        return False

    async def begin(self):
        epoch = self.ui_epoch
        keyboard_visible = time.monotonic() < self.keyboard_until
        target = await asyncio.to_thread(focused_game, keyboard_visible)
        if not self.ui_until or epoch != self.ui_epoch or self.discard_requested: return
        if not target:
            self.status('请先选中游戏里的聊天输入框，再按听写键。', 'error')
            return
        self.target = target
        self.target_epoch = epoch
        await self.close_wave()
        if self.discard_requested:return
        self.audio_bytes = 0
        try:
            self.wave_window = await asyncio.create_subprocess_exec(sys.executable, str(HERE/'wave_window.py'),
                json.dumps({'target':target,'style':self.bar}), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        except OSError:
            self.wave_window = None
        if self.discard_requested:
            self.wave_status('cancelled')
            return
        try:
            self.recorder = await asyncio.create_subprocess_exec(
                'parec', '--raw', '--rate=16000', '--channels=1', '--format=s16le', '--latency-msec=50',
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        except OSError:
            self.status('麦克风录音未能启动，请检查 Steam 的音频输入设备。', 'error')
            return
        self.start_stream()
        self.capture = asyncio.create_task(self.read_audio(self.recorder))
        self.press_time = time.monotonic()
        if self.discard_requested:
            await self.finish(discard=True)
            return
        self.status('正在听，松开按键结束', 'recording', keyboard_visible)
        if self.wave_window is None:
            self.status('正在听，当前画面无法显示听写框', 'wave_unavailable')

    async def finish(self, discard=False, reason=None):
        self.reset_press()
        if discard:
            self.cancel_stream()
        if self.discard_requested:
            self.status()
        elif not discard:
            # A confirmed release ends recording. Pressing the same back button
            # again before delivery cancels without requiring a second binding.
            self.cancel_on_repress = True
            self.status('正在转写…', 'recognizing')
        else:
            self.status()
            if not reason: await self.close_wave()
        await terminate(self.recorder)
        data = await self.capture
        self.recorder = self.capture = None
        if self.discard_requested:
            self.cancel_stream()
            return
        can_send = not discard and await self.can_deliver(self.target, self.target_epoch)
        if self.discard_requested:return
        if not can_send:
            self.cancel_stream()
            self.status(reason or '已离开原游戏输入框，本次听写已取消。', 'error')
        elif not data:
            self.cancel_stream()
            self.status('麦克风没有返回音频。请在 Steam 的音频设置中检查输入设备。', 'error')
        elif len(data) < RATE // 7:
            self.cancel_stream()
            self.status('按住听写键直到说完，再松开。', 'error')
        elif not any(data):
            self.cancel_stream()
            self.status('麦克风录到的是静音，请检查输入音量或静音开关。', 'error')
        elif self.pending_id is not None:
            self.pending_until = time.monotonic() + 8
            self.issue('finish', id=self.pending_id)
        else:
            self.status('语音连接已结束，请重新按住说话。', 'error')

    async def hotkey(self):
        next_focus_check = 0
        focus_missing_since = None
        while True:
            now = time.monotonic()
            if self.signed and not self.enabled and now > self.connect_until:
                self.status('语音连接已暂停。')
                return
            if not self.signed:
                if not self.qr and now > self.login_deadline:
                    stage = {'starting':'组件启动', 'browser_ready':'网页加载', 'page_loaded':'登录页面',
                             'waiting_qr':'官网二维码'}.get(self.login_stage, '登录页面')
                    raise RuntimeError(f'获取二维码超时（{stage}），已停止自动重试；请检查网络或系统组件后重新连接')
                if now > self.connect_until:
                    self.status('二维码已过期，请重新连接账号。', 'error')
                    return
                await asyncio.sleep(.15)
                continue
            async with self.input_lock:
                if self.enabled and self.signed and self.ui_until:
                    if self.pending_id is not None and now > self.pending_until:
                        self.cancel_stream()
                        self.status('听写超时，松开后可重试', 'error')
                    if self.clear_due is not None:
                        await self.clear_draft()
                    if self.start_due:
                        self.start_due = False
                        self.beginning = True
                        try:
                            await self.begin()
                        finally:
                            self.beginning = False
                    if self.recorder:
                        now = time.monotonic()
                        if self.discard_requested:
                            await self.finish(discard=True)
                        elif self.recorder.returncode is not None or (not self.audio_bytes and now-self.press_time > 3):
                            await self.finish(discard=True, reason='麦克风未能持续录音，请检查 Steam 的音频输入设备。')
                        elif self.finish_due:
                            await self.finish()
                        elif now-self.press_time >= MAX_SECONDS:
                            await self.finish(discard=True, reason='单次录音已达 20 秒，请分段说。')
                        elif now >= self.ui_until and now >= next_focus_check:
                            next_focus_check = now + .3
                            if await asyncio.to_thread(focused_game) == self.target:
                                focus_missing_since = None
                            elif focus_missing_since is None:
                                focus_missing_since = now
                            elif now-focus_missing_since >= .45:
                                await self.cancel_utterance()
                    else:
                        focus_missing_since = None
            await asyncio.sleep(.035 if self.enabled else .15)

    async def run(self):
        tasks = []
        try:
            await self.connect()
            tasks = [asyncio.create_task(fn()) for fn in (self.controls, self.browser_events, self.hotkey, self.sample_keys)]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.close_wave()
            await self.close_clipboard()
            await terminate(self.recorder)
            if self.capture: await self.capture
            if self.browser and self.browser.returncode is None:
                command_file(self.folder, seq=self.seq + 1, action='shutdown')
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.browser.wait(), 2)
            await terminate(self.browser)
            if self.keys: self.keys.close()
    

def main():
    os.umask(0o077)
    if os.geteuid() == 0:
        raise RuntimeError('登录助手必须以普通用户运行')
    if sys.argv[1:] == ['forget']:
        if PROFILE.exists(): shutil.rmtree(PROFILE)
        return
    runtime = Path(os.environ['XDG_RUNTIME_DIR'])
    with tempfile.TemporaryDirectory(dir=runtime, prefix='wowdeck-voice-') as temp:
        asyncio.run(Session(Path(temp)).run())


if __name__ == '__main__':
    try: main()
    except RuntimeError as e: send(enabled=False, signed=False, auth='error', phase='error', qr='', message=str(e))
    except (OSError, ValueError): send(enabled=False, signed=False, auth='error', phase='error', qr='', message='语音助手无法启动，请检查 SteamOS 系统组件')
