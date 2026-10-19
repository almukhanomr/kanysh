# Kanysh Basic

[Website: kanysh.com](https://kanysh.com) · [Russian](README.ru.md)

**An AI copilot for calculations on geological models, alongside Petrel and RMS.**
Open an exported model, ask for a check or scenario in your chat, and receive a report
with assumptions and independent numerical checks.

Kanysh Basic is an **MCP server for subsurface modeling + local web viewer**. MCP is
the connection that lets your chat use the calculation tools. The chat requests work;
the viewer displays projects, revisions, reports and 3D scenes. Numerical work runs
locally. Your chat client controls which messages and tool results reach its AI provider.

**Windows: [install the Claude Desktop extension in three steps](docs/INSTALL_WINDOWS.md).**
Download the release `.mcpb` → double-click → Install → choose your exported model folder.
No terminal or WSL is needed for static workflows. A client supporting MCPB 0.4's UV
runtime and internet access for the initial dependency download are required.
[Russian installation guide](docs/INSTALL_WINDOWS.ru.md).

Native Windows installation in Claude Desktop is verified: the `.mcpb` installs by
double-click and the tools run on a real exported model ([Volve test](docs/VOLVE_REAL_DATA_TEST.md));
issues found during that check were fixed in 0.2.0.dev5/dev6 ([CHANGELOG](CHANGELOG.md)).
[macOS/Linux source installation and first result](docs/GETTING_STARTED.md).

![Norne corner-point model coloured by source porosity](examples/reference/norne/results/scene.png)

*Public Norne geometry and porosity: 44,927 active cells. Statoil / OPM,
ODbL-1.0 / DbCL-1.0. Demo fluid parameters are explicit benchmark assumptions,
not a field reserves estimate.*

## Get your first result

1. **Install on Windows:** follow the [three-step extension guide](docs/INSTALL_WINDOWS.md).
   Keep `%LOCALAPPDATA%\kanysh-basic` for results and choose your real model folder.
2. **Open Norne demo** in the viewer to inspect saved public geometry and reports.
   This does not run a new calculation.
3. In Claude, ask: **“Use Kanysh Basic's start tool, then assess my registered model folder.”**
   Confirm that actual tool results appear. Add another folder with **Add folder** in the viewer.
4. Confirm file-derived proposals, then ask for QC or a scenario. Save the report and
   XLSX/PDF exports. Use the same results home when reconnecting.

For **macOS/Linux or IT source installation**, install [uv](https://docs.astral.sh/uv/getting-started/installation/),
open the source folder and run:

```bash
uv python install 3.12
uv sync --frozen --no-dev --extra ui --extra viewer --python 3.12
uv run --no-sync kanysh-basic --home "$HOME/.kanysh-basic" setup
```

Close Claude clients before setup. It backs up configuration and opens the viewer.
The default install uses **CPU PyTorch**; NVIDIA is an explicit [GPU option](docs/INSTALL_WINDOWS.md#gpu-nvidia-optional-for-it).
**WSL/Linux is only needed for optional [OPM Flow deck runs](#run-your-own-deck-in-opm-flow-optional).**
The source-only extension includes no Python environment; its host installs dependencies.
Acceptance with chat clients other than Claude Desktop remains **NOT RUN**.

## CPU or NVIDIA edition

| Extension | Default results home on Windows | Runtime |
|---|---|---|
| `kanysh-basic-0.2.0-dev6.mcpb` | `%LOCALAPPDATA%\kanysh-basic` | CPU |
| `kanysh-basic-gpu-0.2.0-dev6.mcpb` | `%LOCALAPPDATA%\kanysh-basic-gpu` | CUDA 12.6 on Windows/Linux; CPU on macOS |

Both extensions can be installed alongside each other. Keep their separate default
homes. The GPU edition's first installation downloads approximately **2.5 GB**; allow
additional disk space for dependencies. It reports the detected GPU/CUDA version or
falls back to CPU with a warning. Calculations retain their existing CPU default:
request `prefer_gpu` with explicit CPU fallback, or `require_gpu`, for supported
operations. CUDA is verified on an RTX 3080 Ti Laptop: GPU regional/corner-point volumes
pass the mandatory CPU comparison. MPS acceleration is not implemented.

The host installs Python and dependencies **before** running the MCP entry point.
Fast MCP initialization cannot prevent a timeout during that host-controlled download.
After Python starts, tool discovery
is immediate while local services initialize. A `STARTING` response includes a retry
interval; `FAILED` includes the log path and keeps the MCP connection available.
The viewer and `startup-status.json` show the actual results folder, including any
Windows MSIX LocalAppData virtualization. [Startup and build evidence](docs/DESKTOP_STARTUP.md).

Build either extension from a prepared source environment (Node/npm and `uv` required):

```bash
uv run --no-sync python scripts/build_mcpb.py --variant cpu
uv run --no-sync python scripts/build_mcpb.py --variant gpu
```

Both commands use the official `mcpb validate` / `mcpb pack` CLI and a separate checked-in
UV lock. Add `--refresh-lock` only when intentionally updating dependency resolution.

## Five things to ask

| Task | Example message |
|---|---|
| Check a model | “Assess my registered folder, tell me what is missing, then check the imported model. Show severity and affected IJK cells.” |
| Calculate regional volumes | “Prepare oil and free-gas volumes by region. Ask for contacts, Bo/Bg and saturation assumptions, and calculate after I confirm them.” |
| Reconcile with Petrel/RMS | “Compare the regional volumes with my Petrel CSV. Explain differences in units, definitions and assumptions without changing inputs.” |
| Explore sensitivity | “Build a tornado analysis for the parameter ranges I provide. Keep the baseline and assumptions in the report.” |
| Compare model versions | “Compare these two revisions with the same IJK grid. Show changed cells and their regional pore-volume impact.” |

The agent asks for required engineering inputs. Values found in files are proposals
with source evidence until you confirm them. Missing constants are not guessed.
Independent numerical PASS still requires geological review.

## Prepare your model and read the result

Export exchange files from Petrel/RMS; native project databases are unsupported.
For a first grid check, prefer ECLIPSE ASCII DATA/GRDECL with its INCLUDE files,
geometry, active mask and properties. [Export checklist](docs/PETREL_EXPORT.md).

Open a report's result page to inspect its assumptions, independent checks and
regional tables. Ask for Excel/PDF export and use the resulting file links to save
it. A finished job can still have QC issues. `NOT RUN` means a check was not performed.
[Result/status guide](docs/GETTING_STARTED.md#5-calculate-a-scenario-and-keep-the-report).

The accepted workflows also include exchanged surfaces/wells/tops/polygons, LAS/model
comparison, explicit saturation-height functions and correlated scalar Monte Carlo.
[Capabilities and evidence](docs/COPILOT_RESULT.md) · [Norne recording recipe and exact numbers](docs/DEMO.md).

Real-data check: the public Equinor Volve model (680,400 cells) was imported from its
ECLIPSE GRID/INIT output, checked, and volumed by region; pore volume matches ECLIPSE `PORV`
except where the deck applies explicit history-match multipliers. [Volve results and gaps found](docs/VOLVE_REAL_DATA_TEST.md).

## Run your own deck in OPM Flow (optional)

`simulation_deck_run` runs your own ECLIPSE-format `.DATA` deck and its INCLUDE files in
OPM Flow exactly as supplied: no deck generation or default values. Executors are native
Linux or, on Windows, a dedicated WSL2 distribution `kanysh-opm` (your own distributions
and Docker are not used). Set it up once:

```bash
kanysh-basic setup-opm
```

It installs OPM Flow, pins the version and binary hash and self-tests on SPE1. Without it,
deck runs are refused with `SIMULATOR_UNAVAILABLE` and install steps; static workflows are
unaffected. Results include summary vectors (Parquet), PRT/DBG logs and an optional comparison
with your reference SMSPEC. On Volve, OPM Flow matched ECLIPSE initial FOIP exactly and field
pressure within 0.46 % after three documented deck edits.

## Current limits

- `eclipse_import` streams ASCII DATA/GRDECL, binary EGRID and legacy `.GRID` with INIT/GRDECL
  properties; a synthetic **200 million-cell** corner-point profile passes import, QC, volumes,
  tornado and scene export on CPU. The legacy XTGeo/ROFF import retains its **2 million-cell cap**.
  [Scaling implementation](docs/SCALING.md) · [Measured limits and benchmarks](docs/BENCHMARKS.md).
- Unsupported DATA keywords are listed in the import report. Decks with `ADDZCORN` are refused
  by the ASCII importer (import the simulator's GRID/EGRID output instead). SWATINIT is not equilibrium SWAT.
- Bo/Bg, contacts, saturations, units and CRS/datum need an explicit basis. STOIIP/GIIP
  are initial volumes, not recoverable reserves or production forecasts.
- Polygon selection keeps whole cells by mean corner XY; saturation-height functions
  use mean corner Z. Scalar uncertainty is not spatial simulation.
- CPU blocks support resource-bounded process pools. Regional/imported corner-point volumes
  also support float64 CUDA with mandatory CPU comparison. Viewer previews are bounded;
  calculation inputs are not downsampled.
- OPM Flow runs the deck as given; it may reject keywords ECLIPSE tolerates. `parsing_strictness=low`
  lists ignored keywords and reports `PASS_WITH_IGNORED_KEYWORDS`. Decks referencing files outside
  the INCLUDE closure (RESTART, IMPORT, GDFILE, ...) are refused. No MPI runs yet.
- The web app is an English-language viewer. Calculations run through the connected
  chat/MCP, CLI or REST. Gradio/Plotly are optional `[ui]` dependencies; `[viewer]` enables scenes.

Kanysh Basic contains the accepted workflows above. Further modelling development
belongs to **Kanysh Advanced**: [roadmap](docs/ROADMAP.md). Local Advanced experiments
are excluded from Basic GitHub publication, packages and production MCP profiles.

## Technical reference and contribution

[MCP/CLI/REST setup](docs/MCP_SETUP.md) · [IT setup reference](docs/ONBOARDING.md) ·
[CONTRIBUTING](CONTRIBUTING.md) · [Publication audit](docs/PRE_PUBLICATION_AUDIT.md).
CI targets Windows/Ubuntu/macOS with ruff and CPU pytest, excluding gpu/opm/external tests.

The Python namespace, data-format IDs, MCP resource URIs and `OPENSUBSURFACE_*`
environment names retain their existing identifiers for compatibility. The package
and public CLI are `kanysh-basic`; `opensubsurface` remains a CLI compatibility alias.
This is a development release (`0.2.0.dev6`); [external acceptance](docs/ACCEPTANCE.md) is separate.

Application source: Apache-2.0. Norne data: ODbL/DbCL with upstream notices retained.
Dependencies have separate licences: [THIRD_PARTY](THIRD_PARTY.md).
