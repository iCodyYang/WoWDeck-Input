import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from test_scheme import module as backend
from model import validate
from voice.control import VoiceControl
from evdev_mod.input import _clean_str
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'voice'))
import worker


def plugin():
    p = backend.Plugin()
    p.config = validate({})
    p.devices, p.input_errors, p.input_details = {}, {}, []
    p.input_status, p.last_scan = '插件已关闭', 0
    p.game_active = p.grabbing = p.stopping = False
    p.grab_timeout = p.capture = None
    p.error, p.version = '', 'test'
    p.voice = SimpleNamespace(state={'enabled':False}, signal=Mock(), call=AsyncMock())
    p.session = SimpleNamespace(read=Mock(return_value={}))
    p.scheme_values = AsyncMock(return_value={})
    p.engine_available = Mock(return_value=True)
    return p


class KeyboardRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_enabling_invalidates_previous_disabled_scan_status(self):
        p=plugin()
        p.lock=asyncio.Lock()
        p.persist=Mock()
        p.last_scan=123
        p.set_scheme=AsyncMock()
        await p.set_master(True)
        state=await p.set_enabled(True)
        self.assertEqual(p.last_scan,0)
        self.assertIn('正在初始化',state['status']['inputStatus'])

    async def test_initial_status_cannot_claim_disabled_when_enabled(self):
        p = plugin()
        p.config.update(pluginEnabled=True, enabled=True)
        self.assertIn('正在初始化', (await p.get_state())['status']['inputStatus'])
        p.config['enabled'] = False
        self.assertIn('键盘输入法已关闭', (await p.get_state())['status']['inputStatus'])
        p.config['pluginEnabled'] = False
        self.assertIn('总开关已关闭', (await p.get_state())['status']['inputStatus'])

    async def test_one_scan_exception_does_not_kill_monitor(self):
        p = plugin()
        p.config.update(pluginEnabled=True, enabled=True)
        scans = 0
        def scan():
            nonlocal scans
            scans += 1
            if scans == 1: raise UnicodeDecodeError('utf8', b'\xff', 0, 1, 'fixture')
            p.stopping = True
        p.scan_keyboards = scan
        with patch.object(backend.asyncio, 'sleep', new_callable=AsyncMock):
            await p.watch()
        self.assertEqual(scans, 2)
        self.assertEqual(p.input_errors['scan'], '检测异常：UnicodeDecodeError')

    async def test_explicit_inspection_does_not_enable_or_open_inputs(self):
        p = plugin()
        p.task = asyncio.create_task(asyncio.sleep(60))
        try:
            with patch.object(backend, 'keyboard_inventory', return_value=['BT：实体键盘']), \
                 patch.object(backend.ev, 'InputDevice') as open_device:
                result = await p.inspect_keyboards()
            self.assertEqual(result['status']['inputDetails'], ['BT：实体键盘'])
            self.assertFalse(p.config['pluginEnabled'])
            open_device.assert_not_called()
            p.voice.call.assert_not_awaited()
            p.session.read.assert_not_called()
        finally:
            p.task.cancel()
            await asyncio.gather(p.task, return_exceptions=True)

    async def test_dead_monitor_can_be_restarted_by_inspection(self):
        p = plugin()
        p.task = asyncio.create_task(asyncio.sleep(0))
        await p.task
        p.watch = AsyncMock()
        with patch.object(backend, 'keyboard_inventory', return_value=[]):
            await p.inspect_keyboards()
        await p.task
        p.watch.assert_awaited_once()

    async def test_bad_keyboard_does_not_prevent_another_keyboard_opening(self):
        p=plugin()
        p.config.update(pluginEnabled=True,enabled=True)
        p.session.read.return_value={'DISPLAY':':7'}
        p.voice_keys_down=set()
        dev=Mock(fd=9876)
        dev.name='Bluetooth Keyboard'
        dev.info=SimpleNamespace(vendor=1)
        dev.capabilities.return_value={1:[29,30,57]}
        def open_device(path):
            if path.endswith('event1'):raise ValueError('unsupported metadata')
            return dev
        real_stat=backend.os.stat
        def stat(path,*args,**kwargs):
            if str(path).startswith('/dev/input/event'):return SimpleNamespace(st_ino=1,st_ctime_ns=1)
            return real_stat(path,*args,**kwargs)
        loop=asyncio.get_running_loop()
        with patch.object(Path,'glob',return_value=iter([Path('/dev/input/event1'),Path('/dev/input/event2')])), \
             patch.object(backend,'keyboard_endpoint',return_value=True), \
             patch.object(backend.ev,'InputDevice',side_effect=open_device), \
             patch.object(backend.os,'stat',stat),patch.object(loop,'add_reader'):
            p.scan_keyboards()
        self.assertEqual(set(p.devices),{'/dev/input/event2'})
        self.assertIn('ValueError',p.input_errors['/dev/input/event1'])


class InputMetadata(unittest.TestCase):
    def test_firmware_label_need_not_be_utf8(self):
        self.assertEqual(_clean_str(b'Keyboard\xff\0ignored'), 'Keyboard\ufffd')

    def test_inventory_reports_hidden_and_virtual_without_opening_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sysfs, inputs = root/'sys/class/input', root/'dev/input'
            (inputs/'.hidden').mkdir(parents=True)
            for i,name in enumerate(['AT Translated Set 2 keyboard','Bluetooth Keyboard','InputPlumber Keyboard']):
                device = root/('devices/virtual/input/input2' if i==2 else f'devices/physical/input{i}')
                (device/'id').mkdir(parents=True)
                (device/'capabilities').mkdir()
                (device/'name').write_text(name)
                (device/'id/vendor').write_text('0001')
                (device/'capabilities/key').write_text(f'{sum(1<<k for k in (29,30,57)):x}')
                entry=sysfs/f'event{i}'
                entry.mkdir(parents=True)
                (entry/'device').symlink_to(device)
                (inputs/('.hidden/' if i==1 else '')/f'event{i}').touch()
            with patch.object(backend.ev, 'InputDevice') as open_device:
                rows=backend.keyboard_inventory(sysfs,inputs)
            self.assertIn('键盘候选 3 个', rows[0])
            self.assertIn('实体键盘',rows[1])
            self.assertIn('被系统映射工具隐藏',rows[2])
            self.assertIn('系统映射键盘（未接管）',rows[3])
            open_device.assert_not_called()


class LoginRecovery(unittest.IsolatedAsyncioTestCase):
    def controller(self):
        with patch('voice.control.report_stream', return_value=None):
            return VoiceControl(SimpleNamespace(pw_uid=2345,pw_dir='/tmp/test-user'))

    async def test_login_spawn_failure_blocks_automatic_restart(self):
        ctrl = self.controller()
        with patch.object(ctrl, 'spawn_options', side_effect=ValueError('fixture')):
            with self.assertRaises(ValueError): await ctrl.call('restore')
        self.assertTrue(ctrl.view('F7')['retryBlocked'])
        p=plugin()
        p.config.update(pluginEnabled=True, voiceWanted=True)
        p.lock=asyncio.Lock()
        p.voice=ctrl
        p.voice.call=AsyncMock()
        await p.reconcile_voice()
        p.voice.call.assert_not_awaited()

    async def test_worker_error_is_preserved_and_no_auto_respawn(self):
        ctrl=self.controller()
        stream=asyncio.StreamReader()
        stream.feed_data(json.dumps(dict(phase='error',auth='error',message='二维码超时')).encode()+b'\n')
        stream.feed_eof()
        proc=SimpleNamespace(stdout=stream,wait=AsyncMock(),pid=987654)
        ctrl.proc=proc
        with patch('voice.control.os.killpg'):
            await ctrl.read(proc)
        self.assertTrue(ctrl.retry_blocked)
        self.assertEqual(ctrl.state['message'],'二维码超时')
        self.assertFalse(ctrl.state['running'])

    async def test_refresh_keeps_existing_browser_and_account(self):
        ctrl=self.controller()
        ctrl.proc=Mock(returncode=None)
        ctrl.proc.stdin.is_closing.return_value=False
        ctrl.state.update(running=True,auth='guest')
        with patch.object(ctrl,'_stop',new_callable=AsyncMock) as stop:
            await ctrl.call('refresh')
            stop.assert_not_awaited()
        ctrl.proc.stdin.write.assert_called_once_with(b'refresh_login\n')

    async def test_browser_is_forced_offscreen_with_independent_scaling(self):
        with tempfile.TemporaryDirectory() as directory:
            session=worker.Session(Path(directory)/'runtime')
            session.folder.mkdir()
            with patch.object(worker,'PROFILE',Path(directory)/'profile'), \
                 patch.object(worker,'qml_binary',return_value='/usr/lib/qt6/bin/qml'), \
                 patch.object(worker,'send'), \
                 patch.dict(worker.os.environ,{'QT_SCALE_FACTOR':'2','QT_SCREEN_SCALE_FACTORS':'2;2','WAYLAND_DISPLAY':'wayland-1'}), \
                 patch.object(worker.asyncio,'create_subprocess_exec',new_callable=AsyncMock) as spawn:
                await session.connect()
            args, options=spawn.call_args
            self.assertEqual(args[1:3],('-platform','offscreen'))
            self.assertEqual(options['env']['QT_QPA_PLATFORM'],'offscreen')
            self.assertEqual(options['env']['QT_SCALE_FACTOR'],'1')
            self.assertNotIn('WAYLAND_DISPLAY',options['env'])
            self.assertNotIn('QT_SCREEN_SCALE_FACTORS',options['env'])

    async def test_missing_qr_stops_with_bounded_failure(self):
        session=worker.Session(Path('.'))
        session.login_deadline=time.monotonic()-1
        session.login_stage='page_loaded'
        with self.assertRaisesRegex(RuntimeError,'获取二维码超时（登录页面）'):
            await asyncio.wait_for(session.hotkey(),1)

    async def test_browser_component_error_is_classified_without_leaking_log(self):
        session=worker.Session(Path('.'))
        stream=asyncio.StreamReader()
        stream.feed_data(b'module "QtWebEngine" is not installed /private/fixture\n')
        stream.feed_eof()
        session.browser=SimpleNamespace(stdout=stream)
        with self.assertRaisesRegex(RuntimeError,'系统缺少 Qt WebEngine 模块') as error:
            await session.browser_events()
        self.assertNotIn('/private/fixture',str(error.exception))

    async def test_login_refresh_clears_only_qr_and_resets_deadline(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(worker,'send'):
            session=worker.Session(Path(directory))
            session.qr='old-qr'
            session.login_deadline=0
            session.refresh_login()
            self.assertEqual(session.qr,'')
            self.assertGreater(session.login_deadline,time.monotonic())
            self.assertEqual(json.loads((session.folder/'command.json').read_text())['action'],'login')
