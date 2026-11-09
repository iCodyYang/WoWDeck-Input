import os
import ctypes
import errno
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from voice import draft_install as draft


class DraftInstall(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.game = self.base / 'World of Warcraft' / '_forever_'
        self.game.mkdir(parents=True)
        self.exe = self.game / 'Wow.exe'
        self.exe.write_bytes(b'MZ executable')
        self.proc = self.base / 'proc'
        self.proc.mkdir()
        self.bundle = self.base / 'bundle'
        self.bundle.mkdir()
        for name in draft.FILES:
            (self.bundle/name).write_text(name)
        self.addons = self.game / 'Interface' / 'AddOns'
        self.target = self.addons / draft.NAME

    def pid(self, number, comm, cwd, image, mapped=None):
        pid = self.proc / str(number)
        pid.mkdir()
        (pid/'comm').write_text(comm)
        (pid/'cmdline').write_bytes(os.fsencode(image) + b'\0-launcherlogin\0')
        (pid/'cwd').symlink_to(cwd)
        if mapped:
            (pid/'maps').write_text('00004000-00008000 r-xp 0000 08:01 42 ' + str(mapped) + '\n')

    def test_uses_mapped_wow_executable_not_launcher_or_wrong_wine_client(self):
        self.pid(40, 'Battle.net.exe', self.game, 'Wow.exe', self.exe)
        with self.assertRaisesRegex(ValueError, '先进入'):
            draft.running_client(self.proc)
        self.pid(41, 'Wow.exe', self.base, 'not-a-host-path', self.exe)
        self.assertEqual(draft.running_client(self.proc), self.game)
        second = self.base / 'other' / '_forever_'
        second.mkdir(parents=True)
        (second/'Wow.exe').write_bytes(b'MZ executable')
        self.pid(42, 'Wow.exe', second, 'Wow.exe', second/'Wow.exe')
        with self.assertRaisesRegex(ValueError,'多份'):
            draft.running_client(self.proc)

    def test_resolves_forever_relative_argv_without_writing_a_retail_client(self):
        self.pid(52, 'Wow.exe', self.game.parent, '_forever_\\WOW.EXE')
        self.assertEqual(draft.running_client(self.proc), self.game)
        self.exe.write_bytes(b'not a PE')
        with self.assertRaisesRegex(ValueError, '先进入'):
            draft.running_client(self.proc)

    def test_a_known_retail_image_vetoes_a_misleading_working_directory(self):
        retail = self.game.parent / '_retail_'
        retail.mkdir()
        (retail/'Wow.exe').write_bytes(b'MZ executable')
        self.pid(53, 'Wow.exe', self.game, 'Wow.exe', retail/'Wow.exe')
        with self.assertRaisesRegex(ValueError, '先进入'):
            draft.running_client(self.proc)

    def test_already_installed_is_idempotent_and_preserves_custom_files(self):
        self.assertTrue(draft.install(self.game,self.bundle))
        self.assertFalse(draft.install(self.game,self.bundle))
        lua = self.target/draft.FILES[1]
        lua.write_text('user edits')
        with self.assertRaisesRegex(ValueError,'已有不同'):
            draft.install(self.game,self.bundle)
        self.assertEqual(lua.read_text(),'user edits')

    def test_does_not_follow_directory_or_file_symlinks(self):
        elsewhere = self.base/'elsewhere'
        elsewhere.mkdir()
        (self.game/'Interface').symlink_to(elsewhere,target_is_directory=True)
        with self.assertRaises(OSError):
            draft.install(self.game,self.bundle)
        self.assertEqual(list(elsewhere.iterdir()),[])
        (self.game/'Interface').unlink()
        self.target.mkdir(parents=True)
        (self.target/draft.FILES[0]).symlink_to(self.bundle/draft.FILES[0])
        (self.target/draft.FILES[1]).write_text(draft.FILES[1])
        with self.assertRaisesRegex(ValueError,'已有不同'):
            draft.install(self.game,self.bundle)

    def test_publish_failure_can_retry_without_partial_files(self):
        with patch.object(draft,'publish',side_effect=OSError('storage failure')):
            with self.assertRaisesRegex(OSError,'storage failure'):
                draft.install(self.game,self.bundle)
        self.assertEqual(list(self.addons.iterdir()),[])
        self.assertTrue(draft.install(self.game,self.bundle))

    def test_ntfs_fallback_installs_and_preserves_an_occupied_name(self):
        def unsupported(*args):
            ctypes.set_errno(errno.EINVAL)
            return -1
        with patch('voice.draft_install.ctypes.CDLL') as libc:
            libc.return_value.renameat2.side_effect = unsupported
            libc.return_value.renameatx_np.side_effect = unsupported
            self.assertTrue(draft.install(self.game, self.bundle))
            stage = self.addons/'.other-stage'
            stage.mkdir()
            fd = os.open(self.addons, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with self.assertRaises(FileExistsError):draft.publish(fd, stage.name)
            finally:
                os.close(fd)
            self.assertTrue((self.target/draft.FILES[0]).is_file())
            self.assertTrue(stage.exists())

    def test_concurrent_unknown_directory_wins_without_overwrite(self):
        real_publish = draft.publish
        def concurrent_change(parent, staging):
            self.target.mkdir()
            return real_publish(parent, staging)
        with patch.object(draft,'publish',side_effect=concurrent_change):
            with self.assertRaisesRegex(ValueError,'已有不同'):
                draft.install(self.game,self.bundle)
        self.assertEqual(list(self.target.iterdir()),[])
        self.assertEqual(list(self.addons.iterdir()),[self.target])

    def test_known_old_releases_upgrade_and_interrupted_upgrade_resumes(self):
        releases = [{name: (version + name).encode() for name in draft.FILES}
                    for version in ('0.1.0', '0.2.0')]
        known = {name: {hashlib.sha256(r[name]).hexdigest() for r in releases}
                 for name in draft.FILES}
        self.target.mkdir(parents=True)
        saved = self.game/'WTF'/'SavedVariables'/'WoWDeckDraft.lua'
        saved.parent.mkdir(parents=True)
        saved.write_text('existing user position')
        with patch.object(draft, 'PREVIOUS', known):
            for release in releases:
                for name, data in release.items(): (self.target/name).write_bytes(data)
                self.assertTrue(draft.install(self.game, self.bundle))
                self.assertFalse(draft.install(self.game, self.bundle))
                self.assertEqual(saved.read_text(), 'existing user position')
            (self.target/draft.FILES[1]).write_bytes(releases[0][draft.FILES[1]])
            self.assertTrue(draft.install(self.game, self.bundle))
            self.assertEqual((self.target/draft.FILES[1]).read_bytes(),
                             (self.bundle/draft.FILES[1]).read_bytes())
