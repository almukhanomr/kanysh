"""Build a source-only UV-runtime MCPB; no user data, virtualenv or experimental code."""

import hashlib
import json
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(target=None):
    target = Path(target or ROOT / "dist/kanysh-basic-0.2.0-dev1.mcpb")
    manifest = dict(
        manifest_version="0.4",
        name="kanysh-basic",
        display_name="Kanysh Basic",
        version="0.2.0-dev.1",
        description="AI copilot for geological model calculations alongside Petrel/RMS",
        author=dict(name="Kanysh Basic contributors"),
        license="Apache-2.0",
        homepage="https://kanysh.com",
        server=dict(
            type="uv",
            entry_point="server.py",
            mcp_config=dict(
                command="uv",
                args=["run", "--directory", "${__dirname}", "server.py"],
                env={
                    "OPENSUBSURFACE_HOME": "${user_config.home}",
                    "KANYSH_SOURCE_FOLDER": "${user_config.data_folder}",
                    "PYTHONUTF8": "1",
                },
            ),
        ),
        user_config=dict(
            home=dict(
                type="directory",
                title="Local calculation home",
                description="Results and local metadata. Windows default: %LOCALAPPDATA%\\kanysh-basic. Other systems use ~/.kanysh-basic.",
                default=r"%LOCALAPPDATA%\kanysh-basic",
                required=True,
            ),
            data_folder=dict(
                type="directory",
                title="Model folder (optional)",
                description="Allow read-only access to this exported model folder. You can also add it in the viewer.",
                required=False,
            ),
        ),
        tools_generated=True,
        prompts_generated=True,
        compatibility=dict(platforms=["win32", "darwin", "linux"], runtimes=dict(python=">=3.12 <3.13")),
    )
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependencies = (
        pyproject["project"]["dependencies"]
        + pyproject["project"]["optional-dependencies"]["ui"]
        + pyproject["project"]["optional-dependencies"]["viewer"]
    )
    project = (
        '[project]\nname = "kanysh-basic-mcpb"\nversion = "0.2.0.dev1"\nrequires-python = ">=3.12,<3.13"\ndependencies = '
        + json.dumps(dependencies, indent=2)
        + "\n"
    )
    project += """
[tool.uv.sources]
torch = { index = "pytorch-cpu", marker = "sys_platform != 'darwin'" }
[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true
"""
    launcher = """import os
import sys
from pathlib import Path
source = str(Path(__file__).parent / "src")
sys.path.insert(0, source)
os.environ["PYTHONPATH"] = source + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")
from opensubsurface.desktop import run
if __name__ == "__main__":
    run()
"""
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        bundle.writestr("pyproject.toml", project)
        bundle.writestr("server.py", launcher)
        for path in sorted((ROOT / "src/opensubsurface").rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                bundle.write(path, path.relative_to(ROOT))
        for name in ("LICENSE", "NOTICE", "THIRD_PARTY.md"):
            bundle.write(ROOT / name, name)
    with zipfile.ZipFile(target) as bundle:
        assert bundle.testzip() is None
        assert not any(
            "__pycache__" in n or n.startswith(("experimental/", ".data/", ".venv/"))
            for n in bundle.namelist()
        )
        assert json.loads(bundle.read("manifest.json"))["server"]["type"] == "uv"
    return dict(
        path=str(target),
        sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        archive_check="PASS",
        host_installation="NOT RUN",
        windows_acceptance="NOT RUN",
        dependency_installation="Host UV runtime; requires network and compatible packages",
    )


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
