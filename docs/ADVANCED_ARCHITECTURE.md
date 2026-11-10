# Kanysh Advanced — целевая архитектура (предложение)

Статус: **проект, не реализовано**. Документ описывает, как развивать Kanysh Basic в
Kanysh Advanced по backlog из [ROADMAP](ROADMAP.md) и [VISION](VISION.md). Ни одна
возможность ниже не заявляется как готовая. Отступления от VISION (исполнение без
Dask-сети, чанковое хранилище) оформлять отдельными ADR перед реализацией.

## 1. Что такое Advanced относительно Basic

| | Kanysh Basic | Kanysh Advanced |
|---|---|---|
| Роль | Локальный MCP-copilot рядом с Petrel/RMS | Инженерная платформа: модель → динамика → ансамбли |
| Топология | Один процесс, один владелец, loopback | Control plane + удалённые workers, команда |
| Данные | SQLite + локальные blobs | PostgreSQL + объектное хранилище (S3/MinIO), чанки |
| Расчёты | Статика, QC, объёмы, неопределённость скаляров | + структура, свойства, OPM Flow, HM/ES-MDA, оптимизация |
| Доступ | Локальный токен | OIDC, роли по проектам, аудит |

Принцип: **Advanced — это не форк, а то же ядро плюс пакеты операций и серверные
backends.** Basic остаётся профилем `workstation` той же кодовой базы. Все принципы
Basic сохраняются: immutable ревизии, явные научные входы, независимые численные
проверки, честные `FAIL` / `NOT RUN`, LLM не вычисляет числа.

## 2. Обзор

```text
 MCP-клиенты (Claude/ChatGPT)   Web-viewer (vtk.js)    CLI / REST
            │ OAuth                │ OIDC session          │ token
            └──────────────┬───────┴───────────────────────┘
                           ▼
 ┌──────────────────── CONTROL PLANE ─────────────────────────┐
 │ Gateway: REST /api/v1 · MCP Streamable HTTP · AuthN/AuthZ  │
 │ Operation Registry ── единственный источник контрактов     │
 │ Catalog (ревизии, lineage, staleness)   Approvals/Policies │
 │ Job Ledger + Scheduler (leases)         Workflow/Ensemble  │
 │ Audit log                               Tile/LOD API       │
 └───────┬──────────────────────────┬─────────────────────────┘
         │ PostgreSQL               │ lease / heartbeat / cancel (исходящий HTTPS от worker)
         ▼                          ▼
 ┌── DATA PLANE ──────┐   ┌── WORKER POOLS (отдельные образы) ──────────────┐
 │ Artifact store     │◄──┤ cpu-geo   : XTGeo, GSTools, импорт, QC, объёмы  │
 │ S3/MinIO/локально  │   │ gpu-geo   : GemPy/PyTorch CUDA, tetra-объёмы    │
 │ content-addressed  │   │ solver-opm: OPM Flow (CPU/GPU build) + resdata  │
 │ чанки Zarr/Parquet │   │ render    : LOD-пирамиды, срезы, сцены          │
 └────────────────────┘   └─────────────────────────────────────────────────┘
```

Модульный монолит control plane + отдельные worker-процессы. Kubernetes, Redis,
Celery, Ray не требуются: очередь — это таблица ledger в PostgreSQL.

## 3. Фундамент: что переделать в ядре до новых функций

Это этап 0. Без него каждая новая операция Advanced увеличивает уже существующий долг.

### 3.1. Реестр операций вместо if-цепочек

Сейчас одна операция описана в семи местах: `schemas.py`, `contracts.py`
(`CONTRACTS`/`READ_ONLY`/`DESCRIPTIONS`), `service.invoke`, `HEAVY`, `DEVICE_MATRIX`,
whitelist больших сеток, `execution/tasks.run`, `workflows/engine.OUTPUT_KINDS`.
Целевая форма — одна декларация рядом с реализацией:

```python
@operation(
    name="regional_volumes",
    input=RegionalVolumes,              # Pydantic, как сейчас
    output_kind="analysis_report",
    ports={"properties": "properties", "polygon": "dataset"},
    devices=("cpu", "cuda"),
    backends=("in_memory", "cartesian-zarr", "cornerpoint-zarr"),
    pool="cpu-geo",
    read_only=False,
    profiles=("agent", "full"),
    preflight=regional_preflight,       # синхронный отказ до постановки job
)
def regional_volumes(ctx: WorkerContext, p: RegionalVolumes) -> OperationResult: ...
```

Из реестра генерируются: MCP tools и их схемы, REST-маршруты, матрица устройств,
проверка портов workflow, список операций, допустимых для больших сеток, документация
покрытия. `Service` сокращается до тонкого фасада: validate → preflight → resolve →
submit. Пакеты Advanced регистрируют операции через entry points
(`kanysh.operations`), не трогая ядро.

### 3.2. Структура пакетов (uv workspace)

```text
packages/
  kanysh-core/        контракты, реестр, catalog, ledger, worker ABI, ошибки
  kanysh-basic/       статические операции, локальный профиль, MCPB
  kanysh-structural/  многоразломные модели, сетки
  kanysh-petro/       upscaling каротажа, фации, SGS, корреляция
  kanysh-dynamic/     SimulationCase, deck, OPM runner, результаты
  kanysh-ensemble/    ансамбли, ES-MDA, оптимизация
  kanysh-server/      PostgreSQL/S3 backends, OIDC, scheduler, worker-agent
  kanysh-viewer/      web-клиент, tile/LOD API
```

Тяжёлые зависимости (torch, gempy, xtgeo, OPM) принадлежат пакетам операций и
образам workers, а не ядру. Control plane устанавливается без torch.

### 3.3. Worker ABI — сохранить и стабилизировать

Нынешний контракт каталога попытки — сильная сторона Basic, он становится публичным
ABI между control plane и любым worker:

```text
attempt/
  request.json     операция, payload, resolved refs (hash, не пути control plane)
  inputs/          staged read-only по content hash
  output/          только сюда пишет worker
  progress.jsonl   стадии и измеренный прогресс
  worker.log
  cancel           файл-сигнал
  result.json      атомарно через os.replace
```

Worker не имеет доступа к БД, учётным данным провайдеров и чужим проектам.

## 4. Данные

### 4.1. Catalog (PostgreSQL; SQLite остаётся для профиля workstation)

| Таблица | Назначение |
|---|---|
| `projects`, `members` | проект, CRS/datum, роли участников |
| `artifacts` | `(id, revision)`, kind, schema_version, content_hash, manifest (JSONB) |
| `artifact_edges` | lineage: `src → dst`, роль входа; основа staleness и аудита |
| `blobs` | hash, размер, backend, `verified_at` |
| `jobs`, `attempts` | статус/стадия/target **колонками**, не JSON-blob; индексы по статусу |
| `leases` | какой worker держит попытку, срок, heartbeat |
| `targets` | зарегистрированные workers: pool, capabilities, RAM/VRAM, образ/digest |
| `approvals` | подтверждение научных параметров человеком (см. 7.3) |
| `policies` | политика передачи данных, лимиты, бюджет |
| `workflows`, `runs`, `run_nodes` | определения и исполнения DAG |
| `audit_log` | кто/что/когда, включая вызовы MCP |

Staleness не хранится флагом, а вычисляется по `artifact_edges`: артефакт устарел,
если у любого его входа есть более новая ревизия. Старые ревизии остаются доступными.

### 4.2. Artifact store

- Интерфейс `BlobBackend` (локальный диск / S3 / MinIO через fsspec).
- **Чанки вместо одного blob.** Крупные сетки и кубы — Zarr v3 с шардингом, каждый
  шард адресуется хешем; манифест артефакта — Merkle-список шардов. Сейчас 18 ГБ
  модель — это один `grid.zip`, который целиком перехешируется при каждом чтении.
- Проверка целостности: полная — при публикации и по расписанию (scrub); при чтении —
  только шарды, которые реально читаются, плюс кэш `(hash, size, mtime) → verified_at`.
- Доступ workers — короткоживущие подписанные URL на конкретные хеши попытки.
- Сборка мусора: blob удаляется, только если на него нет ссылок ни в одном манифесте
  и истёк grace-период.

### 4.3. Новые виды артефактов

`structural_model` (несколько разломов/несогласий), `sim_grid`, `grid_mapping`,
`facies_model`, `upscaled_logs`, `variogram_model`, `fluid_model`, `rock_model`,
`completion_set`, `schedule`, `simulation_case`, `simulation_result`,
`observation_set`, `parameter_space`, `ensemble`, `ensemble_iteration`,
`optimization_study`, `lod_pyramid`, `velocity_model`, `interpretation`.
Каждый вид — JSON Schema с версией и мигратором чтения старых версий.

## 5. Исполнение

### 5.1. Ledger и аренда попыток (pull-модель)

```text
queued → leased → staging → running → publishing → succeeded
                     │          │           │
                     └──────────┴───────────┴──► failed / cancelled / interrupted
```

- Worker-agent сам опрашивает control plane **исходящим** HTTPS (mTLS или токен
  target): `POST /leases` → получает попытку, подписанные URL входов и выходов.
  На GPU-узле нет входящих портов; работает за NAT и в чужой сети.
- Выдача попытки — `SELECT … FOR UPDATE SKIP LOCKED` по совместимости
  pool/capabilities/политики проекта. Heartbeat каждые N секунд; пропуск срока →
  `interrupted`, новая попытка — только если операция помечена идемпотентной.
- Отмена приходит в ответе на heartbeat; agent завершает дерево процессов (логика
  `terminate_tree` из Basic) и подтверждает освобождение GPU.
- Публикация остаётся на control plane: проверка хешей выходов → манифест → запись
  ревизии в одной транзакции. Worker никогда не пишет в catalog.

Почему не Dask-сеть: в Basic Dask используется как пул из двух потоков, запускающих
subprocess; удалённый Dask-scheduler — доверенная сеть с pickle, без модели прав и
без надёжной отмены нативного solver. Dask остаётся допустимым **внутри** worker для
блочного параллелизма.

### 5.2. Preflight ресурсов

Единая функция оценки по реестру: `cells × bytes_per_cell(operation, backend)` +
измеренная калибровка прошлых запусков → требуемые RAM/VRAM/диск. Scheduler сверяет
оценку с `targets`. Правило Basic сохраняется: сетка, точность и физика никогда не
уменьшаются автоматически; при нехватке — `INSUFFICIENT_MEMORY` с цифрами.

### 5.3. Политика размещения

Порядок: политика данных проекта → совместимый pool/образ → устройство/точность →
здоровье и ресурсы → локальность данных → очередь. Передача данных на удалённый
target запрещена, пока владелец проекта не задал политику; флаг в запросе LLM
(`allow_remote`) права не повышает.

## 6. Предметные модули

### 6.1. Structural (kanysh-structural)

- GemPy: несколько серий, несколько разломов с явной матрицей отношений, несогласия.
- Большие модели: вычисление по октантам/блокам с сохранением scalar fields в Zarr.
- Сетка для динамики: сначала только проверяемые классы — Cartesian и stair-step с
  явными непроводящими границами по разлому. Corner-point по наклонным разломам —
  отдельный исследовательский этап; до него `UNSUPPORTED_GRID_BRIDGE`.
- Контроль: аналитические fixtures смещения на каждый тип отношения разломов.

### 6.2. Petro (kanysh-petro)

- Upscaling каротажа в ячейки (арифметическое/гармоническое/по фациям) с отчётом о
  покрытии; результат — `upscaled_logs`, исходный LAS неизменен.
- Фации: индикаторное моделирование / усечённые гауссовы поля; свойства — SGS и
  ко-кригинг по фациям (GSTools), тренды явными входами.
- Корреляция скважин: хранение пользовательских отметок; автоподсказки — только как
  proposals, как сейчас сделано для контактов.
- Приёмка ансамбля: воспроизведение гистограммы и вариограммы с заранее заданными
  допусками (незакрытый пункт FR-12).

### 6.3. Dynamic (kanysh-dynamic)

```text
sim_grid + свойства + fluid_model + rock_model + completion_set + schedule + init
        │ валидация схем и QC таблиц
        ▼
 simulation_case (immutable) ──► deck generator ──► bundle (DATA + INCLUDE + manifest)
        │                                               │
        │                              pool solver-opm: flow в контейнере,
        │                              argv без shell, immutable input mount
        ▼                                               ▼
 сверка in-place: статика ↔ OPM INIT      simulation_result: summary (Parquet),
                                          restart (Zarr по report steps), per-well
```

- Генератор deck — шаблоны по `physics_profile` (двухфазный dead-oil → трёхфазный
  black-oil); каждый профиль имеет reference case и баланс масс в приёмке.
- Образ solver закрепляется по digest; факт GPU-исполнения подтверждается журналом
  solver, а не наличием устройства.
- Результаты читаются только resdata/opm.io; `grid_mapping` восстанавливает форму
  с неактивными ячейками.

### 6.4. Ensemble и history matching (kanysh-ensemble)

```text
parameter_space ─► prior sample (seed) ─► N × forward (fan-out в ledger)
                                               │
 observation_set ─────────────────────────────►│ отклики на датах наблюдений
                                               ▼
                         ES-MDA update (iterative_ensemble_smoother)
                                               │
                       ensemble_iteration[k] ──┴─► следующий проход или отчёт
```

- Не писать сглаживатель самим: использовать `iterative_ensemble_smoother` (Equinor);
  собственный слой — параметры, наблюдения, ошибки измерений, локализация, учёт.
- Каждая итерация — immutable `ensemble_iteration` с матрицами параметров/откликов.
- Упавшие реализации не пересэмплируются и не исчезают: фиксируются
  `completed/total`, причина, правило исключения (как в Basic для Monte Carlo).
- Отчёт HM обязан показывать: невязку до/после, схлопывание ансамбля (spread),
  и предупреждение, что совпадение с историей не доказывает прогнозную силу.
- Оптимизация: сначала явный дискретный перебор (≤ N вариантов), затем
  суррогат/байесовская; NPV — только при явных ценах, затратах и ставке.

### 6.5. Viewer (kanysh-viewer)

- Операция `lod_build` создаёт `lod_pyramid`: уровни детализации сетки (внешняя
  оболочка + разрезы) и пирамиды сейсмических срезов как артефакты.
- Tile API отдаёт нужный уровень по frustum/бюджету; клиент — vtk.js вместо
  экспортируемого HTML на 7+ МБ.
- Picking: клик → `(artifact, revision, ijk | inline/xline/sample, domain)` →
  новая ревизия `interpretation`. Viewer по-прежнему не запускает научные расчёты
  напрямую, а создаёт те же операции реестра.

## 7. Безопасность и доступ

### 7.1. Аутентификация

- Люди: внешний OIDC-провайдер (Keycloak/Entra/Google) — собственный OAuth-сервер
  не писать.
- MCP: control plane — OAuth resource server (protected resource metadata, audience,
  scopes `project:read`, `job:submit`, `artifact:read`); проверить handshake в
  реальных клиентах до объявления поддержки.
- Workers: учётные данные target с отзывом; на попытку выдаётся токен, ограниченный
  её входами и выходами.

### 7.2. Авторизация

Роли на проект: `owner`, `engineer`, `viewer`. Проверка — в одном месте (gateway →
реестр), включая cache hit, выдачу подписанных URL и tile API.

### 7.3. Подтверждение человеком как серверный факт

В Basic `parameters_confirmed` — поле схемы, и документация честно говорит, что это
не доказательство. В Advanced: proposals из файлов создают запись `approvals`
(`pending`); подтвердить её может только аутентифицированный человек через viewer
или MCP elicitation; `calculation_plan` принимает `approval_id`, и сервер сам
проверяет, что утверждённые значения совпадают с планом. Агент не может подтвердить
за пользователя.

### 7.4. Прочее

Аудит всех вызовов; секреты только в env/secret store; tracebacks не уходят клиенту;
deck-импорт без `PYACTION` и внешних путей (как сейчас).

## 8. Топологии развёртывания

| Профиль | Состав | БД / хранилище |
|---|---|---|
| `workstation` | один процесс + локальные worker-процессы (это Basic) | SQLite + диск |
| `hybrid` | локальный control plane + удалённый GPU-agent по исходящему HTTPS | SQLite + диск, staging по хешам |
| `team-server` | compose: gateway, PostgreSQL, MinIO, worker-пулы, reverse proxy с TLS | PostgreSQL + S3 |

Один код, разные backends за интерфейсами `Catalog`, `BlobBackend`, `Scheduler`.

## 9. Порядок работ

| Этап | Содержание | Критерий выхода |
|---|---|---|
| 0. Фундамент | реестр операций, разбор `service.py`/`tasks.py`, workspace, чанковый store + кэш проверки, lineage, jobs колонками, типизация | все тесты Basic зелёные, поведение MCP не изменилось |
| 1. Remote | worker-agent, leases, staging, отмена, VRAM preflight; OIDC для server-профиля | один и тот же расчёт: локально = удалённо, отмена ≤ 30 с |
| 2. Dynamic | SimulationCase, deck, OPM CPU, результаты, сверка in-place | no-flow, waterflood 20×20×5, upstream black-oil reference |
| 3. Ensembles/HM | fan-out, ES-MDA, отчёт HM | синтетический twin-эксперимент восстанавливает параметры в допуске |
| 4. Structural/Petro | многоразломные модели, upscaling, фации | fixtures по каждому типу отношений; статистика ансамбля |
| 5. Viewer/LOD | пирамиды, tile API, picking | сцена 100M+ ячеек в бюджете памяти клиента |

Этапы 2–5 независимы после этапа 1 и могут идти параллельно. Этап 0 обязателен первым.

## 10. Открытые решения (нужны ADR)

1. Pull-agent вместо Dask Distributed для удалённого исполнения (отступление от VISION §5).
2. Zarr v3 + шардинг (сейчас закреплён `zarr<3`) и миграция существующих `grid.zip`.
3. Лицензирование и граница open-core: какие пакеты Advanced остаются Apache-2.0.
4. Класс сеток для моста «faulted geology → simulation grid».
5. Web-клиент: vtk.js против trame с серверным рендерингом для очень больших сцен.
