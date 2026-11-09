"""Corroborate one mapped F-key press using the Deck's existing physical R5 reports."""
import asyncio
import os
import time
from pathlib import Path


def report_stream():
    # The physical USB interface and Steam's client have the same HID id. Only
    # observe the physical driver's debug FIFO; never open a controller endpoint.
    for device in Path('/sys/bus/hid/devices').glob('0003:28DE:1205.*'):
        try:
            if (device/'driver').resolve().name != 'hid-steam' or (device/'hidraw').exists():
                continue
            if (device.resolve().parent/'bInterfaceNumber').read_text().strip() != '02':
                continue
            path = Path('/sys/kernel/debug/hid')/device.name/'events'
            if os.access(path, os.R_OK):
                return path
        except OSError:
            continue


def r5_state(line):
    header, separator, body = line.partition(b' = ')
    if not separator or not header.startswith(b'report (size 64) (') or not header.endswith(b'numbered)'):
        return None
    try:
        data = bytes.fromhex(body.decode('ascii'))
    except (ValueError, UnicodeError):
        return None
    if len(data) == 64 and data[:3] == b'\x01\x00\x09':
        return bool(data[10] & 1)


async def observe_press(token, signal):
    path = report_stream()
    if not path: return
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return
    fragment = b''
    held = False
    start = last_report = time.monotonic()
    next_update = 0
    try:
        while time.monotonic()-start < 21:
            now = time.monotonic()
            try:
                chunk = os.read(fd, 8192)
                if not chunk: return
                lines = (fragment+chunk).split(b'\n')
                fragment = lines.pop()[-512:]
                valid = False
                for line in lines:
                    down = r5_state(line)
                    if down is None: continue
                    last_report = now
                    valid = True
                    if not down:
                        if held: signal(f'r5 {token} 0')
                        return
                    held = True
                if valid and held and now >= next_update:
                    signal(f'r5 {token} 1')
                    next_update = now+.10
            except BlockingIOError:
                pass
            if now-last_report > .4: return
            await asyncio.sleep(.012)
    except OSError:
        pass
    finally:
        os.close(fd)
