"""Owner-only native directory picker; paths never come from an MCP tool argument."""

import os
import subprocess
import sys
from pathlib import Path

from opensubsurface.adapters.local_sources import LocalSources
from opensubsurface.errors import DomainError


def choose_folder():
    if sys.platform == "darwin":
        command = [
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Kanysh Basic: allow read-only access to a data folder")',
        ]
    elif sys.platform == "win32" or os.environ.get("WSL_INTEROP"):
        command = [
            "powershell.exe",
            "-NoProfile",
            "-STA",
            "-Command",
            "Add-Type -AssemblyName System.Windows.Forms; $picker = New-Object System.Windows.Forms.FolderBrowserDialog; $picker.Description = 'Kanysh Basic: allow read-only access'; if ($picker.ShowDialog() -eq 'OK') { Write-Output $picker.SelectedPath }",
        ]
    else:
        command = [
            sys.executable,
            "-c",
            "import tkinter as t; from tkinter import filedialog; r=t.Tk(); r.withdraw(); print(filedialog.askdirectory(title='Kanysh Basic: allow read-only access')); r.destroy()",
        ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DomainError(
            "FOLDER_DIALOG_UNAVAILABLE", "Native dialog unavailable; use owner CLI source-add"
        ) from error
    if result.returncode:
        if sys.platform == "darwin" and "-128" in result.stderr:
            return None
        raise DomainError("FOLDER_DIALOG_UNAVAILABLE", "Native dialog failed; use owner CLI source-add")
    value = result.stdout.strip()
    if value and os.environ.get("WSL_INTEROP"):
        converted = subprocess.run(
            ["wslpath", "-u", value], capture_output=True, text=True, timeout=10, check=False
        )
        if converted.returncode:
            raise DomainError(
                "FOLDER_DIALOG_UNAVAILABLE",
                "Cannot map Windows folder into WSL; use source-add with a WSL path",
            )
        value = converted.stdout.strip()
    return Path(value) if value else None


def add_folder(store):
    path = choose_folder()
    if path is None:
        return dict(status="CANCELLED", registered=False)
    source = LocalSources(store).register(path.name or "Data", path)
    return dict(status="REGISTERED", source=source, read_only=True)
