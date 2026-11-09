"""User-session function key detection and guarded WoW draft insertion."""
import ctypes
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def xcommand(display, *args):
    try:
        return subprocess.check_output(args, env=dict(os.environ, DISPLAY=display),
                                       stderr=subprocess.DEVNULL, timeout=1, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def is_wow_class(properties):
    return any(name.casefold() in {'wow.exe', 'wowclassic.exe', 'wowclassict.exe',
                                   'world of warcraft', 'world of warcraft: forever'}
               for name in re.findall(r'"([^"]+)"', properties))


WOW_PROCESSES = {'wow.exe', 'wowclassic.exe', 'wowclassict.exe'}


def wow_pid(pid, uid=None):
    try:
        entry = Path('/proc', str(int(pid)))
        return entry.stat().st_uid == (os.geteuid() if uid is None else uid) and (entry/'comm').read_text().strip().casefold() in WOW_PROCESSES
    except (OSError, ValueError):
        return False


def display_property(properties, key):
    match = re.search(r'^' + key + r'\(CARDINAL\) = (\d+)', properties, re.MULTILINE)
    if not match:
        return None
    value = int(match.group(1))
    if value > 0xffffffff:
        return None
    name = value.to_bytes(4, sys.byteorder).split(b'\0', 1)[0].decode('ascii', 'ignore')
    return name if re.fullmatch(r':\d+', name) else None


def focused_game(allow_keyboard=False):
    # Gamescope's primary root publishes the base window and foreground app.
    root = os.environ.get('WDI_ROOT_DISPLAY') or os.environ.get('DISPLAY')
    if not root:
        return None
    props = xcommand(root, 'xprop', '-root', 'GAMESCOPE_FOCUSED_WINDOW',
                     'GAMESCOPE_FOCUSED_APP', 'GAMESCOPE_FOCUSED_APP_GFX',
                     'GAMESCOPE_FOCUS_DISPLAY', 'GAMESCOPE_KEYBOARD_FOCUS_DISPLAY')
    values = dict(re.findall(r'(GAMESCOPE_\w+)\(CARDINAL\) = (\d+)', props))
    app = values.get('GAMESCOPE_FOCUSED_APP')
    win = values.get('GAMESCOPE_FOCUSED_WINDOW')
    base = values.get('GAMESCOPE_FOCUSED_APP_GFX')
    keyboard_overlay = allow_keyboard and app == '769'
    if not win or win == '0' or base in {None, '0', '769'} or (app != base and not keyboard_overlay):
        return None
    display = display_property(props, 'GAMESCOPE_FOCUS_DISPLAY')
    if not display:
        return None
    if not keyboard_overlay:
        if display != display_property(props, 'GAMESCOPE_KEYBOARD_FOCUS_DISPLAY'):
            return None
        if xcommand(display, 'xdotool', 'getwindowfocus') != win:
            return None
    identity = xcommand(display, 'xprop', '-id', win, 'WM_CLASS', '_NET_WM_PID', 'STEAM_GAME')
    pid = re.search(r'_NET_WM_PID\(CARDINAL\) = (\d+)', identity)
    classes = {name.casefold() for name in re.findall(r'"([^"]+)"', identity)}
    if classes & {'steam', 'steamwebhelper', 'steamwebhelper.exe', 'battle.net.exe', 'explorer.exe', 'wowdeckvoicewave'}:
        return None
    tagged = re.search(r'^STEAM_GAME\(CARDINAL\) = (\d+)', identity, re.MULTILINE)
    if is_wow_class(identity) or (pid and wow_pid(pid.group(1))) or (classes and tagged and tagged.group(1) == base):
        return (display, win, base)
    return None


def local_displays():
    return sorted(':' + p.name[1:] for p in Path('/tmp/.X11-unix').glob('X*') if p.name[1:].isdigit())


def wave_has_focus(display):
    win = xcommand(display, 'xdotool', 'getwindowfocus')
    if not win.isdecimal(): return False
    return '"WowDeckVoiceWave"' in xcommand(display, 'xprop', '-id', win, 'WM_CLASS')


FUNCTION_KEYS = tuple(f'F{i}' for i in range(1, 13))


class VoiceKey:
    """Query only supported function-key bits; never grab a keyboard."""
    def __init__(self, names, watch_edges=False):
        if not names or any(name not in FUNCTION_KEYS for name in names):
            raise ValueError('请选择 F1 至 F12')
        self.x = ctypes.CDLL('libX11.so.6')
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.x.XStringToKeysym.argtypes = [ctypes.c_char_p]
        self.x.XStringToKeysym.restype = ctypes.c_ulong
        self.x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.x.XKeysymToKeycode.restype = ctypes.c_ubyte
        self.x.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.handles = {}
        self.names = names
        self.refresh_after = 0
        self.stream = None
        self.edge_display = None
        if watch_edges:
            try:
                from xedges import EdgeStream
                self.stream = EdgeStream(self.x)
            except (OSError, AttributeError):
                pass  # Keep keymap polling when XInput2 is unavailable.
        self.refresh()

    def refresh(self):
        self.refresh_after = time.monotonic() + 2
        for display in local_displays():
            if display in self.handles: continue
            handle = self.x.XOpenDisplay(display.encode())
            if handle:
                codes = {name:self.x.XKeysymToKeycode(handle, self.x.XStringToKeysym(name.encode())) for name in self.names}
                self.handles[display] = (handle, codes)
        if self.stream:
            root = os.environ.get('DISPLAY')
            props = xcommand(root, 'xprop', '-root', 'GAMESCOPE_FOCUS_DISPLAY') if root else ''
            display = display_property(props, 'GAMESCOPE_FOCUS_DISPLAY')
            if display != self.edge_display and display in self.handles:
                handle, codes = self.handles[display]
                self.stream.attach(handle)
                self.stream.read(handle, codes[self.names[0]])  # discard old edges on a focus change
            self.edge_display = display

    def edges(self, now):
        if not self.stream or self.edge_display not in self.handles:
            return []
        handle, codes = self.handles[self.edge_display]
        records = self.stream.read(handle, codes[self.names[0]])
        if not records:
            return []
        last = records[-1][0]
        return [(now - ((last - stamp) & 0xffffffff) / 1000, down) for stamp, down in records]

    def pressed(self):
        if time.monotonic() >= self.refresh_after: self.refresh()
        bits = (ctypes.c_ubyte * 32)()
        down = set()
        for handle, codes in self.handles.values():
            self.x.XQueryKeymap(handle, bits)
            down.update(name for name, code in codes.items() if code and bits[code // 8] & (1 << (code % 8)))
        return down

    def close(self):
        for handle, _ in self.handles.values():
            self.x.XCloseDisplay(handle)
        self.handles.clear()


def detect_function_key():
    keys = VoiceKey(FUNCTION_KEYS)
    try:
        before = keys.pressed()
        end = time.monotonic() + 20
        while time.monotonic() < end:
            down = keys.pressed()
            if len(down) == 1 and not before:
                return next(iter(down))
            before = down
            time.sleep(.02)
        return ''
    finally:
        keys.close()


def draft_component_ready(target):
    """Verify this window is WoW and its running client has the matching component."""
    if focused_game() != target:
        return False
    props = xcommand(target[0], 'xprop', '-id', target[1], 'WM_CLASS', '_NET_WM_PID')
    pid = re.search(r'_NET_WM_PID\(CARDINAL\) = (\d+)', props)
    if not (is_wow_class(props) or (pid and wow_pid(pid.group(1)))):
        return False
    from draft_install import BUNDLE, FILES, NAME, running_client
    try:
        directory = running_client() / 'Interface' / 'AddOns' / NAME
        for name in FILES:
            local = BUNDLE / name
            installed = directory / name
            if (not installed.is_file() or installed.stat().st_size != local.stat().st_size
                    or installed.read_bytes() != local.read_bytes()):
                return False
        return True
    except (OSError, ValueError):
        return False


def draft_signal(target, key, prepare):
    # Pick a standard existing function key other than the user's voice trigger.
    # No keymap changes, clipboard commands, focus transfer, Delete or Enter.
    if not draft_component_ready(target) or focused_game() != target:
        return False
    fn = 'F10' if key == 'F11' else 'F11'
    chord = ('ctrl+shift+' if prepare else 'alt+shift+') + fn
    try:
        subprocess.run(['xdotool', 'key', '--clearmodifiers', chord], check=True, timeout=1,
                       env=dict(os.environ, DISPLAY=target[0]), stderr=subprocess.DEVNULL)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def signal_clear_draft(target, key='F7'):
    return draft_signal(target, key, prepare=False)


def paste_draft(target, text, key='F7', guarded=False):
    from clipboard_delivery import ClipboardDelivery
    def reject(code):
        if guarded: print('error:' + code, flush=True)
        return False
    text = ' '.join(text.split()).strip()  # single chat draft, no Return or control sequence
    if not text or len(text) > 1500:
        return reject('invalid_text')
    if focused_game() != target:
        return reject('focus_changed')
    try:
        clipboard = ClipboardDelivery()
    except (ImportError, ValueError, RuntimeError):
        return reject('clipboard_init')
    if guarded:
        print('ready', flush=True)
        if sys.stdin.buffer.readline() != b'commit\n':
            return False
    if focused_game() != target:
        return reject('focus_changed')
    if not clipboard.publish(text) or not clipboard.settle():
        return reject(clipboard.failure)
    if focused_game() != target:
        return reject('focus_changed')
    # Start the companion's bounded paste ticket only after clipboard preparation.
    draft_signal(target, key, prepare=True)
    if focused_game() != target:
        return reject('focus_changed')
    if not clipboard.send_key(
            ['xdotool', 'key', '--clearmodifiers', 'ctrl+v'], dict(os.environ, DISPLAY=target[0]),
            lambda: focused_game() == target):
        return reject(clipboard.failure)
    if guarded:
        # A key was sent, not an acknowledgement from the game's edit box.
        print('sent', flush=True)
        clipboard.serve(sys.stdin.fileno())
    else:
        clipboard.settle(2000)
    return True


if __name__ == '__main__':
    if sys.argv[1:] == ['--detect']:
        print(detect_function_key())
        sys.exit(0)
    guarded = sys.argv[1:] == ['--guarded-paste']
    request = json.loads(sys.stdin.buffer.readline()) if guarded else json.load(sys.stdin)
    try:
        ok = paste_draft(tuple(request['target']), request['text'], request.get('key', 'F7'), guarded)
    except Exception:
        # Never print the transcript or exception arguments to the status pipe.
        if guarded: print('error:helper_failed', flush=True)
        ok = False
    sys.exit(0 if ok else 1)
