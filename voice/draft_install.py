"""Install the bundled chat editor in the running user's WoW Forever client."""
import ctypes
import errno
import fcntl
import hashlib
import os
import secrets
import stat
import sys
from contextlib import ExitStack
from pathlib import Path

NAME = 'WoWDeckDraft'
FILES = (NAME + '.toc', NAME + '.lua')
BUNDLE = Path(__file__).resolve().parents[1] / 'companion' / NAME
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
PREVIOUS = {
    'WoWDeckDraft.toc': {
        '4a01fdb9d3164ed9fdc6acf35e15948d821dc921083df9ac84c104c0bacea686',
        '610945bfc14516c9ba4bf49558824c557a7f872562a0372e4471283271181f32',
        'cde00bce44cf27fc0e753de03b9b3f51d4a4881239963c286b15710bcd588140',
        '06da630400ca9913496c6b5b39ec32c9cbc3455e33fbfc80812176454d88f85c',
    },
    'WoWDeckDraft.lua': {
        '052c660c8304d97843a49061aa542d20ed246dce6dcd5d61ac23a674fbd61822',
        '0644d1a9e12791ff58c0a97e90f8ca159c4c0e3f017a41ed7a9b901acc581d99',
        'c9b8901f034957d9939cb8dc44d43a02bbf658402e7b255a7b6281dbaf3e6b5c',
        'c33b52b3560c61ea02c5c64ce71531ff0c77a07cc22e1363eca4f15e32008ddc',
    },
}


def client_for_exe(path):
    try:
        exe = path.resolve(strict=True)
        if exe.name.casefold() != 'wow.exe' or exe.parent.name.casefold() != '_forever_':
            return None
        if not exe.is_file():
            return None
        with exe.open('rb') as f:
            return exe.parent if f.read(2) == b'MZ' else None
    except (OSError, RuntimeError):
        return None


def process_clients(pid):
    # Wine maps the Windows PE into a Linux process; /proc/pid/exe itself
    # generally points to the Wine loader. A mapped image is the best witness.
    mapped = set()
    saw_wow_image = False
    try:
        with (pid/'maps').open(errors='replace') as maps:
            for line in maps:
                if not line.rstrip('\n').casefold().endswith('/wow.exe'):
                    continue
                fields = line.rstrip('\n').split(None, 5)
                if len(fields) == 6 and fields[5].startswith('/'):
                    saw_wow_image = True
                    root = client_for_exe(Path(fields[5]))
                    if root:
                        mapped.add(root)
    except OSError:
        pass
    if saw_wow_image:
        return mapped

    # Fall back to the launched image's host path or an argv path resolved
    # relative to its own real cwd. Wine's Z: drive maps to the host root.
    cwd = (pid/'cwd').resolve(strict=True)
    argv = (pid/'cmdline').read_bytes().split(b'\0')
    args = [os.fsdecode(arg).strip('"').replace('\\','/') for arg in argv[:2]]
    image = next((arg for arg in args if arg.rsplit('/', 1)[-1].casefold() == 'wow.exe'), None)
    if not image or '..' in Path(image).parts:
        return set()
    if image[:3].casefold() == 'z:/':
        image = image[2:]
    if ':' in image:
        return set()  # A drive letter by itself does not identify a host path.
    image_path = Path(image)
    candidates = [(cwd / image_path).parent]
    if tuple(s.casefold() for s in image_path.parts) == ('_forever_', 'wow.exe') and cwd.name.casefold() == '_forever_':
        candidates.append(cwd)
    for directory in candidates:
        if directory.name.casefold() != '_forever_' or not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.name.casefold() == 'wow.exe':
                root = client_for_exe(path)
                if root and root == directory.resolve():
                    return {root}
    return set()


def running_client(proc=Path('/proc')):
    clients = set()
    for pid in proc.iterdir():
        if not pid.name.isdecimal():
            continue
        try:
            if pid.stat().st_uid == os.geteuid() and (pid/'comm').read_text().strip().casefold() == 'wow.exe':
                clients.update(process_clients(pid))
        except (OSError, RuntimeError):
            continue  # A process can exit during discovery.
    if not clients:
        raise ValueError('请先进入《魔兽世界：无限》，再安装聊天框组件。')
    if len(clients) != 1:
        raise ValueError('发现多份正在运行的游戏，请仅保留要安装组件的客户端。')
    return clients.pop()


def open_dir(stack, path, parent=None, create=False):
    if create:
        try:
            os.mkdir(path, mode=0o755, dir_fd=parent)
        except FileExistsError:
            pass
    fd = os.open(path, DIR_FLAGS, dir_fd=parent)
    stack.callback(os.close, fd)
    return fd


def installed_state(parent, expected):
    try:
        fd = os.open(NAME, DIR_FLAGS, dir_fd=parent)
    except FileNotFoundError:
        return 'absent'
    except OSError as exc:
        raise ValueError('已有不同的同名组件，请先核对游戏的 AddOns 目录。') from exc
    with ExitStack() as stack:
        stack.callback(os.close, fd)
        older = False
        if set(os.listdir(fd)) == set(FILES):
            for name in FILES:
                metadata = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 65536:
                    break
                with os.fdopen(os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd), 'rb') as f:
                    data = f.read(metadata.st_size + 1)
                if data != expected[name]:
                    if hashlib.sha256(data).hexdigest() not in PREVIOUS[name]:
                        break
                    older = True
            else:
                return 'previous' if older else 'current'
    raise ValueError('已有不同的同名组件，请先核对游戏的 AddOns 目录。')


def publish(parent, staging):
    # Atomically publish the complete folder without ever replacing an occupied
    # name, including an existing empty directory. Both names have the same dirfd.
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        rename, flag = libc.renameatx_np, 4  # RENAME_EXCL, local development
    else:
        rename, flag = libc.renameat2, 1  # RENAME_NOREPLACE on SteamOS
    result = rename(parent, os.fsencode(staging), parent, os.fsencode(NAME), flag)
    if result == -1:
        code = ctypes.get_errno()
        if code in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP):
            # NTFS-3G accepts a plain directory rename but not RENAME_NOREPLACE.
            # Serialize installers and recheck the name immediately before the
            # atomic rename. A nonempty directory or unrelated file cannot be replaced.
            fcntl.flock(parent, fcntl.LOCK_EX)
            try:
                try:
                    os.stat(NAME, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    os.rename(staging, NAME, src_dir_fd=parent, dst_dir_fd=parent)
                    return
                raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), NAME)
            finally:
                fcntl.flock(parent, fcntl.LOCK_UN)
        raise OSError(code, os.strerror(code))


def install(client, bundle=BUNDLE):
    expected = {name:(bundle/name).read_bytes() for name in FILES}
    with ExitStack() as stack:
        root = open_dir(stack, client)
        interface = open_dir(stack, 'Interface', root, create=True)
        addons = open_dir(stack, 'AddOns', interface, create=True)
        state = installed_state(addons, expected)
        if state == 'current':
            return False
        staging = '.' + NAME + '-' + secrets.token_hex(12)
        os.mkdir(staging, mode=0o755, dir_fd=addons)
        try:
            stage = open_dir(stack, staging, addons)
            for name, data in expected.items():
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                with os.fdopen(os.open(name, flags, 0o644, dir_fd=stage), 'wb') as f:
                    f.write(data)
            try:
                if state == 'previous':
                    # Each file is replaced atomically. A suspended update can
                    # resume from an exact mixture of known shipped releases.
                    dest = open_dir(stack, NAME, addons)
                    for name in FILES:
                        installed_state(addons, expected)
                        os.replace(name, name, src_dir_fd=stage, dst_dir_fd=dest)
                else:
                    publish(addons, staging)
            except FileExistsError:
                if installed_state(addons, expected) == 'current':
                    return False
                raise
            return True
        finally:
            # After success staging no longer exists. On failure/retry only
            # remove the files this invocation was preparing in its private dir.
            try:
                cleanup = open_dir(stack, staging, addons)
            except FileNotFoundError:
                pass
            else:
                for name in FILES:
                    try:
                        os.unlink(name, dir_fd=cleanup)
                    except FileNotFoundError:
                        pass
                os.rmdir(staging, dir_fd=addons)


def main():
    if os.geteuid() == 0:
        raise ValueError('请使用当前游戏用户安装聊天框组件。')
    installed = install(running_client())
    print('组件已安装，退出并重新打开游戏后生效。' if installed else '组件已安装；首次使用请退出并重新打开游戏。')


if __name__ == '__main__':
    try:
        main()
    except ValueError as exc:
        sys.exit(str(exc))
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EROFS):
            sys.exit('当前游戏用户无法写入此游戏的 AddOns 目录。')
        sys.exit('无法安全安装聊天框组件，请检查游戏目录和存储设备后重试。')
