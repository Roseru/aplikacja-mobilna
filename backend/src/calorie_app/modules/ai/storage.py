"""Private prepared-photo files. Caller owns DB intents and per-key IO locks.

Provision the root before startup: POSIX owner=current UID/mode 0700; Windows
protected DACL with access only for the current service SID, SYSTEM and local
Administrators. API and worker must share that service identity. This module
checks permissions; it never changes ACLs or creates roots in system Temp.
"""

import ctypes
import os
import re
import stat
import time
from contextlib import contextmanager
from pathlib import Path

from calorie_app.core.errors import DomainError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
_KEY = re.compile(r"^[0-9a-f]{32}$")
_OBJECT = re.compile(r"^([0-9a-f]{32})\.(jpg|staging)$")


def _unavailable() -> DomainError:
    return DomainError(503, "ai_storage_unavailable")


def _key(key: str) -> str:
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise _unavailable()
    return key


def _not_link(info: os.stat_result) -> None:
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise OSError("unsafe_storage_object")


def _private_file(info: os.stat_result) -> None:
    _not_link(info)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise OSError("unsafe_storage_object")
    if os.name != "nt" and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600):
        raise OSError("unsafe_storage_permissions")


class _Windows:
    """Narrow Win32 handle/ACL helpers, initialized only on Windows."""

    def __init__(self):
        from ctypes import wintypes

        self.types = wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.security = ctypes.WinDLL("advapi32", use_last_error=True)
        self.kernel.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.GetCurrentProcess.restype = wintypes.HANDLE
        self.kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        self.security.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        self.security.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.security.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.LPWSTR),
        ]
        self.security.GetNamedSecurityInfoW.argtypes = [
            wintypes.LPWSTR,
            ctypes.c_int,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.security.GetNamedSecurityInfoW.restype = wintypes.DWORD
        self.security.GetSecurityDescriptorControl.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.WORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.security.GetAce.argtypes = [
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.sid = self._current_sid()

    def _sid_string(self, pointer):
        value = self.types.LPWSTR()
        if not self.security.ConvertSidToStringSidW(pointer, ctypes.byref(value)):
            raise OSError("storage_acl_unavailable")
        try:
            return value.value
        finally:
            self.kernel.LocalFree(ctypes.cast(value, ctypes.c_void_p))

    def _current_sid(self):
        token = self.types.HANDLE()
        if not self.security.OpenProcessToken(
            self.kernel.GetCurrentProcess(), 8, ctypes.byref(token)
        ):
            raise OSError("storage_acl_unavailable")
        try:
            size = self.types.DWORD()
            self.security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            buffer = ctypes.create_string_buffer(size.value)
            if not self.security.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
                raise OSError("storage_acl_unavailable")
            return self._sid_string(ctypes.c_void_p.from_buffer(buffer).value)
        finally:
            self.kernel.CloseHandle(token)

    def private_acl(self, path: Path, directory: bool) -> None:
        owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        result = self.security.GetNamedSecurityInfoW(
            str(path),
            1,
            5,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if result:
            raise OSError("storage_acl_unavailable")
        try:
            if not dacl.value or self._sid_string(owner) != self.sid:
                raise OSError("unsafe_storage_permissions")
            control, revision = self.types.WORD(), self.types.DWORD()
            if not self.security.GetSecurityDescriptorControl(
                descriptor, ctypes.byref(control), ctypes.byref(revision)
            ):
                raise OSError("storage_acl_unavailable")
            if directory and not control.value & 0x1000:  # SE_DACL_PROTECTED
                raise OSError("unsafe_storage_permissions")
            # ACL header: revision, reserved, size, ACE count, reserved.
            count = ctypes.c_ushort.from_address(dacl.value + 4).value
            allowed = {self.sid, "S-1-5-18", "S-1-5-32-544"}
            current_mask = 0
            for index in range(count):
                ace = ctypes.c_void_p()
                if not self.security.GetAce(dacl, index, ctypes.byref(ace)):
                    raise OSError("storage_acl_unavailable")
                kind, flags = ctypes.string_at(ace, 2)
                if kind == 1:
                    # Do not advertise writable storage under an unknown deny
                    # policy; availability must fail closed as well as writes.
                    raise OSError("unsafe_storage_permissions")
                if kind != 0:
                    raise OSError("unsafe_storage_permissions")
                sid = self._sid_string(ace.value + 8)
                if sid not in allowed:
                    raise OSError("unsafe_storage_permissions")
                if sid == self.sid and not flags & 8:  # INHERIT_ONLY_ACE
                    current_mask |= ctypes.c_uint32.from_address(ace.value + 4).value
            required = 0x63 if directory else 0x3  # list/add/traverse/deletechild or read/write
            if not current_mask & 0x10000000 and current_mask & required != required:
                raise OSError("unsafe_storage_permissions")
        finally:
            self.kernel.LocalFree(descriptor)

    def open(self, path: Path, *, directory=False, create=False):
        # Directory handles forbid DELETE sharing to pin every path component;
        # OPEN_REPARSE_POINT prevents following a newly swapped junction/link.
        access = 0x80 if directory else (0xC0000000 if create else 0x80000000)
        flags = 0x00200000 | (0x02000000 if directory else 0x80)
        handle = self.kernel.CreateFileW(
            str(path), access, 3 if directory else 0, None, 1 if create else 3, flags, None
        )
        if handle == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), "storage_open_failed")
        return handle


class PhotoStorage:
    def __init__(self, root: Path):
        self.root = Path(root)

    @contextmanager
    def _access(self):
        if not self.root.is_absolute() or len(self.root.parts) < 2 or ".." in self.root.parts:
            raise OSError("unsafe_storage_root")
        handles = []
        windows = None
        try:
            if os.name == "nt":
                windows = _Windows()
                current = Path(self.root.anchor)
                for part in self.root.parts[1:]:
                    current /= part
                    handle = windows.open(current, directory=True)
                    handles.append(handle)
                    info = current.lstat()
                    _not_link(info)
                    if not stat.S_ISDIR(info.st_mode):
                        raise OSError("unsafe_storage_root")
                windows.private_acl(self.root, True)
                yield None, windows
            else:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
                descriptor = os.open(self.root.anchor, flags)
                handles.append(descriptor)
                for part in self.root.parts[1:]:
                    descriptor = os.open(part, flags, dir_fd=descriptor)
                    handles.append(descriptor)
                info = os.fstat(descriptor)
                if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise OSError("unsafe_storage_permissions")
                if os.fstatvfs(descriptor).f_flag & os.ST_RDONLY:
                    raise OSError("storage_filesystem_read_only")
                yield descriptor, None
        finally:
            for handle in reversed(handles):
                if windows:
                    windows.kernel.CloseHandle(handle)
                else:
                    os.close(handle)

    def availability(self) -> bool:
        try:
            with self._access():
                return True
        except (OSError, ValueError):
            return False

    def _stat(self, name, directory):
        try:
            if directory is None:
                return (self.root / name).lstat()
            return os.stat(name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return None

    def _open_file(self, name, directory, windows, create=False):
        if windows:
            import msvcrt

            handle = windows.open(self.root / name, create=create)
            try:
                descriptor = msvcrt.open_osfhandle(
                    handle, os.O_BINARY | (os.O_RDWR if create else 0)
                )
            except BaseException:
                windows.kernel.CloseHandle(handle)
                raise
        else:
            flags = os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            flags |= os.O_WRONLY | os.O_CREAT | os.O_EXCL if create else os.O_RDONLY
            descriptor = os.open(name, flags, 0o600, dir_fd=directory)
        try:
            _private_file(os.fstat(descriptor))
            if windows:
                windows.private_acl(self.root / name, False)
            return descriptor
        except BaseException:
            os.close(descriptor)
            if create:
                self._unlink(name, directory)
            raise

    def _unlink(self, name, directory):
        if directory is None:
            os.unlink(self.root / name)
        else:
            os.unlink(name, dir_fd=directory)

    def activate(self, key: str, prepared: bytes) -> None:
        key = _key(key)
        if not isinstance(prepared, bytes) or not 0 < len(prepared) <= MAX_IMAGE_BYTES:
            raise _unavailable()
        # Defense against accidentally passing the original PNG/WebP: only the
        # prepared JPEG object belongs on disk; codec provenance is caller-owned.
        if not prepared.startswith(b"\xff\xd8") or not prepared.endswith(b"\xff\xd9"):
            raise _unavailable()
        staging, active = key + ".staging", key + ".jpg"
        created = False
        try:
            with self._access() as (directory, windows):
                if self._stat(active, directory) is not None:
                    raise OSError("storage_key_exists")
                try:
                    descriptor = self._open_file(staging, directory, windows, create=True)
                    created = True
                    with os.fdopen(descriptor, "wb") as output:
                        output.write(prepared)
                        output.flush()
                        os.fsync(output.fileno())
                    if windows:
                        if not windows.kernel.MoveFileExW(
                            str(self.root / staging), str(self.root / active), 8
                        ):
                            raise OSError("storage_activation_failed")
                    else:
                        # Per-key session lock belongs to caller. There is no
                        # DB transaction or account-row lock around this IO.
                        os.rename(staging, active, src_dir_fd=directory, dst_dir_fd=directory)
                        os.fsync(directory)
                    created = False
                finally:
                    if created:
                        try:
                            self._unlink(staging, directory)
                        except FileNotFoundError:
                            pass
        except (OSError, ValueError):
            raise _unavailable() from None

    def read(self, key: str) -> bytes:
        key = _key(key)
        try:
            with self._access() as (directory, windows):
                try:
                    descriptor = self._open_file(key + ".jpg", directory, windows)
                except FileNotFoundError:
                    raise DomainError(410, "image_unavailable") from None
                with os.fdopen(descriptor, "rb") as source:
                    if not 0 < os.fstat(source.fileno()).st_size <= MAX_IMAGE_BYTES:
                        raise OSError("invalid_storage_size")
                    data = source.read(MAX_IMAGE_BYTES + 1)
                if not 0 < len(data) <= MAX_IMAGE_BYTES:
                    raise OSError("invalid_storage_size")
                return data
        except (OSError, ValueError):
            raise _unavailable() from None

    def delete(self, key: str) -> None:
        key = _key(key)
        try:
            with self._access() as (directory, windows):
                for name in (key + ".jpg", key + ".staging"):
                    info = self._stat(name, directory)
                    if info is None:
                        continue
                    _private_file(info)
                    if windows:
                        windows.private_acl(self.root / name, False)
                    try:
                        self._unlink(name, directory)
                    except FileNotFoundError:
                        pass
                if directory is not None:
                    os.fsync(directory)
        except (OSError, ValueError):
            raise _unavailable() from None

    def candidates(self, grace_seconds: int, limit: int) -> list[str]:
        if (
            type(grace_seconds) is not int
            or not 0 <= grace_seconds <= 2**31
            or type(limit) is not int
            or not 1 <= limit <= 1000
        ):
            raise ValueError("invalid_orphan_limits")
        cutoff, candidates = time.time() - grace_seconds, []
        try:
            with self._access() as (directory, windows):
                with os.scandir(directory if directory is not None else self.root) as entries:
                    for entry in entries:
                        match = _OBJECT.fullmatch(entry.name)
                        if match is None or match[1] in candidates:
                            continue
                        # Windows DirEntry.stat caches FindFile metadata with
                        # st_nlink=0; lstat obtains the actual link count.
                        info = self._stat(entry.name, directory)
                        if info is None:
                            continue
                        _private_file(info)
                        if info.st_mtime > cutoff:
                            continue
                        # A fresh staging object protects its whole key.
                        other = self._stat(
                            match[1] + (".staging" if match[2] == "jpg" else ".jpg"), directory
                        )
                        if other is not None:
                            _private_file(other)
                            if other.st_mtime > cutoff:
                                continue
                        if windows:
                            windows.private_acl(self.root / entry.name, False)
                        candidates.append(match[1])
                        if len(candidates) == limit:
                            break
            return candidates
        except (OSError, ValueError):
            raise _unavailable() from None
