import asyncio
import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'voice'))
import worker


class VoiceStream(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.s=worker.Session(Path(tmp.name))
        self.s.enabled=self.s.signed=True
        self.s.target=(':1','42','123');self.s.ui_until=float('inf')
        patcher=patch.object(worker,'send');patcher.start();self.addCleanup(patcher.stop)

    def commands(self):
        value=json.loads((self.s.folder/'command.json').read_text())
        return value.get('commands',[value])

    async def test_audio_reaches_bridge_before_release_and_finish_never_resends_it(self):
        s=self.s;s.start_stream();job=s.pending_id
        stream=asyncio.StreamReader()
        capture=asyncio.create_task(s.read_audio(SimpleNamespace(stdout=stream)))
        audio=b'\x10\x01'*4000
        stream.feed_data(audio);await asyncio.sleep(0)
        self.assertFalse(capture.done(),'recording has not ended')
        messages=self.commands()
        self.assertEqual([m['action'] for m in messages],['start','chunk'])
        self.assertEqual(base64.b64decode(messages[1]['audio']),audio)
        self.assertEqual(messages[1]['id'],job)
        s.acknowledge(messages[-1]['seq'])
        self.assertNotIn('audio',(s.folder/'command.json').read_text())
        stream.feed_eof();s.capture=capture
        with patch.object(s,'can_deliver',return_value=True):await s.finish()
        self.assertEqual(self.commands(),[{'seq':s.seq,'action':'finish','id':job}])

    def test_slow_browser_ack_cannot_drop_newer_chunks(self):
        s=self.s;s.start_stream();job=s.pending_id
        s.issue('chunk',id=job,audio='AQI=');one=s.seq
        s.issue('chunk',id=job,audio='AwQ=');two=s.seq
        s.acknowledge(one)
        self.assertEqual(self.commands(),[{'seq':two,'action':'chunk','id':job,'audio':'AwQ='}])
        for stale in (one,one-1,None,s.seq+10):s.acknowledge(stale)
        self.assertEqual(self.commands()[0]['seq'],two)

    def test_cancel_removes_all_unsent_audio_and_late_ack_preserves_next_session(self):
        s=self.s;s.start_stream();previous=s.pending_id
        s.issue('chunk',id=previous,audio='AQI=');old_ack=s.seq
        s.cancel_stream()
        self.assertEqual([m['action'] for m in self.commands()],['cancel'])
        s.start_stream();s.acknowledge(old_ack)
        self.assertNotEqual(s.pending_id,previous)
        self.assertEqual([m['action'] for m in self.commands()],['cancel','start'])

    async def test_menu_stops_forwarding_before_recorder_is_drained(self):
        s=self.s;s.start_stream();s.ui_until=0
        stream=asyncio.StreamReader();stream.feed_data(b'\x10\x01'*4000);stream.feed_eof()
        await s.read_audio(SimpleNamespace(stdout=stream))
        self.assertEqual([m['action'] for m in self.commands()],['start'])

    async def test_discard_cancels_before_waiting_for_capture(self):
        s=self.s;s.start_stream()
        s.recorder=Mock(returncode=None,wait=AsyncMock(return_value=0))
        async def draining():
            self.assertIsNone(s.pending_id)
            self.assertEqual(self.commands()[0]['action'],'cancel')
            return b'\x10\x01'*4000
        s.capture=asyncio.create_task(draining())
        await s.finish(discard=True)
        self.assertIsNone(s.pending_id)

    async def test_connection_failure_during_recording_stops_capture_without_paste(self):
        s=self.s;s.auth='signed';s.start_stream();job=s.pending_id
        s.recorder=Mock(returncode=None,wait=AsyncMock(return_value=0))
        s.capture=asyncio.create_task(asyncio.sleep(0,result=b'\x10\x01'*4000))
        reader=asyncio.StreamReader()
        state=dict(auth='signed',seq=s.seq,result=dict(id=job,text='',error='语音服务连接超时',stats={'total_ms':5000,'text':'private'}))
        reader.feed_data(b'WDI:'+json.dumps(dict(kind='state',data=json.dumps(state))).encode()+b'\n');reader.feed_eof()
        s.browser=SimpleNamespace(stdout=reader)
        with patch.object(s,'paste',new_callable=AsyncMock) as paste:
            with self.assertRaisesRegex(RuntimeError,'已退出'):await s.browser_events()
        paste.assert_not_awaited()
        self.assertIsNone(s.recorder)
        self.assertEqual(s.credit,'语音服务连接超时')
        self.assertEqual(s.diagnostics,{'total_ms':5000})
