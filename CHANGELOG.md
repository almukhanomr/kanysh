# Changelog

## Unreleased — OPM Flow deck runs (optional)

- New `simulation_deck_run`: runs the user's own ECLIPSE-format `.DATA` deck and its INCLUDE
  closure in OPM Flow exactly as supplied (byte-for-byte snapshot, revision-checked; no deck
  generation or defaults). Decks referencing files outside the closure (RESTART, IMPORT, GDFILE,
  PATHS, ...) are refused explicitly.
- Executors: native Linux, or Windows via a dedicated WSL2 distribution `kanysh-opm` (the user's
  own distributions are untouched). Docker Desktop is not used. `kanysh-basic setup-opm` creates
  the distribution, installs OPM Flow from the OPM PPA, holds the packages, records the binary
  sha256/version in `opm-runtime.json` and self-tests on SPE1. Runs refuse a changed binary
  (`STALE_SOLVER`).
- Simulation is optional: without a set-up executor the request is refused synchronously with
  `SIMULATOR_UNAVAILABLE` and install steps; `diagnostics`/`capabilities` report the state.
- Portable SMSPEC/UNSMRY reader (no resdata on Windows); summary published as Parquet with
  PRT/DBG/flow logs in `job_logs`. Optional comparison with a user reference SMSPEC at an explicit
  tolerance. Cancellation also stops the simulator inside WSL.
- Real-data (Volve) fixes: deck parser applies `MAXVALUE`/`MINVALUE` and unquoted edit records,
  reports region edits (`MULTIREG`, ...) per record, and refuses `ADDZCORN` instead of silently
  importing a grid without those faults. New reader for the simulator's legacy `.GRID` output
  (corners used as written); `simulation_deck_run` gets an explicit `parsing_strictness=low`
  (ignored keywords listed, status `PASS_WITH_IGNORED_KEYWORDS`) and OPM's fatal input message in
  errors. `folder_assess` flags far-above-datum GOC placeholders. See docs/VOLVE_REAL_DATA_TEST.md.

## Unreleased — MCP smoke-test fixes (2026-10-18)

- MCP tools publish self-contained input schemas: every `$ref` inlined, every field
  documented with units, the Z-up convention and allowed enum values; examples for
  `regional_volumes.scenarios` and `calculation_plan` contacts/zones/inputs.
  Argument errors return `INVALID_ARGUMENTS` with JSON-path `field`/`fields` and remediation.
- Startup reports `stage`/`substage`/`elapsed_s`/`waiting_for`; read-only discovery
  (`source_list`, `folder_assess`, `project_list`, `job_status`, ...) answers from
  `SERVICE_READY` while CUDA warm-up and the viewer start. New read-only `diagnostics` tool.
- `regional_volumes` (and reconcile/tornado/Monte Carlo) preflight synchronously: region ids,
  absent SWAT/PORO/NTG with `field` + remediation, depth-sign slips. Renamed
  `oil_gas_saturation` -> `sg_in_oil_zone`, `gas_oil_saturation` -> `so_in_gas_zone`
  (old names remain deprecated aliases; semantics unchanged).
- Corner-point pinch-outs (zero-length pillars, positive volume, no negative Jacobian) are
  valid `pinched_pillar_cell` (INFO), no longer `degenerate_cell`. Twisted/inverted/degenerate
  cells still fail `geometry_policy=strict` (default); explicit `exclude_flagged` reports the
  excluded cells, bounding GRV/PV and share, with `PASS_WITH_EXCLUSIONS`.
- `model_qc` reports absent arrays as `missing_property:<name>` (WARNING), not range errors.
- GPU refusals name the GPU-capable operations and suggest `prefer_gpu`/`cpu`;
  `compute_targets_list` returns an operation -> device matrix.
- `job_status` is compact by default (`verbose=true` for the full record) with worker
  `progress`/`eta_s`; `job_logs` returns worker log lines, workflow node log, stage events and
  child job tails; `calculation_status` reports per-node state and progress. Worker start-up
  imports are lazy (2.6 s -> 0.4 s per node).
- `folder_assess` proposes every EQUIL record per EQLNUM region, RSVD tables and PVTO/PVTG
  table references with line ranges; no scalar Bo is chosen.
- `eclipse_import` records `input_z_direction`, `stored_z_direction`, `z_conversion` and
  per-field `region_ids`; plans on imported properties no longer fail on a missing memory bound.

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
