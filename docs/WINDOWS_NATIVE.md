# Native Windows implementation and acceptance

Kanysh Basic now has a native Windows backend. WSL is reserved for optional Linux-only
OPM Flow hydrodynamics. This document distinguishes implementation/local evidence from
actual Windows acceptance. [User installation: English](INSTALL_WINDOWS.md) /
[Русский](INSTALL_WINDOWS.ru.md). [Machine-readable evidence](windows-native-check.json).

| Requirement | Implementation | Actual evidence / limit |
|---|---|---|
| W1: single controller | Portalocker non-blocking exclusive lock; a metadata reader never releases the owner's lock or cancels its jobs | Independent-process exclusion/reacquisition and existing owner/reader tests pass on macOS. Native Windows NOT RUN |
| W1: process lifetime | CREATE_NEW_PROCESS_GROUP on Windows; psutil recursive descendants → terminate → wait → kill. Orphan PID must match creation time and worker argv/job folder | Real parent/child cancellation and timeout, orphan mismatch and valid cleanup pass on macOS. Same tests in Windows CI; Windows NOT RUN |
| W1/W2: filesystem | Windows CreateFileW OPEN_REPARSE_POINT; reject all reparse points, pin every ancestor without FILE_SHARE_DELETE, retain NTFS volume/file ID. Long-path prefix is internal. Source IDs use normalized absolute paths and case-insensitive root comparison on Windows. Relative paths reject drive/ADS/trailing-dot aliases | POSIX source containment/root-replacement/revision tests pass. Native NTFS, case, Unicode/long paths, junction and ancestor-swap tests exist; Windows NOT RUN |
| W2: folder selection | Native Windows PowerShell folder picker with UTF-8 output; CLI drive paths and installer model-folder configuration share the source boundary | Installer-selected folder automatically registers and is assessed through real MCP SDK on macOS. Actual Windows picker/Claude dialog NOT RUN |
| W3: dependencies | CPU uv group is default. Exclusive gpu extra selects CUDA 12.6 with `--no-group cpu --extra gpu`. Explicit PyTorch indexes. resdata solver extra is Linux-only; native simulation execution returns SOLVER_PLATFORM_UNSUPPORTED | Exact MCPB resolves 168 packages for Windows x64 CPython 3.12 with torch 2.14.1+cpu; no CUDA/resdata. Native packages require wheels, with only pure-Python asciitree allowed from source. Resolution is not installation; NVIDIA NOT RUN |
| W4: extension | win32/darwin/linux platforms; Windows default `%LOCALAPPDATA%\kanysh-basic`; optional owner-selected model folder; first-run browser; startup.log/startup-status.json and viewer.log | Archive bytes checked against current source/notices. MCP stdio SDK, startup status, shared viewer/controller and isolated one-cell DATA import pass on macOS. Claude Desktop Windows UV install NOT RUN |
| W5: CI | Windows/Ubuntu/macOS CPU matrix, ruff, publication guard, no gpu/opm/external. Explicit skips for Linux-only OPM/optional reader and symlink privilege. Native Windows junction tests do not require symlink privilege | Local macOS CPU dev3: 171 passed, 5 skipped, 2 deselected; 0 failures/errors, 422.80 s. Additional Desktop process suite: 11 passed (includes two later-added lifecycle cases). GitHub-hosted Windows CI NOT RUN. The previously observed account billing lock must be resolved by the account owner before hosted runs can execute |
| W6/W7: installation | Three-step English/Russian guide with labelled illustrations, GPU and optional OPM/WSL sections; README makes native Windows the primary installation route | Guides/links checked. Pictures are illustrations, not Windows acceptance screenshots |

Additional portability work: all application Path.read_text/write_text calls explicitly
use UTF-8, worker environment retains Windows runtime/temp variables, pread has a
single-reader Windows seek/read fallback, source directory enumeration uses the pinned
Windows handle's final path, and Service.close disposes SQLite connections.

## Before calling the Windows release validated

Follow the acceptance checklist in [INSTALL_WINDOWS](INSTALL_WINDOWS.md#windows-release-acceptance-record-actual-evidence).
Record the precise MCPB hash, Claude Desktop version and actual dependency installation
on a clean Windows x64 machine. Then run the native CI/tests and a fresh Norne scenario.
Do not infer these outcomes from a platform declaration, a cross-platform resolver,
a local SDK connection, saved Norne reports, or a macOS test pass.

## 0.2.0.dev3 Desktop startup

Migrations/WAL/schema marker, source registration and viewer startup now have separate
cross-process locks. MCP serves initialize/tool discovery before background service
startup. Two same-home clients share a managed viewer using PID/create-time leases;
standalone viewers remain independent. CPU/GPU extensions have separate default homes
and ports. Actual resolved homes are visible, including MSIX virtualization.

Local macOS process/SDK tests cover concurrent migrations, STARTING/FAILED transport,
shared-viewer lifetime and CPU fallback without CUDA. Official CPU/GPU MCPB validation
passes. These are **not** Windows Desktop or NVIDIA acceptance. Windows Claude UV
installation, enable/disable/re-enable with no orphan processes, GPU detection and
actual CUDA computations remain **NOT RUN**. New hosted CI for these uncommitted changes
has not been run. See [Desktop startup evidence](DESKTOP_STARTUP.md).
