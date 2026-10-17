# Compatibility spikes

Дата проверки: 17 октября 2026, Asia/Almaty. Стенд: macOS 27.0.1 arm64, 16 GiB RAM,
10 logical CPU, Python 3.12.14. Полные версии и hashes wheels закреплены в `uv.lock`.

| Компонент | Выбранная версия | Проверка / статус |
|---|---|---|
| GemPy / engine | 2026.0.3 / 2026.0.3.post1 | PASS, реальные PyTorch CPU horizontal/dipping/single-fault fixtures |
| NumPy / SciPy | 2.5.4 / 1.18.1 | PASS, analytical volumes, RMS, envelope |
| PyTorch | 2.14.1 | CPU доступен; CUDA NOT RUN, NVIDIA отсутствует |
| GSTools | 1.7.0 | PASS, exact conditioning/logit/seed/holdout/independent anisotropic covariance; API cond_err='nugget' |
| lasio | 0.32 | PASS, LAS 2.0, null sample, явный MD mapping |
| segyio | 1.9.14 | PASS, IEEE float32, big/little endian, scalar −100 |
| Zarr | 2.18.7 | PASS, trace chunks и slices в ZipStore |
| Dask / distributed | 2026.8.0 | PASS, inproc scheduler + isolated subprocess cancel |
| Gradio / Plotly | 5.50.0 / 6.9.0 | PASS, Chrome CPU demo и отдельные analytical result fixtures: series/snapshot/bands/CSV; VTK/trame verified separately below |
| Matplotlib | 3.11.2 | Agg PNG + self-contained HTML/Markdown/JSON/CSV static report; no display server |
| Agent static workflow | static_volumetrics_v1 | PASS на CPU: GemPy CSV → pinned plan → 3 OWC → seeded scalar uncertainty → independent numerical checks → report; SDK disconnect/reconnect, partial failure/resume, corrupt/wrong results |
| MCP Python SDK | 1.30.0 | PASS, stdio и общий ASGI Streamable HTTP ClientSession list/call, token guard/shared REST artifacts |
| Local headless / filesystem sources | текущий source | PASS на macOS CPU: CLI HTTP daemon без Gradio, source scan/snapshot/import, disconnect, path/revision/revocation checks; Windows launcher ещё NOT RUN |
| OPM Flow | solver не установлен | NOT RUN, native forecast/conservation/INIT/restart pipeline требует Linux стенда |
| resdata | 6.3.5, установлен solver extra | PASS, Summary.writer→binary SMSPEC/UNSMRY→reader; EGRID/INIT/two-report UNRST format fixture с независимым resfo writer, ACTNUM/inactive/IJK и snapshots; real Flow outputs NOT RUN |
| Docker | CLI установлен | daemon не запущен; images/build NOT RUN |

Научные тесты: `uv run pytest tests/scientific -q`. GemPy использует custom grid, исключая
лишнюю octree-сетку. Проверка API выполнена по установленному коду, поскольку старые
примеры `Grid.set_active_grid` несовместимы с этой версией.

Первичные источники адаптеров:
[GemPy](https://docs.gempy.org/examples/geometries/a01_horizontal_stratigraphic.html),
[GSTools](https://geostat-framework.readthedocs.io/projects/gstools/en/stable/examples/05_kriging/01_ordinary_kriging.html),
[segyio](https://segyio.readthedocs.io/en/latest/segyio.html),
[OPM solver](https://opm-project.org/?page_id=1798),
[MCP SDK](https://github.com/modelcontextprotocol/python-sdk),
Эти ссылки подтверждают API-кандидаты, а не приёмку Kanysh Basic.

Для OPM отсутствует проверенный build/digest. Он намеренно не объявлен поддержанным:
выбрать build в Linux, pin digest, выполнить no-flow/waterflood/upstream CPU и CUDA tests.
Первый пользовательский профиль графстанции — Windows + NVIDIA через WSL2.
Реальные WSL2/DrvFs/reparse-point/GPU memory и native numerical tests на такой станции ещё нужны;
подготовленная инструкция/launcher не считаются этой приёмкой.

Публикационная CPU-регрессия: **150 passed, 2 deselected**, 0 failures/errors, 420.60 s;
gpu/opm/external исключены. GitHub-hosted Ubuntu/macOS CI пока NOT RUN
([raw XML](test-results.xml)). Ruff и offline uv lock check — PASS.
Контроль через постоянный HTTP MCP daemon: [agent-control.json](agent-control.json),
[HTML report](../examples/agent-demo/generated/report.html),
[report ZIP](../examples/agent-demo/generated/report.zip).
Chrome 1440×1050: изображение загружено, горизонтального переполнения и page errors нет.
Это синтетический CPU контроль и SDK-подключение, не испытание внешней LLM.

Большой Cartesian профиль: 15 новых integration cases, в том числе GRDECL RLE/D-exponent,
I-fast/K-down mapping, PERMZ/PERMX, >4M cells, independent checks и damaged/missing chunks.
Уменьшенный фактический benchmark: 8 388 608 cells / 377 488 256 bytes input,
max process-tree RSS 457 670 656 bytes (~436.5 MiB); analytical + numerical + property validation PASS.
[Raw small benchmark](benchmark-large-small.json). Полный контроль выполнен отдельно: 402.7M cells /
18.119GB raw input / sampled max process-tree RSS353.5MiB, все numerical/property checks PASS;
[raw large benchmark](benchmark-large.json), [scope](LARGE_MODEL_RESULT.md).
Сквозной GRDECL HTTP MCP demo: [отчёт](../examples/cartesian-grdecl/generated/report.html).

Внешние входные данные: SPE10 model2 OPM/opm-data, pinned commit/SHA-256, 1.122M actual cells,
all source PORO/PERMX/PERMZ preserved and independently compared; three static OWC controls PASS.
[Evidence](../examples/reference/spe10model2/results/acceptance.json).
Это stand-alone upstream-data acceptance сверх полного регрессионного набора, а не запуск Flow/field forecast.

XTGeo 4.27.0 + PyVista0.49.1/trame3.13.2/trame-pyvista0.2.1 проверены на GRDECL/EGRID/ROFF,
полевой Norne и настоящем HTML/PNG unified scene. Новый SEG-Y source importer:269422096 bytes,
67108864 IEEE float32 samples bitwise exact, sampled RSS402.5MiB.
[Scope/evidence](PETREL_WORKFLOW.md), [seismic raw](benchmark-seismic.json).

Защита больших срезов/LGR, сцена и MCP-first просмотрщик включены в последний полный прогон.
Предыдущие 13 целевых проверок также сохранены:
[test-results-scene-seismic.xml](test-results-scene-seismic.xml).

MCP-first: Gradio/Plotly находятся в extra ui; собственные LLM/ASR SDK удалены.
Runpod проверяется отдельно в experimental/runpod и не входит в продукт.
Новая контрольная проверка: [MCP_FIRST_RESULT.md](MCP_FIRST_RESULT.md).

Copilot A–D/O additions: [COPILOT_RESULT.md](COPILOT_RESULT.md).
Full DATA Norne import and bounded 20M-cell ASCII corner-point path have separate
acceptance evidence. XLSX/PDF: OpenPyXL3.1.5, ReportLab4.5.1, pypdf6.21.0;
serialization/independent reader and rendered fixture checks passed. Source-only
MCPB launched through SDK stdio plus shared viewer/controller and isolated import:
[raw check](mcpb-check.json). Actual Claude Desktop installation and Windows/WSL2 remain NOT RUN.
The updated wheel passed the existing UI-free core environment check;
a new full offline dependency solve could not run because the registry cache is incomplete:
[copilot-core-check.json](copilot-core-check.json).
