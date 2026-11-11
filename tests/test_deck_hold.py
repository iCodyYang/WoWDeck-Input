"""Replay Deck HID reports through a real nonblocking pipe and the F7 state machine."""
import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from voice import deck_hold

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'voice'))
import worker


def report(*buttons):
    # Independently transcribed from upstream hid-steam.c's Deck packet table.
    positions = {'L4': (13, 1), 'L5': (9, 7), 'R4': (13, 2), 'R5': (10, 0),
                 'A': (8, 7), 'Steam': (9, 5), 'QAM': (14, 2), 'touch': (10, 4)}
    data = bytearray(64)
    data[:3] = b'\x01\x00\x09'
    for button in buttons:
        offset, bit = positions[button]
        data[offset] |= 1 << bit
    return b'report (size 64) (unnumbered) = ' + data.hex(' ').encode() + b'\n'


class Reports(unittest.TestCase):
    def test_four_distinct_grips_and_no_game_or_menu_buttons(self):
        for button in ('L4', 'L5', 'R4', 'R5'):
            with self.subTest(button=button):
                self.assertEqual(deck_hold.back_buttons(report(button, 'A', 'touch')), {button})
        self.assertEqual(deck_hold.back_buttons(report('Steam', 'QAM', 'A')), set())
        self.assertEqual(deck_hold.back_buttons(report('L4', 'R5')), {'L4', 'R5'})

    def test_bad_or_unrelated_packets_are_not_releases(self):
        for line in (b'noise', b'report (size 64) (unnumbered) = xx',
                     report('R5').replace(b'01 00 09', b'01 00 04'),
                     report('R5')[:-10], report('R5').replace(b'size 64', b'size 63')):
            self.assertIsNone(deck_hold.back_buttons(line))


class HoldReplay(unittest.IsolatedAsyncioTestCase):
    async def replay(self, chunks, relay=None):
        reader, writer = os.pipe()
        os.set_blocking(reader, False)
        messages = []
        def signal(message):
            messages.append(message)
            if relay:
                relay(message)
        try:
            with patch.object(deck_hold, 'report_stream', return_value=Path('/test-events')), \
                    patch.object(deck_hold.os, 'open', return_value=reader) as opened:
                task = asyncio.create_task(deck_hold.observe_press(7, signal))
                try:
                    for chunk in chunks:
                        os.write(writer, chunk)
                        await asyncio.sleep(.025)
                    os.close(writer)
                    writer = None
                    await asyncio.wait_for(task, 1)
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                opened.assert_called_once_with(Path('/test-events'), os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        finally:
            if writer is not None:
                os.close(writer)
        with self.assertRaises(OSError):
            os.fstat(reader)  # Observer owns and closes its reader on every exit.
        return messages

    async def test_all_four_grips_keep_a_pulsed_f7_recording_until_real_release(self):
        for button in ('L4', 'L5', 'R4', 'R5'):
            with self.subTest(button=button), tempfile.TemporaryDirectory() as folder, patch.object(worker, 'send'):
                session = worker.Session(Path(folder))
                session.enabled = session.signed = True
                session.ui_until = float('inf')
                session.press_number = 6
                start = time.monotonic()
                session.key_edge(True, start, mapped=True)
                session.key_edge(False, start + .01, mapped=True)
                def relay(message):
                    _, token, state = message.split()
                    self.assertNotEqual(state, 'lost')
                    session.back_hold_event(int(token), state == '1', time.monotonic())
                    if state == '1':
                        session.advance_press(start + .30)
                        self.assertTrue(session.start_due)
                        self.assertFalse(session.finish_due)
                        session.recorder = Mock(returncode=None)
                messages = await self.replay([report(button), report(button, 'A'), report()], relay)
                self.assertEqual(messages, ['hold 7 1', 'hold 7 0'])
                self.assertTrue(session.finish_due)
                self.assertFalse(session.discard_requested)

    async def test_other_back_button_cannot_extend_recording_after_trigger_is_released(self):
        messages = await self.replay([report('L4'), report('L4', 'R5'), report('R5')])
        self.assertEqual(messages, ['hold 7 1', 'hold 7 0'])

    async def test_ambiguous_or_missing_grip_is_not_guessed(self):
        for first in (report(), report('L4', 'R5'), report('A', 'Steam', 'QAM')):
            with self.subTest(first=first):
                self.assertEqual(await self.replay([first]), [])

    async def test_fragmented_reports_and_unrelated_frames_do_not_end_hold(self):
        down = report('R4')
        messages = await self.replay([down[:70], down[70:] + b'unrelated frame\n', report()])
        self.assertEqual(messages, ['hold 7 1', 'hold 7 0'])

    async def test_press_and_release_in_one_read_still_delivers_both_edges(self):
        self.assertEqual(await self.replay([report('L5') + report()]), ['hold 7 1', 'hold 7 0'])

    async def test_device_eof_is_loss_not_release(self):
        self.assertEqual(await self.replay([report('R5')]), ['hold 7 1', 'hold 7 lost'])

    async def test_unavailable_debug_stream_never_opens_controller(self):
        with patch.object(deck_hold, 'report_stream', return_value=None), patch.object(deck_hold.os, 'open') as opened:
            await deck_hold.observe_press(7, Mock())
            opened.assert_not_called()

    async def test_cancelled_observer_closes_without_sending_a_release(self):
        reader, writer = os.pipe()
        os.set_blocking(reader, False)
        seen = asyncio.Event()
        messages = []
        def signal(message):
            messages.append(message)
            seen.set()
        try:
            os.write(writer, report('L4'))
            with patch.object(deck_hold, 'report_stream', return_value=Path('/test-events')), \
                    patch.object(deck_hold.os, 'open', return_value=reader):
                task = asyncio.create_task(deck_hold.observe_press(7, signal))
                try:
                    await asyncio.wait_for(seen.wait(), 1)
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            self.assertEqual(messages, ['hold 7 1'])
            with self.assertRaises(OSError):
                os.fstat(reader)
        finally:
            os.close(writer)
