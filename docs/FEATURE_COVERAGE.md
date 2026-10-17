# Покрытие функций / ориентир Petrel

`validated` означает проверенный указанный узкий scope, `implemented` — код без полной
приёмки, `limited` — частичная реализация, `planned` — отсутствующая функциональность.
**Полный паритет с Petrel и готовность полного релиза v0.2 не заявляются.**

| FR | Предметный процесс / ориентир Petrel | Реальный scope этой сборки | Компонент | Профиль | Acceptance | Статус |
|---|---|---|---|---|---|---|
| 01 | Проекты и версии | immutable refs/hash, atomic artifacts, ZIP, backup/restore | persistence/store, Alembic | local-cpu | A-12 | validated |
| 02 | Скважины и исходная интерпретация | collars/XYZMD/LAS/markers/surfaces/orientations; no complex deviation surveys | adapters/imports | local-cpu | A-02 | limited |
| 03 | QC и координаты | Pint lengths, declared projected metric CRS/datum, finite/ranges/MD/normals; no geodetic datum inference | schemas/imports | local-cpu | A-03 | limited |
| 04 | Локальный просмотрщик | проекты/ревизии, отчёты, 3D HTML, SEG-Y slices, upload и offline Norne; без научных форм | ui extra | local-cpu | A-09 | limited |
| 05 | Согласные слои | actual GemPy/PyTorch CPU + explicit horizontal analytical model; horizontal/dipping/single-fault fixtures validated | adapters/structure | local-cpu; CUDA code untested | A-04/A-06 | limited |
| 06 | Свойства / статические объёмы | constants per zone, fractional OWC, analytic STOIIP, seeded scalar table/P-convention; out-of-core Cartesian NPY/GRDECL-properties → Zarr import/volume/uncertainty/independent checks; 402.7M-cell /18.119GB raw-model CPU control PASS; sampled RSS353.5MiB; single file/ZIP>15GiB NOT RUN | domain/numerics, tasks | CPU validated; CUDA NOT RUN | A-05 | validated (CPU scope) |
| 07 | Вычислительные targets/jobs | Dask local, isolated processes, ledger/attempts/bounded retry, cancel/timeouts, cache primitive, RAM/GPU/VRAM diagnostics; remote transport absent | execution, service | local-cpu; Windows/WSL NVIDIA first target NOT RUN | A-07/A-08 | limited |
| 08 | Внешние MCP-клиенты | stdio/HTTP, typed plans, validation/reports, active-viewer links; без собственного чата/голоса | mcp/service | local | A-11; A-10 replaced | limited |
| 09 | SEG-Y | streaming regular zero-offset poststack 3D, direct source import beyond upload cap into float32 Zarr; 269.4MB/67.1M samples bitwise exact; IEEE/endian/scalar fixtures | adapters/seismic | local-cpu | B-01 | limited |
| 10 | Атрибуты / picks / time-depth | RMS/envelope CPU validated, picks version JSON + depth CSV; no pixel/polyline interpolation | seismic/tasks/numerics | local-cpu; CUDA NOT RUN | B-02/B-03/B-04 | limited |
| 11 | Простой разлом | single planar GemPy fault, explicit relation, side blocks, convex plane preview; OPM bridge rejected | structure/tasks | CPU validated, CUDA NOT RUN | B-05 | limited |
| 12 | Геостатистика | GSTools Exponential krige/CondSRF/logit/log, holdout, anis ratios checked against independent covariance system; ensemble statistical acceptance incomplete | adapters/geostat | CPU | B-06 | limited |
| 13 | Simulation grid bridge | same-resolution Cartesian, I-fast/K-down mapping, ACTNUM and net-rock NTG convention | adapters/opm | CPU exporter | B-07 | validated (mapping); limited (bridge) |
| 14 | PVT / SCAL / schedule | explicit accepted synthetic constants/STCOND, typed bounds/monotonic SWOF/report days; no arbitrary events/completions | schemas/opm | CPU exporter | B-08/B-09 | limited |
| 15 | OPM Flow | real executable launcher, output presence/report-day checks; no solver binary/GPU build validation | adapters/opm | CPU code; CUDA blocked | B-10/B-11/B-12 | implemented / unvalidated |
| 16 | Прогноз / анализ | resdata summary/INIT/restart adapter; REST snapshots, date/unit alignment, water-cut, CSV; component QC narrow profile; native Flow/restart acceptance pending | adapters/opm/results, domain/results | solver extra; analytical numerical fixtures validated | B-13/B-14 | limited |
| 17 | Ансамбли / uncertainty | explicit realization×schedule accounting, partial/restart/resume; dynamic pointwise bands and constraints/ranking ≤10 validated analytically; six real Flow cases pending | workflows/ensembles, domain/results | local-cpu | C-01/C-02/C-03 | limited |
| 18 | Workflows | DAG/fan-out/fan-in, pinned refs, params, partial/restart/resume input+config+library+source+Flow hashes; single-artifact typed port preflight; advanced output ports incomplete | workflows/engine, service | local-cpu | C-04/C-05 | limited |
| 19 | Managed cloud | Вынесен в experimental/runpod; исключён из пакета и MCP | experimental | mocks only | вне основной приёмки | experimental |
| 20 | Приёмка / benchmarks | raw tests, CPU-volume benchmark, compatibility/acceptance ledger and docs; full engineering acceptance open | docs/scripts/tests | current CPU host | A–C | limited |

Наличие extra `viewer/solver/voice` не считается реализацией или validation функций.
Подробный остаток: ROADMAP.md. Полные статусы критериев: ACCEPTANCE.md.

Corner-point XTGeo GRDECL/EGRID/ROFF, ACTNUM, explicit GRDECL/scalar properties, tetrahedral volumes
и Norne field acceptance: [PETREL_WORKFLOW](PETREL_WORKFLOW.md). Native Petrel projects не поддерживаются.
