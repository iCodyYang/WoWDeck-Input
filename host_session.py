"""Read only the display fields needed from the current user's Steam session.

No environment dumps, shell evaluation, persistent cache or account data.
"""
import os
import re
import time
from pathlib import Path

FIELDS = {'DISPLAY', 'XAUTHORITY', 'PULSE_SERVER', 'XDG_CURRENT_DESKTOP',
          'GAMESCOPE_WAYLAND_DISPLAY', 'STEAM_GAME_DISPLAY_0'}
STEAM_NAMES = {'steam', 'steamwebhelper'}


def environment(text, separator='\n'):
    result = {}
    for line in text.split(separator):
        line = line.strip()
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, sep, value = line.partition('=')
        if sep and key in FIELDS:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if len(value) < 4096 and '\x00' not in value and '\n' not in value:
                result[key] = value
    return result


def is_gamescope(env):
    # XDG_CURRENT_DESKTOP is a colon-separated list, not necessarily one name.
    desktops = env.get('XDG_CURRENT_DESKTOP', '').casefold().split(':')
    if any(desktops):
        return 'gamescope' in desktops
    return bool(env.get('GAMESCOPE_WAYLAND_DISPLAY') and env.get('STEAM_GAME_DISPLAY_0'))


def steam_processes(proc=Path('/proc'), uid=None):
    try:
        entries = list(proc.iterdir())
    except OSError:
        return
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            owner = entry.stat().st_uid
            if uid is not None and owner != uid:
                continue
            if (entry/'comm').read_text(errors='replace').strip() in STEAM_NAMES:
                yield entry, owner
        except OSError:
            continue


class GameSession:
    def __init__(self, user, runtime=None, proc=Path('/proc'), sockets=Path('/tmp/.X11-unix'), clock=time.monotonic):
        self.uid = user.pw_uid
        self.runtime = runtime or Path('/run/user')/str(self.uid)
        self.proc, self.sockets, self.clock = proc, sockets, clock
        self.until = 0
        self.cached = {}

    def usable(self, env):
        display = re.fullmatch(r':(\d+)(?:\.\d+)?', env.get('DISPLAY', ''))
        return bool(is_gamescope(env) and display and (self.sockets/('X'+display[1])).exists())

    def read(self):
        if self.clock() >= self.until:
            self.cached = self.discover()
            self.until = self.clock() + 2
        return dict(self.cached)

    def discover(self):
        # A live Steam process also works on images without gamescope-environment.
        # Do not inspect game/browser command lines or expose unrelated env values.
        desktop_steam = False
        for entry, _ in steam_processes(self.proc, self.uid):
            try:
                env = environment((entry/'environ').read_text(errors='replace'), '\x00')
            except OSError:
                continue
            if self.usable(env):
                return env
            if env.get('XDG_CURRENT_DESKTOP') and not is_gamescope(env):
                desktop_steam = True
        # A stale file from a previous Gaming Mode must not activate in desktop Steam.
        if desktop_steam:
            return {}
        try:
            env = environment((self.runtime/'gamescope-environment').read_text(errors='replace'))
        except OSError:
            env = {}
        if self.usable(env):
            return env
        if os.geteuid() == self.uid:
            env = {key: os.environ[key] for key in FIELDS if key in os.environ}
            if self.usable(env):
                return env
        return {}
