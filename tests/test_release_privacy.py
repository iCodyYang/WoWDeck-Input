import asyncio
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import build_release as release
from test_scheme import module as backend


class ReleaseBoundary(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root/'source'
        self.output = self.root/'output'
        for name in set(release.runtime_files().values()) | set(release.SOURCE):
            path = self.source/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('public fixture\n')
        (self.source/'package.json').write_text(json.dumps({'version':'0.2.0-alpha.20'}))

    def test_extra_private_files_are_never_collected_and_archives_are_reproducible(self):
        marker = 'private-fixture-' + 'do-not-distribute'
        for name in ('settings.json', 'voice/data/Default/Cookies', 'voice/command.json',
                     'docs/images/login.png', 'src/private-settings.ts', 'tests/account.json',
                     'VALIDATION.md', '.env', 'work/device-receipt.json'):
            path = self.source/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(marker)
        hashes = release.build(self.source, self.output)
        self.assertEqual(hashes, release.build(self.source, self.output))
        for name in hashes:
            with zipfile.ZipFile(self.output/name) as archive:
                self.assertIsNone(archive.testzip())
                for entry in archive.namelist():
                    self.assertNotIn(marker.encode(), archive.read(entry))
        with zipfile.ZipFile(self.output/'WoWDeck-Input-0.2.0-alpha.20.zip') as archive:
            self.assertEqual(set(archive.namelist()),
                             {release.FOLDER+'/'+p for p in release.runtime_files()})
            self.assertEqual(archive.read(release.FOLDER+'/VALIDATION.md'), b'public fixture\n')

    def test_allowlisted_symlink_is_rejected_before_reading_its_target(self):
        target = self.root/'private'
        target.write_text('not public')
        path = self.source/'voice/site.js'
        path.unlink()
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            release.build(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_inline_credential_blocks_release_without_printing_the_value(self):
        fake = 'sessionid' + '=' + 'x'*32
        (self.source/'voice/site.js').write_text(fake)
        with self.assertRaises(ValueError) as error:
            release.build(self.source, self.output)
        self.assertIn('session_cookie_literal', str(error.exception))
        self.assertNotIn(fake, str(error.exception))
        self.assertFalse(self.output.exists())


class CleanFirstLaunch(unittest.IsolatedAsyncioTestCase):
    async def test_new_user_has_no_login_and_launches_no_voice_process(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)/'new-user'
            home.mkdir()
            settings = Path(directory)/'settings'
            user = SimpleNamespace(pw_name='new-user', pw_uid=2345, pw_gid=2345, pw_dir=str(home))
            with patch.object(backend.decky, 'DECKY_PLUGIN_SETTINGS_DIR', str(settings), create=True), \
                 patch.object(backend.Plugin, 'session_user', return_value=user), \
                 patch.object(backend.Plugin, 'watch', new_callable=AsyncMock), \
                 patch.object(backend.Plugin, 'watch_voice', new_callable=AsyncMock), \
                 patch('voice.control.report_stream', return_value=None), \
                 patch('asyncio.create_subprocess_exec', new_callable=AsyncMock) as spawn:
                plugin = backend.Plugin()
                await plugin._main()
                try:
                    await plugin.reconcile_voice()
                    state = await plugin.get_voice_state()
                    self.assertFalse(any(plugin.config[k] for k in ('pluginEnabled','enabled','voiceWanted')))
                    self.assertEqual(plugin.config['voiceKey'], 'F7')
                    self.assertFalse(any(state[k] for k in ('signed','enabled','running','hasProfile')))
                    self.assertEqual(state['qr'], '')
                    spawn.assert_not_called()
                    self.assertEqual(list(home.iterdir()), [])
                finally:
                    await asyncio.gather(plugin.task, plugin.voice_task)
