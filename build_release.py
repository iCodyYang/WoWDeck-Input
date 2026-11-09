"""Build shareable archives from an explicit source allowlist, never a device install."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import re
import tempfile
import zipfile

FOLDER = 'WoWDeck Input'
CORE = ('wubi.py', 'data/wubi86/wubi86.dict.yaml', 'data/wubi86/LICENSE',
        'data/wubi86/AUTHORS', 'data/wubi86/SOURCE.json', 'data/wubi86/COPYING.GPL3', 'main.py', 'model.py', 'host_session.py', 'package.json', 'plugin.json', 'dist/index.js',
        'LICENSE', 'NOTICE.md', 'README.md', 'README.en.md', 'INSTALL.md',
        'PRIVACY.md', 'RELEASE_NOTES.md', 'docs/VOICE.md')
VOICE = ('Browser.qml', 'LICENSE-Murmur.txt', 'clipboard_delivery.py', 'control.py',
         'deck_hold.py', 'draft_install.py', 'game.py', 'site.js', 'wave_window.py',
         'waveform.py', 'worker.py', 'xedges.py')
EVDEV = ('LICENSE.python-evdev', '__init__.py', 'device.py', 'ecodes.py', 'eventio.py',
         'eventio_async.py', 'events.py', 'input.py', 'util.py')
ADDON = ('companion/WoWDeckDraft/WoWDeckDraft.toc', 'companion/WoWDeckDraft/WoWDeckDraft.lua')
SOURCE = ('src/utility/wubi.ts', 'tests/wubi.mjs', 'tests/wubi-context.mjs', 'tests/test_wubi.py', '.gitignore', 'build_release.py', 'build_frontend.mjs', 'tsconfig.json',
          'rollup.config.js', 'docs/RELEASE_VALIDATION.md',
          'src/Voice.tsx', 'src/WaveEditor.tsx', 'src/config.ts', 'src/index.tsx',
          'src/keyboard-setup.ts', 'src/utility/context.ts', 'src/utility/display.ts',
          'src/utility/keyboard.ts', 'src/utility/map.ts',
          'tests/draft_clear.lua', 'tests/keyboard-setup.mjs', 'tests/menu-priority.mjs',
          'tests/preferences.mjs', 'tests/test_clipboard_delivery.py',
          'tests/test_control_safety.py', 'tests/test_draft_install.py',
          'tests/test_model.py', 'tests/test_scheme.py', 'tests/test_voice.py',
          'tests/test_voice_cancel.py', 'tests/test_voice_stream.py',
          'tests/test_waveform.py', 'tests/voice-site.mjs', 'tests/voice_smoke.py',
          'tests/wave-editor.mjs', 'tests/test_release_privacy.py', 'tests/test_compatibility.py',
          'tests/test_startup_recovery.py', 'tests/login-page.mjs')

# Report only the rule and file, never the matched credential or private value.
# The explicit file list is the main boundary; these scans are additional guards.
RULES = {
    'private_key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'jwt_literal': r'eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}',
    'session_cookie_literal': r'(?:sessionid|sessionid_ss|sid_tt)\s*=\s*[A-Za-z0-9%_-]{16,}',
    'bearer_literal': r'Bearer\s+[A-Za-z0-9_./+-]{24,}',
    'personal_mac_path': r'/Users/[A-Za-z0-9_.-]+/',
    'personal_device_name': r'steamdeck[-]cody(?:\.local)?',
    'private_lan_address': r'\b192[.]168[.]\d{1,3}[.]\d{1,3}\b',
}


def runtime_files():
    names = (*CORE, *(f'voice/{p}' for p in VOICE),
             *(f'py_modules/evdev_mod/{p}' for p in EVDEV), *ADDON)
    files = {name: name for name in names}
    # Keep the local chronological log out of release archives.
    files['VALIDATION.md'] = 'docs/RELEASE_VALIDATION.md'
    return files


def read_source(base, relative):
    parts = PurePosixPath(relative)
    if parts.is_absolute() or '..' in parts.parts:
        raise ValueError('Invalid release path')
    path = base
    for part in parts.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Symlink is not allowed in a release: ' + relative)
    if not path.is_file():
        raise ValueError('Missing release source: ' + relative)
    data = path.read_bytes()
    content = data.decode('utf-8')  # No opaque database, image, cache or binary payload.
    for rule, expression in RULES.items():
        if re.search(expression, content, re.IGNORECASE):
            raise ValueError('Release scan rejected ' + relative + ': ' + rule)
    return data


def write_zip(path, members):
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=9)
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == set(members)
        assert all(archive.read(name) == data for name, data in members.items())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(base=None, output=None):
    base = Path(base or Path(__file__).parent).resolve()
    output = Path(output or base/'release')
    runtime = {name: read_source(base, source) for name, source in runtime_files().items()}
    source = dict(runtime)
    source.update({name: read_source(base, name) for name in SOURCE})
    version = json.loads(runtime['package.json'])['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', version):
        raise ValueError('Invalid release version')
    packages = {
        f'WoWDeck-Input-{version}.zip': {f'{FOLDER}/{p}': data for p, data in runtime.items()},
        f'WoWDeck-Input-{version}-source.zip': {f'{FOLDER}/{p}': data for p, data in source.items()},
        f'WoWDeckDraft-{version}.zip': {p.removeprefix('companion/'): runtime[p] for p in ADDON},
    }
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output, prefix='.release-build-') as temp:
        stage = Path(temp)
        hashes = {name: write_zip(stage/name, members) for name, members in packages.items()}
        audit = dict(version=version, policy='explicit source allowlist; no device export',
                     text_scan='passed', symlinks='rejected',
                     excluded=['browser profiles', 'cookies', 'local storage', 'settings',
                               'logs', 'screenshots', 'device receipts', 'backups', 'recordings'],
                     packages={name: dict(sha256=hashes[name], files={
                         p: hashlib.sha256(data).hexdigest() for p, data in members.items()
                     }) for name, members in packages.items()})
        (stage/'SHA256SUMS.json').write_text(json.dumps(hashes, indent=2)+'\n')
        (stage/'RELEASE_AUDIT.json').write_text(json.dumps(audit, indent=2)+'\n')
        for name in (*packages, 'SHA256SUMS.json', 'RELEASE_AUDIT.json'):
            (stage/name).replace(output/name)
    return hashes


if __name__ == '__main__':
    print(json.dumps(build(), indent=2))
