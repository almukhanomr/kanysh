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

## Basic verification still outstanding

These are verification/deployment tasks for **Kanysh Basic**, not Advanced features:

- Native Windows x64 / Claude Desktop UV installation and optional NVIDIA workstation checks. The native backend is implemented; WSL is optional for OPM Flow.
- Actual Claude Desktop extension installation and real external MCP-client checks.
- GitHub-hosted Ubuntu/macOS CI execution and user-supplied Petrel/RMS reconciliation
  datasets with confirmed assumptions. The workflow is configured; hosted CI is NOT RUN.

External resources do not establish correctness by themselves. Basic and Advanced
both retain independent numerical checks, immutable provenance, explicit scientific
inputs, and honest FAIL / NOT RUN statuses. No Advanced capability was added in the
publication or naming pass.
