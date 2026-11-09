import asyncio
import json
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root/'voice'))
from waveform import BAR_COUNT, DEFAULT_BAR, FRAME_BYTES, WaveMeter, bar_rect, bar_settings, error_label
from model import validate
from worker import Session
from test_control_safety import backend


def pcm(amplitude):
    return struct.pack('<hh', amplitude, -amplitude) * (FRAME_BYTES // 4)


class MeterTests(unittest.TestCase):
    def test_failure_labels_distinguish_connection_recognition_and_paste(self):
        for message,label in (
                ('语音服务连接超时，请检查网络后重试','连接超时'),
                ('语音服务没有返回结果，请检查网络后重试','识别超时'),
                ('没有收到完整的识别结果，请检查麦克风后重试','识别超时'),
                ('麦克风录到的是静音','未识别到声音'),
                ('文字未能填入','填入失败')):
            self.assertEqual(error_label(message),label)

    def test_silence_gentle_voice_and_loud_peak_follow_pcm(self):
        meter = WaveMeter()
        self.assertEqual(meter.feed(pcm(0)), [0]*BAR_COUNT)
        soft = meter.feed(pcm(600))[-1]
        loud = meter.feed(pcm(12000))[-1]
        self.assertTrue(0 < soft < loud <= 1)
        self.assertEqual(meter.feed(pcm(0))[-3:], [soft,loud,0])
        self.assertEqual(meter.feed(pcm(0)*BAR_COUNT), [0]*BAR_COUNT)

    def test_odd_pipe_boundaries_produce_same_waveform(self):
        audio = pcm(0)+pcm(1300)+pcm(4400)
        expected = WaveMeter().feed(audio)
        meter = WaveMeter()
        self.assertIsNone(meter.feed(audio[:71]))
        meter.feed(audio[71:1381])
        self.assertEqual(meter.feed(audio[1381:]), expected)

    def test_position_stays_on_screen_even_at_corners_and_after_resolution_change(self):
        for width,height in ((1280,800),(1920,1080),(640,480)):
            for x,y in ((0,0),(1,1),(0.3,0.78)):
                px,py,w,h = bar_rect(width,height,bar_settings({'x':x,'y':y}))
                self.assertEqual((px,py),(round((width-w)*x),round((height-h)*y)))
                self.assertLess(w,width/4)
                self.assertLessEqual(px+w,width)
                self.assertLessEqual(py+h,height)

    def test_old_settings_migrate_without_enabling_anything(self):
        config = validate({'version':2,'pluginEnabled':False,'voiceWanted':False,'voiceKey':'F11'})
        self.assertEqual(config['voiceBar'],DEFAULT_BAR)
        self.assertFalse(config['pluginEnabled'] or config['voiceWanted'])
        style = bar_settings({'x':-.3,'y':1.9,'opacity':0})
        self.assertEqual(style, {'x':0,'y':1,'opacity':.2})
        with self.assertRaises(ValueError): bar_settings({'x':float('nan')})
        self.assertEqual(validate({**config,'voiceBar':style})['voiceKey'],'F11')


class WaveLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_audio_stays_intact_and_child_gets_only_levels(self):
        session = Session(Path('.'))
        session.phase = 'recording'
        writer = Mock()
        writer.is_closing.return_value = False
        writer.transport.get_write_buffer_size.return_value = 0
        session.wave_window = SimpleNamespace(returncode=None,stdin=writer)
        data = pcm(900)+pcm(5000)
        reader = asyncio.StreamReader()
        reader.feed_data(data)
        reader.feed_eof()
        self.assertEqual(await session.read_audio(SimpleNamespace(stdout=reader)), data)
        values = json.loads(writer.write.call_args.args[0])
        self.assertEqual(values,WaveMeter().feed(data))
        self.assertEqual(len(values),BAR_COUNT)

    async def test_menu_cancels_recording_and_removes_wave_before_upload(self):
        session = Session(Path('.'))
        await session.update_ui('ui game')
        recorder = session.recorder = Mock(returncode=None, wait=AsyncMock(return_value=0))
        popup = session.wave_window = Mock(returncode=None, wait=AsyncMock(return_value=0))
        session.capture = asyncio.create_task(asyncio.sleep(0,result=pcm(1000)*8))
        with patch('worker.send'), patch('worker.command_file') as command:
            await session.update_ui('ui blocked')
        recorder.terminate.assert_called_once()
        popup.terminate.assert_called_once()
        popup.stdin.close.assert_called_once()
        self.assertIsNone(session.wave_window)
        command.assert_not_called()

    async def test_save_position_only_changes_style_and_does_not_start_voice(self):
        plugin=backend.Plugin()
        plugin.lock=asyncio.Lock()
        plugin.config=validate({'version':2,'pluginEnabled':True})
        plugin.stopping=False
        plugin.voice=Mock()
        plugin.persist=Mock()
        style={'x':.13,'y':.94,'opacity':.44}
        self.assertEqual(await plugin.set_voice_bar(style), style)
        self.assertEqual(validate(plugin.config)['voiceBar'], style)
        self.assertFalse(plugin.config['voiceWanted'])
        plugin.persist.assert_called_once()
        plugin.voice.call.assert_not_called()
        plugin.config['pluginEnabled']=False
        with self.assertRaises(ValueError):
            await plugin.set_voice_bar(DEFAULT_BAR)
