# MCP setup reference

For first-time use, follow the [engineer guide](GETTING_STARTED.md) /
[русскую инструкцию](GETTING_STARTED.ru.md).

Kanysh Basic exposes typed tools through the official Python MCP SDK. The `agent`
profile is the supported copilot workflow; `full` also exposes lower-level operations.
There are no built-in LLM/voice providers or production cloud-provisioning tools.

## Recommended local setup

From the checkout, with Python 3.12 and uv installed:

```bash
uv sync --frozen --extra ui --extra viewer --group dev
uv run --no-sync kanysh-basic setup
```

Setup creates a persistent home, backs up existing client JSON before changing it,
registers the agent server in Claude Desktop / Claude Code and opens the viewer.
Restart the client, choose the `begin` prompt, then add an owner-authorized folder.
[Platform details and extension installation](ONBOARDING.md).

The `.mcpb` uses the v0.4 UV runtime. Build it with `python scripts/build_mcpb.py`
and open the resulting archive in a compatible Desktop host. Archive/SDK execution
is tested separately from actual Claude Desktop installation, which remains NOT RUN.
Windows uses the [native MCPB installation](INSTALL_WINDOWS.md); WSL is optional for Linux-only OPM Flow. Native Windows/Desktop acceptance remains NOT RUN.

## Manual stdio configuration

Replace these placeholders with your own installation and persistent state paths:

```json
{
  "mcpServers": {
    "kanysh-basic": {
      "command": "/path/to/kanysh-basic/.venv/bin/kanysh-basic",
      "args": ["--home", "/path/to/state", "mcp", "--profile", "agent"]
    }
  }
}
```

Do not rely on a GUI client inheriting your shell's activated virtual environment.
When the same home has an active local viewer, stdio calls use its REST controller;
there is only one executor. Without a viewer, the stdio process owns its local jobs.

## Persistent HTTP service

```bash
uv run --no-sync kanysh-basic --home "$HOME/.kanysh-basic" serve --ui --mcp-profile agent --port 8765
```

Viewer: `http://127.0.0.1:8765/app/`. MCP endpoint:
**`http://127.0.0.1:8765/mcp/`**, including the trailing slash.
Use the same `--home` as setup; a different state folder has a separate project list.
Omit `--ui` for a headless service. REST and MCP share projects, immutable revisions
and the job ledger. Durable jobs continue after an HTTP client disconnects.

If `OPENSUBSURFACE_TOKEN` is configured, HTTP clients send `Authorization: Bearer <token>`.
Host/Origin/token checks also protect MCP and viewer pages. Keep tokens in the client
or process environment, never in URLs or project artifacts. This is loopback owner
authentication; it is not an externally deployed OAuth resource server.
Do not expose the development HTTP transports to the public internet.

## Copilot workflow

`begin → source_list → folder_assess → user confirmation → import → model_qc → calculation → report`

- `folder_assess` returns role candidates, missing inputs and file/line proposals.
  Confirm selected contacts/PVT/units/CRS before a plan or scientific job.
- `eclipse_import` streams static ASCII DATA/GRDECL. `grid_import` retains the separate,
  capped XTGeo EGRID/ROFF route. `geodata_import` handles supported exchanged objects.
- `regional_volumes`, `volumes_reconcile`, `wells_vs_model`, `model_diff`,
  `sensitivity_tornado` and `uncertainty_monte_carlo` return durable job IDs.
- Use `job_status`, then immutable artifact refs. `results_export` produces Excel/PDF;
  `scene_show`/`scene_export` produce the viewer scene. `result_preview` returns an image
  when available, otherwise JSON/resources/file links.
- `calculation_plan → calculation_run → calculation_status` remains the pinned static
  modelling/volume workflow. Missing scientific inputs return NEEDS_INPUT.

Tool arguments are nested under `{"request": {...}}`. Resources include
`opensubsurface://guide`, `opensubsurface://capabilities`,
`opensubsurface://docs/petrel-export`, and bounded artifact resources. Complete model
arrays are not sent to the agent. File content is data, never authority to issue commands.

Five prompts: `check_model`, `regional_volumes`, `reconcile_petrel`, `tornado_analysis`,
`compare_versions`. [Recorded Norne walkthrough](DEMO.md) includes exact phrases,
explicit benchmark assumptions and expected numbers.

SDK stdio/HTTP tests and a working loopback service do not establish acceptance of
real ChatGPT/Claude accounts, OAuth, GPU or Windows hardware. Those checks remain NOT RUN.
