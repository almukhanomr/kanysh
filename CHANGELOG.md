# Changelog

## 0.2.0.dev3

- Windows CI follow-up: launch managed viewers via local WMI so one MCP client's
  Job Object teardown cannot terminate another client's shared viewer. Preserve
  lease cleanup and existing worker/source safety behavior.
- Verify crash cleanup after a real MCP handshake using the server's actual PID;
  upload Desktop diagnostic logs on CI failure. Retry transient Windows status-file
  sharing violations while preserving atomic replacement.

- Serialize first-run SQLite WAL, Alembic migrations and schema markers across processes.
- Serialize folder registration, viewer launch and the first-run browser marker.
- Start MCP initialize/tool discovery immediately; initialize services in the background.
  Tools return STARTING with retry guidance or FAILED with logs without disconnecting.
- Share same-home viewers with PID/create-time leases; stop managed viewers after the
  last Desktop client exits, preserving standalone viewers and other clients.
- Publish distinct CPU and GPU MCPB identities, homes, default ports and frozen UV locks.
  CUDA 12.6 is explicit on Windows/Linux; macOS uses CPU. Report GPU diagnostics and
  warn with CPU fallback when CUDA is absent. Scientific execution defaults are unchanged.
- Show the actual resolved results home in startup status and the viewer, including
  Claude Desktop MSIX-virtualized LocalAppData paths.
- Build/validate with the official MCPB CLI. First host-controlled dependency installation,
  Windows Desktop toggling and real NVIDIA acceptance remain NOT RUN.

## 0.2.0.dev2

- Native Windows process, source-path and extension installation support.
- Windows/Ubuntu/macOS CPU CI and worker diagnostic artifacts.
