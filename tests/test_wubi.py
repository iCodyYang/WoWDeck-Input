import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
import unittest
import test_scheme as _scheme
from model import DEFAULTS, validate
import wubi


class WubiData(unittest.TestCase):
    def test_unmodified_upstream_table_and_notices(self):
        root = wubi.TABLE.parent
        manifest = json.loads((root/'SOURCE.json').read_text())
        for name, digest in manifest['files'].items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(), digest)
        self.assertEqual(hashlib.sha256((root/'COPYING.GPL3').read_bytes()).hexdigest(),
                         manifest['additional_license']['sha256'])
        table = wubi.table()
        self.assertGreater(sum(map(len, table.values())), 100000)
        for code, text in [('a','工'), ('wq','你'), ('vbg','好'), ('khk','中')]:
            self.assertEqual(table[code][0], text)
        self.assertTrue(all(1 <= len(code) <= 4 and set(code) <= set('abcdefghijklmnopqrstuvwxy') for code in table))

    def test_existing_preferences_are_unchanged(self):
        for scheme in ('keep', 'full', 'xiaohe', 'wubi86'):
            for key in ('F7','F9','F10'):
                config = copy.deepcopy(DEFAULTS)
                config.update(scheme=scheme, voiceKey=key, pluginEnabled=True, enabled=True,
                              voiceWanted=True, appearance_migrated=True)
                config['appearance'].update(x=231,y=485)
                self.assertEqual(validate(config), config)
        self.assertEqual(DEFAULTS['scheme'], 'full')
        self.assertEqual(DEFAULTS['voiceKey'], 'F7')


class WubiSettings(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = _scheme.SchemeChanges.asyncSetUp
    asyncTearDown = _scheme.SchemeChanges.asyncTearDown
    async def test_wubi_does_not_write_system_pinyin_or_voice_settings(self):
        p = self.plugin
        original = copy.deepcopy(p.config)
        p.user_command = AsyncMock(side_effect=AssertionError('Wubi must not read/write dconf'))
        p.engine_available = lambda: False
        await p.set_scheme('wubi86')
        await p.set_enabled(True)
        self.assertEqual(p.config, {**original, 'scheme':'wubi86', 'enabled':True})
        self.assertFalse((p.directory/'pinyin-before.json').exists())
        self.assertIs(await p.get_wubi_table(), wubi.table())

    async def test_switch_back_restores_explicit_choice_only(self):
        p = self.plugin
        await p.set_scheme('wubi86')
        self.assertEqual(self.values, self.original)
        await p.set_scheme('full')
        self.assertEqual(self.values['DoublePinyin'], 'false')
        await p.set_scheme('xiaohe')
        self.assertEqual(self.values, self.original)

    async def test_no_table_load_for_normal_enable_and_unauthorized_rpc(self):
        with patch('wubi.table', side_effect=AssertionError('unexpected table load')):
            await self.plugin.set_enabled(True)
            with self.assertRaises(ValueError):
                await self.plugin.get_wubi_table()

    async def test_failure_preserves_prior_scheme(self):
        with patch('wubi.table', side_effect=ValueError('broken table')):
            with self.assertRaises(ValueError):
                await self.plugin.set_scheme('wubi86')
        self.assertEqual(self.plugin.config['scheme'], 'full')
        self.assertEqual(self.values, self.original)
