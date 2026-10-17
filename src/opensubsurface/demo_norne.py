"""Install the bundled public Norne artifacts for offline viewing; never run calculations."""

import hashlib
import json
from importlib.resources import as_file, files

from opensubsurface.errors import DomainError, require


def open_demo(store):
    folder = files("opensubsurface").joinpath("data/norne")
    declaration = json.loads(folder.joinpath("demo.json").read_text())
    pid = declaration["project_id"]
    try:
        store.project(pid)
    except DomainError as error:
        if error.code != "NOT_FOUND":
            raise
        with as_file(folder.joinpath("project.zip")) as path:
            require(
                hashlib.sha256(path.read_bytes()).hexdigest() == declaration["sha256"],
                "INTEGRITY_ERROR",
                "Bundled Norne demo hash mismatch",
            )
            store.import_project(path)
    return dict(project_id=pid, **{k: declaration[k] for k in ("scope", "license", "source_commit")})
