"""Immutable JSON manifests + content-addressed files; SQLAlchemy metadata on local SQLite."""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import portalocker
from sqlalchemy import Column, Integer, MetaData, String, Table, UniqueConstraint, create_engine, select

from opensubsurface.errors import require


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


metadata = MetaData()
projects = Table("projects", metadata, Column("id", String, primary_key=True), Column("data", String))
objects = Table(
    "objects",
    metadata,
    Column("id", String, primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("project_id", String, index=True),
    Column("kind", String),
    Column("data", String),
)
jobs = Table(
    "jobs",
    metadata,
    Column("id", String, primary_key=True),
    Column("project_id", String, index=True),
    Column("operation", String),
    Column("key", String, nullable=True),
    Column("payload_hash", String),
    Column("data", String),
    UniqueConstraint("project_id", "operation", "key"),
)
uploads = Table(
    "uploads",
    metadata,
    Column("id", String, primary_key=True),
    Column("project_id", String),
    Column("data", String),
)
state = Table("state", metadata, Column("id", String, primary_key=True), Column("data", String))


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for directory in ("blobs", "uploads", "attempts"):
            (self.root / directory).mkdir(exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.root / 'metadata.db'}", connect_args={"check_same_thread": False, "timeout": 30}
        )
        self.lock = threading.RLock()
        # Serialize WAL setup, Alembic's version-table creation and schema marker.
        # This lock is distinct from the executor ownership lock.
        try:
            with portalocker.Lock(self.root / "migrate.lock", mode="a", timeout=120):
                with self.engine.connect() as c:
                    c.exec_driver_sql("PRAGMA journal_mode=WAL")
                    c.commit()
                from alembic import command
                from alembic.config import Config

                config = Config()
                config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
                with self.engine.begin() as connection:
                    config.attributes["connection"] = connection
                    command.upgrade(config, "head")
                self.set_state("schema_version", {"version": 1})
        except BaseException:
            self.engine.dispose()
            raise

    def set_state(self, key, value):
        with self.lock, self.engine.begin() as c:
            c.execute(state.delete().where(state.c.id == key))
            c.execute(state.insert().values(id=key, data=canonical(value)))

    def get_state(self, key, default=None):
        with self.engine.connect() as c:
            row = c.execute(select(state.c.data).where(state.c.id == key)).scalar_one_or_none()
        return json.loads(row) if row else default

    def create_project(self, data):
        record = dict(id=uid("project"), schema_version=1, created_at=now(), **data)
        with self.engine.begin() as c:
            c.execute(projects.insert().values(id=record["id"], data=canonical(record)))
        return record

    def project(self, project_id):
        with self.engine.connect() as c:
            raw = c.execute(select(projects.c.data).where(projects.c.id == project_id)).scalar_one_or_none()
        require(raw is not None, "NOT_FOUND", "Проект не найден", "project_id")
        return json.loads(raw)

    def list_projects(self):
        with self.engine.connect() as c:
            return [json.loads(row) for row in c.execute(select(projects.c.data)).scalars()]

    def list_objects(self, project_id, limit=200, offset=0):
        self.project(project_id)
        with self.engine.connect() as c:
            return [
                json.loads(r)
                for r in c.execute(
                    select(objects.c.data)
                    .where(objects.c.project_id == project_id)
                    .order_by(objects.c.id, objects.c.revision)
                    .limit(min(limit, 200))
                    .offset(offset)
                ).scalars()
            ]

    def object(self, project_id, ref, verify=True):
        if hasattr(ref, "model_dump"):
            ref = ref.model_dump()
        with self.engine.connect() as c:
            raw = c.execute(
                select(objects.c.data).where(
                    objects.c.id == ref["id"],
                    objects.c.revision == ref["revision"],
                    objects.c.project_id == project_id,
                )
            ).scalar_one_or_none()
        require(raw is not None, "INPUT_REVISION_CONFLICT", "Объект или ревизия недоступны", "ref")
        obj = json.loads(raw)
        if verify:
            self.verify(obj)
        return obj

    def verify(self, obj):
        for name, h in obj.get("files", {}).items():
            path = self.root / "blobs" / h
            require(
                path.is_file() and file_hash(path) == h,
                "INTEGRITY_ERROR",
                "Нарушена целостность артефакта",
                name,
                "Восстановите durable store из резервной копии",
            )
        data = {k: v for k, v in obj.items() if k != "content_hash"}
        require(digest(data) == obj["content_hash"], "INTEGRITY_ERROR", "Нарушена целостность manifest")

    def publish(self, project_id, kind, summary, files=None, parameters=None, sources=None, object_id=None):
        self.project(project_id)
        file_refs = {}
        for name, source in (files or {}).items():
            require(PurePosixPath(name).name == name, "INVALID_PATH", "Недопустимое имя файла")
            h = file_hash(source)
            dest = self.root / "blobs" / h
            if not dest.exists() or file_hash(dest) != h:
                tmp = dest.with_suffix("." + uuid.uuid4().hex)
                shutil.copyfile(source, tmp)
                os.replace(tmp, dest)
            file_refs[name] = h
        with self.lock, self.engine.begin() as c:
            object_id = object_id or uid(kind)
            existing_project = c.execute(
                select(objects.c.project_id).where(objects.c.id == object_id)
            ).scalar()
            require(
                existing_project is None or existing_project == project_id,
                "PERMISSION_DENIED",
                "Нельзя создавать ревизию объекта другого проекта",
            )
            revisions = c.execute(select(objects.c.revision).where(objects.c.id == object_id)).scalars().all()
            record = dict(
                id=object_id,
                project_id=project_id,
                revision=max(revisions, default=0) + 1,
                kind=kind,
                schema_version=1,
                created_at=now(),
                source_ids=sources or [],
                parameters=parameters or {},
                summary=summary,
                files=file_refs,
            )
            record["content_hash"] = digest(record)
            c.execute(
                objects.insert().values(
                    id=object_id,
                    revision=record["revision"],
                    project_id=project_id,
                    kind=kind,
                    data=canonical(record),
                )
            )
        return record

    def path(self, obj, name):
        require(name in obj["files"], "NOT_FOUND", "Файл артефакта не найден")
        self.verify(obj)
        return self.root / "blobs" / obj["files"][name]

    def upload(self, project_id, name, stream, max_bytes=256 * 1024 * 1024, source=None):
        self.project(project_id)
        upload_id = uid("upload")
        path = self.root / "uploads" / upload_id
        total = 0
        try:
            with path.open("wb") as out:
                while chunk := stream.read(1024 * 1024):
                    total += len(chunk)
                    require(total <= max_bytes, "UPLOAD_TOO_LARGE", "Превышен лимит загрузки 256 MB")
                    out.write(chunk)
            record = dict(
                id=upload_id,
                project_id=project_id,
                name=Path(name).name,
                size_bytes=total,
                content_hash=file_hash(path),
            )
            if source is not None:
                record["source"] = source
            with self.engine.begin() as c:
                c.execute(
                    uploads.insert().values(id=upload_id, project_id=project_id, data=canonical(record))
                )
            return record
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def upload_record(self, project_id, upload_id):
        with self.engine.connect() as c:
            raw = c.execute(
                select(uploads.c.data).where(uploads.c.id == upload_id, uploads.c.project_id == project_id)
            ).scalar_one_or_none()
        require(raw is not None, "NOT_FOUND", "Загрузка недоступна в этом проекте")
        return json.loads(raw)

    def upload_path(self, project_id, upload_id):
        record = self.upload_record(project_id, upload_id)
        path = self.root / "uploads" / record["id"]
        require(file_hash(path) == record["content_hash"], "INTEGRITY_ERROR", "Загрузка повреждена")
        return path

    def put_job(self, operation, payload):
        h = digest(payload)
        key = payload.get("idempotency_key")
        with self.lock, self.engine.begin() as c:
            if key:
                row = c.execute(
                    select(jobs.c.data, jobs.c.payload_hash).where(
                        jobs.c.project_id == payload["project_id"],
                        jobs.c.operation == operation,
                        jobs.c.key == key,
                    )
                ).first()
                if row:
                    require(row[1] == h, "IDEMPOTENCY_CONFLICT", "Ключ уже использован с другим запросом")
                    return json.loads(row[0]), False
            record = dict(
                id=uid("job"),
                project_id=payload["project_id"],
                operation=operation,
                status="queued",
                stage="В очереди",
                created_at=now(),
                updated_at=now(),
                attempt_id=uid("attempt"),
                attempts=[],
                payload=payload,
                payload_hash=h,
                backend=None,
                target="local-cpu",
                warnings=[],
                events=[],
                result=None,
                error=None,
            )
            c.execute(
                jobs.insert().values(
                    id=record["id"],
                    project_id=payload["project_id"],
                    operation=operation,
                    key=key,
                    payload_hash=h,
                    data=canonical(record),
                )
            )
            return record, True

    def job(self, job_id):
        with self.engine.connect() as c:
            raw = c.execute(select(jobs.c.data).where(jobs.c.id == job_id)).scalar_one_or_none()
        require(raw is not None, "NOT_FOUND", "Задание не найдено")
        return json.loads(raw)

    def update_job(self, job_id, **changes):
        with self.lock, self.engine.begin() as c:
            raw = c.execute(select(jobs.c.data).where(jobs.c.id == job_id)).scalar_one()
            record = json.loads(raw)
            if record["status"] in ("succeeded", "failed", "cancelled", "interrupted"):
                return record
            record.update(changes, updated_at=now())
            if "stage" in changes:
                record["events"].append({"time": now(), "stage": changes["stage"]})
            c.execute(jobs.update().where(jobs.c.id == job_id).values(data=canonical(record)))
            return record

    def list_jobs(self, project_id=None, limit=200):
        with self.engine.connect() as c:
            query = select(jobs.c.data)
            if project_id:
                query = query.where(jobs.c.project_id == project_id)
            records = [json.loads(r) for r in c.execute(query).scalars()]
            records.sort(key=lambda r: r["created_at"])
            return records if limit is None else records[-min(limit, 200) :]

    def export_project(self, project_id, path):
        project = self.project(project_id)
        with self.engine.connect() as c:
            records = [
                json.loads(r)
                for r in c.execute(select(objects.c.data).where(objects.c.project_id == project_id)).scalars()
            ]
        manifest = dict(schema_version=1, project=project, objects=records)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", canonical(manifest))
            seen = set()
            for obj in records:
                self.verify(obj)
                for h in obj["files"].values():
                    if h not in seen:
                        z.write(self.root / "blobs" / h, f"blobs/{h}")
                        seen.add(h)
        return str(path)

    def import_project(self, path):
        # Validate the entire bundle before publishing any metadata.
        with zipfile.ZipFile(path) as z:
            names = [i.filename for i in z.infolist()]
            require(len(names) == len(set(names)), "INVALID_ARCHIVE", "Дубли путей в ZIP")
            require(
                sum(i.file_size for i in z.infolist()) <= 512 * 1024**2,
                "INVALID_ARCHIVE",
                "Распакованный ZIP превышает 512 MB",
            )
            for name in names:
                p = PurePosixPath(name)
                require(
                    not p.is_absolute() and ".." not in p.parts and "\\" not in name,
                    "INVALID_ARCHIVE",
                    "Небезопасный путь в ZIP",
                )
            require("manifest.json" in names, "INVALID_ARCHIVE", "Отсутствует manifest")
            require(
                z.getinfo("manifest.json").file_size <= 8 * 1024**2,
                "INVALID_ARCHIVE",
                "Manifest слишком велик",
            )
            manifest = json.loads(z.read("manifest.json"))
            require(manifest.get("schema_version") == 1, "INVALID_ARCHIVE", "Неизвестная схема")
            project = manifest["project"]
            require(
                re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,100}", project.get("id", "")) is not None,
                "INVALID_ARCHIVE",
                "Недопустимый project ID",
            )
            from opensubsurface.schemas import ProjectCreate

            ProjectCreate.model_validate(
                {k: project[k] for k in ("name", "crs", "vertical_datum", "length_unit")}
            )
            allowed = {"id", "name", "crs", "vertical_datum", "length_unit", "schema_version", "created_at"}
            require(set(project) <= allowed, "INVALID_ARCHIVE", "Неизвестные поля проекта")
            referenced = set()
            for obj in manifest["objects"]:
                require(
                    re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,100}", obj.get("id", "")) is not None,
                    "INVALID_ARCHIVE",
                    "Недопустимый object ID",
                )
                require(
                    isinstance(obj.get("revision"), int)
                    and obj["revision"] > 0
                    and obj.get("schema_version") == 1,
                    "INVALID_ARCHIVE",
                    "Неизвестная schema/revision",
                )
                require(obj["project_id"] == project["id"], "INVALID_ARCHIVE", "Чужой объект")
                require(
                    digest({k: v for k, v in obj.items() if k != "content_hash"}) == obj["content_hash"],
                    "INTEGRITY_ERROR",
                    "Повреждён manifest",
                )
                for name, h in obj["files"].items():
                    require(
                        len(h) == 64 and all(c in "0123456789abcdef" for c in h),
                        "INVALID_ARCHIVE",
                        "Неверный hash",
                    )
                    require(PurePosixPath(name).name == name, "INVALID_ARCHIVE", "Неверное имя файла")
                    referenced.add(h)
            require(
                set(names) == {"manifest.json"} | {f"blobs/{h}" for h in referenced},
                "INVALID_ARCHIVE",
                "Лишние или недостающие файлы",
            )
            with tempfile.TemporaryDirectory(dir=self.root) as temp:
                for h in referenced:
                    dest = Path(temp) / h
                    with z.open(f"blobs/{h}") as source, dest.open("wb") as out:
                        shutil.copyfileobj(source, out)
                    require(file_hash(dest) == h, "INTEGRITY_ERROR", "Повреждён blob")
                with self.lock, self.engine.begin() as c:
                    require(
                        c.execute(select(projects.c.id).where(projects.c.id == project["id"])).first()
                        is None,
                        "CONFLICT",
                        "Проект с таким ID уже существует",
                    )
                    for h in referenced:
                        dest = self.root / "blobs" / h
                        if not dest.exists() or file_hash(dest) != h:
                            os.replace(Path(temp) / h, dest)
                    c.execute(projects.insert().values(id=project["id"], data=canonical(project)))
                    for obj in manifest["objects"]:
                        c.execute(
                            objects.insert().values(
                                id=obj["id"],
                                revision=obj["revision"],
                                project_id=project["id"],
                                kind=obj["kind"],
                                data=canonical(obj),
                            )
                        )
        return project

    def backup(self, dest):
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        with (
            sqlite3.connect(self.root / "metadata.db") as source,
            sqlite3.connect(dest / "metadata.db") as out,
        ):
            source.backup(out)
        shutil.copytree(self.root / "blobs", dest / "blobs", dirs_exist_ok=True)
        shutil.copytree(self.root / "uploads", dest / "uploads", dirs_exist_ok=True)
