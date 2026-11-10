# Kanysh Advanced — future development

**Kanysh Basic** is the accepted A–D/O1–O6 MCP copilot alongside Petrel/RMS.
Its implementation and current limits are recorded in [COPILOT_RESULT](COPILOT_RESULT.md).
New modelling capabilities belong to **Kanysh Advanced**. They are a development
backlog, not features available in Basic or a committed delivery schedule.

## Advanced backlog

- Richer multi-horizon/multi-fault structural modelling, large GemPy builds,
  well-log upscaling, facies/spatial property simulation and well correlation.
- Large binary EGRID/ROFF import beyond the current capped XTGeo route;
  S3/file-storage integration and complete-field Volve demonstrations.
- Server-side LOD/rendering for very large scenes, interactive picking and seismic
  polyline interpretation. Basic retains its bounded offline viewer.
- Remote compute registration/transport, resource/VRAM preflight and remote cancellation.
- Full OPM initialization/waterflood, fluid/completion/schedule schemas, three-phase
  profiles, per-well dynamic results and validated CPU/GPU solver configuration.
- History matching / ES-MDA, richer ensembles and development-plan optimization.
- Extended typed workflow ports, staleness/permissions/limits and output validation.
- Externally deployed OIDC/OAuth infrastructure and production deployment profiles.

The [historical long-term vision](VISION.md) provides context. Implemented portions
already included in Basic remain Basic. Unimplemented vision items are Advanced
candidates; the historical ledger does not establish their readiness.
Runpod remains an isolated Advanced experiment in `experimental/runpod`, excluded
from the Basic package and production MCP profiles.

## Basic verification status

Verified (2026-10-18…19, Windows 11 x64, 16 cores, 64 GB, RTX 3080 Ti Laptop):

- GitHub-hosted CI: Ubuntu, macOS and Windows CPU suites pass on `main` (commit `aabb128`).
- Native Windows: the `.mcpb` installs in Claude Desktop and the tools run on a real exported
  model ([Volve test](VOLVE_REAL_DATA_TEST.md)). This is an owner check without a
  machine-readable record.
- CUDA: `gpu`-marker tests pass ([raw result](test-results-scaling-gpu.xml): 10 passed,
  1 skipped); Norne regional volumes on CUDA match the mandatory CPU comparison
  ([benchmark](benchmark-scaling-norne-cuda.json)). CUDA is slower than CPU on that profile;
  no speed-up is claimed.
- OPM Flow 2026.04 in WSL2 runs a user deck (Volve, 339 report steps) and is compared with
  the supplied ECLIPSE results.

Still outstanding for **Kanysh Basic** (verification, not Advanced features):

- ChatGPT and remote OAuth MCP connectors; Desktop disable/re-enable with no orphan processes.
- User-supplied Petrel/RMS reconciliation datasets with confirmed assumptions.
- GPU runs on 10–200 million cells and large binary field EGRID/INIT.
- Gaps found on Volve: `ADDZCORN`, initial SWAT import, scattered-point surfaces, RESCUE.

External resources do not establish correctness by themselves. Basic and Advanced
both retain independent numerical checks, immutable provenance, explicit scientific
inputs, and honest FAIL / NOT RUN statuses. No Advanced capability was added in the
publication or naming pass.
