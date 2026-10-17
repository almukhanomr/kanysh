# Расчёт через MCP без собственного интерфейса

Реализованный профиль `static_volumetrics_v1`: CSV surface points/orientations → GemPy CPU
или явная горизонтальная модель → постоянные свойства по зонам → объёмы при нескольких OWC →
seeded scalar uncertainty → независимая численная проверка → отчёт.
Для готовых больших сеток доступен [блочный профиль](LARGE_MODELS.md).
MCP-клиент предоставляет агента; внутри Kanysh Basic отдельная LLM не нужна.

## Запуск

Python 3.12; команды этого справочника — для macOS/Linux из корня проекта. Для Windows используйте нативный MCPB: [инструкция](INSTALL_WINDOWS.ru.md). WSL нужен только для OPM Flow. Старый дополнительный профиль WSL2
или использовать [PowerShell launcher](../scripts/start-workstation.ps1).

```bash
uv sync --frozen --group dev
./.venv/bin/kanysh-basic --home .data source-add agent-demo examples/agent-demo
./.venv/bin/kanysh-basic --home .data serve --no-ui --mcp-profile agent --port 8765
```

Запишите `id` из вывода source-add (также доступен через `sources`). Сервис держать работающим.
Endpoint: `http://127.0.0.1:8765/mcp/`. При установленном OPENSUBSURFACE_TOKEN передавать
`Authorization: Bearer <token>`; ключ не помещать в разговор, план или project ZIP.
Для UI вместе с MCP убрать `--no-ui`. Профиль `full` сохраняет низкоуровневые инструменты.

Для отдельного stdio-клиента: `kanysh-basic --home /separate/state mcp --profile agent`.
Нельзя запускать два executor над одним каталогом состояния. Для общего состояния используйте
HTTP работающего сервиса. Реальные ChatGPT/Claude подключения ещё NOT RUN; SDK-проверка
не доказывает доступность localhost из облачного клиента. Детали транспорта: [MCP_SETUP](MCP_SETUP.md).

## Контракт агента

Все tool arguments обёрнуты в `{"request":{...}}`. Ответ содержит result или error.
Инструкции сервера, resource `opensubsurface://guide` и prompt `static_calculation`
объясняют обязательные допущения, восстановление и границы проверки.

| Шаг | Tools | Что сохраняется / возвращается |
|---|---|---|
| Проект и источник | project_create, project_list, source_list, source_scan, source_inspect | CRS/datum, source_id, относительный путь, file_revision, CSV columns; preview по умолчанию отсутствует |
| План | calculation_plan, plan_validate | NEEDS_INPUT с вопросами либо immutable plan со snapshot исходных байтов, SHA-256, спецификацией и runtime fingerprint |
| Исполнение | calculation_run, calculation_status | run_id, статус, checkpoint, refs и ошибки; повтор того же плана по умолчанию идемпотентен |
| Наблюдение | job_status, job_logs, job_cancel, compute_targets_list | постоянный ledger и ограниченные диагностические данные; отмена затрагивает child jobs |
| Проверка и выдача | result_validate, report_export, result_preview, artifact_inspect | validation artifact, HTML/Markdown/JSON/CSV/PNG, нативный MCP ImageContent и binary resources |

Agent profile содержит 23 tools. Регистрация/отзыв папок остаётся owner CLI действием.
Содержимое файлов, заголовки, имена и заметки считаются данными, а не инструкциями агенту.

`calculation_plan` не запускает численные jobs. Он требует явных grid/method, разрешения
горизонтального допущения, свойств всех зон, выбранных zone_ids, Bo, вариантов OWC и assumptions.
Единицы входных координат также задаются явно. Неопределённые параметры возвращаются вопросами.
CSV discovery показывает возможные роли; orientations содержит также surface columns,
поэтому окончательную роль выбирают по смыслу, а не по первому candidate_kind.

GemPy использует surfaces и orientations (либо разрешённое horizontal_assumption).
horizontal_explicit использует horizons_z; surfaces/orientations в этом режиме отклоняются,
collars служат QC evidence и не ограничивают геометрию. Пустой horizons_z означает одну зону.
Система Z вверх: OWC — отметка Z, не положительная глубина вниз. CRS/datum проекта объявляет пользователь.

План содержит собственные input blobs: исходную папку можно отозвать, а план экспортировать
в project ZIP и импортировать на другой установке с совместимым runtime. Смена кода/библиотек
вызывает STALE_PLAN; нужен новый план. По умолчанию CPU; GPU policy проверяет сервер,
наличие NVIDIA само по себе не подтверждает поддержку операции.

## Контрольная демонстрация

Во втором терминале, пока сервер работает:

```bash
./.venv/bin/python scripts/agent_demo.py --source-id SOURCE_ID
```

Это настоящий MCP SDK клиент по HTTP, выполняющий явную спецификацию через tools.
Он создаёт проект, исследует CSV из examples/agent-demo, строит GemPy модель с горизонтом -1020 м,
считает OWC -1040/-1030/-1020 м и проверяет STOIIP **2 000 000 / 1 000 000 / 0 standard m³**.
Неопределённость: phi uniform[.15,.25], seed=42, 30 samples для первого контакта.
Контрольные данные синтетические, Apache-2.0; это не запасы извлечения и не прогноз добычи.

Результаты сохраняются в examples/agent-demo/generated: report.html (самодостаточный), report.md,
report.json, volumes.csv, volumes.png, run.json и report.zip. --output задаёт другую папку.
run.json позволяет запросить состояние тем же или другим MCP-клиентом. Скрипт не тестирует
рассуждения ChatGPT/Claude и не вызывает внешнюю LLM.

Пример задания агенту после подключения:

> Найди synthetic source agent-demo. Создай проект LOCAL_METRIC/SYNTHETIC_MSL. Сначала
> покажи, каких параметров не хватает для static_volumetrics_v1; не придумывай их.
> Для контрольного расчёта возьми явную спецификацию из scripts/agent_demo.py как данные.
> Сохрани план, проверь его, запусти, дождись завершения и верни численные объёмы,
> статус независимых проверок, run_id, отчёт и допущения.

## Что проверяет валидатор

Отдельный worker проверяет manifest/blob hashes и поддержанные численные инварианты.
Объёмы повторно интегрируются по пересечениям интервалов слоёв, без вызова рабочего
volume kernel. Проверяются все шесть метрик, единицы, сериализованные результаты;
для uncertainty — число samples, seed, sampled parameters, все метрики каждой реализации,
Q/P, mean/std. Quantiles вычисляются независимой формулой linear interpolation.
Tolerance: rtol=1e-8, atol=1e-7; признаки PASS/FAIL/NOT RUN и evidence сохраняются в validation.json.
Q10=P90, Q50=P50, Q90=P10 (P — exceedance). Явные варианты OWC не получают вероятностей.

Для datasets проверяются строки/finite/units/coordinates/normals; для model — shape/extent/zones
и аналитическая классификация horizontal_explicit; для properties — bounds, объявленные
константы и соответствие родительской сетке. GemPy boundary fit/convergence на произвольных
полевых данных автоматически не принимается. Geological fitness всегда REQUIRES_REVIEW.
Seeded scalar uncertainty не является набором пространственных геостатистических реализаций.

Общий PASS возможен, только когда для каждого ожидаемого артефакта есть проверка именно его
id/revision/hash и все обязательные checks прошли. Неподдержанный validator возвращает INCOMPLETE,
повреждённые байты или неверные объёмы — FAIL. FAIL/INCOMPLETE финального отчёта завершает
calculation run ошибкой VALIDATION_FAILED, сохраняя отчёт и evidence.

## Длительные и неуспешные расчёты

Отключение MCP-сессии не отменяет jobs. calculation_status использует run_id, возвращённый
calculation_run; автоматическое пробуждение чата не обещается. Остановка сервиса прерывает
процессы, startup reconciliation фиксирует это в ledger.

Для failed/interrupted run запросите статус и ошибки; report_export(project_id,run_id)
создаёт доступный частичный отчёт. Это асинхронный job: дождитесь job_status=succeeded,
затем используйте его result ref в result_preview/artifact_inspect.
Отчёт содержит missing nodes, ошибки и parent_status_at_export. Автоматический отчёт создаётся
до завершения родительского workflow; terminal status проверяйте через calculation_status.

Для совместимого восстановления передайте **checkpoint ref**, а не job_id:
`calculation_run(request:{project_id,plan:{id,revision},resume_run:{id,revision}})`.
Успешные узлы с совпадающими hashes/runtime переиспользуются, отчёт получает новый run_id.
Изменение научных входов требует нового плана; resume не исправляет неверную геологию.

## Границы и проверка на вашей станции

Проверено на macOS CPU: GemPy→три OWC→uncertainty→independent checks→report через MCP SDK,
disconnect/reconnect, идемпотентность, source revocation + bundle restore, partial report,
resume, повреждённые blobs и неверные числа при валидных hashes.

```bash
./.venv/bin/pytest tests/integration/test_calculations.py tests/integration/test_agent_mcp.py tests/scientific/test_calculation_validation.py -q
./.venv/bin/kanysh-basic doctor
./.venv/bin/pytest tests/gpu -q
```

Windows/WSL2 и NVIDIA выполняет владелец на своей станции. GPU skip означает NOT RUN.
CSV snapshot по-прежнему ≤256 MiB, все CSV plan inputs ≤512 MiB, GemPy grid ≤4 млн ячеек.
Для готовых больших декартовых моделей добавлен отдельный grid_import → properties ref → plan
с блочным хранением и вычислениями (до 2 млрд ячеек по контракту). [LARGE_MODELS](LARGE_MODELS.md).
Поддержаны NPY и раздельные GRDECL таблицы свойств с явно объявленной Cartesian геометрией.
Corner-point COORD/ZCORN, native Petrel projects, S3 и remote compute ещё не реализованы.
Фактический CPU Cartesian контроль>15GiB выполнен: 402.7M cells /18.119GB raw input, sampled peak RSS353.5MiB.
Это семь NPY файлов, не один файл>15GiB; [точный scope](LARGE_MODEL_RESULT.md).
Нативный OPM forecast, CUDA equivalence и реальные ChatGPT/Claude connectors требуют
своей приёмки; весь релиз v0.2 остаётся открытым.

Corner-point, большие SEG-Y и сохранённая общая 3D-сцена доступны в том же MCP профиле: [PETREL_WORKFLOW](PETREL_WORKFLOW.md).

Просмотрщик: `uv run --extra ui --extra viewer kanysh-basic serve --ui`.
MCP-ответы о report/scene включают viewer_url только при активном просмотрщике того же каталога состояния.
Встроенных чата/голоса и cloud tools в сервере нет.
