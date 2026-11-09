import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'voice'))
import game
import worker


class GameFocus(unittest.TestCase):
    def target(self, front, base, klass, focused='99', keyboard=False):
        def xcommand(display, *args):
            if '-root' in args:
                return f'GAMESCOPE_FOCUSED_WINDOW(CARDINAL) = 99\nGAMESCOPE_FOCUSED_APP(CARDINAL) = {front}\nGAMESCOPE_FOCUSED_APP_GFX(CARDINAL) = {base}\nGAMESCOPE_FOCUS_DISPLAY(CARDINAL) = 12602, 0\nGAMESCOPE_KEYBOARD_FOCUS_DISPLAY(CARDINAL) = 12602, 0'
            if args[0] == 'xdotool':
                return focused
            return f'WM_CLASS(STRING) = "{klass}"'
        with patch.dict('os.environ', DISPLAY=':0'), patch.object(game,'xcommand',xcommand), patch.object(game,'local_displays',return_value=[':1']):
            return game.focused_game(keyboard)

    def test_only_focused_game(self):
        self.assertEqual(self.target('123','123','Wow.exe'),(':1','99','123'))
        self.assertIsNone(self.target('769','123','Wow.exe'))
        self.assertIsNone(self.target('123','123','Battle.net.exe'))
        self.assertIsNone(self.target('123','123','Wow.exe','98'))


    def test_only_verified_keyboard_can_handoff_to_same_game(self):
        self.assertEqual(self.target('769','123','Wow.exe',focused='17',keyboard=True),(':1','99','123'))
        self.assertIsNone(self.target('769','123','Battle.net.exe',keyboard=True))
        self.assertIsNone(self.target('769','769','Wow.exe',keyboard=True))

class DraftGuard(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_game_focus_allows_audio_without_any_open_keyboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = worker.Session(Path(tmp))
            session.enabled = session.signed = True
            await session.update_ui('ui game')
            self.assertEqual(session.keyboard_until, 0)
            session.target = (':1','99','123')
            session.start_stream()
            session.capture = asyncio.create_task(asyncio.sleep(0, result=b'x'*10000))
            with patch.object(worker,'send'), patch.object(worker,'focused_game',return_value=session.target):
                await session.finish()
            self.assertIsNotNone(session.pending_id)
            commands=worker.json.loads((Path(tmp)/'command.json').read_text())['commands']
            self.assertEqual([cmd['action'] for cmd in commands], ['start','finish'])

    async def test_focus_change_drops_audio_before_cloud(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = worker.Session(Path(tmp))
            session.capture = asyncio.create_task(asyncio.sleep(0,result=b'0'*10000))
            session.target = (':1','99','123')
            await session.update_ui('ui game')
            with patch.object(worker,'send'),patch.object(worker,'focused_game',return_value=None):
                await session.finish()
            self.assertIsNone(session.pending_id)
            self.assertFalse((Path(tmp)/'command.json').exists())

    async def test_focus_change_drops_transcript_before_paste(self):
        session=worker.Session(Path('.'));session.enabled=True;session.signed=True;session.target=(':1','99','123')
        await session.update_ui('ui game')
        with patch.object(worker,'send'),patch.object(worker,'focused_game',return_value=None),patch('asyncio.create_subprocess_exec',new_callable=AsyncMock) as spawn:
            await session.paste('测试')
            spawn.assert_not_called()

    async def test_menu_cancels_audio_and_reopening_game_cannot_paste_old_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = worker.Session(Path(tmp))
            session.enabled = session.signed = True
            session.target = (':1','99','123')
            await session.update_ui('ui keyboard')
            self.assertGreater(session.keyboard_until, 0)
            session.pending_id = 2
            with patch.object(worker, 'send'), patch.object(worker, 'focused_game', return_value=session.target), \
                    patch('asyncio.create_subprocess_exec', new_callable=AsyncMock) as spawn:
                await session.update_ui('ui blocked')
                self.assertIsNone(session.pending_id)
                self.assertIn('cancel', (Path(tmp)/'command.json').read_text())
                await session.update_ui('ui game')
                self.assertEqual(session.keyboard_until, 0)
                await session.paste('旧草稿')
                spawn.assert_not_awaited()

    async def test_hidden_frontend_or_unknown_menu_cannot_start_recording(self):
        session = worker.Session(Path('.'))
        with patch.object(worker, 'focused_game', return_value=(':1','99','123')), \
                patch('asyncio.create_subprocess_exec', new_callable=AsyncMock) as spawn:
            await session.begin()
            spawn.assert_not_awaited()

    async def test_menu_opens_during_focus_check(self):
        session = worker.Session(Path('.'))
        await session.update_ui('ui game')
        target = session.target = (':1','99','123')
        async def open_menu(*args):
            await session.update_ui('ui blocked')
            return target
        with patch('asyncio.to_thread', side_effect=open_menu):
            self.assertFalse(await session.can_deliver(target, session.target_epoch))

class SessionLifetime(unittest.IsolatedAsyncioTestCase):
    async def test_signed_in_current_game_stays_connected_past_old_timeout(self):
        session = worker.Session(Path('.'))
        session.auth = 'signed'
        session.signed = True
        session.connect_until = 0
        session.enabled = True
        with patch.object(worker,'send'):
            task = asyncio.create_task(session.hotkey())
            await asyncio.sleep(.05)
            self.assertFalse(task.done())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_pause_cancels_pending_text_but_keeps_verified_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = worker.Session(Path(tmp))
            session.enabled = session.signed = True
            session.pending_id = 3
            await session.disarm()
            self.assertFalse(session.enabled)
            self.assertTrue(session.signed)
            self.assertIsNone(session.pending_id)
            self.assertIn('cancel',(Path(tmp)/'command.json').read_text())

    async def test_resume_does_not_restart_live_browser(self):
        from control import VoiceControl
        ctrl = VoiceControl(SimpleNamespace(pw_uid=2345))
        ctrl.state.update(running=True, signed=True, auth='signed')
        with patch.object(ctrl,'_stop',new_callable=AsyncMock) as stop:
            await ctrl.call('restore')
            await ctrl.call('refresh')
            stop.assert_not_awaited()
