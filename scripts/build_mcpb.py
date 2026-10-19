"""Build CPU/GPU source bundles with per-variant UV locks and the official MCPB CLI."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# shutil.which finds npx.cmd on Windows, where CreateProcess cannot run a bare "npx".
MCPB = [shutil.which("npx") or "npx", "--yes", "@anthropic-ai/mcpb@2.1.2"]


def configuration(variant):
    if variant not in ("cpu", "gpu"):
        raise ValueError("variant must be cpu or gpu")
    root = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = root["version"]
    name = "kanysh-basic" + ("-gpu" if variant == "gpu" else "")
    manifest = dict(
        manifest_version="0.4",
        name=name,
        display_name="Kanysh Basic" + (" (GPU)" if variant == "gpu" else ""),
        version=version.replace(".dev", "-dev."),
        description=(
            "AI copilot for geological models. "
            + (
                "GPU: first installation downloads approximately 2.5 GB; CPU fallback without CUDA."
                if variant == "gpu"
                else "CPU edition with a local web viewer."
            )
        ),
        author=dict(name="Kanysh Basic contributors"),
        license="Apache-2.0",
        homepage="https://kanysh.com",
        server=dict(
            type="uv",
            entry_point="server.py",
            mcp_config=dict(
                command="uv",
                args=["run", "--frozen", "--directory", "${__dirname}", "server.py"],
                env={
                    "OPENSUBSURFACE_HOME": "${user_config.home}",
                    "KANYSH_SOURCE_FOLDER": "${user_config.data_folder}",
                    "KANYSH_VARIANT": variant,
                    "PYTHONUTF8": "1",
                },
            ),
        ),
        user_config=dict(
            home=dict(
                type="directory",
                title="Local calculation home",
                description="Local metadata and results. The resolved path is shown in the viewer and startup-status.json; MSIX may virtualize LocalAppData.",
                default="%LOCALAPPDATA%" + chr(92) + name,
                required=True,
            ),
            data_folder=dict(
                type="directory",
                title="Model folder (optional)",
                description="Allow read-only access to exported models; can also be added in the viewer.",
                required=False,
            ),
        ),
        tools_generated=True,
        prompts_generated=True,
        compatibility=dict(platforms=["win32", "darwin", "linux"], runtimes=dict(python=">=3.12 <3.13")),
    )
    deps = (
        root["dependencies"] + root["optional-dependencies"]["ui"] + root["optional-dependencies"]["viewer"]
    )
    index = "pytorch-cpu" if variant == "cpu" else "pytorch-cu126"
    url = "https://download.pytorch.org/whl/" + ("cpu" if variant == "cpu" else "cu126")
    project = (
        "[project]\nname = "
        + json.dumps(name + "-mcpb")
        + "\nversion = "
        + json.dumps(version)
        + '\nrequires-python = ">=3.12,<3.13"\ndependencies = '
        + json.dumps(deps, indent=2)
        + "\n"
        + '\n[tool.uv]\npackage = false\n[tool.uv.sources]\ntorch = { index = "'
        + index
        + '", marker = "sys_platform != \'darwin\'" }\n[[tool.uv.index]]\nname = "'
        + index
        + '"\nurl = "'
        + url
        + '"\nexplicit = true\n'
    )
    return manifest, project


def prepare_lock(variant, refresh=False):
    _, project = configuration(variant)
    folder = ROOT / "deploy/mcpb" / variant
    folder.mkdir(parents=True, exist_ok=True)
    pyproject = folder / "pyproject.toml"
    if refresh:
        pyproject.write_text(project, encoding="utf-8")
        subprocess.run(
            [
                shutil.which("uv")
                or str(ROOT / (".venv/Scripts/uv.exe" if os.name == "nt" else ".venv/bin/uv")),
                "lock",
                "--directory",
                str(folder),
            ],
            check=True,
        )
    if (
        not pyproject.is_file()
        or pyproject.read_text(encoding="utf-8") != project
        or not (folder / "uv.lock").is_file()
    ):
        raise RuntimeError(
            f"Stale/missing {variant} lock: run scripts/build_mcpb.py --variant {variant} --refresh-lock"
        )
    return folder


def build(target=None, variant="cpu", *, official=False, refresh_lock=False):
    manifest, project = configuration(variant)
    name, version = manifest["name"], manifest["version"].replace("-dev.", "-dev")
    target = Path(target or ROOT / "dist" / f"{name}-{version}.mcpb").resolve()
    locked = prepare_lock(variant, refresh_lock)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kanysh-mcpb-") as temp:
        stage = Path(temp)
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (stage / "pyproject.toml").write_text(project, encoding="utf-8")
        shutil.copyfile(locked / "uv.lock", stage / "uv.lock")
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
        (stage / "server.py").write_text(launcher, encoding="utf-8")
        shutil.copytree(
            ROOT / "src/opensubsurface",
            stage / "src/opensubsurface",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        for filename in ("LICENSE", "NOTICE", "THIRD_PARTY.md"):
            shutil.copyfile(ROOT / filename, stage / filename)
        if official:
            subprocess.run([*MCPB, "validate", str(stage / "manifest.json")], check=True)
            subprocess.run([*MCPB, "pack", str(stage), str(target)], check=True)
        else:
            # Offline archive assembly for unit tests; release CLI always uses official pack.
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for path in sorted(stage.rglob("*")):
                    if path.is_file():
                        bundle.write(path, path.relative_to(stage).as_posix())
    with zipfile.ZipFile(target) as bundle:
        assert bundle.testzip() is None
        assert not any(
            "__pycache__" in n or n.startswith(("experimental/", ".data/", ".venv/"))
            for n in bundle.namelist()
        )
    return dict(
        path=str(target),
        variant=variant,
        sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        archive_check="PASS",
        mcpb_validate="PASS" if official else "NOT RUN (unit archive)",
        packager="mcpb pack 2.1.2" if official else "unit-test ZIP",
        lock_file=str(locked / "uv.lock"),
        host_installation="NOT RUN",
        windows_acceptance="NOT RUN",
        dependency_installation="Host UV runtime, before Python entry point; network required",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=["cpu", "gpu"], default="cpu")
    parser.add_argument("--refresh-lock", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(build(args.output, args.variant, official=True, refresh_lock=args.refresh_lock), indent=2)
    )
