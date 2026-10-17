# Norne MCP walkthrough — 2–3 minute recording

This is a reproducible public-data demonstration of the accepted features. It is not
a Norne reserves estimate, a simulator initialization or a recording of a tested LLM.
The script uses the real MCP Python SDK against your running service. Real ChatGPT/Claude
client acceptance remains NOT RUN.

## Preparation (off camera)

Python 3.12, uv, a local checkout, and roughly 200 MB for public inputs/results plus
Python dependencies. Fetches are pinned to OPM/opm-data commit
`eaa2261683a97027e057c2bc49612ad1c86390b3`. Preserve the Statoil / OPM ODbL/DbCL notices.

```bash
uv sync --frozen --extra ui --extra viewer --extra solver --group dev
uv run --no-sync python scripts/fetch_norne_reference.py
uv run --no-sync python scripts/fetch_norne_deck.py
uv run --no-sync python scripts/test_norne_reference.py
uv run --no-sync kanysh-basic --home ./state serve --ui --mcp-profile agent --port 8765
```

The reference script uses a fresh executor state per run, recomputes the three-contact
control, checks strict result differences and updates `examples/reference/norne/results`
and the bundled offline project. It never reuses a stale owner source registration.

In another terminal, reproduce the video operations and save their results:

```bash
uv run --no-sync python scripts/demo_norne_mcp.py --home ./state --accept-demo-assumptions
```

`--home` must match the running server. The owner-run script registers
`examples/reference/norne/full/norne` as a read-only source before using MCP;
there is no MCP folder-registration tool. For a chat recording, the owner can instead
choose **Add folder** in the viewer and select that directory. Use `source_list` to
identify it. Never register your entire home directory for this demonstration.

The script follows `begin → folder_assess → import → check_model/model_qc →
regional_volumes → sensitivity_tornado → scene → results_export`.
It creates a new project, preserves the original ACTNUM, waits for actual job states,
and writes `examples/reference/norne/results/mcp/expected.json`, reports, the scene,
`tornado.png`, `results.xlsx` and `results.pdf`. Numerical PASS comes from independent
checks. The explicit flag accepts the benchmark parameters below only.

## Exact recording phrases

Use the same meanings in another language if your chat is not English. Tool names
are stable; the web viewer is English. Times are editorial targets, not a performance
promise. Leave actual job status visible; label any cuts/time compression.

| Time | Say / type | Show |
|---|---|---|
| 0:00–0:15 | **“Begin. Show me what this copilot can do alongside Petrel and RMS.”** Select prompt `begin`. | Welcome and owner folder/demo instructions. |
| 0:15–0:35 | **“Assess my registered Public Norne DATA folder. Show the model files, missing inputs and contact proposals with their source lines. Do not calculate yet.”** | `folder_assess`, full DATA and EQUIL proposal in `INCLUDE/PETRO/E3.prop`. Discovery is not model validation. |
| 0:35–0:55 | **“This is a public benchmark. I confirm metres, source depth positive down, canonical Z negative depth, and a standalone LOCAL_METRIC frame with unverified source datum. Keep original ACTNUM. Import the full DATA; set only missing SWAT to the explicit demo value 0.25. Check the whole model and keep all findings.”** Select `check_model`. | 113,344 cells / 44,927 active. QC status **ISSUES**: 243 degeneracy flags and 1 twist flag; flags may overlap. Independent numerical checks PASS. No silent repairs. |
| 0:55–1:25 | **“Calculate only EQLNUM 1 and 3. I confirm region 1 OWC Z = −2692 m and GOC Z = −2582 m; region 3 OWC Z = −2618 m and GOC Z = −2582 m, from EQUIL lines 18 and 20. Use demo Bo = 1.2 rm³/sm³, Bg = 0.005 rm³/sm³, Sw = 0.25, oil-zone Sg = 0 and gas-zone So = 0.05. These are static demo assumptions, not calibrated field PVT. Report oil and free gas separately and independently check them.”** | Regional rows and totals below. Only 5,520 selected cells; findings elsewhere remain visible. |
| 1:25–1:50 | **“Run an STOIIP tornado: vary the porosity multiplier separately in region 1 and region 3 from 0.9 to 1.1. Keep all other baseline inputs fixed. These are deterministic ranges, not probability distributions.”** | Two-bar tornado and independent checks. |
| 1:50–2:15 | **“Show the full original active grid coloured by porosity in the 3D scene. Use stride 1; do not change calculation inputs.”** | `scene_show` / `scene_export`, all 44,927 active cells. Explain that the scene displays the whole model while regional volumes select EQLNUM 1 and 3. |
| 2:15–2:45 | **“Export the regional, tornado and QC reports to Excel and PDF. Include the assumptions and preserve ISSUES/NOT RUN statuses.”** | XLSX Scenarios/Regions/Checks/Assumptions; PDF tables and tornado. Export PASS verifies serialization, not geological fitness. |

The full DATA has SWATINIT, not a ready equilibrium SWAT. Constant Sw is deliberately
specified for the demo. Bo/Bg and residual saturations are demo inputs, not values
inferred from the PVT tables. No equilibrium, dissolved-gas inventory or Flow forecast
is calculated. Contact interpretation follows the [OPM EQUIL definition](https://opm.github.io/opm-flow-editor-support/keywords/EQUIL.html).

## Expected regional numbers

Source: [`mcp/expected.json`](../examples/reference/norne/results/mcp/expected.json).
Units below: standard m³ for STOIIP/GIIP. Values are from the actual f64 DATA import;
compare numerically with relative tolerance `1e-8`, not screenshots or rounded labels.

| EQLNUM | Selected cells | OWC depth m | GOC depth m | STOIIP sm³ | Free-gas GIIP sm³ |
|---|---:|---:|---:|---:|---:|
| 1 | 4,224 | 2692.0 | 2582.0 | 9,347,773.538443357 | 5,375,318,797.801889 |
| 3 | 1,296 | 2618.0 | 2582.0 | 2,860,855.961962250 | 821,640,253.5218961 |
| Total | 5,520 | regional | regional | **12,208,629.500405606** | **6,196,959,051.323786** |

EQUIL provenance: `full/norne/INCLUDE/PETRO/E3.prop`, lines **18** and **20**, records
1 and 3. These regions pass the numerical geometry requirements of the existing
regional calculation; the model-wide QC findings remain in its report.

| Tornado parameter | Input range (multiplier) | Low STOIIP sm³ | High STOIIP sm³ |
|---|---|---:|---:|
| EQLNUM 1 porosity | 0.9–1.1 | 11,273,852.146561272 | 13,143,406.854249947 |
| EQLNUM 3 porosity | 0.9–1.1 | 11,922,543.904209383 | 12,494,715.096601833 |

## Three-contact offline bundle control

This separate control uses **all 44,927 active cells**, a uniform OWC per scenario,
Sw=0.25 and Bo=1.2, without gas-cap clipping. Contacts are selected from actual
EQUIL OWC records as sensitivity alternatives, rather than a regional initialization.
Active cell-corner depths span **2439.10888671875–3090.133056640625 m**.

| Uniform OWC depth m | Source EQUIL line | STOIIP sm³ |
|---:|---:|---:|
| 2585.5 | 19 | **43,445,409.37812338** |
| 2618.0 | 20 | **90,908,326.84597770** |
| 2693.3 | 22 | **234,909,634.21512446** |

All contacts are strictly inside that interval. Both oil-interval GRV and STOIIP
must increase strictly with deeper OWC. The generation script asserts this on the
fresh calculation; `tests/scientific/test_norne_demo.py` repeats the check on the
actual bundled report. If EQUIL is absent, the helper selects explicit interior
25/50/75 percent positions of the depth range; it does not assign probabilities.
If EQUIL exists but cannot provide three in-range contacts, generation stops.

Results: [`volumes.csv`](../examples/reference/norne/results/volumes.csv),
[`report.html`](../examples/reference/norne/results/report.html),
[`acceptance.json`](../examples/reference/norne/results/acceptance.json).
The offline viewer opens saved evidence; fresh calculations use the MCP workflow above.
