"""Owner-configured read-only filesystem sources for the single-owner local profile.

POSIX openat/O_NOFOLLOW and native Windows pinned handles bind access to registered roots.
Scan is metadata-only; explicit upload creates the existing bounded immutable import snapshot.
"""

import os
import stat
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from opensubsurface.errors import DomainError, require
from opensubsurface.persistence.store import digest, now, uid
from opensubsurface.platform_io import is_reparse, normalized_path, scan_descriptor, windows_opened

STATE = "owner:local_sources"
EXTENSIONS = {
    ".csv",
    ".las",
    ".sgy",
    ".segy",
    ".npy",
    ".json",
    ".grdecl",
    ".inc",
    ".egrid",
    ".roff",
    ".prop",
    ".data",
    ".txt",
    ".asc",
    ".dat",
    ".gri",
    ".irap",
    ".zmap",
    ".cps",
    ".fgr",
    ".well",
    ".rmswell",
    ".pol",
    ".poi",
    ".roffasc",
}
MAX_DIRECTORY_ENTRIES = 10_000
MAX_UPLOAD_BYTES = 256 * 1024**2


def revision(info):
    return digest(
        dict(
            device=info.st_dev,
            inode=info.st_ino,
            size=info.st_size,
            mtime_ns=info.st_mtime_ns,
            ctime_ns=info.st_ctime_ns,
        )
    )


def parts(path):
    require(
        "\\" not in path and "\x00" not in path and ":" not in path,
        "INVALID_SOURCE_PATH",
        "Неверный относительный путь",
    )
    p = PurePosixPath(path)
    require(
        not p.is_absolute()
        and all(not part.startswith(".") and not part.endswith((".", " ")) for part in p.parts),
        "INVALID_SOURCE_PATH",
        "Нужен относительный путь внутри source; скрытые пути и .. запрещены",
    )
    return p.parts


@contextmanager
def opened_source(source, path, directory=False):
    components = parts(path)
    require(directory or bool(components), "INVALID_SOURCE_PATH", "Выберите файл")
    if os.name == "nt":
        try:
            with windows_opened(Path(source["root"]), components, directory) as (fd, info):
                require(
                    (info.st_dev, info.st_ino) == (source["device"], source["inode"]),
                    "SOURCE_CHANGED",
                    "Корневая папка source заменена; требуется регистрация владельца",
                )
                yield fd, source
        except OSError as error:
            raise DomainError(
                "SOURCE_ACCESS_DENIED", "Source unavailable or contains a reparse point"
            ) from error
        return
    descriptors = []
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        current = os.open(source["root"], flags)
        descriptors.append(current)
        info = os.fstat(current)
        require(
            (info.st_dev, info.st_ino) == (source["device"], source["inode"]),
            "SOURCE_CHANGED",
            "Корневая папка source заменена; требуется регистрация владельца",
        )
        for index, component in enumerate(components):
            leaf = index == len(components) - 1
            entry_flags = flags if directory or not leaf else os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            current = os.open(component, entry_flags, dir_fd=current)
            descriptors.append(current)
        info = os.fstat(current)
        require(
            stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),
            "INVALID_SOURCE_PATH",
            "Нужна обычная папка/файл; специальные файлы запрещены",
        )
        yield current, source
    except OSError as error:
        raise DomainError("SOURCE_ACCESS_DENIED", "Source недоступен или путь содержит symlink") from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


class LocalSources:
    def __init__(self, store):
        self.store = store

    def list(self):
        return list(self.store.get_state(STATE, {}).values())

    def register(self, name, directory):
        require(bool(name.strip()) and len(name) <= 120, "INVALID_ARGUMENTS", "Укажите короткое имя source")
        root = normalized_path(directory)
        if os.name == "nt":
            with windows_opened(root, (), True) as (_, info):
                require(info.st_ino != 0, "SOURCE_ACCESS_DENIED", "Filesystem must expose a stable file ID")
        else:
            require(not root.is_symlink(), "SOURCE_ACCESS_DENIED", "Source cannot be a symlink")
            root = root.resolve()
            require(root.is_dir(), "INVALID_SOURCE_PATH", "Источник должен быть существующей папкой")
            info = root.stat()
        sources = self.store.get_state(STATE, {})
        existing = next(
            (s for s in sources.values() if os.path.normcase(s["root"]) == os.path.normcase(str(root))), None
        )
        if existing:
            require(
                (existing["device"], existing["inode"]) == (info.st_dev, info.st_ino),
                "SOURCE_CHANGED",
                "Папка заменена; удалите прежнюю регистрацию перед подключением",
            )
            return existing
        source = dict(
            id=uid("source"),
            name=name,
            root=str(root),
            device=info.st_dev,
            inode=info.st_ino,
            read_only=True,
            created_at=now(),
        )
        sources[source["id"]] = source
        self.store.set_state(STATE, sources)
        return source

    def remove(self, source_id):
        sources = self.store.get_state(STATE, {})
        require(source_id in sources, "NOT_FOUND", "Source не зарегистрирован")
        del sources[source_id]
        self.store.set_state(STATE, sources)
        return dict(source_id=source_id, removed=True)

    def get(self, source_id):
        source = self.store.get_state(STATE, {}).get(source_id)
        require(source is not None, "NOT_FOUND", "Source не зарегистрирован владельцем")
        return source

    @contextmanager
    def opened(self, source_id, path, directory=False):
        with opened_source(self.get(source_id), path, directory) as opened:
            yield opened

    def scan(self, p):
        entries = []
        with self.opened(p["source_id"], p["path"], directory=True) as (descriptor, _):
            with scan_descriptor(descriptor) as iterator:
                for count, entry in enumerate(iterator, 1):
                    require(
                        count <= MAX_DIRECTORY_ENTRIES,
                        "SOURCE_DIRECTORY_TOO_LARGE",
                        "Больше 10 000 записей; выберите более узкую папку",
                    )
                    if entry.name.startswith(".") or is_reparse(entry.stat(follow_symlinks=False)):
                        continue
                    directory = entry.is_dir(follow_symlinks=False)
                    if not directory and (
                        not entry.is_file(follow_symlinks=False)
                        or Path(entry.name).suffix.lower() not in EXTENSIONS
                    ):
                        continue
                    path = str(PurePosixPath(p["path"]) / entry.name)
                    if os.name == "nt" and not directory:
                        # Windows DirEntry.stat has zero volume/file IDs. Use the
                        # same pinned, no-reparse handle as every subsequent read.
                        with self.opened(p["source_id"], path) as (fd, _):
                            info = os.fstat(fd)
                    else:
                        info = entry.stat(follow_symlinks=False)
                    entries.append(
                        dict(
                            path=path,
                            kind="directory" if directory else "file",
                            size_bytes=None if directory else info.st_size,
                            file_revision=None if directory else revision(info),
                        )
                    )
        entries.sort(key=lambda e: e["path"])
        listing = digest(entries)
        require(
            p["offset"] == 0 or p["listing_revision"] is not None,
            "INVALID_ARGUMENTS",
            "Для следующей страницы передайте listing_revision",
        )
        require(
            p["listing_revision"] in (None, listing),
            "SOURCE_CHANGED",
            "Список файлов изменился; начните просмотр с первой страницы",
        )
        next_offset = p["offset"] + p["limit"]
        return dict(
            source_id=p["source_id"],
            path=p["path"],
            entries=entries[p["offset"] : next_offset],
            listing_revision=listing,
            total=len(entries),
            next_offset=next_offset if next_offset < len(entries) else None,
            content_read=False,
            supported_extensions=sorted(EXTENSIONS),
        )

    def upload(self, p):
        self.store.project(p["project_id"])
        require(Path(p["path"]).suffix.lower() in EXTENSIONS, "UNSUPPORTED_FORMAT", "Нужен CSV/LAS/SEG-Y")
        with self.opened(p["source_id"], p["path"]) as (descriptor, _):
            initial = os.fstat(descriptor)
            require(
                revision(initial) == p["file_revision"],
                "SOURCE_CHANGED",
                "Файл изменился; повторите source_scan",
            )
            require(
                initial.st_size <= MAX_UPLOAD_BYTES, "UPLOAD_TOO_LARGE", "Snapshot import ограничен 256 MiB"
            )
            with os.fdopen(os.dup(descriptor), "rb") as stream:
                owner = self

                class CheckedStream:
                    def read(self, size):
                        chunk = stream.read(size)
                        if not chunk:
                            owner.get(p["source_id"])  # Revocation checked before upload publication.
                            require(
                                revision(os.fstat(descriptor)) == p["file_revision"],
                                "SOURCE_CHANGED",
                                "Файл изменён во время копирования; snapshot не опубликован",
                            )
                        return chunk

                return self.store.upload(
                    p["project_id"],
                    Path(p["path"]).name,
                    CheckedStream(),
                    source=dict(source_id=p["source_id"], path=p["path"], file_revision=p["file_revision"]),
                )
