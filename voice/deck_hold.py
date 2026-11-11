"""Corroborate a mapped F-key press with one of the Deck's four back buttons."""
import asyncio
import os
import time
from pathlib import Path

# Packet offsets documented by the upstream Linux hid-steam driver:
# https://github.com/torvalds/linux/blob/master/drivers/hid/hid-steam.c
# Only grip buttons participate; game controls and Steam/Quick Access do not.
BACK_BUTTONS = {'L4': (13, 0x02), 'L5': (9, 0x80),
                'R4': (13, 0x04), 'R5': (10, 0x01)}


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


def back_buttons(line):
    header, separator, body = line.partition(b' = ')
    if not separator or not header.startswith(b'report (size 64) (') or not header.endswith(b'numbered)'):
        return None
    try:
        data = bytes.fromhex(body.decode('ascii'))
    except (ValueError, UnicodeError):
        return None
    if len(data) == 64 and data[:3] == b'\x01\x00\x09':
        return frozenset(name for name, (offset, mask) in BACK_BUTTONS.items()
                         if data[offset] & mask)


async def observe_press(token, signal):
    path = report_stream()
    if not path: return
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return
    fragment = b''
    held = False
    button = None
    released = cancelled = False
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
                for line in lines:
                    buttons = back_buttons(line)
                    if buttons is None: continue
                    last_report = now
                    if button is None:
                        # No layout guessing: an unambiguous grip must already
                        # be held when this mapped F-key starts observation.
                        if len(buttons) != 1: return
                        button = next(iter(buttons))
                    if button not in buttons:
                        released = True
                        signal(f'hold {token} 0')
                        return
                    held = True
                    if now >= next_update:
                        signal(f'hold {token} 1')
                        next_update = now+.10
            except BlockingIOError:
                pass
            if now-last_report > .4: return
            await asyncio.sleep(.012)
    except asyncio.CancelledError:
        cancelled = True
        raise
    except OSError:
        pass
    finally:
        os.close(fd)
        if held and not released and not cancelled:
            signal(f'hold {token} lost')
