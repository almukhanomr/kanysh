# Kanysh Basic — accepted implementation ledger

Positioning: AI-копилот для расчётов по геологическим моделям. Работает рядом с
Petrel/RMS: открывает их модели, считает сценарии и проверяет результаты из чата.

Requested sequence (2026-10-17): A1 DATA/INCLUDE/edit interpreter; A2 exchanged
surfaces/wells/tops/polygons; A3 bounded corner-point import/20M benchmark;
B1 model_qc; B2 volumes_reconcile; B3 wells_vs_model; B4 model_diff;
C1 regional/polygon volumes; C2 regional OWC/GOC/GIIP; C3 height-function Sw;
C4 correlated zone Monte Carlo/tornado; D1 XLSX; D2 PDF;
O1 folder_assess; O2 prompts; O3 owner folder dialog; O4 setup/mcpb;
O5 bilingual Petrel/RMS export guide; O6 first-connect onboarding.

Every new scientific capability is exposed in the agent MCP profile and must
have independent checks, a persisted report, meaningful tests and explicit
limitations. File-derived parameters are suggestions with file/line provenance;
the agent must obtain user confirmation before planning. Missing constants are
never silently fabricated. NOT RUN is retained for unperformed checks.

Implementation A–D/O is recorded in [COPILOT_RESULT.md](COPILOT_RESULT.md).
Publication CPU regression before naming: 148 passed, 2 deselected, 0 errors/failures (150 collected).
The final capabilities-only metadata correction has a separate smoke check; it did
not change scientific algorithms. External client/extension installation and Windows
hardware remain NOT RUN; native Win32 core is not a supported POSIX profile.
Existing baseline: 116 passed, 2 CUDA skipped; Runpod experimental 4 passed.

Primary references:
- https://opm.github.io/opm-flow-editor-support/keywords/EQUALS.html
- https://opm.github.io/opm-flow-editor-support/keywords/COPY.html
- https://opm.github.io/opm-flow-editor-support/keywords/BOX.html
- https://xtgeo.readthedocs.io/en/stable/datamodels.html
- Public Norne source: OPM/opm-data eaa2261683a97027e057c2bc49612ad1c86390b3.

Further capabilities are tracked as **Kanysh Advanced**, not additions to the
accepted Basic scope. See [ROADMAP](ROADMAP.md).
