"""Native filesystem primitives. Windows handles pin ancestors against rename/deletion.

CreateFileW opens reparse points themselves; none are followed. Holding each ancestor
without FILE_SHARE_DELETE prevents a path swap while its child is opened or enumerated.
"""

import os
import stat
from contextlib import contextmanager
from pathlib import Path

from opensubsurface.errors import require


def is_reparse(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def normalized_path(value):
    value = os.path.expandvars(os.path.expanduser(os.fspath(value)))
    require("\x00" not in value, "INVALID_SOURCE_PATH", "NUL in path")
    if os.name == "nt":
        require(
            not value.startswith(("\\\\.\\", "\\\\?\\")), "INVALID_SOURCE_PATH", "Use a drive or UNC path"
        )
        require(Path(value).is_absolute(), "INVALID_SOURCE_PATH", "Use an absolute Windows folder path")
    return Path(os.path.abspath(value))


def read_at(fd, size, offset):
    """Source descriptors have a single reader; Windows has no os.pread."""
    if hasattr(os, "pread"):
        return os.pread(fd, size, offset)
    os.lseek(fd, offset, os.SEEK_SET)
    return os.read(fd, size)


def _windows_api():
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    api.CreateFileW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    api.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    api.GetFileInformationByHandleEx.restype = wintypes.BOOL
    api.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    api.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    return api


def _extended(path):
    path = str(path)
    return "\\\\?\\UNC\\" + path[2:] if path.startswith("\\\\") else "\\\\?\\" + path


def _win_open(path, directory):
    import ctypes
    import msvcrt
    from ctypes import wintypes

    api = _windows_api()
    # OPEN_EXISTING, OPEN_REPARSE_POINT, BACKUP_SEMANTICS; deny FILE_SHARE_DELETE.
    handle = api.CreateFileW(_extended(path), 0x80000000, 3, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:

        class Tag(ctypes.Structure):
            _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

        tag = Tag()
        if not api.GetFileInformationByHandleEx(handle, 9, ctypes.byref(tag), ctypes.sizeof(tag)):
            raise ctypes.WinError(ctypes.get_last_error())
        require(not tag.attributes & 0x400, "SOURCE_ACCESS_DENIED", "Reparse points/junctions are forbidden")
        require(
            bool(tag.attributes & 0x10) == directory, "INVALID_SOURCE_PATH", "Expected regular file/folder"
        )
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        handle = None  # fd now owns the handle.
        return fd
    finally:
        if handle is not None:
            api.CloseHandle(handle)


@contextmanager
def windows_opened(root, components, directory):
    """Open from the volume/share root, keeping every traversed ancestor pinned."""
    descriptors = []
    try:
        paths = [*reversed(root.parents), root]
        current = root
        for component in components:
            current = current / component
            paths.append(current)
        for index, path in enumerate(paths):
            descriptors.append(_win_open(path, directory or index < len(paths) - 1))
        root_fd = descriptors[len(root.parents)]
        yield descriptors[-1], os.fstat(root_fd)
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def scan_descriptor(fd):
    if os.name != "nt":
        return os.scandir(fd)
    import ctypes
    import msvcrt

    api = _windows_api()
    buffer = ctypes.create_unicode_buffer(32768)
    count = api.GetFinalPathNameByHandleW(msvcrt.get_osfhandle(fd), buffer, len(buffer), 0)
    if not count or count >= len(buffer):
        raise ctypes.WinError(ctypes.get_last_error())
    return os.scandir(buffer.value)


def default_home():
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "kanysh-basic"
    return Path.home() / ".kanysh-basic"
