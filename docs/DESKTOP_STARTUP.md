# Desktop startup: 0.2.0.dev3

[Windows installation](INSTALL_WINDOWS.md) · [Русский](INSTALL_WINDOWS.ru.md)

## What changed

The stdio MCP transport starts before database/viewer initialization. Tool names,
input schemas, execution defaults and scientific formulas are unchanged. The agent
profile exposes 37 tools immediately. Heavy services initialize in a daemon thread.
Tools return `STARTING` with `stage`, `retry_after_seconds: 2`, `home` and `log` until
ready. A background exception produces `FAILED` with its message and log path; the
transport stays available for tool discovery and diagnostic calls.

Startup records are JSON lines in `startup.log`; `startup-status.json` and
`startup-<pid>.json` are replaced atomically. The per-process file disambiguates two
concurrent clients; the shared status represents the latest writer. Stages are
`STARTING`, `SERVICE_READY`, `VIEWER_RUNNING` / `VIEWER_ALREADY_RUNNING` /
`VIEWER_FAILED`, `MCP_READY`, `FAILED`. `MCP_READY` records service readiness, not proof
that Claude has successfully invoked a tool. Viewer errors are in `viewer.log`.
The actual resolved home is recorded and displayed in the viewer. With Windows MSIX,
LocalAppData may resolve inside Claude's `Packages/.../LocalCache/Local` directory.

## Multiple clients and process ownership

- `<home>/migrate.lock`: 120-second Portalocker lock covers WAL setup, Alembic upgrade
  and the schema marker. The database schema remains Alembic `0001`.
- `<home>/sources.lock`: serializes source registration/removal without changing the
  source containment, root identity, revision or reparse-point checks.
- `<home>/viewer-start.lock`: serializes same-home viewer discovery/launch and the
  first-run browser marker. A live registered same-home viewer is reused; a foreign
  occupied port causes selection of an available port.
- `<home>/desktop-leases.lock` and lease files: each client records PID/create time
  before service initialization. A managed viewer independently removes stale leases
  and stops after the last live client disappears, including a killed client. PID
  creation time prevents confusing a reused PID with the original client.

On Windows, a managed viewer is created through local WMI as the caller, with its
own lifetime rather than as a child in one MCP client's kill-on-close Job Object.
WMI must be available and permitted by workstation policy. Failure is explicit
(`VIEWER_LAUNCH_UNAVAILABLE`); no administrator elevation or scheduled task is used.
Existing worker cancellation continues to own and terminate worker descendants.

An independently launched CLI viewer is reused but is never stopped by Desktop lease
cleanup. The execution control-plane lock remains separate; clients route calculations
to the active local viewer/controller and do not start duplicate owners.

## CPU and GPU extensions

| Variant | Extension identity | Windows default home | Preferred viewer port |
|---|---|---|---|
| CPU | `kanysh-basic` | `%LOCALAPPDATA%\kanysh-basic` | 8765 |
| GPU | `kanysh-basic-gpu` | `%LOCALAPPDATA%\kanysh-basic-gpu` | 8767 |

Keep the separate homes when installing both. Per-home migration/source/viewer locks
are independent. CPU and GPU packages contain the same production code and tool schemas,
with separate checked-in `deploy/mcpb/{cpu,gpu}/uv.lock` files. Their explicit PyTorch
indexes are respectively `/whl/cpu` and `/whl/cu126` on Windows/Linux. macOS uses CPU
PyTorch from PyPI; scientific MPS acceleration is not implemented.

GPU startup reports CUDA availability, device name, CUDA version and PyTorch version.
Without CUDA it warns and starts on CPU. This fallback does not override a calculation's
explicit `require_gpu` policy. The central `execution/device.py` resolves policies;
service preflight and workers use it, runner/planning pass the selected device through,
and numerical entry points validate it. CPU remains the public default; `prefer_gpu`
requires explicit CPU-fallback permission. Supported operations are unchanged.

The GPU edition initially downloads approximately 2.5 GB, plus other dependencies.
Claude's UV runtime installs Python/dependencies **before** the Python entry point.
Background initialization cannot prevent a host-controlled dependency download timeout.
Neither a successful lock resolution nor an SDK launch proves a clean Claude Desktop
UV installation; that remains NOT RUN.

## Build and reproduce checks

From a prepared Python 3.12 environment with `uv` and Node/npm available:

```bash
uv sync --frozen --extra ui --extra viewer --extra solver --group dev
uv run --no-sync ruff check src tests scripts examples/generators
uv run --no-sync pytest -q -m 'not gpu and not opm and not external'
uv run --no-sync pytest -q tests/integration/test_desktop_startup.py
uv run --no-sync python scripts/build_mcpb.py --variant cpu
uv run --no-sync python scripts/build_mcpb.py --variant gpu
uv run --no-sync python scripts/check_mcpb.py --variant cpu
uv run --no-sync python scripts/check_mcpb.py --variant gpu
```

Release builds run pinned official `@anthropic-ai/mcpb@2.1.2 validate` and `pack`.
Use `--refresh-lock` only when deliberately updating dependencies; commit both the
variant pyproject and lock. Archive unit tests use an offline ZIP helper and do not
claim official validation. SDK checks unpack each actual archive into a temporary
folder, use the existing interpreter, import a synthetic one-cell deck in an isolated
worker, and verify last-client viewer cleanup. They do not install the archive's UV
environment or test real Claude Desktop.

## Recorded local evidence

macOS arm64, Python 3.12, warm installed environment:

| Check | Result |
|---|---|
| Full CPU regression | 177 passed, 5 skipped, 2 deselected in 444.85 s |
| New Desktop process tests | 15 passed; includes two mocked WMI marshalling/error cases |
| Four simultaneous Store processes on empty home | PASS; head `0001`, one schema marker, one registered source |
| Two real stdio Desktop clients, shared viewer | PASS; one viewer, no FAILED; closing one preserves the other |
| Abruptly killed Desktop process | PASS; its managed viewer exits after the stale lease is removed |
| Foreign occupied port / independently launched viewer | PASS; select another port / preserve standalone viewer |
| Deliberately slow/failing background startup | PASS; initialize+tools <3 s; STARTING / FAILED, connection stays alive |
| CPU archive real SDK initialize + tools/list | 0.425 s |
| GPU archive real SDK initialize + tools/list | 0.425 s; CPU fallback without CUDA |
| Official CPU and GPU MCPB validation/packing | PASS |
| Root / CPU / GPU frozen lock consistency and installed package compatibility | PASS |
| Real Windows Claude Desktop installation, toggle/re-enable, no orphans | NOT RUN |
| Real Windows/NVIDIA CUDA computations | NOT RUN |

Initial dev3 measurement of `python -X importtime server.py` with stdin EOF: **4.269 s before**, **0.881 s after**,
both exit 0. This compares process lifetime (including shutdown), not protocol latency;
SDK timing above measures the MCP exchange. Importing `opensubsurface.mcp.server`
does not import torch, gempy, gradio, pyvista, trame, distributed, numpy or scipy.
Timing is a local observation, not a Windows performance guarantee.

Archive hashes and SDK evidence: [CPU](mcpb-check.json), [GPU](mcpb-gpu-check.json).
Full regression: [JUnit](test-results.xml); Desktop cases are also collected in
the separate [15-test Desktop suite](test-results-desktop.xml). Windows acceptance stays separate in
[WINDOWS_NATIVE](WINDOWS_NATIVE.md). No current hosted CI result is implied.


## Hosted Windows follow-up

[Run 39111905173](https://github.com/almukhanomr/kanysh/actions/runs/39111905173)
on 3ac2e68: Windows **172 passed, 4 skipped, 2 failed, 2 deselected**; Linux/macOS green.
Both failures concern Desktop/viewer lifetime. The fix uses local WMI for managed Windows
viewers, exercises an initialized MCP connection before killing its actual server PID,
and collects Desktop logs on CI failure. Windows status replacements retry transient
sharing violations. [Details and evidence limits](WINDOWS_NATIVE.md#windows-ci-lifetime-fix-after-3ac2e68).
A new Windows run is required; local macOS or mocked COM checks do not prove that result.

After this fix, the local full CPU suite passed: **177 passed, 5 skipped, 2 deselected**
in 444.85 s. Native Windows execution of the WMI launcher still awaits the next CI run.
