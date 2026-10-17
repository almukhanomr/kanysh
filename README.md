# Kanysh Basic

[Website: kanysh.com](https://kanysh.com) · [Russian](README.ru.md)

**An AI copilot for calculations on geological models, alongside Petrel and RMS.**
Open an exported model, ask for a check or scenario in your chat, and receive a report
with assumptions and independent numerical checks.

Kanysh Basic is an **MCP server for subsurface modeling + local web viewer**. MCP is
the connection that lets your chat use the calculation tools. The chat requests work;
the viewer displays projects, revisions, reports and 3D scenes. Numerical work runs
locally. Your chat client controls which messages and tool results reach its AI provider.

**Start here: [Your first result in Kanysh Basic](docs/GETTING_STARTED.md).**
The guide explains installation, what to expect at each step, how to connect your
chat, check your own model and save Excel/PDF reports. [Russian guide](docs/GETTING_STARTED.ru.md).

![Norne corner-point model coloured by source porosity](examples/reference/norne/results/scene.png)

*Public Norne geometry and porosity: 44,927 active cells. Statoil / OPM,
ODbL-1.0 / DbCL-1.0. Demo fluid parameters are explicit benchmark assumptions,
not a field reserves estimate.*

## Get your first result

1. **Download and unzip the project.** Use the source ZIP from this repository/release;
   open the inner folder containing `pyproject.toml`. Windows uses Ubuntu inside WSL2.
   [Installation steps and prerequisites](docs/GETTING_STARTED.md#1-install-once).
2. **Install and run setup.** In that folder, with [uv](https://docs.astral.sh/uv/getting-started/installation/) installed:

   ```bash
   uv python install 3.12
   uv sync --frozen --no-dev --extra ui --extra viewer --python 3.12
   uv run --no-sync kanysh-basic --home "$HOME/.kanysh-basic" setup
   ```

   Close your Claude clients before setup. It backs up existing configuration and
   opens the viewer. Use the viewer URL printed by setup if the browser does not open.
3. **Click Open Norne demo.** You should see the saved porosity-coloured grid and
   reports. This opens bundled results without downloading a model or calculating it again.
4. **Restart your chat client and check the connection.** Ask: “Use Kanysh Basic's
   start tool and show me its welcome message.” Confirm that an actual tool result appears.
5. **Click Add folder for your exported model.** Ask the chat to assess the folder
   first. Confirm its input proposals, then request a model check or scenario.

Use the same state folder (`$HOME/.kanysh-basic` in these commands) when returning to
work. [Troubleshooting](docs/GETTING_STARTED.md#if-something-goes-wrong) covers missing
projects, connection problems, folder access and import failures.

This development release may need IT assistance for installation. Actual external
chat-client connections, Claude Desktop installation and Windows/WSL2/NVIDIA hardware
acceptance are **NOT RUN**; local SDK/numerical checks do not establish those results.
A source-only `.mcpb` is also available when supplied with the release; its host must
support MCPB v0.4's UV runtime. Native Windows extension support is not advertised.
[Extension and IT setup reference](docs/ONBOARDING.md).

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

## Current limits

- Binary EGRID/ROFF geometry import uses full RAM and has a **2 million-cell cap**.
  Streaming ASCII COORD/ZCORN was checked at **20 million synthetic cells**, peak RSS
  **1.46 GB**; this is not acceptance of a large field EGRID.
- Unsupported DATA keywords are listed in the import report. SWATINIT is not equilibrium SWAT.
- Bo/Bg, contacts, saturations, units and CRS/datum need an explicit basis. STOIIP/GIIP
  are initial volumes, not recoverable reserves or production forecasts.
- Polygon selection keeps whole cells by mean corner XY; saturation-height functions
  use mean corner Z. Scalar uncertainty is not spatial simulation.
- Basic block imports and copilot analyses use CPU. Viewer previews are bounded;
  calculation inputs are not downsampled. OPM Flow end-to-end remains **NOT RUN**.
- The web app is an English-language viewer. Calculations run through the connected
  chat/MCP, CLI or REST. Gradio/Plotly are optional `[ui]` dependencies; `[viewer]` enables scenes.

Kanysh Basic contains the accepted workflows above. Further modelling development
belongs to **Kanysh Advanced**: [roadmap](docs/ROADMAP.md). Local Advanced experiments
are excluded from Basic GitHub publication, packages and production MCP profiles.

## Technical reference and contribution

[MCP/CLI/REST setup](docs/MCP_SETUP.md) · [IT setup reference](docs/ONBOARDING.md) ·
[CONTRIBUTING](CONTRIBUTING.md) · [Publication audit](docs/PRE_PUBLICATION_AUDIT.md).
CI targets Ubuntu/macOS with ruff and CPU pytest, excluding gpu/opm/external tests.

The Python namespace, data-format IDs, MCP resource URIs and `OPENSUBSURFACE_*`
environment names retain their existing identifiers for compatibility. The package
and public CLI are `kanysh-basic`; `opensubsurface` remains a CLI compatibility alias.
This is a development release (`0.2.0.dev1`); [external acceptance](docs/ACCEPTANCE.md) is separate.

Application source: Apache-2.0. Norne data: ODbL/DbCL with upstream notices retained.
Dependencies have separate licences: [THIRD_PARTY](THIRD_PARTY.md).
