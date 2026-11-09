"""Deterministic X11/GTK scheduling simulation; no host clipboard or game access."""
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'voice'))
import game
from clipboard_delivery import ClipboardDelivery


class Scheduler:
    PRIORITY_DEFAULT, IO_IN, IO_HUP, IO_ERR = 0, 1, 2, 4

    def __init__(self):
        self.now, self.serial = 0, 0
        self.events = {}
        self.watch = None

    def timeout_add(self, ms, callback):
        self.serial += 1
        self.events[self.serial] = (self.now + ms, ms, callback)
        return self.serial

    def source_remove(self, token):
        self.events.pop(token, None)

    def io_add_watch(self, fd, priority, flags, callback):
        self.watch = callback
        return -1

    def MainLoop(self):
        stopped = False
        def quit():
            nonlocal stopped
            stopped = True
        def run():
            nonlocal stopped
            stopped = False
            while not stopped:
                if not self.events:
                    raise AssertionError('unexpected unbounded event loop')
                token = min(self.events, key=lambda t:self.events[t][0])
                self.now, ms, callback = self.events.pop(token)
                if callback():
                    self.events[token] = (self.now + ms, ms, callback)
        return SimpleNamespace(run=run, quit=quit)


class ClipboardTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = Scheduler()
        self.owner, self.text = None, '上次的话'
        self.trace = []
        self.display = SimpleNamespace(sync=lambda:self.trace.append('sync'))
        self.gdk = SimpleNamespace(SELECTION_CLIPBOARD='CLIPBOARD',
            selection_owner_get_for_display=lambda *_: self.owner)

    def backend(self):
        identity = object()
        callbacks = []
        def set_text(text, length):
            self.owner, self.text = identity, text
            self.trace.append('publish')
        clip = SimpleNamespace(get_display=lambda:self.display, set_text=set_text,
                               connect=lambda name, cb:callbacks.append(cb),
                               request_text=lambda cb,data:self.scheduler.timeout_add(1,lambda:cb(clip,self.text,data)))
        gtk = SimpleNamespace(init_check=lambda:(True, []), Clipboard=SimpleNamespace(get=lambda _:clip))
        gi = SimpleNamespace(require_version=lambda *_:None)
        repo = SimpleNamespace(Gdk=self.gdk, GLib=self.scheduler, Gtk=gtk)
        with patch.dict(sys.modules, {'gi':gi, 'gi.repository':repo}):
            return ClipboardDelivery(), callbacks

    def test_first_paste_syncs_and_serves_while_key_sender_is_waiting(self):
        delivery, _ = self.backend()
        self.assertTrue(delivery.publish('第一句'))
        self.assertEqual(self.trace, ['publish','sync'])
        reads = []
        self.scheduler.timeout_add(70, lambda:reads.append(self.text))
        self.assertTrue(delivery.settle())
        self.assertEqual(reads,['第一句'])
        # Model a key sender that cannot finish until Wine reads the selection.
        process = Mock()
        process.poll.side_effect = lambda:0 if len(reads) == 2 else None
        self.scheduler.timeout_add(20, lambda:reads.append(self.text))
        with patch('clipboard_delivery.subprocess.Popen', return_value=process) as launch:
            self.assertTrue(delivery.send_key(['xdotool','key','ctrl+v'], {}))
        launch.assert_called_once()
        process.kill.assert_not_called()
        self.assertEqual(reads,['第一句','第一句'])

    def test_slow_readers_still_get_current_text_and_next_owner_wins(self):
        first, first_callbacks = self.backend()
        second, _ = self.backend()
        first.publish('第一句')
        reads = []
        for delay in (600, 2100):
            self.scheduler.timeout_add(delay, lambda:reads.append(self.text))
        def replace():
            second.publish('第二句')
            first_callbacks[0]()
        self.scheduler.timeout_add(2500, replace)
        first.serve(0)
        self.assertEqual(reads,['第一句','第一句'])
        self.assertEqual(self.text,'第二句')
        self.assertFalse(first.owns())
        self.assertTrue(second.owns())
        # The previous owner neither restores its text nor clears the new one.
        self.assertFalse(first.settle())
        self.assertEqual(self.text,'第二句')

    def test_user_copy_is_not_overwritten_and_no_key_is_sent(self):
        delivery, callbacks = self.backend()
        delivery.publish('听写')
        def copy_elsewhere():
            self.owner, self.text = object(), '用户复制的内容'
            callbacks[0]()
        self.scheduler.timeout_add(100, copy_elsewhere)
        self.assertFalse(delivery.settle())
        with patch('clipboard_delivery.subprocess.Popen') as launch:
            self.assertFalse(delivery.send_key(['xdotool'], {}))
        launch.assert_not_called()
        self.assertEqual(self.text,'用户复制的内容')

    def test_gamescope_takes_ownership_with_identical_text_and_paste_is_allowed(self):
        delivery, callbacks = self.backend()
        delivery.publish('当前一句')
        def relay():
            self.owner=object()  # Gamescope owns the same bytes now.
            callbacks[0]()
        self.scheduler.timeout_add(20,relay)
        self.assertTrue(delivery.settle())
        self.assertFalse(delivery.owns())
        process=Mock();process.poll.return_value=0
        with patch('clipboard_delivery.subprocess.Popen',return_value=process) as launch:
            self.assertTrue(delivery.send_key(['xdotool','key','ctrl+v'],{}))
        launch.assert_called_once()
        self.assertEqual(self.text,'当前一句')
        delivery.serve(0)  # Relay keeps the data; no original owner needs to linger.

    def test_owner_may_change_during_the_key_without_aborting_a_valid_paste(self):
        delivery, callbacks = self.backend()
        delivery.publish('交接期间')
        def relay():
            self.owner=object();callbacks[0]()
        self.scheduler.timeout_add(5,relay)
        process=Mock();process.poll.return_value=0
        with patch('clipboard_delivery.subprocess.Popen',return_value=process):
            self.assertTrue(delivery.send_key(['xdotool'],{}))

    def test_unresponsive_owner_times_out_and_late_reply_cannot_authorize_paste(self):
        delivery, _ = self.backend();delivery.publish('本句')
        self.owner=object()
        callbacks=[]
        delivery.clipboard.request_text=lambda cb,data:callbacks.append(cb)
        with patch('clipboard_delivery.subprocess.Popen') as launch:
            self.assertFalse(delivery.send_key(['xdotool'],{}))
        launch.assert_not_called()
        self.assertEqual(delivery.failure,'clipboard_timeout')
        callbacks[0](delivery.clipboard,'本句',None)
        self.assertEqual(delivery.failure,'clipboard_timeout')

    def test_focus_is_rechecked_after_reading_relayed_clipboard(self):
        delivery, _ = self.backend();delivery.publish('本句');self.owner=object()
        order=[]
        def read(callback,data):
            def returned():
                order.append('read');callback(delivery.clipboard,self.text,data)
            self.scheduler.timeout_add(1,returned)
        delivery.clipboard.request_text=read
        def focus():
            order.append('focus');return False
        with patch('clipboard_delivery.subprocess.Popen') as launch:
            self.assertFalse(delivery.send_key(['xdotool'],{},focus))
        self.assertEqual(order,['read','focus'])
        launch.assert_not_called()
        self.assertEqual(delivery.failure,'focus_changed')

    def test_parent_pipe_closure_wakes_idle_owner_without_polling(self):
        delivery, _ = self.backend()
        delivery.publish('本句')
        self.scheduler.timeout_add(1000, lambda:self.scheduler.watch())
        delivery.serve(0)
        # Only the simulated pipe event was scheduled; serve installs no timer.
        self.assertEqual(self.scheduler.serial, 1)


class PasteOrdering(unittest.TestCase):
    target = (':1','42','123')

    def test_cold_clipboard_is_ready_before_companion_ticket_and_single_paste(self):
        clip = Mock()
        events = []
        clip.publish.side_effect = lambda text:events.append(('publish',text)) or True
        clip.settle.side_effect = lambda *args:events.append(('settle',)) or True
        clip.send_key.side_effect = lambda *args:events.append(('key',)) or True
        stream = SimpleNamespace(buffer=io.BytesIO(b'commit\n'),fileno=lambda:0)
        with patch('clipboard_delivery.ClipboardDelivery',return_value=clip), \
                patch.object(game,'focused_game',return_value=self.target), \
                patch.object(game,'draft_signal',side_effect=lambda *a,**k:events.append(('ticket',))), \
                patch.object(sys,'stdin',stream), patch.object(sys,'stdout',io.StringIO()) as output:
            self.assertTrue(game.paste_draft(self.target,'这句\n是新的',guarded=True))
        self.assertEqual(events,[('publish','这句 是新的'),('settle',),('ticket',),('key',)])
        self.assertEqual(output.getvalue(),'ready\nsent\n')
        clip.serve.assert_called_once_with(0)

    def test_cancel_before_commit_never_publishes_or_pastes(self):
        clip = Mock()
        stream = SimpleNamespace(buffer=io.BytesIO(b''))
        with patch('clipboard_delivery.ClipboardDelivery',return_value=clip), \
                patch.object(game,'focused_game',return_value=self.target), \
                patch.object(sys,'stdin',stream), patch.object(sys,'stdout',io.StringIO()):
            self.assertFalse(game.paste_draft(self.target,'已取消',guarded=True))
        clip.publish.assert_not_called()
        clip.send_key.assert_not_called()

    def test_focus_change_while_clipboard_prepares_does_not_inject(self):
        clip = Mock()
        with patch('clipboard_delivery.ClipboardDelivery',return_value=clip), \
                patch.object(game,'focused_game',side_effect=[self.target,self.target,None]):
            self.assertFalse(game.paste_draft(self.target,'本句'))
        clip.send_key.assert_not_called()
