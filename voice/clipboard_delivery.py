"""Serve one current draft on X11; never swap an older sentence back in.

GTK must process selection requests while Wine updates its clipboard cache and
while xdotool runs. After injection the process sleeps in the GLib event loop
until another clipboard owner takes over or the voice worker closes its pipe.
There is no clipboard history, disk storage, polling loop or paste retry.
"""
import subprocess
import time


class ClipboardDelivery:
    def __init__(self):
        import gi
        gi.require_version('Gtk', '3.0')
        gi.require_version('Gdk', '3.0')
        from gi.repository import Gdk, GLib, Gtk
        if not Gtk.init_check()[0]:
            raise RuntimeError('剪贴板无法连接当前游戏画面')
        self.gdk, self.glib = Gdk, GLib
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.display = self.clipboard.get_display()
        self.owner = None
        self.loop = None
        self.serving = False
        self.text = None
        self.failure = 'clipboard_changed'
        self.clipboard.connect('owner-change', self.owner_changed)

    def owns(self):
        return self.owner is not None and self.owner == self.gdk.selection_owner_get_for_display(
            self.display, self.gdk.SELECTION_CLIPBOARD)

    def owner_changed(self, *_):
        if self.serving and self.loop and not self.owns():
            self.loop.quit()

    def publish(self, text):
        self.text = text
        self.clipboard.set_text(text, -1)
        # Ensure ownership reached the X server before the separate xdotool
        # connection can inject Ctrl+V.
        self.display.sync()
        self.owner = self.gdk.selection_owner_get_for_display(self.display, self.gdk.SELECTION_CLIPBOARD)
        # Gamescope can already have taken ownership to relay this same text.
        # settle() validates the data; ownership alone is not a delivery guard.
        return True

    def matches(self):
        if self.text is None:
            return False
        if self.owns():
            return True
        loop = self.loop = self.glib.MainLoop()
        done = matched = False
        active = True
        self.failure = 'clipboard_timeout'

        def received(_clipboard, text, *_):
            nonlocal done, matched
            if not active:
                return  # Ignore callbacks arriving after the bounded read.
            done, matched = True, text == self.text
            self.failure = '' if matched else 'clipboard_changed'
            loop.quit()

        timer = self.glib.timeout_add(800, lambda: (loop.quit(), True)[1])
        try:
            self.clipboard.request_text(received, None)
            if not done:
                loop.run()
            return matched
        finally:
            active = False
            self.glib.source_remove(timer)
            self.loop = None

    def settle(self, milliseconds=250):
        """Let Wine receive ownership notifications and request the new formats."""
        self.loop = self.glib.MainLoop()
        timer = self.glib.timeout_add(milliseconds, lambda: (self.loop.quit(), True)[1])
        try:
            self.loop.run()
        finally:
            self.glib.source_remove(timer)
            self.loop = None
        return self.matches()

    def send_key(self, command, env, focus_guard=None):
        if not self.matches():
            return False
        # An asynchronous clipboard read can outlive a menu/focus change.
        if focus_guard is not None and not focus_guard():
            self.failure = 'focus_changed'
            return False
        # subprocess.run blocks GTK and can make the first paste time out.
        # Service requests concurrently; inject exactly one key sequence.
        self.failure = 'key_send'
        try:
            process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return False
        self.loop = self.glib.MainLoop()
        deadline = time.monotonic() + 1

        def check():
            if process.poll() is not None or time.monotonic() >= deadline:
                self.loop.quit()
            return True

        timer = self.glib.timeout_add(10, check)
        try:
            self.loop.run()
            sent = process.poll() == 0
        finally:
            self.glib.source_remove(timer)
            self.loop = None
            if process.poll() is None:
                process.kill()
            process.wait()
        return sent and self.matches()

    def serve(self, parent_fd):
        self.loop = self.glib.MainLoop()
        self.serving = True
        # EOF also handles a crashed/terminated worker, so no owner is orphaned.
        def parent_closed(*_):
            self.loop.quit()
            return True
        watch = self.glib.io_add_watch(parent_fd, self.glib.PRIORITY_DEFAULT,
                                      self.glib.IO_IN | self.glib.IO_HUP | self.glib.IO_ERR, parent_closed)
        try:
            if self.owns():
                self.loop.run()
        finally:
            self.glib.source_remove(watch)
            self.loop = None
            self.serving = False
