# Your first result in Kanysh Basic

[Russian](GETTING_STARTED.ru.md) · [Website](https://kanysh.com)

For geologists and reservoir engineers. Start with the saved Norne example, then
check your own model. You can use ordinary language in the connected chat.

Kanysh Basic has two parts: **your chat** requests calculations; the **local viewer**
opens models, reports and files. Calculations and model arrays stay on your workstation.
Your chat client controls what messages and tool results it sends to its AI provider.

This is a development release. Numerical code and local SDK connections have been
checked. Actual Claude Desktop installation, real external chat-client acceptance
and Windows/WSL2/NVIDIA workstation checks remain **NOT RUN**. You may need IT help
for installation, especially on Windows. A GPU is not required for the Basic CPU workflows.

## 1. Install once

### Prepare your workstation

| Your computer | Where to run the commands below |
|---|---|
| macOS | The Terminal application. Install your chosen Claude client separately. |
| Windows | An Ubuntu terminal inside **WSL2**, which runs Linux applications on Windows. Ask IT to prepare it using [Microsoft's WSL instructions](https://learn.microsoft.com/en-us/windows/wsl/install). Do not paste the Linux commands into PowerShell. The Windows route is prepared but not hardware-validated. |
| Linux | A terminal. Use Claude Code or another compatible MCP client; setup does not register a native Claude Desktop application on Linux. |

**Download the source ZIP from this project's GitHub page or release and unzip it.**
If supplied, `kanysh-basic-github-source.zip` is the clean source bundle. Open the
inner folder containing `pyproject.toml`, `uv.lock` and `README.md`. A browser showing
README text is not an installed application.

Install **uv**, the utility that downloads Python and this project's dependencies,
using its [official installation instructions](https://docs.astral.sh/uv/getting-started/installation/).
Close and reopen the terminal if `uv` is not found. Check it with:

```bash
uv --version
```

**Expected:** a version number. Next, change to your unzipped project folder:

```bash
cd "/path/to/kanysh-basic"
```

Replace `/path/to/kanysh-basic` with the actual folder path; keep the quotes. On
Windows this must be a path understood by Ubuntu. Ask IT to locate the folder if
needed. Do not type the example path unchanged.

### Install and connect

Run these commands one at a time in that folder:

```bash
uv python install 3.12
uv sync --frozen --no-dev --extra ui --extra viewer --python 3.12
```

The first command prepares Python 3.12. The second installs Kanysh Basic and the
viewer. First installation needs internet access and several GB of free space for
scientific libraries, in addition to your model data. Wait for the terminal prompt
to return. If a command fails, use the troubleshooting table below before continuing.

Close your Claude clients, then run:

```bash
uv run --no-sync kanysh-basic --home "$HOME/.kanysh-basic" setup
```

**Expected:** setup prints a result and opens a browser viewer headed **Kanysh Basic**.
Its result includes a viewer URL; use that URL if the browser does not open.
`RUNNING` or `ALREADY_RUNNING` is the viewer success status. `CONFIGURED` or `UNCHANGED`
means a client configuration was written or already matched; it does not prove a chat
connection. Setup backs up an existing configuration before changing it.

The folder `$HOME/.kanysh-basic` holds your project records and results. Keep using
this same folder. Existing users with a different state folder should retain their
original `--home` instead of starting an empty one. Details: [setup reference](ONBOARDING.md).

### If you received a Desktop extension instead

A `.mcpb` file is an extension package, not a geological model. The current
`kanysh-basic-0.2.0-dev1.mcpb` needs a host supporting MCPB v0.4's UV runtime.
Its archive/SDK launch is checked; installation in the actual Desktop application
is **NOT RUN**. This bundle does not advertise native Windows support. If the host
rejects it, use the source route above or ask IT; do not rename the file to force an install.
[Extension details](ONBOARDING.md#desktop-extension-package).

## 2. Open Norne before adding your files

In the local viewer click **Open Norne demo**. Allow time for the scene to load.
You should see a Norne project with a porosity-coloured 3D grid. Use **Artifact and
revision** to select a saved `calculation_report` and open its result page.

**Expected:** 113,344 grid cells, 44,927 active cells; the saved three-contact report
uses OWC depths 2585.5 / 2618.0 / 2693.3 m and shows three different STOIIP values.
This opens bundled results and performs no new calculation. The fluid assumptions
are a public benchmark, not Norne reserves. [Exact numbers and a fresh-calculation recipe](DEMO.md).

## 3. Check that the chat is connected

Restart your Claude client after setup. In a new conversation request:

> Use Kanysh Basic's start tool. Show me its welcome message and the projects available.

If the client offers server prompts, you can select **begin** instead. Simply typing
“begin” is not proof that a tool was called.

**Expected:** the client shows an actual Kanysh Basic tool invocation and its returned
result. If it only gives a general explanation or says the tool is unavailable, fix
the connection before requesting calculations. Your client's tool list should expose
Kanysh Basic. Claude Code users can inspect connections with `/mcp`.

The viewer and the chat are separate windows. The viewer has no built-in chat or
calculation forms. After installation, tool names are for the agent; you describe the task.

## 4. Add and check your own model

Export a copy from Petrel/RMS into one dedicated folder. For the first grid check,
prefer a complete **ECLIPSE ASCII DATA/GRDECL** export with its INCLUDE files,
geometry, active-cell mask and properties. Preserve the folder structure.
A native Petrel/RMS project directory is not an exchange export.
[What to export](PETREL_EXPORT.md).

Click **Add folder** in the viewer and select that data folder. The button lets the
local installation owner authorize access. It does not import or calculate the model.
Then send:

> Assess my registered model folder. List the files, missing inputs and available
> checks. Show the source of any proposed parameters. Do not calculate yet.

**Expected:** a file summary and available workflows, or an explicit description of
missing inputs/scan limits. This is discovery, not a model-QC result.

Review the proposed coordinate system, vertical reference, units, depth/Z direction
and region definition against your project documentation. If something is unknown,
say so; the agent should request it rather than invent it. Parameters found in a file
are proposals until you confirm them. Then request:

> I have confirmed the import metadata you listed. Import the model and check its
> geometry and properties. Show severity, affected IJK cells, regional summaries,
> assumptions and independent-check results. Keep all findings; do not repair the model.

Only confirm metadata you have actually checked. **Expected:** a completed job and a
QC report, or an explicit failure/missing-input explanation. An **ISSUES** report is
a result to review, not permission to discard the flagged cells.

## 5. Calculate a scenario and keep the report

For oil/gas volumes, provide the selected regions, OWC/GOC, Bo/Bg, saturation basis,
units and reference datum as applicable. Values from the Norne demo are not defaults
for your field. Start with this request:

> Prepare regional oil and free-gas volumes for this model. First ask me for all
> required contacts, fluid parameters and assumptions. Calculate only after I confirm them.

After reviewing and confirming your inputs, ask:

> Run the confirmed scenario, independently check the result, and show the regional
> table and assumptions. Export the calculation and QC reports to Excel and PDF.

**Expected:** actual job completion, a report and export-file links. If the viewer
is running, report/scene links lead to it. Open the result page and choose the XLSX/PDF
file links to save them. A chat answer without a tool result is not evidence of a calculation.

| What you see | Meaning / next action |
|---|---|
| Job `succeeded` | The operation finished. Read the report's scientific and QC statuses too. |
| Independent checks `PASS` | Numerical checks agree within declared tolerances. Geological interpretation still needs your review. |
| `ISSUES` | Review the listed problems, severity and IJK locations. Do not silently remove cells. |
| `NEEDS_INPUT` | Supply or clarify the missing engineering input. Do not substitute an arbitrary value. |
| `NOT RUN` | That check was not executed; it is not a pass or a zero result. |

## 6. Return to your work

Use the same client and state folder. If the viewer is closed, open a terminal in
the installed project folder and run:

```bash
uv run --no-sync kanysh-basic --home "$HOME/.kanysh-basic" setup
```

It reuses an active viewer or starts one. Restart the chat client if it lost the
connection. Projects are stored in the state folder, not in the chat conversation.
For unattended/manual service operation, IT can use [MCP setup](MCP_SETUP.md).

## If something goes wrong

| Problem | What to do |
|---|---|
| `uv` is not found | Reopen the terminal after installing it. On Windows, install/run uv inside Ubuntu. |
| `pyproject.toml` cannot be found | You are in the wrong folder. Open the unzipped inner project folder and repeat `cd`. |
| Dependencies do not install | Check internet, disk space, Python 3.12 and your organisation's package-access rules. Keep the error text for IT. |
| Viewer did not open | Use the URL printed by setup. For `FAILED`, inspect the indicated `viewer.log`. The port may differ from 8765. |
| Setup shows `STARTING` | Wait briefly and open the printed URL again. If it remains unavailable, inspect the indicated `viewer.log`. |
| Chat cannot see Kanysh Basic | Restart the client; check its MCP connection. Configuration conflicts need the [setup reference](ONBOARDING.md), not repeated blind edits. |
| Projects appear missing | Check the same `--home` was used. A different state folder has a different project list. |
| **Add folder** does not work | It requires a local owner session and desktop dialog. IT can use the documented `source-add` command on a headless host. |
| Model does not load | Check exchange format, INCLUDE files and import report. Binary EGRID/ROFF currently has a 2 million-cell cap; large block import uses ASCII. |
| Agent requests CRS, datum or Bo/Bg | Provide the relevant project basis; this is an input requirement, not something to bypass. |
| An operation failed | Keep the job ID and error/report. Do not report the last successful scenario as this failed run's result. |

For a reproducible bug report include OS, installation route, operation/job ID and
sanitized error text. Remove private paths, credentials and confidential model files.
Usability with independent engineers has not yet been validated.
