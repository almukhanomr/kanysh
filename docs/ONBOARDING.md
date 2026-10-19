# Workstation setup reference for IT

For the engineer walkthrough, start with [Your first result](GETTING_STARTED.md) /
[Первый результат](GETTING_STARTED.ru.md). This page covers configuration and platform details.

The product serves geologists internationally through exchange formats rather than
one Petrel/RMS version. See [English / Russian export guide](PETREL_EXPORT.md).
No vendor licence or project database is bundled.

## Owner setup

Python 3.12, `uv`, then from the project checkout:

```bash
uv sync --frozen --extra ui --extra viewer --group dev
uv run --extra ui --extra viewer kanysh-basic setup
```

Existing installations may pass `--home` with their original state directory.
Default setup home: `%LOCALAPPDATA%\kanysh-basic` on Windows, `~/.kanysh-basic` elsewhere (other commands retain `.data` for compatibility).
`--home /absolute/state` before `setup` overrides it. Setup checks import availability,
registers `agent` stdio entries, creates a backup before changing an existing JSON
configuration, preserves unrelated settings and refuses an existing conflicting
`kanysh-basic` entry. It does not restart Claude or claim client authentication.
Invalid JSON stays unchanged. Close clients while updating their settings to avoid
concurrent writes. Re-running the same setup is idempotent.

Claude Desktop: macOS Application Support / Windows APPDATA `Claude/claude_desktop_config.json`.
Claude Code user scope: `~/.claude.json`, `mcpServers`. Other scopes may shadow it;
check `/mcp` in the client. [Official Claude Code scopes](https://code.claude.com/docs/en/mcp).
A local viewer already serving this home receives stdio submissions through its
REST controller; the client does not start a second Dask controller.

Advanced/test options:
`setup --desktop-config PATH --code-config PATH --no-viewer --no-browser`.
These options allow isolated configuration tests without editing a real account.

Windows uses the **native Win32 backend**; [three-step MCPB installation](INSTALL_WINDOWS.md).
Owner registration accepts paths such as `D:\Geology\FieldA`. Portalocker excludes a
second controller; Windows source handles reject reparse points and pin ancestors.
WSL is optional for Linux-only OPM Flow. Native Windows/Claude Desktop/NVIDIA acceptance
remains **NOT RUN**. Linux without WSL has no native Desktop registration; Claude Code
still gets configured.

The viewer opens at a loopback address, reusing an active viewer or choosing a free
port. `viewer.log` contains launch diagnostics. If the `[ui]` extra is absent, install
it and run setup again. `--no-viewer` skips launching explicitly. An authenticated
installation must make its owner token available to both viewer and stdio clients;
setup does not put secrets in configuration files or URLs.

## First connection

1. Choose prompt **begin / Start** or call `start`.
2. In the local viewer choose **Open Norne demo** (saved offline evidence) or
   **Add folder** (native directory picker, owner UI only). CLI `source-add` remains.
3. Call `source_list`, then `folder_assess`. It scans up to explicit file/depth limits,
   reads only 64 KiB headers per file and never follows symlinks. A partial scan says so.
4. Review role candidates, missing files and available workflows. Confirm selected
   parameter proposals with file/line evidence before planning or calculating.
5. Use a scenario prompt: `check_model`, `regional_volumes`, `reconcile_petrel`,
   `tornado_analysis`, `compare_versions`. Import, validate and inspect actual job results.
6. `results_export` produces XLSX/PDF. Preserve NOT RUN and the scientific assumptions.

Native folder dialog is unavailable on a headless host; owner CLI remains the fallback.
The WSL picker calls Windows FolderBrowserDialog and converts the selected path.
Access remains confined to owner-registered roots; an agent cannot register another root.
Discovery checks are not numerical model validation. A role candidate or file extension
never proves scientific usability. Parameters embedded deep in arrays/includes may not
be visible in the bounded assessment; inspect/import explicitly.

## Desktop extension package

```bash
uv run --no-sync python scripts/build_mcpb.py --variant cpu
uv run --no-sync python scripts/build_mcpb.py --variant gpu
```

Output: `dist/kanysh-basic-0.2.0-dev5.mcpb`, a source-only ZIP using MCPB v0.4 `uv`
runtime. It contains the package, public demo/licences, dependency declarations and
an agent-profile launcher. No virtual environment, local state, secrets or experimental
Runpod code are included. The host resolves Python/dependencies; initial installation
requires network/storage and a compatible host supporting the v0.4 UV runtime.
[Official MCPB specification](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md).

The source bundle declares Windows/macOS/Linux. Windows defaults to LocalAppData;
other hosts use their normal local home. An optional owner-selected model folder is
registered read-only at startup. CPU PyTorch is selected explicitly; no solver extra
is included. The viewer opens on first startup and startup.log records MCP_READY or
failure. UV installation failures happen before the launcher and belong to host logs.
Archive inspection and SDK launches are separate from actual Claude Desktop extension
installation, which remains **NOT RUN**. See [Windows acceptance](INSTALL_WINDOWS.md).

The GPU extension is `dist/kanysh-basic-gpu-0.2.0-dev5.mcpb`, with its own home and
checked-in lock. Official validation/packing and startup concurrency details:
[Desktop startup](DESKTOP_STARTUP.md). Both variants expose identical MCP schemas.
