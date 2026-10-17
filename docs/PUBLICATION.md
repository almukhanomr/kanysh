# Publication packaging · 2026-10-17

The A–D and O1–O6 copilot scope is accepted. This pass changes packaging,
demonstration inputs, documentation and viewer language; it adds no product features.
The extended historical [vision ledger](ACCEPTANCE.md) is a separate scope.

## Norne numerical control

The saved demo and [reference results](../examples/reference/norne/results/acceptance.json)
were recalculated from the pinned public inputs. Active cell corner depths span
2439.10888671875–3090.133056640625 m. The three selected OWC alternatives come from
full-deck EQUIL records, not from guessed depths:

| OWC depth, m | EQUIL include line | STOIIP, standard m³ |
|---|---|---|
| 2585.5 | E3.prop:19 | 43,445,409.37812338 |
| 2618.0 | E3.prop:20 | 90,908,326.84597770 |
| 2693.3 | E3.prop:22 | 234,909,634.21512446 |

All three contacts are strictly inside the active geometry range. Oil interval GRV
and STOIIP are strictly increasing; the bundled-report regression checks the actual
saved numbers and contact evidence. These are uniform whole-active-model sensitivity
alternatives with explicit Sw=0.25 and Bo=1.2, without GOC. They are not the separate
regional oil/gas demonstration or a Norne reserves estimate.

## Publication walkthrough

The real HTTP MCP [walkthrough](DEMO.md) ran begin, folder assessment, full-deck import,
model QC, regional oil/gas, tornado, scene and Excel/PDF export. Its
[raw expected results](../examples/reference/norne/results/mcp/expected.json) record
all job and artifact references. The calculation selects EQLNUM 1 and 3 explicitly,
retaining original ACTNUM; other regions' QC findings remain visible. Total STOIIP
is 12,208,629.500405606 standard m³ and free-gas GIIP is
6,196,959,051.323786 standard m³ under the stated demo assumptions.

The seven-page PDF was rendered and visually checked. The XLSX was reopened,
inspected and rendered independently. Export serialization PASS preserves the source
model QC status ISSUES; it does not turn it into geological acceptance.
The English [viewer](copilot-viewer.png) was checked in a real browser, including
opening the newly bundled Norne scene.

## Verification and distribution

- CPU regression: **150 passed, 2 deselected**, zero failures/errors, 420.60 s;
  [portable JUnit](test-results.xml). Selection: not gpu/opm/external; 152 collected.
- English viewer/onboarding/API checks: [11 passed](test-results-publication-ui.xml).
- Ruff lint/format and offline lock check: PASS.
- Source MCPB rebuilt and executed by a real SDK stdio client, with shared loopback
  viewer and isolated synthetic DATA import: [PASS](mcpb-check.json).
- Wheel, sdist and MCPB identities: [distribution record](copilot-distribution.json).
- Personal workstation paths and development-environment names were removed from
  public text, evidence XML/JSON and embedded project archives. JUnit generation
  normalizes checkout paths and removes hostnames automatically.

CI is configured for Ubuntu/macOS CPU tests, excluding gpu/opm/external markers.
GitHub-hosted CI, actual Claude Desktop extension installation, Windows/WSL2/NVIDIA
hardware and OPM Flow remain **NOT RUN**. No package upload or public release was
performed by this packaging pass.

## Product naming

The released product is **Kanysh Basic**. The public package, CLI, Desktop extension,
MCP server identity, web viewer and report branding use that name. Further modelling
capabilities are tracked as **Kanysh Advanced** in [ROADMAP](ROADMAP.md) and
[VISION](VISION.md); they are not Basic features.

The Python namespace, persisted format identifiers, MCP resource URIs and environment
variable names retain their existing technical identifiers for compatibility. Existing
immutable historical evidence retains its original labels. Fresh Norne reports and the
bundled demo were regenerated; scientific numbers are unchanged.
