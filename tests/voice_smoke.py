"""On a Deck in Gaming Mode, test the unpacked ZIP with a temporary empty account profile."""
import asyncio
import base64
import hashlib
import os
import pwd
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


async def main(plugin):
    sys.path.insert(0, str(plugin))
    from voice.control import VoiceControl
    me = pwd.getpwuid(os.getuid())
    assert me.pw_uid != 0, 'Run this smoke test as the session user'
    with tempfile.TemporaryDirectory(prefix='wowdeck-test-home-') as home:
        user = SimpleNamespace(pw_name=me.pw_name, pw_uid=me.pw_uid, pw_gid=me.pw_gid, pw_dir=home)
        voice = VoiceControl(user)
        previous = None
        try:
            for _ in range(2):
                await voice.call('refresh' if previous else 'restore')
                async with asyncio.timeout(75):
                    while not voice.state['qr']:
                        if not voice.state['running']:
                            raise RuntimeError(voice.state['message'])
                        await asyncio.sleep(.25)
                image = base64.b64decode(voice.state['qr'].split(',',1)[1], validate=True)
                assert image.startswith(b'\x89PNG\r\n\x1a\n')
                digest = hashlib.sha256(image).digest()
                assert digest != previous, 'Expected a fresh official QR after refresh'
                previous = digest
                assert not voice.state['signed'] and not voice.state['enabled']
                try: await voice.call('arm')
                except ValueError: pass
                else: raise AssertionError('Guest could enable recording')
                print('Official PNG received; unsigned guest; microphone disabled', flush=True)
            await voice.call('stop')
            assert not voice.state['running'] and not voice.state['qr']
            profile = Path(home)/'.local/share/wowdeck-input/doubao-browser'
            assert profile.is_dir()
            await voice.call('forget')
            assert not profile.exists()
            print('Close, refresh and private profile removal passed', flush=True)
        finally:
            await voice.call('stop')


if __name__ == '__main__':
    asyncio.run(main(Path(sys.argv[1]).resolve()))
