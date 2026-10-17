"""Audit Git upload candidates without reading ignored owner data or printing secret values."""

import argparse
import io
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

SIGNATURES = {
    "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "github_token": rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b",
    "aws_access_key": rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "provider_token": rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b",
    "slack_token": rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b",
    "personal_path": rb"/Users/[A-Za-z0-9_.-]+/",
    "development_environment": rb"(?i)co" + rb"dex",
}
LOCAL_DIRS = {
    ".git",
    ".venv",
    ".data",
    ".mcp-data",
    ".mcp-desktop",
    ".kanysh-basic",
    ".opensubsurface",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "test-results",
    "playwright-report",
    "dist",
    "experimental",
    ".idea",
    ".vscode",
}
PRIVATE_NAMES = {
    ".env",
    ".envrc",
    ".mcp.json",
    ".claude.json",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}


def candidate_files(root):
    root = Path(root).resolve()
    probe = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True)
    if probe.returncode == 0:
        if Path(probe.stdout.decode().strip()).resolve() != root:
            raise ValueError("Run this audit at the project Git root")
        command = ["git", "-C", str(root)]
        return _listed(command)
    # A temporary index applies the real ignore rules before the first git init.
    with tempfile.TemporaryDirectory(prefix="kanysh-publication-audit-") as temporary:
        git_dir = Path(temporary) / "git"
        subprocess.run(["git", "init", "--bare", "-q", str(git_dir)], check=True, capture_output=True)
        return _listed(["git", "--git-dir=" + str(git_dir), "--work-tree=" + str(root)])


def _listed(command):
    result = subprocess.run(
        command + ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=True,
        capture_output=True,
    )
    return sorted(set(p for p in result.stdout.decode().split("\0") if p))


def inspect_project(root):
    root = Path(root).resolve()
    files = candidate_files(root)
    findings = []
    members = 0
    total_bytes = 0

    def finding(kind, path):
        findings.append(dict(kind=kind, path=path))

    def scan(body, label, depth=0):
        nonlocal members
        members += 1
        for kind, pattern in SIGNATURES.items():
            if re.search(pattern, body):
                finding(kind, label)
        if body.startswith(b"PK\x03\x04"):
            if depth >= 4:
                finding("archive_depth_limit", label)
                return
            try:
                with zipfile.ZipFile(io.BytesIO(body)) as archive:
                    if sum(m.file_size for m in archive.infolist()) > 256 * 1024**2:
                        finding("archive_size_limit", label)
                        return
                    for item in archive.infolist():
                        if not item.is_dir():
                            member = PurePosixPath(item.filename)
                            member_label = label + "!" + item.filename
                            if member.is_absolute() or ".." in member.parts:
                                finding("unsafe_archive_path", member_label)
                            if member.name in PRIVATE_NAMES or (
                                member.name.startswith(".env.") and member.name != ".env.example"
                            ):
                                finding("local_configuration", member_label)
                            if any(part in LOCAL_DIRS for part in member.parts[:-1]):
                                finding("local_artifact", member_label)
                            if re.search(r"\.(?:db|sqlite3?)(?:-(?:wal|shm|journal))?$", member.name):
                                finding("private_or_generated_file", member_label)
                            scan(archive.read(item), member_label, depth + 1)
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
                finding("unreadable_archive", label)

    for name in files:
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts:
            finding("unsafe_git_path", name)
            continue
        path = root / name
        if path.is_symlink():
            finding("symlink", name)
            continue
        if not path.is_file():
            finding("missing_file", name)
            continue
        if any(part in LOCAL_DIRS for part in relative.parts[:-1]):
            finding("local_artifact", name)
        if (
            relative.parts[0] == "state"
            or any(p in {"raw", "prepared", "state", "full"} for p in relative.parts[2:-1])
        ) and relative.parts[0] in {"state", "examples"}:
            finding("owner_state_or_download", name)
        if relative.name in PRIVATE_NAMES or (
            relative.name.startswith(".env.") and relative.name != ".env.example"
        ):
            finding("local_configuration", name)
        if relative.name == ".DS_Store" or relative.suffix in {
            ".pem",
            ".key",
            ".p12",
            ".pfx",
            ".db",
            ".sqlite",
            ".sqlite3",
            ".pyc",
            ".log",
            ".tmp",
            ".bak",
        }:
            finding("private_or_generated_file", name)
        if re.search(r"\.(?:db|sqlite3?)-(?:wal|shm|journal)$", relative.name):
            finding("private_or_generated_file", name)
        size = path.stat().st_size
        total_bytes += size
        if size > 50 * 1024**2:
            finding("file_above_publication_limit", name)
            continue
        scan(path.read_bytes(), name)
    return dict(
        status="PASS" if not findings else "FAIL",
        candidate_files=len(files),
        candidate_bytes=total_bytes,
        inspected_files_and_archive_members=members,
        findings=findings,
        scope="Current tracked and non-ignored working-tree files, including nested ZIP contents; Git history is not scanned. Signature checks do not prove absence of every possible secret.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = inspect_project(args.root)
    encoded = json.dumps(result, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded)
    print(encoded, end="")
    raise SystemExit(0 if result["status"] == "PASS" else 1)
