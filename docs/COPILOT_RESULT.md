# Copilot implementation evidence · 2026-10-17

Product: an AI copilot alongside Petrel/RMS, operating through MCP with a local
viewer. The A–D/O scope is accepted; this publication pass adds no product features. External acceptance is stated separately.

| Request | Implemented scope | Evidence / limits |
|---|---|---|
| A1 | Static DATA GRID/EDIT/PROPS/REGIONS, confined relative INCLUDE, BOX/ENDBOX, EQUALS/MULTIPLY/COPY/ADD; geometry, mask and requested properties/regions | Full unmodified Norne: 58 deck files, 113344 cells / 44927 active; all original properties compared and geometry checked with XTGeo. Unsupported keywords listed with locations. No simulator initialization. |
| A2 | IRAP ASCII/binary, ZMAP+, CPS-3 ASCII, RMS well ASCII; mapped Petrel ASCII trajectories/tops/polygons; scene actors | Analytical format roundtrips, source hashes and canonical-table checks. ASCII mappings/units explicit; CPS-3 order explicit. Binary CPS-3 and native project databases unsupported. |
| A3 | Streaming COORD/ZCORN into chunked corner-point Zarr | 20M synthetic cells: peak RSS 1458208768 bytes, 133.88s import, all corners/properties checked; raw evidence below. Large binary EGRID/ROFF still uses capped full-RAM XTGeo route. |
| B1 | model_qc: signed/trilinear Jacobians, twist/collapse, ranges, NTG/PORO, zero PV, six-neighbour clusters, severity/IJK CSV, region summary | Independent determinants and cluster accounting; numerical checks are separate from model issue status. Connectivity is topological, not transmissibility. |
| B2 | volumes_reconcile: explicit CSV mapping, units/metric/region definitions, recomputation, differences, evidence-labelled possible causes | Analytical mismatch control: matching HCPV plus differing STOIIP identifies a possible Bo basis; inferred cause is never asserted as fact or used to alter data. |
| B3 | wells_vs_model: explicit LAS curve/units, XYZ/MD trajectory interpolation, point-to-cell lookup, bias/MAE/RMSE/correlation by well/region | Independent Cramer-rule containment and scalar RMSE. Original LAS imported, no hidden upscaling; gaps/outside/nulls reported; no samples → NOT RUN. |
| B4 | model_diff: equal IJK revisions, changed fields/cells/IJK CSV and region GRV/PV/HCPV impacts | Independent bulk integrals. Invalid/missing values yield unavailable impacts; different topology/CRS rejected. No inferred contact/Bo/STOIIP. |
| C1–C3 | Regional/fault-block and whole-cell polygon volumes; regional OWC/GOC, STOIIP/GIIP; explicit Sw height table/Leverett J | Independent tetra/determinant/ConvexHull controls. Polygon membership uses mean corner XY, not fractional XY clipping. Height Sw evaluated at mean corner Z. All physical inputs explicit. |
| C4 | One-at-a-time tornado; seeded bounded marginal Monte Carlo with Gaussian-copula latent correlations | Every valid draw independently checked; failed draws retained, no resampling. Linear-rank quantile check; P90=Q10/P50=Q50/P10=Q90. Partial draws labelled conditional. Not spatial uncertainty. |
| D1–D2 | results_export: XLSX Scenarios/Regions/Checks/Assumptions/Definitions and other tables; PDF tables/plots/assumptions/provenance and optional seismic slices | Every workbook cell reopened/compared; independent PDF text/page checks. Export PASS is serialization only. PDF presentation row limit explicit; source NOT RUN/FAIL retained. Fixture rendered and visually reviewed with Poppler and artifact_tool. |
| O1–O2 | folder_assess and five scenario prompts | Bounded headers, role candidates/missing inputs/workflows, file/line proposals requiring user confirmation before plan/calculation. Scientific assessment NOT RUN until import/checks. |
| O3 | Owner-only Add folder button, native picker, CLI retained | Dialog registration/cancellation tested with a controlled picker. Actual OS interaction on Windows/WSL NOT RUN. No folder registration MCP tool. |
| O4 | setup environment/home/client JSON backup/idempotency, viewer launch/reuse; source UV-runtime .mcpb builder | Isolated config and archive tests. Real Claude client connection/extension installation NOT RUN. Native Windows backend and Windows/macOS/Linux MCPB are prepared; Windows/Desktop UV installation remains NOT RUN. WSL is optional for OPM Flow. [Windows evidence](WINDOWS_NATIVE.md). |
| O5–O6 | Bilingual global export guide, bundled MCP resource, first-connection start/begin | Format-first guidance; version-specific vendor GUI menus NOT RUN. Saved Norne demo is explicitly distinguished from fresh calculation. |

All new scientific operations are in the `agent` profile and return durable job IDs,
immutable results, reports and numerical check evidence. `folder_assess` is a read-only
JSON discovery report, not a scientific result. The server instructs the client to
obtain user confirmation; a schema flag is not proof that a human actually confirmed it.

## Raw controls

- [Full Norne DATA import](norne-data-check.json), script `scripts/test_full_norne_deck.py`.
- [20M corner-point benchmark](benchmark-cornerpoint-20m.json), script `scripts/benchmark_cornerpoint.py`.
- [Initial 20M failure before memory fix](benchmark-cornerpoint-20m-first.json) is retained.
- [Existing 18.1GB Cartesian benchmark](LARGE_MODEL_RESULT.md).
- [Existing streaming SEG-Y benchmark](benchmark-seismic.json).
- New adapter/scientific tests: `test_eclipse_deck.py`, `test_geodata.py`,
  `test_copilot_analyses.py`, `test_results_export.py`.
- MCP/worker integration: `test_copilot_mcp.py`; onboarding/prompts/config/archive:
  `test_onboarding.py`; scene includes wells, surfaces, markers, polygons, grid and seismic.

The Norne DATA test does not substitute SWATINIT for SWAT: equilibrium Sw, fresh reserves,
Flow history and geological fitness remain NOT RUN. The independent XTGeo corner comparison
uses a precision bound derived from its internal float32 ZCORN ULP and pillar slope:
0.0044459m bound, 0.00070552m maximum observed difference; source float64 is retained.

No new acceptance is claimed for Windows/NVIDIA/WSL2 hardware, native Win32 execution,
real ChatGPT/Claude accounts, OPM Flow, full Volve, 1TB models or 15GB field SEG-Y.
Menu differences and unsupported keywords remain visible rather than silently filled in.

## Final validation

- Publication CPU suite: **150 passed, 2 deselected, 0 failures/errors**, 152 collected,
  420.60 seconds; [portable JUnit](test-results.xml). Selection excludes gpu/opm/external.
  This includes the three-distinct-contact bundle regression, MCP/worker path and scene actors.
- [Publication controls](PUBLICATION.md) include recomputed Norne and the actual regional oil/gas MCP demonstration.
  The 2M XTGeo route remains distinct from streaming DATA; no scientific algorithm changed in packaging.
- Ruff and format checks PASS; frozen lock has 200 resolved packages.
- Full Norne DATA control rerun PASS; 20M benchmark evidence retained with its actual scope.
- Wheel/sdist built; [distribution identities](copilot-distribution.json) recorded outside the archives; optional UI and excluded SDK/Runpod paths verified in the archive.
- Updated wheel in an existing UI-free core environment: [PASS](copilot-core-check.json).
  All 114 installed package requirements also pass `uv pip check`. A fresh full offline solve was unavailable because the registry cache is incomplete.
- Source MCPB with SDK stdio/shared viewer/isolated import: [PASS](mcpb-check.json),
  [archive identity](mcpb-build.json). Real Desktop installation is NOT RUN.
- Owner setup exercised only with isolated configuration files: [evidence](setup-check.json).
  Original/backup/idempotency/conflict behaviour has integration tests; real user config was not edited.
- Actual Norne XLSX imported/rendered through artifact_tool; PDF rendered by Poppler and all 7 pages
  visually reviewed. [PDF](../examples/reference/norne/results/mcp/results.pdf),
  [XLSX](../examples/reference/norne/results/mcp/results.xlsx). Source model QC remains ISSUES.
- [Viewer screenshot](copilot-viewer.png): Add folder, revision list, reports/scene and offline Norne.
- [Runtime identity](copilot-runtime.json) includes the export and polygon dependency versions.

No external acceptance is inferred from these CPU SDK/serialization fixtures.
