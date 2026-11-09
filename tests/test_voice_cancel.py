import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'voice'))
import worker
from model import validate


class VoiceCancel(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.s = worker.Session(Path(tmp.name))
        self.s.enabled = self.s.signed = self.s.accept_cancel = True
        self.s.ui_until = float('inf')
        self.s.auth = 'signed'
        self.s.target = (':1','42','123')
        sending = patch.object(worker,'send')
        sending.start()
        self.addCleanup(sending.stop)

    async def test_long_hold_requires_release_before_transcription(self):
        s=self.s
        s.physical_event(True, 1)
        s.advance_press(1.1)
        self.assertFalse(s.start_due)
        s.advance_press(1.3)
        self.assertTrue(s.start_due)
        s.recorder=Mock()
        s.physical_event(False, 1.5)
        self.assertTrue(s.finish_due and s.cancel_on_repress)

    def tap(self, start):
        self.s.physical_event(True,start)
        self.s.physical_event(False,start+.07)

    async def test_double_tap_only_clears_delivered_draft(self):
        s=self.s
        self.tap(1); self.tap(1.2)
        self.assertIsNone(s.clear_due)
        s.delivery=(s.target,0)
        self.tap(2)
        self.assertFalse(s.start_due or s.clear_due)
        self.tap(2.2)
        with patch.object(worker,'focused_game',return_value=s.target), patch.object(worker.game,'signal_clear_draft',return_value=True) as signal:
            await s.clear_draft()
            signal.assert_called_once_with(s.target,'F7')
            self.tap(3);self.tap(3.2)
            await s.clear_draft()
            signal.assert_called_once()

    async def test_new_hold_or_menu_invalidates_old_tap(self):
        s=self.s
        s.delivery=(s.target,0)
        self.tap(1)
        s.physical_event(True,1.2);s.advance_press(1.5)
        self.assertTrue(s.start_due)
        self.assertIsNone(s.delivery)
        s.physical_event(False,1.7)
        s.delivery=(s.target,0)
        self.tap(2); await s.update_ui('ui blocked')
        await s.update_ui('ui game'); self.tap(2.2)
        self.assertIsNone(s.clear_due)

    def test_mapped_pulse_plus_r5_hold_uses_physical_release(self):
        s=self.s
        s.key_edge(True,1,mapped=True)
        token=s.hold_token
        s.key_edge(False,1.02,mapped=True)
        s.r5_event(token,True,1.1)
        s.advance_press(1.3)
        self.assertTrue(s.start_due)
        s.recorder=Mock()
        s.r5_event(token,False,1.45)
        self.assertTrue(s.finish_due)

    def test_two_short_steam_pulses_between_polls_still_count_twice(self):
        s=self.s
        s.delivery=(s.target,0)
        s.keys=Mock()
        s.keys.pressed.return_value=set()
        s.keys.edges.side_effect=[[(1,True),(1.008,False)],[(1.18,True),(1.19,False)],[]]
        for now in (1.015,1.2,1.61):s.read_key(now)
        self.assertIs(s.clear_due,s.delivery)
        self.assertFalse(s.start_due)

    async def test_repress_invalidates_late_result_but_next_result_is_delivered(self):
        s = self.s
        s.cancel_on_repress = True
        s.pending_id = s.seq = 7
        self.tap(1)
        self.assertFalse(s.start_due)
        self.assertEqual(json.loads((s.folder/'command.json').read_text()),{'action':'cancel','seq':8})
        s.pending_id = s.seq = 9
        s.accept_cancel, s.discard_requested = True, False
        stream = asyncio.StreamReader()
        for seq,phrase in [(7,'已取消'),(9,'下一句')]:
            data=json.dumps(dict(auth='signed',seq=seq,result=dict(id=seq,text=phrase)))
            stream.feed_data(b'WDI:'+json.dumps(dict(kind='state',data=data)).encode()+b'\n')
        stream.feed_eof()
        s.browser=SimpleNamespace(stdout=stream)
        with patch.object(s,'paste',new_callable=AsyncMock) as paste:
            with self.assertRaisesRegex(RuntimeError,'已退出'):
                await s.browser_events()
            paste.assert_awaited_once_with('下一句')

    async def test_cancel_during_focus_wait_never_starts_paste_helper(self):
        s=self.s
        async def delayed_focus(*args):
            s.request_cancel()
            return False
        with patch.object(s,'can_deliver',side_effect=delayed_focus), patch('asyncio.create_subprocess_exec') as spawn:
            await s.paste('不要填入')
            spawn.assert_not_called()
        self.assertEqual(s.phase,'cancelled')

    async def test_cancel_while_paste_helper_prepares_never_commits(self):
        s = self.s
        s.cancel_on_repress = True
        child = SimpleNamespace(stdin=Mock(), stdout=Mock())
        child.stdin.drain = AsyncMock()
        async def becoming_ready():
            self.tap(1)
            return b'ready\n'
        child.stdout.readline = becoming_ready
        with patch.dict('os.environ', DISPLAY=':0'), patch.object(s, 'can_deliver', return_value=True), \
                patch('asyncio.create_subprocess_exec', return_value=child), patch.object(worker, 'terminate', new_callable=AsyncMock):
            await s.paste('本句不要')
        self.assertEqual(s.phase, 'cancelled')
        self.assertNotIn(b'commit\n', [call.args[0] for call in child.stdin.write.call_args_list])

    async def test_double_click_while_clipboard_is_still_serving_is_preserved(self):
        s=self.s
        child=SimpleNamespace(stdin=Mock(), stdout=Mock())
        child.stdin.drain=AsyncMock()
        child.stdout.readline=AsyncMock(side_effect=[b'ready\n', b'sent\n'])
        child.wait = AsyncMock()
        with patch.dict('os.environ', DISPLAY=':0'), patch.object(s, 'can_deliver',return_value=True), \
                patch('asyncio.create_subprocess_exec',return_value=child), patch.object(worker, 'terminate',new_callable=AsyncMock):
            await s.paste('语音草稿')
        self.assertEqual(s.phase, 'done')
        self.assertIs(s.clipboard, child)
        child.wait.assert_not_awaited()
        child.stdin.close.assert_not_called()
        self.tap(1);self.tap(1.2)
        self.assertIsNotNone(s.clear_due)
        self.assertIs(s.clear_due, s.delivery)

    async def test_next_paste_retires_only_previous_owner_after_new_key_is_sent(self):
        s = self.s
        old = s.clipboard = SimpleNamespace(stdin=Mock())
        child = SimpleNamespace(stdin=Mock(), stdout=Mock())
        child.stdin.drain = AsyncMock()
        child.stdout.readline = AsyncMock(side_effect=[b'ready\n', b'sent\n'])
        async def retire(process):
            self.assertIs(process, old)
            self.assertIs(s.clipboard, child)
            self.assertEqual(s.phase, 'done')
        with patch.dict('os.environ', DISPLAY=':0'), patch.object(s, 'can_deliver', return_value=True), \
                patch('asyncio.create_subprocess_exec', return_value=child), patch.object(worker, 'terminate', side_effect=retire):
            await s.paste('下一句')
        old.stdin.close.assert_called_once()
        child.stdin.close.assert_not_called()

    async def test_failed_helper_cannot_arm_clear_or_retry_paste(self):
        s = self.s
        child = SimpleNamespace(stdin=Mock(), stdout=Mock())
        child.stdin.drain = AsyncMock()
        child.stdout.readline = AsyncMock(side_effect=[b'ready\n', b''])
        with patch.dict('os.environ', DISPLAY=':0'), patch.object(s, 'can_deliver', return_value=True), \
                patch('asyncio.create_subprocess_exec', return_value=child) as spawn, \
                patch.object(worker, 'terminate', new_callable=AsyncMock):
            await s.paste('本句')
        spawn.assert_awaited_once()
        self.assertIsNone(s.clipboard)
        self.assertIsNone(s.delivery)
        self.assertEqual(s.phase, 'error')
        child.stdin.close.assert_called_once()

    async def test_clipboard_failure_does_not_blame_chat_focus(self):
        s=self.s
        child=SimpleNamespace(stdin=Mock(),stdout=Mock())
        child.stdin.drain=AsyncMock()
        child.stdout.readline=AsyncMock(side_effect=[b'ready\n',b'error:clipboard_timeout\n'])
        with patch.dict('os.environ',DISPLAY=':0'),patch.object(s,'can_deliver',return_value=True), \
                patch('asyncio.create_subprocess_exec',return_value=child), \
                patch.object(worker,'terminate',new_callable=AsyncMock):
            await s.paste('本句')
        self.assertIn('剪贴板读取超时',s.credit)
        self.assertNotIn('选中',s.credit)
        self.assertIsNone(s.delivery)

    async def test_disable_closes_retained_clipboard_owner(self):
        s = self.s
        child = s.clipboard = SimpleNamespace(stdin=Mock())
        with patch.object(worker, 'terminate', new_callable=AsyncMock) as terminate:
            await s.disarm()
            terminate.assert_awaited_once_with(child)
        self.assertIsNone(s.clipboard)
        child.stdin.close.assert_called_once()

    async def test_real_helper_pipes_keep_one_owner_and_close_on_disable(self):
        # Actual child process/pipe lifecycle, without GTK, game keys or audio.
        s = self.s
        spawn = asyncio.create_subprocess_exec
        children = []
        async def fake_owner(*args, **kwargs):
            program = "import sys; sys.stdin.readline(); print('ready',flush=True); sys.stdin.readline(); print('sent',flush=True); sys.stdin.read()"
            process = await spawn(sys.executable, '-c', program, stdin=asyncio.subprocess.PIPE,
                                  stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            children.append(process)
            return process
        try:
            with patch.dict('os.environ', DISPLAY=':0'), patch.object(s, 'can_deliver', return_value=True), \
                    patch('asyncio.create_subprocess_exec', side_effect=fake_owner):
                await s.paste('第一句')
                self.assertIsNone(children[0].returncode)
                await s.paste('第二句')
                self.assertIsNotNone(children[0].returncode)
                self.assertIsNone(children[1].returncode)
                await s.disarm()
                self.assertIsNotNone(children[1].returncode)
        finally:
            for child in children:
                child.stdin.close()
                await worker.terminate(child)

    def test_idle_or_already_pasted_is_untouched(self):
        s=self.s
        s.status('已填入','done')
        with patch.object(worker,'command_file') as command:
            s.request_cancel()
            command.assert_not_called()
            self.assertEqual(s.phase,'done')

    def test_upgrade_keeps_switches_and_explicit_keys(self):
        old = {'version':2,'voiceKey':'F7','voiceCancelKey':'F6','pluginEnabled':True,'voiceWanted':True}
        upgraded=validate(old)
        self.assertEqual(upgraded['voiceKey'],'F7')
        self.assertTrue(upgraded['voiceWanted'] and upgraded['pluginEnabled'])
        self.assertNotIn('voiceCancelKey',upgraded)
        self.assertEqual(validate({**old,'wake':{'key':63,'mods':['Ctrl']}})['voiceKey'],'F7')
        self.assertEqual(validate({**old,'voiceKey':'F11'})['voiceKey'],'F11')
        preview = {**old,'version':3,'voiceKey':'F5'}
        self.assertEqual(validate(preview)['voiceKey'],'F7')
        self.assertEqual(validate({**preview,'wake':{'key':65,'mods':['Ctrl']}})['voiceKey'],'F5')
        self.assertEqual(validate({**upgraded,'voiceKey':'F5'})['voiceKey'],'F5')
