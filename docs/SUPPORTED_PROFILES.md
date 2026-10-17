# Профили и ограничения

| Профиль | Состояние |
|---|---|
| local-cpu macOS arm64 / Python 3.12 | Проверен, включая UI, API, scientific kernel и MCP SDK |
| local-cpu Linux x86_64 | Код подготовлен; чистая Linux установка NOT RUN |
| local-cuda Linux/WSL2 NVIDIA | Tensor paths реализованы, tests есть; NOT RUN |
| Windows + NVIDIA workstation | Первый целевой пользовательский профиль через WSL2; launcher подготовлен, на Windows/WSL ещё NOT RUN; native Windows backend отсутствует |
| remote-cuda | Advanced backlog; transport/worker registration is not part of Basic |
| server | Локальный Host/Origin/token/session guard и общий HTTP MCP проверены; нужны OIDC/HTTPS и реальные внешние клиенты |

Установка CPU: `uv sync --frozen --group dev`; запуск MCP/API: `uv run kanysh-basic serve`.
Просмотрщик: `uv run --extra ui --extra viewer kanysh-basic serve --ui`.
Не используйте системный Python 3.14 для этого lock: выбран Python 3.12 из-за научных wheels.
На macOS нет CUDA; MPS не считается выполнением GPU требований.
Постоянный локальный MCP/API без UI и подключение папок: [LOCAL_WORKSTATION](LOCAL_WORKSTATION.md).
`doctor` показывает реальную доступную RAM и GPU/VRAM, не объявляя backend прошедшим acceptance.

Импорт: шаблоны в examples/templates. LAS 1.2/2.0 (проверен 2.0); MD в явных units;
CSV в UTF-8; SEG-Y regular zero-offset poststack 3D, fixed sampling, IBM/IEEE float32.
IEEE float32/endian/scalars проверены; IBM profile требует дополнительного реального fixture.
Поля headers по умолчанию inline189/crossline193; при неоднозначности выберите mapping.
Обычный seismic_import ограничен 50 млн samples, загрузка — 256 MB, ZIP uncompressed — 512 MB.
Отдельный seismic_source_import обходит upload limit и пишет float32 Zarr плитками;
фактически проверены 269,4 МБ и 67,1 млн samples, оба порядка трасс. [Профиль](PETREL_WORKFLOW.md).
Этот лимит — implementation profile, не гарантия любого SEG-Y размера.

Структура: conformable custom regular grid GemPy; horizontal/dipping/single planar fault CPU fixtures проверены. Явная
horizontal модель доступна отдельно и не называется GemPy. Несколько горизонтов требуют явного stratigraphic_order от молодого к старому.
Planar fault задаётся через fault_create: 3+ coplanar points, единичная нормаль; смещение
определяют surface points по обеим сторонам. Связь Fault→Stratigraphy сохранена явно.
Faulted structural models запрещены для автоматического OPM bridge; voxelization не подменяет fault grid.
Пример: examples/workflows/single_fault.json. Произвольные fault networks не поддерживаются.

Геостатистика: Exponential 3D, ordinary kriging, exact/no nugget, log/logit, seeded conditional SRF.
Rotated anisotropy, nested variograms, ensemble statistical acceptance не заявлены.

OPM: deck generator Cartesian oil-water/dead-oil, no upscaling; NTG отдельно. `simulation_submit`
вызывает настоящий `flow`. Установите `uv sync --frozen --extra solver` для resdata.
Без Flow возвращается SOLVER_UNAVAILABLE; без reader — RESULT_READER_UNAVAILABLE.
Reader и явные STCOND/initial-state проверяются до запуска solver. Выбранный executable разрешается
в абсолютный путь; SHA-256 сохраняется в result и учитывается при resume. Это identity evidence,
не подтверждение корректности или закреплённой upstream сборки.
Generated case: `flow examples/generated/CASE.DATA --output-dir=/tmp/opm-demo` на отдельном Linux
стенде с выбранным build. Не считайте этот deck проверенным до запуска и conservation checks.
Resdata 6.3.5 установлен; native summary SDK roundtrip и искусственный binary EGRID/INIT/UNRST
fixture проверены, включая два report steps, ACTNUM mismatch и inactive restoration. INIT/restart
adapter и component balance ограничены generated Cartesian METRIC oil-water профилем;
реальные Flow outputs ещё не проверены. Анализ и UI проверены на явно помеченных аналитических
fixtures в отдельной БД.

MCP-клиент использует собственный AI-интерфейс. Ключи генеративных моделей и ASR серверу не нужны.
Просмотрщик устанавливается через `--extra ui`, запускается `serve --ui`; научных форм в нём нет.

Большие готовые Cartesian grids имеют отдельный блоковый профиль (NPY либо раздельные GRDECL
property tables + явная Cartesian geometry): [LARGE_MODELS](LARGE_MODELS.md).
Он не повышает лимиты GemPy и обычного ZIP/CSV import; не принимает native Petrel. Corner-point имеет отдельный XTGeo/Zarr backend с RAM preflight и лимитом 2 млн ячеек.
До2 млрд cells — контрактный предел. Фактически проверены 402.7M cells и18.119GB raw-модель
(семь NPY файлов), sampled peak process-tree RSS353.5MiB: [evidence](LARGE_MODEL_RESULT.md).
Большие corner-point/native Petrel, Windows/CUDA и один файл/ZIP>15GiB остаются отдельными критериями.

Corner-point Norne: все113344 cells/44927 active, оригинальные PORO/NTG/PERMX/FIPNUM,
independent tetrahedral contact checks и 3D export PASS. [Доказательства](PETREL_WORKFLOW.md).
Установка viewer: `uv sync --frozen --extra viewer --extra solver --group dev`.
