"""OPM Flow executors: native Linux, or Windows through a dedicated WSL2 distribution.

Simulation is optional. Nothing here runs at MCP start-up; status() is cheap and never
boots a WSL distribution. Docker Desktop is deliberately not used (licensing for large
companies and common corporate bans). The user's own WSL distributions are never touched.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from opensubsurface.errors import DomainError

DISTRO = os.environ.get("KANYSH_OPM_DISTRO", "kanysh-opm")
BASE_IMAGE = "Ubuntu-24.04"
PACKAGES = ("mpi-default-bin", "libopm-simulators-bin")
RUNTIME_FILE = "opm-runtime.json"
PID_FILE = ".kanysh-flow.pid"
WSL_ENV = dict(os.environ, WSL_UTF8="1")


def _wsl(*args, timeout=60, check=False, user="root"):
    # -e executes directly: no intermediate shell re-expanding $ or quotes.
    command = ["wsl.exe", "-d", DISTRO, "-u", user, "-e", *args]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=check,
        env=WSL_ENV,
    )


def wsl_present():
    if sys.platform != "win32" or shutil.which("wsl.exe") is None:
        return False, None
    try:
        status = subprocess.run(
            ["wsl.exe", "--list", "--quiet"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=WSL_ENV,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, None
    if status.returncode != 0:
        return False, None
    names = {line.strip().strip("\x00") for line in status.stdout.splitlines() if line.strip()}
    return True, DISTRO in names


def recorded(home):
    try:
        return json.loads((Path(home) / RUNTIME_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def remediation():
    if sys.platform == "win32":
        return (
            "OPM Flow runs in WSL2 on Windows. 1) If WSL is missing: in an administrator PowerShell run "
            "`wsl --install --no-distribution` and reboot (needs virtualization enabled in BIOS). "
            "2) Then run `kanysh-basic setup-opm` (creates the separate 'kanysh-opm' distribution, installs "
            "a pinned OPM Flow and runs a self-test). Static calculations work without this."
        )
    return (
        "Install OPM Flow (e.g. Ubuntu: add-apt-repository ppa:opm/ppa && apt-get install "
        "mpi-default-bin libopm-simulators-bin), or set OPENSUBSURFACE_FLOW_EXECUTABLE, then run "
        "`kanysh-basic setup-opm` to pin and self-test it."
    )


def status(home):
    """Cheap availability report for diagnostics and preflight (no distribution boot)."""
    pinned = recorded(home)
    if sys.platform.startswith("linux"):
        executable = shutil.which(os.environ.get("OPENSUBSURFACE_FLOW_EXECUTABLE", "flow"))
        ok = executable is not None and pinned is not None and pinned.get("executor") == "linux"
        return dict(
            available=ok,
            executor="linux",
            flow=executable,
            pinned=pinned,
            reason=None if ok else ("flow not found" if executable is None else "not pinned/self-tested"),
            remediation=None if ok else remediation(),
        )
    if sys.platform == "win32":
        wsl, distro = wsl_present()
        ok = bool(wsl and distro and pinned and pinned.get("executor") == "wsl")
        reason = (
            None
            if ok
            else "WSL2 is not installed or not enabled"
            if not wsl
            else f"WSL distribution '{DISTRO}' not created"
            if not distro
            else "OPM not pinned/self-tested in WSL"
        )
        return dict(
            available=ok,
            executor="wsl",
            distribution=DISTRO,
            wsl_installed=wsl,
            distribution_present=distro,
            pinned=pinned,
            reason=reason,
            remediation=None if ok else remediation(),
        )
    return dict(available=False, executor=None, reason="Unsupported platform", remediation=remediation())


def require_available(home):
    state = status(home)
    if not state["available"]:
        raise DomainError(
            "SIMULATOR_UNAVAILABLE",
            "OPM Flow is not set up on this computer: " + str(state["reason"]),
            "",
            state["remediation"],
            dict(simulator=state),
        )
    return state


def probe(executor):
    """Identify the installed flow: version line, binary sha256, package version."""
    if executor == "wsl":
        version = _wsl("flow", "--version", timeout=120)
        binary = _wsl("bash", "-c", "sha256sum $(readlink -f $(command -v flow))", timeout=120)
        package = _wsl("dpkg-query", "-W", "-f=${Version}", "libopm-simulators-bin", timeout=60)
        release = _wsl("bash", "-c", ". /etc/os-release && echo $PRETTY_NAME", timeout=60)
        if version.returncode != 0:
            raise DomainError("SIMULATOR_UNAVAILABLE", "flow --version failed in WSL", "", remediation())
        return dict(
            executor="wsl",
            distribution=DISTRO,
            os=release.stdout.strip(),
            flow_version=version.stdout.strip().splitlines()[-1] if version.stdout.strip() else "",
            flow_sha256=binary.stdout.split()[0] if binary.stdout.split() else None,
            package_version=package.stdout.strip() or None,
        )
    executable = shutil.which(os.environ.get("OPENSUBSURFACE_FLOW_EXECUTABLE", "flow"))
    if executable is None:
        raise DomainError("SIMULATOR_UNAVAILABLE", "flow executable not found", "", remediation())
    from opensubsurface.persistence.store import file_hash

    version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=120)
    return dict(
        executor="linux",
        flow=str(Path(executable).resolve()),
        flow_version=version.stdout.strip().splitlines()[-1] if version.stdout.strip() else "",
        flow_sha256=file_hash(Path(executable).resolve()),
        package_version=None,
    )


def verify_pin(home):
    """The binary must still be the one pinned and self-tested by setup-opm."""
    pinned = recorded(home)
    current = probe(pinned["executor"])
    if current["flow_sha256"] != pinned["flow_sha256"] or current["flow_version"] != pinned["flow_version"]:
        raise DomainError(
            "STALE_SOLVER",
            "Installed OPM Flow differs from the pinned, self-tested version",
            "",
            "Re-run `kanysh-basic setup-opm` to re-pin and self-test the current OPM Flow.",
            dict(pinned=pinned, current=current),
        )
    return pinned


def command(executor, deck, output, threads, strictness="normal"):
    """argv that runs flow on deck (a local path); output is a sibling directory name."""
    options = [
        f"--output-dir={output}",
        f"--threads-per-process={threads}",
        f"--parsing-strictness={strictness}",
    ]
    if executor == "wsl":
        script = f'echo $$ > {PID_FILE}; exec flow "$1" ' + " ".join(options)
        return [
            "wsl.exe",
            "-d",
            DISTRO,
            "--cd",
            str(Path(deck).parent),
            "-e",
            "bash",
            "-c",
            script,
            "flow",
            deck.name,
        ]
    executable = shutil.which(os.environ.get("OPENSUBSURFACE_FLOW_EXECUTABLE", "flow"))
    return [executable, deck.name, *options]


def kill_external(directory):
    """Stop a flow left running inside WSL after its Windows wsl.exe parent was terminated."""
    if sys.platform != "win32":
        return False
    for pid_file in Path(directory).rglob(PID_FILE):
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        try:
            _wsl("kill", "-TERM", str(pid), timeout=30)
            _wsl("bash", "-c", f"sleep 2; kill -KILL {pid} 2>/dev/null || true", timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            pass
        pid_file.unlink(missing_ok=True)
        return True
    return False


def setup(home, log=print, install=True):
    """Owner command: create/verify the executor, pin OPM Flow, self-test, record opm-runtime.json.

    Never elevates privileges and never edits the user's other WSL distributions.
    """
    home = Path(home)
    if sys.platform == "win32":
        wsl, distro = wsl_present()
        if not wsl:
            raise DomainError("WSL_UNAVAILABLE", "WSL2 is not installed or not enabled", "", remediation())
        if not distro:
            if not install:
                raise DomainError(
                    "SIMULATOR_UNAVAILABLE", f"WSL distribution '{DISTRO}' missing", "", remediation()
                )
            log(f"Creating WSL distribution '{DISTRO}' from {BASE_IMAGE} (download, a few minutes)...")
            created = subprocess.run(
                ["wsl.exe", "--install", BASE_IMAGE, "--name", DISTRO, "--no-launch"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3600,
                env=WSL_ENV,
            )
            if created.returncode != 0 or not wsl_present()[1]:
                raise DomainError(
                    "SETUP_FAILED",
                    "Could not create the WSL distribution: " + (created.stdout + created.stderr)[-1500:],
                    "",
                    "Check network/Microsoft Store access and WSL policy; run `wsl --update`, then retry.",
                )
        if install:
            log("Installing OPM Flow from the official OPM PPA inside WSL (apt)...")
            script = (
                "set -e; export DEBIAN_FRONTEND=noninteractive; apt-get update -q; "
                "apt-get install -y -q software-properties-common; add-apt-repository -y ppa:opm/ppa; "
                "apt-get update -q; apt-get install -y -q " + " ".join(PACKAGES) + "; "
                "apt-mark hold " + " ".join(PACKAGES)
            )
            installed = _wsl("bash", "-c", script, timeout=7200)
            if installed.returncode != 0:
                raise DomainError(
                    "SETUP_FAILED",
                    "OPM installation in WSL failed: " + (installed.stdout + installed.stderr)[-2000:],
                    "",
                    "Check network/proxy access to ppa.launchpadcontent.net and archive.ubuntu.com, then retry.",
                )
        executor = "wsl"
    elif sys.platform.startswith("linux"):
        executor = "linux"
    else:
        raise DomainError(
            "SIMULATOR_UNAVAILABLE", "OPM Flow executors: Linux or Windows+WSL2", "", remediation()
        )
    identity = probe(executor)
    log("Self-test: SPE1 (repository copy of the OPM reference deck)...")
    test = selftest(home, executor)
    held = None
    if executor == "wsl":
        holds = set(_wsl("apt-mark", "showhold", timeout=60).stdout.split())
        held = all(name in holds for name in PACKAGES)
    record = dict(identity, selftest=test, packages=list(PACKAGES), held=held)
    from opensubsurface.persistence.store import now

    record["pinned_at"] = now()
    (home / RUNTIME_FILE).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def selftest(home, executor):
    import tempfile
    from importlib.resources import files

    from opensubsurface.simulation import summary

    # Unmodified OPM SPE1 reference deck (ODbL header retained), shipped with the package.
    deck = Path(str(files("opensubsurface").joinpath("data/opm/SPE1CASE2.DATA")))
    # WSL may hold the directory briefly after exit; never mask the real error.
    with tempfile.TemporaryDirectory(dir=home, ignore_cleanup_errors=True) as temp:
        work = Path(temp) / "deck"
        work.mkdir()
        local = work / "SPE1CASE2.DATA"
        shutil.copyfile(deck, local)
        with (Path(temp) / "flow.log").open("w", encoding="utf-8") as stream:
            result = subprocess.run(
                command(executor, local, "out", 1),
                cwd=work,
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=1800,
                env=WSL_ENV,
            )
        log_tail = (Path(temp) / "flow.log").read_text(encoding="utf-8", errors="replace")[-2000:]
        smspec = work / "out" / "SPE1CASE2.SMSPEC"
        if result.returncode != 0 or not smspec.is_file():
            raise DomainError("SETUP_FAILED", "OPM self-test on SPE1 failed: " + log_tail, "", remediation())
        data = summary.read(smspec)
        # SPE1 reports FOPR (not FOPT) over a 10-year (3650-day) schedule.
        rate = float(summary.vector(data, "FOPR").max())
        if not (rate > 0 and data["days"][-1] >= 3650 - 1e-6):
            raise DomainError(
                "SETUP_FAILED", "Self-test did not complete the SPE1 schedule", "", remediation()
            )
        return dict(case="SPE1CASE2", status="PASS", days=float(data["days"][-1]), max_FOPR=rate)
