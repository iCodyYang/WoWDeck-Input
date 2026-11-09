import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from test_scheme import module as backend
from model import Chord, validate


class MasterSwitch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.profile = self.home / '.local/share/wowdeck-input/doubao-browser/data'
        self.profile.mkdir(parents=True)
        self.p = backend.Plugin()
        self.p.user = SimpleNamespace(pw_uid=1000, pw_dir=temp.name)
        self.p.path = self.home / 'settings.json'
        self.p.config = validate({})
        self.p.stopping = self.p.grabbing = False
        self.p.grab_timeout = self.p.capture = None
        self.p.voice_keys_down = set()
        self.p.devices = {}
        self.p.lock = asyncio.Lock()
        self.p.voice = backend.VoiceControl(self.p.user)
        self.p.voice.call = AsyncMock()
        self.p.get_state = AsyncMock()

    async def test_first_upgrade_requires_explicit_opt_in(self):
        old = {'version':1, 'enabled':True, 'voiceWanted':True, 'voiceR5':True,
               'scheme':'xiaohe', 'voiceKey':'F11', 'appearance':{'x':81}}
        self.p.config = validate(old)
        self.assertFalse(self.p.config['pluginEnabled'])
        self.assertFalse(self.p.config['voiceWanted'])
        self.assertNotIn('voiceR5', self.p.config)
        for key in ('scheme', 'voiceKey', 'enabled'):
            self.assertEqual(self.p.config[key], old[key])
        self.assertEqual(self.p.config['appearance']['x'], 81)
        await self.p.reconcile_voice()
        await self.p.set_master(True)
        await self.p.reconcile_voice()
        self.p.voice.call.assert_not_awaited()

    async def test_voice_switch_restores_and_arms_without_game_process(self):
        p = self.p
        await p.set_master(True)
        await p.voice_action('arm')
        p.voice.call.reset_mock()
        await p.reconcile_voice()
        p.voice.call.assert_awaited_once_with('restore')
        p.voice.state.update(running=True, signed=True, enabled=False)
        await p.reconcile_voice()
        p.voice.call.assert_awaited_with('arm', 'F7')

    async def test_off_wins_against_queued_reconcile_and_survives_reload(self):
        p = self.p
        p.config.update(pluginEnabled=True, voiceWanted=True)
        async with p.lock:
            off = asyncio.create_task(p.set_master(False))
            await asyncio.sleep(0)
            detection = asyncio.create_task(p.reconcile_voice())
            await asyncio.sleep(0)
        await asyncio.gather(off,detection)
        p.config = validate(json.loads(p.path.read_text()))
        self.assertFalse(p.config['pluginEnabled'])
        await p.reconcile_voice()
        p.voice.call.assert_awaited_once_with('stop')
        self.assertTrue(self.profile.is_dir())

    async def test_master_off_cancels_capture_and_releases_open_device(self):
        p = self.p
        p.config.update(pluginEnabled=True, enabled=True, voiceWanted=True)
        device = Mock(fd=8877)
        p.devices['keyboard'] = dict(device=device, grabbed=True, chord=Chord())
        p.grabbing = True
        p.capture = {'target':'adjust'}
        p.voice_keys_down = {'keyboard'}
        with patch.object(asyncio.get_running_loop(), 'remove_reader'):
            await p.set_master(False)
        self.assertIsNone(p.capture)
        self.assertFalse(p.grabbing or p.devices or p.voice_keys_down)
        device.ungrab.assert_called_once()
        device.close.assert_called_once()
        p.voice.call.assert_awaited_once_with('stop')
        await p.grab_keyboards()
        device.grab.assert_not_called()
        for action in ('arm','restore','login','refresh','test'):
            with self.assertRaises(ValueError):
                await p.voice_action(action)
        for op in (p.begin_capture('wake'), p.set_enabled(True), p.set_voice_key('F11')):
            with self.assertRaises(ValueError):
                await op
        p.voice.call.assert_awaited_once_with('stop')

    async def test_standby_off_releases_worker_even_with_keyboard_enabled(self):
        p = self.p
        p.config.update(pluginEnabled=True, enabled=True, voiceWanted=True)
        await p.voice_action('disarm')
        await p.reconcile_voice()
        p.voice.call.assert_awaited_once_with('stop','F7')
        state = validate(json.loads(p.path.read_text()))
        self.assertTrue(state['enabled'] and state['pluginEnabled'])
        self.assertFalse(state['voiceWanted'])
        self.assertTrue(self.profile.is_dir())

    async def test_plain_m_is_not_forwarded_and_keyboard_lease_expires(self):
        p = self.p
        p.config.update(pluginEnabled=True, enabled=True, voiceWanted=True)
        p.voice.state['enabled'] = True
        p.voice.signal = Mock()
        p.last_open = 0
        device = Mock()
        device.read.return_value = [SimpleNamespace(type=1, code=50, value=v) for v in (1,0)]
        p.devices['usb'] = dict(device=device, grabbed=False, chord=Chord())
        with patch.object(backend.decky, 'emit', AsyncMock()) as emit:
            p.read_device('usb')
            await asyncio.sleep(0)
            emit.assert_not_awaited()
        p.voice.signal.assert_not_called()
        device.grab.assert_not_called()
        await p.grab_keyboards()
        self.assertTrue(p.grabbing)
        await asyncio.sleep(1)
        self.assertFalse(p.grabbing)
        device.ungrab.assert_called_once()

    async def test_disable_stops_a_live_helper_and_pending_key_detector(self):
        p = self.p
        p.config.update(pluginEnabled=True, voiceWanted=True)
        p.voice = backend.VoiceControl(p.user)
        # A local stand-in for the worker that exits only after the stop command.
        worker = await asyncio.create_subprocess_exec(sys.executable, '-c',
            'import sys\nfor line in sys.stdin:\n if line.strip() == "stop": sys.exit(0)\nsys.exit(1)',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, start_new_session=True)
        p.voice.proc = worker
        p.voice.state.update(running=True, enabled=True, signed=True)
        p.voice.reader = asyncio.create_task(p.voice.read(worker))
        detector = p.voice.detector = asyncio.create_task(asyncio.sleep(60))
        try:
            await asyncio.wait_for(p.set_master(False), 8)
            self.assertEqual(worker.returncode, 0)
            self.assertTrue(detector.cancelled())
            self.assertFalse(p.voice.state['running'])
            self.assertTrue(self.profile.is_dir())
        finally:
            if worker.returncode is None:
                worker.kill()
                await worker.wait()


class DeviceSelection(unittest.TestCase):
    def test_controller_endpoints_excluded_before_evdev_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            device = root / 'event1/device'
            (device/'id').mkdir(parents=True)
            (device/'capabilities').mkdir()
            (device/'id/bustype').write_text('0003')
            keys = sum(1 << k for k in (29, 30, 57))
            def candidate(vendor, controller):
                (device/'id/vendor').write_text(vendor)
                # Four zero groups separate the first 64 bits from BTN_GAMEPAD.
                words = ('1000000000000 0 0 0 ' if controller else '') + f'{keys:x}'
                (device/'capabilities/key').write_text(words)
                return backend.keyboard_endpoint('/dev/input/event1', root)
            self.assertFalse(candidate('28de', False))
            self.assertFalse(candidate('054c', True))
            self.assertTrue(candidate('046d', False))
            (device/'id/bustype').write_text('0005')
            self.assertTrue(candidate('046d', False))
            (device/'id/bustype').write_text('0006')
            self.assertTrue(candidate('046d', False))
