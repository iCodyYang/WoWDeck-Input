import asyncio
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from test_scheme import module as backend
from host_session import GameSession, environment
from model import validate


class KeyboardHardware(unittest.TestCase):
    def test_internal_and_bluetooth_names_and_right_ctrl(self):
        for name in ('AT Translated Set 2 keyboard', 'Bluetooth Keyboard', 'I2C Keyboard'):
            for ctrl in (29, 97):
                dev = SimpleNamespace(name=name, info=SimpleNamespace(vendor=1),
                    capabilities=lambda: {1: [30, 57, ctrl]})
                self.assertTrue(backend.is_external_keyboard(dev), (name, ctrl))

    def test_physical_buses_and_controller_filter_before_open(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device = root/'class/input/event0/device'
            (device/'id').mkdir(parents=True)
            (device/'capabilities').mkdir()
            (device/'name').write_text('AT Translated Set 2 keyboard')
            (device/'id/vendor').write_text('0001')
            def check(keys):
                bits = sum(1 << k for k in keys)
                words = []
                while bits:
                    words.append(f'{bits & ((1 << 64)-1):x}')
                    bits >>= 64
                (device/'capabilities/key').write_text(' '.join(reversed(words)))
                return backend.keyboard_endpoint('/dev/input/event0', root/'class/input')
            for bus in ('0003', '0005', '0011', '0018', '001c'):
                (device/'id/bustype').write_text(bus)
                self.assertTrue(check([30, 57, 97]), bus)
            for controller_key in (288, 304, 544, 704):
                self.assertFalse(check([29, 30, 57, controller_key]))
            self.assertFalse(check([115, 116]))  # volume/power-only platform device
            (device/'id/vendor').write_text('28de')
            self.assertFalse(check([29, 30, 57]))
            (device/'id/vendor').write_text('0001')
            (device/'name').write_text('Steam Controller Keyboard')
            self.assertFalse(check([29, 30, 57]))
            # Virtual keyboard output is not indiscriminately grabbed: it may carry menu keys.
            virtual = root/'devices/virtual/input/input1'
            virtual.parent.mkdir(parents=True)
            device.rename(virtual)
            device.symlink_to(virtual)
            (virtual/'name').write_text('InputPlumber Keyboard')
            self.assertFalse(backend.keyboard_endpoint('/dev/input/event0', root/'class/input'))


class SessionCompatibility(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.user = SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid(), pw_name='tester', pw_dir=tmp.name)
        self.proc, self.runtime, self.sockets = [self.root/name for name in ('proc', 'runtime', 'sockets')]
        for path in (self.proc, self.runtime, self.sockets): path.mkdir()
        (self.sockets/'X7').touch()
        self.now = 10
        self.probe = GameSession(self.user, self.runtime, self.proc, self.sockets, lambda:self.now)
        self.clean_env = patch.dict(os.environ, {}, clear=True)
        self.clean_env.start()
        self.addCleanup(self.clean_env.stop)

    def steam(self, values, name='steam', pid='100'):
        process = self.proc/pid
        process.mkdir(exist_ok=True)
        (process/'comm').write_text(name)
        (process/'environ').write_text('\x00'.join(f'{k}={v}' for k,v in values.items())+'\x00')

    def test_original_steam_os_file_and_colon_desktop(self):
        for desktop in ('gamescope', 'gamescope:steam'):
            (self.runtime/'gamescope-environment').write_text(f'export XDG_CURRENT_DESKTOP="{desktop}"\nDISPLAY=\':7\'\n')
            self.now += 3
            self.assertEqual(self.probe.read()['DISPLAY'], ':7')

    def test_live_steam_without_environment_file_or_ibus_service(self):
        self.steam({'XDG_CURRENT_DESKTOP':'gamescope', 'DISPLAY':':7', 'XAUTHORITY':'/tmp/game-authority',
                    'DO_NOT_COPY':'unrelated-private-fixture', 'LD_PRELOAD':'unrelated.so'})
        result = self.probe.read()
        self.assertEqual(result['DISPLAY'], ':7')
        self.assertEqual(result['XAUTHORITY'], '/tmp/game-authority')
        self.assertNotIn('DO_NOT_COPY', result)
        self.assertNotIn('LD_PRELOAD', result)

    def test_display_environment_marker_fallback(self):
        self.steam({'GAMESCOPE_WAYLAND_DISPLAY':'gamescope-0', 'STEAM_GAME_DISPLAY_0':':8', 'DISPLAY':':7'})
        self.assertEqual(self.probe.read()['DISPLAY'], ':7')

    def test_desktop_steam_blocks_stale_file(self):
        (self.runtime/'gamescope-environment').write_text('XDG_CURRENT_DESKTOP=gamescope\nDISPLAY=:7\n')
        self.steam({'XDG_CURRENT_DESKTOP':'KDE', 'DISPLAY':':7'})
        self.assertEqual(self.probe.read(), {})

    def test_nested_game_does_not_activate_desktop(self):
        self.steam({'XDG_CURRENT_DESKTOP':'KDE', 'DISPLAY':':7'})
        self.steam({'XDG_CURRENT_DESKTOP':'gamescope', 'DISPLAY':':7'}, name='Wow.exe', pid='101')
        self.assertEqual(self.probe.read(), {})

    def test_missing_socket_and_remote_display_do_not_activate(self):
        for display in (':9', 'remote:7', 'localhost:7'):
            self.steam({'XDG_CURRENT_DESKTOP':'gamescope', 'DISPLAY':display})
            self.now += 3
            self.assertEqual(self.probe.read(), {})

    def test_other_user_steam_not_used(self):
        self.steam({'XDG_CURRENT_DESKTOP':'gamescope', 'DISPLAY':':7'})
        self.probe.uid += 1
        self.assertEqual(self.probe.read(), {})

    def test_cache_expires_and_does_not_hold_previous_session(self):
        self.steam({'XDG_CURRENT_DESKTOP':'gamescope', 'DISPLAY':':7'})
        with patch.object(self.probe, 'discover', wraps=self.probe.discover) as discover:
            first = self.probe.read()
            first['DISPLAY'] = ':99'  # callers cannot corrupt the cache
            self.assertEqual(self.probe.read()['DISPLAY'], ':7')
            discover.assert_called_once()
            self.steam({'XDG_CURRENT_DESKTOP':'KDE', 'DISPLAY':':7'})
            self.now += 3
            self.assertEqual(self.probe.read(), {})
            self.assertEqual(discover.call_count, 2)

    def test_voice_uses_same_session_and_user_without_deck_path(self):
        self.steam({'XDG_CURRENT_DESKTOP':'gamescope:steam', 'DISPLAY':':7', 'XAUTHORITY':'/tmp/game-authority'})
        with patch('voice.control.report_stream', return_value=None), patch('voice.control.os.geteuid', return_value=999):
            voice = backend.VoiceControl(self.user, session=self.probe)
            options = voice.spawn_options()
        self.assertEqual(options['env']['DISPLAY'], ':7')
        self.assertEqual(options['env']['HOME'], self.user.pw_dir)
        self.assertNotIn('DO_NOT_COPY', options['env'])
        self.steam({'XDG_CURRENT_DESKTOP':'KDE', 'DISPLAY':':7'})
        self.now += 3
        with self.assertRaises(ValueError): voice.spawn_options()

    def test_environment_parser_never_evaluates_shell(self):
        result = environment('export DISPLAY=":7"\nIGNORED=value\nXAUTHORITY=$(anything)\n')
        self.assertEqual(result, {'DISPLAY':':7', 'XAUTHORITY':'$(anything)'})


class InputLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.p = p = backend.Plugin()
        p.config = validate({})
        p.config.update(pluginEnabled=True, enabled=True)
        p.stopping = p.grabbing = p.game_active = False
        p.capture = p.grab_timeout = None
        p.last_open = 0
        p.devices = {}
        p.voice_keys_down = set()
        p.input_errors = {}
        p.session = SimpleNamespace(read=Mock(return_value={'DISPLAY':':7'}))
        p.voice = SimpleNamespace(state={'enabled':False}, signal=Mock())
        self.device = d = Mock(fd=9876)
        d.name = 'AT Translated Set 2 keyboard'
        d.info = SimpleNamespace(vendor=1)
        d.capabilities.return_value = {1:[29,30,57]}
        self.paths = [Path('/dev/input/event7')]
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        real_stat = os.stat
        def device_stat(path, *args, **kwargs):
            if str(path) == '/dev/input/event7':
                return SimpleNamespace(st_ino=7, st_ctime_ns=1)
            return real_stat(path, *args, **kwargs)
        for target, value in (
            ('pathlib.Path.glob', lambda *args:iter(self.paths)),
            ('os.stat', device_stat),
        ): self.stack.enter_context(patch(target, value))
        self.stack.enter_context(patch.object(backend, 'keyboard_endpoint', return_value=True))
        self.open = self.stack.enter_context(patch.object(backend.ev, 'InputDevice', return_value=d))
        loop = asyncio.get_running_loop()
        self.stack.enter_context(patch.object(loop, 'add_reader'))
        self.stack.enter_context(patch.object(loop, 'remove_reader'))

    def events(self, pairs):
        self.device.read.return_value = [SimpleNamespace(type=1, code=code, value=value) for code,value in pairs]

    async def test_scan_to_wake_and_voice_press_release(self):
        p = self.p
        p.scan_keyboards()
        self.assertTrue(p.game_active)
        self.assertIn('/dev/input/event7', p.devices)
        self.device.grab.assert_not_called()
        self.events([(29,1),(57,1),(57,0),(29,0)])
        with patch.object(backend.decky, 'emit', AsyncMock()) as emit:
            p.read_device('/dev/input/event7')
            await asyncio.sleep(0)
            emit.assert_awaited_once_with('open_keyboard')
        p.voice.state['enabled'] = True
        self.events([(65,1),(65,2),(65,0)])
        p.read_device('/dev/input/event7')
        self.assertEqual([c.args for c in p.voice.signal.call_args_list], [('physical 1',),('physical 0',)])

    async def test_permission_failure_is_visible_and_retried(self):
        self.open.side_effect = PermissionError()
        self.p.scan_keyboards()
        self.assertIn('没有读取键盘的权限', self.p.input_errors['/dev/input/event7'])
        self.open.side_effect = None
        self.p.scan_keyboards()
        self.assertFalse(self.p.input_errors)
        self.assertIn('/dev/input/event7', self.p.devices)

    async def test_disconnect_reconnect_and_desktop_release(self):
        p = self.p
        p.scan_keyboards()
        self.paths.clear()
        p.scan_keyboards()
        self.assertFalse(p.devices)
        self.device.close.assert_called_once()
        self.paths.append(Path('/dev/input/event7'))
        p.scan_keyboards()
        self.assertIn('/dev/input/event7', p.devices)
        await p.grab_keyboards()
        p.session.read.return_value = {}
        p.scan_keyboards()
        self.assertFalse(p.devices or p.grabbing or p.game_active)
        self.device.ungrab.assert_called_once()
        self.assertIn('未识别到 Steam 游戏模式', p.input_status)

    async def test_off_switch_does_not_probe_or_open_device(self):
        self.p.config['pluginEnabled'] = False
        self.p.scan_keyboards()
        self.p.session.read.assert_not_called()
        self.open.assert_not_called()
        self.assertEqual(self.p.input_status, '插件已关闭')

    async def test_controller_rejected_without_opening(self):
        with patch.object(backend, 'keyboard_endpoint', return_value=False):
            self.p.scan_keyboards()
        self.open.assert_not_called()


class UserCompatibility(unittest.TestCase):
    def test_non_deck_steam_user_on_legacy_loader(self):
        user = SimpleNamespace(pw_uid=2345, pw_name='handheld')
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(backend.decky, 'DECKY_USER_HOME', None, create=True), \
             patch.object(backend.os, 'geteuid', return_value=0), \
             patch.object(backend, 'steam_processes', return_value=iter([(Path('/proc/101'),2345)])), \
             patch.object(backend.pwd, 'getpwuid', return_value=user) as lookup, \
             patch.object(backend.pwd, 'getpwnam') as legacy:
            self.assertIs(backend.Plugin.session_user(), user)
            lookup.assert_called_once_with(2345)
            legacy.assert_not_called()
