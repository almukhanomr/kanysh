> Kanysh Advanced: historical long-term vision and future development context. Implemented A–D/O1–O6 features are accepted as Kanysh Basic. Unimplemented items belong to the Advanced backlog, not the Basic feature promise. See ROADMAP.md, COPILOT_RESULT.md and DEMO.md.

# Kanysh Advanced — long-term vision (historical scope)

Уточнение продукта от 2026-10-17 имеет приоритет: собственные чат/голос удалены, UI — optional просмотрщик, Runpod — experimental. A-10 заменено MCP-клиентами и исключено из обязательной приёмки. См. ADR-003.

Дата: 15 октября 2026 года. Статус: задание на разработку и последующую проверку. Линейка продукта: Kanysh Basic (принятый функционал) и Kanysh Advanced (дальнейшее развитие). Public interface and primary documentation are English; README.ru.md provides a Russian introduction.

**Этот документ полностью заменяет ТЗ v0.1 для нового объёма работ. Он самодостаточен: передавать development contributors предыдущий файл не требуется.** Версия v0.2 относится к ТЗ и целевому релизу, а не означает наличие реализованного продукта. В рамках подготовки документа библиотеки, расчёты и GPU-стенды не запускались.

## 1. Цель продукта

Создать открытую инженерную платформу с управлением через внешние MCP-клиенты и локальным веб-просмотрщиком. Долгосрочный ориентир — функциональное покрытие рабочих процессов SLB Petrel. Цель v0.2 — работающий сквозной процесс в явно ограниченном классе задач:

**Скважины и сейсмика → интерпретация → структурная модель → свойства коллектора → статические объёмы → подготовка гидродинамической модели → расчёт разработки → анализ результатов → сравнение вариантов и неопределённости.**

Расчёты запускаются на локальном CPU/GPU, собственном сервере или облачном GPU. Команда пользователя задаёт предметную задачу и ограничения; инженерные библиотеки выполняют вычисления, а приложение управляет данными, очередью и результатами.

Пример целевого запроса:

> «Открой демонстрационный проект. Построй три реализации пористости и проницаемости, подготовь для каждой сценарий заводнения, запусти на разрешённом сервере и сравни накопленную добычу нефти, обводнённость и давление. Сохрани весь процесс для повторного запуска».

## 2. Что изменилось относительно предыдущего объёма

Обязательными стали: SEG-Y и простые сейсмические атрибуты; ручные отметки горизонтов; один простой структурный разлом; вариограммы, кригинг и условные поля; мост от геологической сетки к расчётному случаю OPM Flow; прогноз добычи; ансамбли гидродинамических расчётов; сохранённые рабочие процессы; локальный контроль jobs и результатов; облачный lifecycle вынесен в experimental.

Сохранены: CPU как полноценный путь, GPU локально и удалённо, воспроизводимость, контроль единиц, версия данных, отмена заданий, реальные API/MCP-интеграции и научные контрольные примеры.

Расширение не означает полное соответствие Petrel. Для каждого модуля ниже указаны поддерживаемые постановки и ограничения. Недоступный алгоритм должен возвращать понятную ошибку, а не имитировать результат.

## 3. Три обязательные поставки

Поставки A, B и C — последовательные части одного обязательного релиза v0.2. Завершение только A не означает завершения данного ТЗ. Каждая поставка остаётся отдельно запускаемой и имеет собственную приёмку.

| Поставка | Назначение | Обязательный результат |
|---|---|---|
| A. Основа | Данные, простая геология, статические объёмы и вычислительная среда | Контрольный проект проходит путь от импорта до объёмов через MCP/CLI/REST; UI только просматривает результаты; CPU, локальный и удалённый CUDA |
| B. Инженерный процесс | Сейсмика, геостатистика и гидродинамика | Данные → модель → поддерживаемый OPM-case → расчёт → прогноз и сравнение |
| C. Автоматизация | Ансамбли, повторяемые процессы, управляемое облако | Workflow повторяется на новых версиях входов, независимые расчёты распределяются по GPU, облачные ресурсы учитываются и завершаются |

### 3.1. Матрица обязательных функций

| ID | Функция | Поставка |
|---|---|---|
| FR-01 | Проекты, версии, артефакты, экспорт/импорт | A |
| FR-02 | Скважины, XYZ/MD-траектории, LAS, разбивки, поверхности, ориентировки | A |
| FR-03 | QC, единицы, CRS, вертикальные датумы, происхождение данных | A |
| FR-04 | Просмотр проектов/ревизий/отчётов, 3D-сцены, seismic slices и загрузка файлов | A |
| FR-05 | GemPy: согласные слои, регулярная сетка | A |
| FR-06 | Свойства по зонам, статические объёмы, скалярные реализации | A |
| FR-07 | CPU/CUDA, remote targets, jobs, staging и кэш | A |
| FR-08 | MCP tools/resources, внешний AI-клиент, локальные viewer links | A |
| FR-09 | SEG-Y, геометрия съёмки, inline/crossline/time/depth slices | B |
| FR-10 | RMS/envelope, ручная разметка горизонта, простой time-depth adapter | B |
| FR-11 | Один простой разлом и версии структурной интерпретации | B |
| FR-12 | Вариограммы, кригинг, условные реализации свойств | B |
| FR-13 | Геологическая сетка → ограниченный класс simulation grids → OPM case | B |
| FR-14 | PVT, rock/fluid, скважины, completions, schedule, initialization и QC | B |
| FR-15 | OPM Flow CPU и проверенный GPU solver profile | B |
| FR-16 | Давление/насыщенность во времени, дебиты, накопленная добыча и water cut | B |
| FR-17 | Ансамбли static/dynamic cases, неопределённость, ограниченный перебор вариантов | C |
| FR-18 | Сохранение/проверка/повтор рабочего процесса, зависимости и resume | C |
| FR-19 | Managed cloud вынесен в experimental/runpod; не обязательная поставка | Experimental |
| FR-20 | Сквозная приёмка, benchmarks, feature coverage и эксплуатационная документация | A–C |

### 3.2. За пределами обязательного релиза

Полное чтение закрытых проектов Petrel, сложные системы разломов/несогласий, профессиональный well tie и инверсия, полный цикл обработки исходной сейсмики, DFN, композиционная/термальная/EOR-физика, геомеханика, геонавигация, оптимизация траекторий и противостолкновительный анализ, промышленная автоматическая адаптация на историю, произвольное укрупнение сеток, multi-GPU одного solver, корпоративное совместное редактирование, непрерывный голосовой агент и локальная LLM.

Не заявлять геомеханику или иные функции через наличие стороннего пакета в dependencies. Поддержка означает рабочий адаптер, контрольный пример и пройденную приёмку.

## 4. Принципы реализации и готовые компоненты

1. Переиспользовать библиотеки и приложения до написания собственных алгоритмов. Собственный код — контракты, интеграция, QC, простые формулы и orchestration.
2. REST, CLI и MCP используют один application service. Внешний чат получает сохранённые результаты MCP; optional UI только просматривает их и загружает файлы.
3. LLM не вычисляет запасы, прогнозы и физические параметры текстом. Все числа получаются из сохранённых результатов инструментов.
4. Data model, jobs и workflows существуют независимо от диалога и LLM-провайдера.
5. Факт наличия GPU не означает поддержки всех операций; CPU fallback всегда виден.
6. Никаких фиктивных результатов, фальшивого прогресса и неподтверждённых заявлений об ускорении.
7. Не выбирать весь технологический стек заново перед каждым этапом. Существенные изменения фиксировать в ADR с причиной и результатом проверки.

| Подсистема | Предпочтительная готовая основа | Собственный слой |
|---|---|---|
| Окружение | Python 3.11+, uv, lockfiles; Docker для solver/server | Профили и совместимые версии |
| API/схемы | FastAPI, Pydantic | Предметные команды |
| Viewer | Gradio Blocks / optional extra ui | Просмотр готовых данных и файлов |
| 3D/разрезы | PyVista/VTK + trame | Связь сцены с IDs, picks и jobs |
| Графики | Plotly | Каротаж, атрибуты, time series, uncertainty |
| Скважины | lasio, при необходимости welly | Mapping, QC, привязка к траектории |
| Сейсмика | segyio, NumPy/SciPy, PyTorch | Индекс геометрии, чанки, атрибуты и picks |
| Структура | GemPy/gempy-engine | Входы, версии, QC, transform координат |
| Геостатистика | GSTools | Подготовка conditioning data и модели зон |
| Сетки и обмен | XTGeo по подтверждённым форматам | Проверка mappings и ограниченный exporter |
| Гидродинамика | OPM Flow отдельным процессом/контейнером | Генерация поддерживаемого case, запуск, отчёты |
| Чтение результатов | resdata; запасной вариант opm.io после проверки | Нормализация единиц/векторов/времени |
| Дополнительный просмотр | ResInsight | Экспорт совместимого пакета и инструкция открытия |
| Вычислительные массивы | NumPy/SciPy/PyTorch CPU/CUDA | Формулы и adapter kernels |
| Единицы/координаты | Pint, pyproj | Вертикальные датумы, соглашения глубины |
| Хранение | SQLAlchemy/Alembic, SQLite; Parquet, Zarr, fsspec/S3 | Метаданные, manifests и hashes |
| Исполнение | Dask Distributed | Постоянный job ledger, размещение и lifecycle |
| MCP | Официальный Python SDK | Tools/resources и авторизация |
| AI-интерфейс | Внешний MCP-клиент | Сервер не содержит LLM/ASR SDK |
| Проверки | pytest, Ruff, Playwright для критичных UI-путей | Научные эталоны и интеграционные сценарии |

Документированные возможности ключевых компонентов: GemPy [S1], GSTools [S2], segyio [S3], OPM [S4], resdata/ResInsight [S5]. Это исходные кандидаты; совместимость выбранных версий нужно проверить. Runpod вынесен в экспериментальный профиль, а не по заявлению о минимальной цене или повсеместной доступности [S6].

OpendTect не включать обязательной тяжёлой зависимостью первого релиза: рассмотреть для расширенной интерпретации после работающего SEG-Y-пути. Не встраивать несколько полноценных desktop-приложений в один UI одновременно.

### 4.1. Проверка совместимости до масштабной разработки

Собрать минимальные spike-примеры: GemPy CPU/CUDA; LAS; SEG-Y headers/slice; GSTools conditioning; OPM fixture CPU/GPU; result reader; Gradio/trame; Dask cancellation; MCP transport/auth; provider API sandbox/mock.

Закрепить версии, commit/digest образов, CUDA/driver requirements и лицензии. Если OPM и GemPy требуют разных окружений, разделить worker images вместо принудительного общего env.

По умолчанию сервер headless. Optional extra [ui] добавляет Gradio просмотрщик, который показывает сохранённые отчёты и scene_export HTML. PyVista/trame для создания сцен находится в extra [viewer].

`THIRD_PARTY.md` должен содержать компонент, версию, лицензию, способ включения, источник моделей/данных и ограничения поставки. Не распространять тестовые данные без проверенной лицензии. Исходный код, контейнеры, solver и ML-weights могут иметь разные условия.

## 5. Архитектура и топологии

Модули: optional UI/viewer; application service; domain adapters; execution layer; MCP; storage. Runpod lifecycle controller находится вне пакета в experimental/runpod. Начинать модульным монолитом с отдельными вычислительными процессами. Не требовать Kubernetes, Redis, Celery, Ray и Slurm вместе с Dask.

Три обязательные топологии:

- **Local:** API/UI/БД/артефакты на машине пользователя, локальный Dask cluster, CPU или NVIDIA GPU.
- **Local + remote:** локальный control plane подключает доверенный GPU-сервер; входы staged и проверены, результаты возвращаются.
- **Server:** control plane и workers находятся на сервере, пользователь открывает HTTPS UI/MCP. Автоматическое выделение workers через managed provider относится к отдельному эксперименту.

SQLite хранится только на локальном диске одного control plane, без NFS. Workers не пишут в БД напрямую. Использовать миграции, позволяющие позднее перейти на PostgreSQL. Один владелец установки достаточен; это не отменяет авторизацию удалённых API.

Dask — доверенная вычислительная сеть, не публичный пользовательский API. Подключение: один проверенный SSH-туннель/SSHCluster-профиль либо private network + mutual TLS [S7]. На облачном worker использовать документированный приватный канал; не публиковать scheduler без защиты.

Все тяжёлые операции получают input artifact IDs/revisions и JobSpec. Объёмные данные передаются через artifact store, не через контекст LLM и не внутри гигантского сериализованного task payload.

## 6. Модель данных и форматы

### 6.1. Сущности

Базовые: `Project`, `Dataset`, `Well`, `Trajectory`, `WellLog`, `Marker`, `Surface`, `Orientations`, `StructuralModel`, `Grid`, `PropertySet`, `Scenario`, `Artifact`, `Job`, `ComputeTarget`, `SceneState`.

Расширенные: `SeismicSurvey`, `SeismicVolume`, `Interpretation`, `VelocityModel`, `Fault`, `VariogramModel`, `ConditioningSet`, `SimulationCase`, `FluidModel`, `RockModel`, `CompletionSet`, `Schedule`, `SimulationResult`, `ScenarioSet`, `WorkflowDefinition`, `WorkflowRun`, `CloudLease`, `BudgetPolicy`.

Обязательные метаданные объекта: `id, project_id, revision, schema_version, created_at, source_ids, parameters, content_hash, artifact_refs`. Ревизия immutable. Изменение входов создаёт новый объект/ревизию и помечает зависимые результаты stale; старые результаты остаются доступными.

Jobs фиксируют конкретные ревизии, версии библиотек/solver, image digest, seed, precision, фактическое устройство, координатный transform и units. Любое число в отчёте связано с артефактом и методикой.

### 6.2. Координаты и единицы

- X/Y — метры в объявленной проекции EPSG/WKT; синтетический проект может иметь явно локальную систему.
- Внутренняя Z — высота в метрах, положительное направление вверх, с заданным datum.
- MD — расстояние по стволу; TVD — вертикальная глубина; TVDSS хранится с явным знаком и datum.
- Для вертикальной скважины MD→Z требует reference elevation. Для наклонной — XYZ/MD trajectory.
- Перевод в положительную вниз глубину OPM выполняется в одном адаптере и проверяется обратным преобразованием.
- Сейсмическое время — отдельная размерность: TWT в секундах/мс по метаданным. Нельзя накладывать временной горизонт на глубинную модель без time-depth transform.
- Не смешивать абсолютное давление и избыточное, пластовые и стандартные объёмы. Rate включает единицу времени и условия измерения.
- Проницаемость хранить с явной единицей (например mD), pressure с явной единицей и reference; внутренний канонический формат документировать.
- Неизвестный vertical datum, units или reference pressure — ошибка/уточнение. pyproj не создаёт отсутствующие геодезические данные.

### 6.3. Минимальные входы

| Данные | Поддержка |
|---|---|
| Устья | CSV `well_id,x,y,reference_elevation` + CRS/datum/units |
| Траектории | CSV `well_id,md,x,y,z`, MD строго возрастает |
| Разбивки | CSV `well_id,horizon,md`, связь с trajectory |
| Каротаж | LAS 1.2/2.0, явный well mapping, units/null [S8] |
| Поверхности | CSV `horizon,x,y,z`, экспорт нормализованных поверхностей |
| Ориентировки | CSV `horizon,x,y,z,nx,ny,nz` с проверкой нормалей |
| Свойства по зонам | CSV/JSON porosity, permeability, NTG, Sw |
| Сейсмика | Регулярный poststack 3D SEG-Y rev0/rev1 в подтверждённых библиотекой encoding profiles |
| PVT/SCAL | CSV/JSON только поддерживаемых tabular schemas, units обязательны |
| Расчётный случай | Сгенерированный OPM deck; импорт ограниченного набора deck profiles с includes |
| Производственные данные | CSV well_id/date/oil_rate/water_rate/gas_rate/pressure/units; для сравнения, не автоматического history matching |

Для каждого формата нужны шаблон, пример, ограничения и ошибки. Импорт проходит upload→parse→QC→normalize→atomic publish. Данные с ошибками не становятся валидной моделью автоматически. Null не заменяется нулём.

QC: схемы, единицы, диапазоны, дубликаты, порядок MD/time, привязка wells, sample geometry, неизвестные references, NaN/Inf, активные ячейки, конфликт горизонтов, `0≤phi,NTG,Sw≤1`, `K≥0`, `Bo>0`, сумма насыщенностей. Отчёт: code/severity/object/row/message/suggested_action.

Экспорт проекта: безопасный ZIP с manifest, hashes, schema versions, Parquet/JSON/Zarr и допустимыми solver files. Проверка путей, распакованного размера и целостности; без pickle, credentials, API keys и временных signed URLs.

## 7. Поставка A: геология и статические объёмы

### 7.1. Структурная модель

GemPy строит согласные слои на регулярной сетке по surface points, orientations, stratigraphic order, extent и resolution. Выходы: zone/lithology ID, scalar fields при необходимости, поверхности границ, active mask и QC.

Одна конвенция осей/индексов для NumPy, Zarr, VTK и последующего OPM adapter. Сохранить transform нормализации GemPy. Передача в viewer не меняет мировые координаты.

Ориентировки обязательны, либо пользователь явно выбирает предположение «горизонтальные слои» для простого случая. Не выводить неизвестные ориентировки молча. Черновая и полная сетка — отдельные версии. При нехватке памяти разрешение не снижается автоматически.

### 7.2. Простые свойства

Константы по зоне или явное mean/median выбранной кривой по интервалу; количество валидных samples и missing fraction показываются. Усреднение по отсчётам MD не выдаётся за объёмное усреднение пласта.

Проницаемость сохраняется и отображается, но не используется в формуле статического объёма. Подготовка свойств из необработанного каротажа с комплексной петрофизической интерпретацией не входит в A.

### 7.3. Формулы статических объёмов

Базовый профиль: нефтяная зона без газовой шапки, горизонтальный OWC, заданные Sw и постоянный Bo. Capillary transition не моделируется. Для regular cell `V=dx×dy×dz`; membership определяется в центре ячейки. Доля выше контакта `f_contact` рассчитывается по вертикальному пересечению ячейки с горизонтальной плоскостью.

```text
GRV              = Σ V                                  # полная активная зона
GRV_oil_interval = Σ(V × f_contact)
NetRockVolume    = Σ(V × f_contact × NTG)
PV               = Σ(V × f_contact × NTG × phi)
HCPV             = Σ(V × f_contact × NTG × phi × (1−Sw))
STOIIP           = HCPV / Bo
```

Суммы относятся к выбранным активным reservoir zones. Пропуски в активной области блокируют вычисление. Результат в стандартных м³ обозначается «начальный объём нефти», не «извлекаемые запасы». Bo и условия объёма обязательны.

Показать дискретизационную ошибку границ и допущения. Для сложной модели статические результаты не должны автоматически считаться совпадающими с initialization OPM: сверка описана отдельно.

### 7.4. Первые сценарии

В A: независимые scalar distributions по phi/NTG/Sw/Bo/contact, constant/uniform/triangular и физические bounds. Sample table генерируется на CPU с seed, сохраняется и используется одинаково на CPU/GPU. Геометрия неизменна.

В отчёте Q10/Q50/Q90 с фиксированным методом квантилей. Нефтяное соглашение вероятности превышения при использовании P-обозначений: P90=Q10, P50=Q50, P10=Q90. Не смешивать определения.

## 8. Поставка B: сейсмика и интерпретация

### 8.1. SEG-Y

Использовать segyio [S3]. Поддерживать подтверждённые sample formats, координатные scalars, endian, trace headers, sampling interval, sample origin, inline/crossline mapping и CRS. При неоднозначных headers требовать explicit mapping и preview.

Профиль B: regular poststack 3D с фиксированным sampling. Prestack, нерегулярная геометрия и variable trace length возвращают unsupported profile. Отсутствующие traces отображаются маской; их нельзя заполнять нулём без явной операции. Дубликаты геометрии блокируют canonical cube до выбора правила.

Создать canonical chunked volume и geometry index. Импорт/индексация потоковые, без обязательного чтения всего куба в RAM. UI запрашивает нужные slices, а не полный куб. Original SEG-Y immutable, индекс и canonical cube — производные артефакты.

### 8.2. Просмотр и атрибуты

Inline/crossline/time slice для TWT, depth slice для depth-domain. Видимы оси/units, color scale, amplitude clipping, выбранная trace position. Отметка на пикселе превращается в coordinate/sample index с сохранением domain.

Обязательные атрибуты: RMS в заданном окне и envelope через Hilbert transform. Использовать SciPy CPU и совместимые PyTorch CUDA операции; одинаковые окно, нормировка и boundary policy. Для tiled RMS использовать halo; для Hilbert считать полную trace в sample-axis или эквивалентный проверенный алгоритм, не независимые куски без математического обоснования.

При слишком короткой trace или пропусках операция сообщает применённую mask policy. Синтетические тесты определяют ожидаемые границы и длину выходного массива.

### 8.3. Ручная интерпретация и time-depth

Пользователь ставит/редактирует/удаляет horizon picks на срезах, создаёт именованный horizon, сохраняет новую revision и экспортирует точки. Минимум — polyline picks на выбранных inline/crossline и интерполяция в пределах покрытой области. Сохранять original picks, метод интерполяции и область extrapolation; по умолчанию extrapolation отключена.

Для передачи временного горизонта в GemPy необходим `VelocityModel`. Обязательный простой профиль: заданная пользователем постоянная скорость либо одна монотонная 1D таблица time-depth с явным origin/datum. В constant-velocity demo: `depth_difference = velocity × TWT / 2`. Checkshot/VSP сложной пространственной модели — последующий этап.

Между временной сейсмикой и глубинной сценой нельзя переключать подписи осей без пересчёта. Transform и допущение 1D должны быть видимы. На синтетическом примере проверить время→глубина→время.

## 9. Поставка B: разломы и пространственные свойства

### 9.1. Один простой разлом

Через GemPy поддержать один planar fault, смещающий согласную последовательность; explicit fault relations и input orientations [S1]. Показать fault surface, блоки и результат в разрезе. Сохранить исходную интерпретацию и параметры.

Проверки: правильная сторона смещения, отсутствие недопустимых zone IDs, совпадение геометрии CPU/GPU вне полосы дискретизации, соответствие синтетическому эталону. Не утверждать поддержку arbitrary fault networks.

**Граница моста к OPM:** автоматическая подготовка динамической модели в B гарантируется для модели без разломов. Структурная модель с наклонным разломом поддерживается для просмотра/статических объёмов; её автоматическая динамическая передача блокируется с объяснением. Отдельный grid-aligned sealing barrier можно задать в simulation profile и проверить как явно упрощённый сценарий, но это не эквивалент геологического fault sealing.

### 9.2. Геостатистика

Использовать GSTools для experimental variogram, covariance model, ordinary kriging и conditioned random fields [S2]. B должен включать isotropic profile и один проверенный geometric anisotropy profile. Основной путь CPU; не обещать GPU GSTools без отдельной реализации и проверки.

Поток: выбрать кривые/units→разбить по зонам→заблокировать по ячейкам/интервалам→описать duplicates и агрегирование→исследовать распределение→выбрать transform→оценить вариограмму→kriging/conditional realization→QC.

Для K использовать log transform с правилом нулевых значений; для phi — ограничивающий invertible transform либо иной явно заданный способ. Простое clipping после моделирования запрещено выдавать за отсутствие изменения статистики. Transformation и обратное преобразование включаются в проверку кондиционирования.

Минимальный свойственный набор: phi и K, NTG/Sw можно оставить по зонам. Пермеабельность изотропная либо Kx=Ky и Kz=ratio×Kx с явным ratio. Не предполагать физическую связь phi-K автоматически: независимость или заданная регрессия с residual model указывается как допущение.

По умолчанию моделировать отдельно по зонам; перенос conditioning через границы и разломы запрещён без выбранной модели связности. Сохранять variogram parameters, coordinate scaling, seed и conditioning set revision.

Проверить восстановление наблюдений для exact profile, leave-one-well-out validation, RMSE/bias и воспроизводимость. Отчёт по одной realization не подтверждает корректность статистики ансамбля; для ансамбля дополнительно проверять распределение и variogram с заранее заданными допусками.

## 10. Поставка B: от геологической модели к OPM Flow

### 10.1. Поддерживаемая физика и расчётные случаи

OPM Flow — отдельный закреплённый исполняемый solver, а не переписанная математическая модель [S4]. Обязательный автоматически создаваемый профиль B: изотермическая двухфазная нефть–вода, dead oil, single porosity/single permeability, Cartesian grid, producer и water injector, rate/BHP controls, closed boundaries. Поддержать один односкважинный depletion case и один waterflood case.

Дополнительно: импорт и запуск одного проверенного трёхфазного black-oil reference case с поддерживаемыми PVT/SCAL и keywords. Генерация произвольных compositional/thermal/EOR/CO₂ cases не входит в v0.2. Наличие таких режимов в OPM не означает их поддержку приложением.

`SimulationCase` содержит physics_profile, grid/property revisions, fluid_model, rock_model, equilibrium/initial_state, wells/completions, schedule, solver_profile и output_requests. Каждый элемент явно задан или получен из именованного demo template. Для реальных данных не подставлять неизвестные PVT и SCAL как будто они измерены.

### 10.2. Контракт сеток и свойств

Первый мост: регулярная геологическая сетка → совпадающая по разрешению Cartesian simulation grid. Это исключает неявное укрупнение. Экспортировать размеры ячеек, глубины, ACTNUM, PORO, PERMX/PERMY/PERMZ и необходимые region IDs. Использовать поддерживаемый XTGeo/OPM writer либо небольшой шаблонный exporter только этого профиля; не писать универсальный parser геометрии.

Обязателен `GridMapping`: geological cell ID ↔ simulator I/J/K ↔ linear index ↔ result cell ID. Сохранить axis orientation, cell-center coordinates, active masks и units. Для неактивных ячеек result reader должен восстанавливать исходную форму без сдвига индексов.

Проверки перед deck generation:

- число, форма и порядок ячеек, положительные размеры и объёмы;
- пористость и проницаемость в диапазонах, заполненность активной области;
- связность активной области и отсутствие неожиданно изолированных скважин;
- преобразование Z-up к depth-down и положение top/bottom;
- totals pore volume и net rock volume до/после экспорта;
- положение completions именно в ожидаемых I/J/K.

Для B зафиксировать одну convention NTG: porosity — свойство net rock, NTG — отдельная доля. Если выбранный deck profile использует NTG keyword, не умножать PORO на NTG повторно. Любой альтернативный профиль с effective porosity имеет другое имя и отдельный тест; запрещено смешивать их. Проверить simulator pore volume по этому соглашению.

Upscaling не выполнять автоматически. Если сетка слишком большая, пользователь создаёт новую coarse geological realization с предупреждением либо подключает больший target. Перенос K арифметическим средним не объявлять эквивалентом flow-based upscaling.

Наклонные faulted grids не становятся корректными simulation grids только после voxelization. Неподдерживаемый мост возвращает `UNSUPPORTED_GRID_BRIDGE`. Импортированный reference corner-point case может запускаться как самостоятельный кейс; это не доказательство возможности автоматически построить такую сетку.

### 10.3. Флюиды, порода и начальное состояние

Базовый профиль требует oil/water density, viscosity и formation volume factor tables/constants в поддерживаемой форме; rock compressibility/reference pressure; относительные фазовые проницаемости и, при использовании, capillary pressure tables. Данные оформляются типизированными schemas; экспорт сверяется с закреплённым OPM manual.

QC таблиц: ordered abscissa, положительные физические величины, saturation endpoints, корректные диапазоны, units, duplicate rows, ожидаемая монотонность только для величин, где она обязательна. Не «чинить» SCAL сортировкой значений без разрешённого преобразования.

Initialization: equilibrium по заданному reference depth/pressure и contact либо explicit pressure/saturation arrays в отдельном профиле. Сохранить, какой метод выбран; нельзя одновременно задавать противоречащие equilibrium и explicit arrays.

Рассчитать initial fluid-in-place средствами OPM и сравнить с входными cell pore volumes и подходящим статическим расчётом. Для demo constant-Bo/no-capillarity случая значения должны сходиться в установленном допуске. Для различающихся постановок отчёт объясняет причину расхождения, а не подгоняет параметры.

### 10.4. Скважины, completions и schedule

Минимум: вертикальные producer/injector, explicit completion intervals/IJK, well radius, skin, status. B не обещает произвольную multi-segment well модель.

Контроли: producer oil/liquid rate с BHP limit; water injector rate с BHP limit; open/shut и изменения по датам. Документировать surface/reservoir rate convention и pressure datum. Две скважины не получают одинаковые имена после нормализации.

Schedule имеет start date, report dates и управляемые события. Проверить порядок дат, положительные интервалы, существование wells, единицы, конфликтующие события и ограничения. Изменение schedule создаёт новый case, не меняет завершённую симуляцию.

### 10.5. Генерация, импорт и запуск deck

Сгенерировать читаемый deck и все включённые файлы, manifest, QC report и configuration snapshot. Пользователь может скачать и запустить case непосредственно закреплённым OPM Flow вне приложения.

Импортированный deck проходит parser/QC и whitelist supported physics profiles. INCLUDE разрешён только внутри case bundle; запрещены path traversal, внешние абсолютные пути и исполняемые пользовательские callback/script-механизмы. В v0.2 не исполнять PYACTION или произвольный пользовательский код из deck.

OPM запускается отдельным процессом/контейнером с resource limits, argv-массивом без shell interpolation, immutable input mount и отдельной output directory. Сохранять stdout/stderr, solver exit code, convergence diagnostics и report-time progress. Нельзя считать exit code 0 достаточным без ожидаемых outputs и проверки завершения report schedule.

CPU profile обязателен. CUDA profile использует реально поддерживаемую данным build конфигурацию линейного solver. Факт исполнения solver на GPU проверяется по журналу/профилю и метрикам, а не по наличию GPU на сервере. Обновить проверку по выбранной версии: обзорная страница GPU у OPM описывает интерфейс 24.10 и не доказывает возможности последующего build [S4].

### 10.6. Чтение и анализ результатов

Использовать resdata или проверенный opm.io; не разбирать бинарные simulator outputs вручную [S5]. Минимум: grid/active mapping, initialization, restart snapshots по report dates, summary vectors и units.

UI: pressure, Sw и при трёхфазном reference case So/Sg; time slider; legend; срез; выделение wells. Summary: oil/water/gas rates по доступным фазам, cumulative production/injection, BHP, field pressure при доступности.

Water cut вычисляется по surface liquid rates `water/(oil+water)` с явной обработкой нулевого знаменателя как undefined. Не считать zero-liquid water cut равным нулю без отметки. Для сравнения cases показывать одинаковые units и даты; rate/cumulative series интерполируются по различным, документированным правилам. Не экстраполировать конец незавершённой симуляции.

Поддержать экспорт CSV и совместимого case/result пакета для ResInsight. ResInsight — дополнительный независимый просмотр; основные показатели должны быть доступны и в собственном UI.

При наличии observed production data показать сопоставление и RMSE/bias на общих датах; это диагностическое сравнение, не автоматический history matching.

## 11. Поставка C: ансамбли и рабочие процессы

### 11.1. Расчётные ансамбли

Поддержать ensembles геологических свойств и dynamic cases. Каждая realization имеет parameter row, seed, input revisions, job IDs и статус. Формировать явную таблицу сочетаний geological realization × development scenario; не запускать непредусмотренное декартово произведение молча.

Обязательный demo: 3 пространственные реализации свойств × 2 schedules = 6 dynamic cases. Отдельный static benchmark — 30 реализаций. Минимальный bounded search сравнивает до 10 явно заданных schedules/rate profiles и ранжирует их по выбранной метрике с заданными ограничениями. Это дискретный перебор, а не доказательство глобального оптимума.

Метрики: cumulative oil на выбранную дату, cumulative water/injection, water cut, достижение BHP limits, число failed cases, длительность расчёта. Экономический NPV не обязателен: без цен, затрат и discount rate его не рассчитывать.

Неопределённость: min/max/mean/std/Q10/Q50/Q90, распределение конечных метрик и, для общих report dates, pointwise bands. Pointwise P50 curve может не соответствовать ни одной реальной realization; так её и подписывать. Для представительной реализации выбирать конкретный case по явно указанному критерию.

Незавершённые/failed cases не исключаются незаметно. Указывать completed/total, причины исключения, policy for partial reports. Повторять только незавершённые реализации с теми же sampled inputs. Не регенерировать seed при retry.

### 11.2. WorkflowDefinition и WorkflowRun

Workflow — сохранённый DAG разрешённых операций, подготовленный через MCP/CLI/REST. Использовать JSON/YAML с версией схемы и Pydantic validation; граф зависимостей можно проверять готовой graphlib. Dask исполняет вычислительные узлы; собственный слой хранит смысл и состояние workflow, а не заменяет Dask.

Узел содержит operation, arguments, input references, output ports, execution policy и retry policy. Ссылки могут указывать на pinned artifact revision или параметр запуска. Никаких произвольных Python/shell snippets и eval выражений. Минимальные конструкции — последовательность, fan-out по явному списку параметров, fan-in результатов; сложные условия/циклы не обязательны.

Перед запуском: проверить отсутствие циклов, типы связей, наличие входов, permissions, поддержку операций, число jobs, лимиты и возможные передачи данных. Показать план и оценку. Разрешённый workflow запускается без повторного запроса на каждый обратимый шаг внутри утверждённой политики.

Каждый run сохраняет resolved inputs и plan hash. Изменение определения не меняет уже запущенный run. Resume использует завершённые node outputs только при совпадении input/config hashes и versions. Инвалидация входа пересчитывает зависимые узлы, не независимые.

Кэш не означает право доступа: перед повторным использованием проверяются project permissions и целостность артефакта. Workflow export не содержит credentials.

## 12. Вычислительный контракт и GPU

### 12.1. Поддержка операций

| Операция | CPU | NVIDIA CUDA | Примечание |
|---|---|---|---|
| Импорт, QC, CRS, deck generation | Обязательно | Не требуется | GPU не нужен для каждой стадии |
| GemPy слои/поддерживаемый fault case | Обязательно | Обязательно на контрольных примерах | Закрепить PyTorch backend и dtype |
| Свойства/статические объёмы | Обязательно | Обязательно | Настоящие tensor operations |
| RMS/envelope | Обязательно | Обязательно на поддерживаемых traces | Проверка границ и численной ошибки |
| GSTools | Обязательно | Не обещается | Remote CPU worker допустим |
| OPM поддерживаемый CPU-case | Обязательно | Проверенный GPU solver profile обязателен хотя бы для одного benchmark | Ускоряется поддерживаемая часть solver, не весь pipeline |
| Независимые realizations | Обязательно | Один GPU на job; несколько workers | Не distributed single-case solver |
| 3D viewer | Отдельная способность | Отдельная способность | Rendering GPU не доказывает scientific GPU |

Основной GPU-профиль: Linux x86_64 + NVIDIA; локально также документированный WSL2. macOS: CPU/UI + remote NVIDIA. AMD/Apple MPS — будущие capability profiles после проверки каждого модуля, не обязательные CUDA substitutes.

### 12.2. JobSpec

```json
{
  "operation": "volumetrics_calculate",
  "project_id": "demo",
  "inputs": [{"id": "property-set-01", "revision": 2}],
  "parameters": {
    "zone_ids": [2],
    "contact_z_m": -1050.0,
    "bo": 1.2
  },
  "execution": {
    "placement": "auto",
    "target_id": null,
    "device_policy": "prefer_gpu",
    "allow_cpu_fallback": true,
    "allow_remote": false,
    "precision": "float64",
    "timeout_seconds": 3600,
    "max_retries": 1,
    "budget_policy_id": null
  },
  "idempotency_key": "demo-volumes-001"
}
```

`placement=local/remote/auto`; `device_policy=cpu/prefer_gpu/require_gpu`. Target хранит location (`local/server/cloud`), capabilities, env/image versions, health, worker slots, RAM/VRAM и connection profile. Секреты хранятся отдельно. OPM mixed CPU/GPU solver отдельно отмечает фактические стадии исполнения.

`require_gpu` проверяется относительно конкретной операции/solver profile: при неподдерживаемом path — `NO_COMPATIBLE_GPU`, без скрытого fallback. `prefer_gpu` допускает CPU только если разрешено и с явным сообщением причины. Если GSTools-фаза CPU является частью общего workflow, это отражается в плане; не помечать весь workflow как полностью GPU.

### 12.3. Выбор места и ресурсы

Порядок: project data policy → compatible operation/env → device/precision → health/resources → data locality → очередь и измеренная производительность → стоимость. Начать с детерминированных правил. Без benchmark прогноз помечается estimate, а не гарантией.

Удалённая передача запрещена по умолчанию, пока владелец не задаст политику проекта. Нехватка локальной памяти не меняет права. Boolean из LLM-запроса не может повысить разрешения.

Один compute process на GPU по умолчанию. Worker привязан к устройству, Dask resources ограничивают concurrency, отдельный preflight оценивает RAM/VRAM с рабочими буферами и запасом. `CUDA_VISIBLE_DEVICES` не резервирует память.

OOM: один допустимый retry с меньшим evaluation batch только если алгоритм поддерживает это без изменения результата. Не уменьшать сетку, точность или физику автоматически. Глобальная интерполяция и solver не становятся out-of-core от простого chunking входов.

Точность по умолчанию float64; float32 разрешён явно и с отдельными допусками. Не включать mixed precision в научный solver без проверки. Про GPU throughput FP32 нельзя делать вывод о скорости требующего FP64 расчёта.

### 12.4. Метрики

Измерять cold start, staging/upload/download, подготовку, compute, write и full wall time; CUDA-замеры синхронизировать. Хранить hardware, CPU threads, MPI ranks, GPU, driver, env/image, precision, grid size, peaks RAM/VRAM при доступности.

Не устанавливать заранее обязательное ускорение в N раз. Критерий — реальное GPU-исполнение, приемлемая ошибка и честный benchmark относительно разумно настроенного CPU. Малый case может быстрее работать на CPU. Проверить OPM convergence отдельно: одинаковый exit code не подтверждает одинаковый физический результат.

## 13. Jobs, сохранность и удалённые данные

Состояния: `queued→staging→running→succeeded/failed/cancelled/interrupted`, промежуточное `cancel_requested`. Отдельный attempt_id для каждой попытки, timestamps и stage events. Terminal state не перезаписывается; повтор — новая попытка.

- Submit записывает job в постоянную БД до ответа; цель ответа локально ≤2 с без upload.
- API/UI/MCP читают status, stage, timestamp, target, фактический backend, retries, warnings, logs и artifact refs.
- Процент показывать только при реальном измерении; иначе stage и elapsed time.
- Закрытие UI/чата не завершает job.
- Result publication атомарна: temporary outputs→validation→hash→manifest→publish.
- Idempotency key scoped к project+operation; одинаковый payload возвращает существующий job, другой payload с тем же ключом — конфликт.
- Не обещать exactly-once Dask execution. Retry допускается для чистых вычислений с идемпотентной публикацией.
- После рестарта reconciliation сверяет persistent jobs с executor. Потерянный job становится interrupted, а не succeeded.
- Cancel Future недостаточен для нативного solver/CUDA. Каждый compute subprocess/контейнер должен прекращаться независимо, с освобождением своего GPU; соседние jobs не убиваются.
- Timeout/cancel останавливает child process tree. На контрольной длинной задаче освобождение ресурсов ≤30 с.
- Native solver restart из середины не обязателен. Resume ансамбля/workflow обязан сохранять завершённые jobs; restart из OPM checkpoint — последующее улучшение.

Artifact staging: immutable IDs+hashes, manifest, целостность после передачи и cached copies по target. На повторном запуске неизменённые inputs не пересылаются. Источником истины остаётся durable store, не ephemeral worker disk.

Для больших сейсмических данных вычислять рядом с существующим хранилищем; viewer получает slices/preview. S3 credentials не раскрываются LLM; signed URLs короткоживущие и имеют минимальные права. Изменение прав проверяется и при cache hit.

## 14. Облачный эксперимент

Исключён из основного продукта, MCP и обязательной приёмки. Код и прежние документы находятся в experimental/runpod.

## 15. Локальный просмотрщик

Extra [ui]: проекты/ревизии, отчёты, scene_export HTML, сейсмические срезы, загрузка файлов и кнопка «Open Norne demo». Научных форм запуска, чата и записи голоса нет. Демо открывает bundled immutable artifacts без сети и вычислений. Запуск расчётов — MCP/CLI/REST.

## 16. REST, CLI и MCP

Один application service обслуживает все каналы. OpenAPI и JSON Schemas генерируются из фактических контрактов. CLI предоставляет запуск demo, импорт, submit/status/cancel, workflow run, export и benchmark; credentials не передаются в командной строке открытым текстом.

MCP SDK — официальный Python, transports stdio и Streamable HTTP [S11]. Строковые имена ниже — API проектируемой системы, не встроенные tools внешних клиентов.

### 16.1. Обязательные группы инструментов

| Группа | Инструменты | Поставка |
|---|---|---|
| Проект/данные | `project_create`, `project_list`, `project_inspect`, `dataset_import`, `dataset_validate`, `artifact_inspect` | A |
| Геология/объёмы | `model_build`, `properties_assign`, `volumetrics_calculate`, `scenarios_run`, `scenarios_compare` | A |
| Targets/jobs | `compute_targets_list`, `job_status`, `job_cancel` | A |
| Сцена | `scene_show`, `scene_inspect` | A |
| Сейсмика | `seismic_inspect`, `seismic_slice`, `seismic_attribute`, `interpretation_save`, `horizon_convert_domain` | B |
| Геостатистика | `variogram_fit`, `properties_krige`, `properties_simulate` | B |
| Simulation | `simulation_case_create`, `simulation_validate`, `simulation_submit`, `simulation_results`, `simulation_compare` | B |
| Workflow | `workflow_save`, `workflow_validate`, `workflow_run`, `workflow_status`, `workflow_cancel` | C |
| Ансамбль | `ensemble_plan`, `ensemble_run`, `ensemble_compare` | C |


Для каждой операции определить Pydantic input/output schemas, read/write annotations, idempotency, permissions, units и допустимые ошибки. Избегать универсального инструмента `execute_anything`. Не создавать сотни мелких tools, дублирующих каждую кнопку viewer.

### 16.2. Длительность, файлы и ответы

Импорт получает `upload_id` предварительно загруженного файла или разрешённый project artifact ID. Произвольный local path/URL от LLM не принимается. CLI может явно загрузить указанный пользователем файл через контролируемый upload.

REST namespace `/api/v1`: projects, uploads, datasets, models, simulations, jobs, targets, artifacts, scenes, workflows, ensembles. Cloud routes/tools исключены из продукта. Длинный submit — HTTP 202 с job_id; MCP — структурированный accepted result. Polling возвращает фактические состояния; state остаётся в БД.

Большие массивы не включаются в tool response. Возвращать compact summary, schema/units, artifact IDs и защищённые URLs. Настроить размер summary и pagination. ChatGPT/Claude могут открывать собственный viewer по ссылке; встроенный 3D MCP App не является условием v0.2.

Пример submission ensemble:

```json
{
  "project_id": "demo",
  "base_case": {"id": "waterflood-case", "revision": 3},
  "property_realization_ids": ["realization-01", "realization-02", "realization-03"],
  "schedule_ids": ["schedule-a", "schedule-b"],
  "combination_mode": "cartesian_explicit",
  "expected_case_count": 6,
  "execution": {
    "placement": "remote",
    "target_id": "gpu-server-01",
    "device_policy": "prefer_gpu",
    "allow_cpu_fallback": true,
    "allow_remote": true,
    "precision": "float64",
    "timeout_seconds": 3600,
    "max_retries": 1,
    "budget_policy_id": null
  },
  "idempotency_key": "demo-ensemble-001"
}
```

Указанные IDs immutable; при использовании versioned objects передавать revision. Сервер сверяет permissions независимо от flags в JSON. Один ensemble job имеет child jobs; его статус не скрывает failures или pending cleanup.

Ошибки: `INVALID_UNITS`, `MISSING_DATUM`, `AMBIGUOUS_GEOMETRY`, `INVALID_PVT`, `INVALID_SCHEDULE`, `UNSUPPORTED_PHYSICS`, `UNSUPPORTED_GRID_BRIDGE`, `NO_COMPATIBLE_GPU`, `INSUFFICIENT_MEMORY`, `TARGET_UNREACHABLE`, `DATA_TRANSFER_DENIED`, `BUDGET_EXCEEDED`, `CLOUD_STATE_UNKNOWN`, `CLEANUP_FAILED`, `INPUT_REVISION_CONFLICT`, `COMPUTE_FAILED`, `AUTH_REQUIRED`. Ошибка содержит code, русский message, field pointers и remediation; secrets/tracebacks не раскрываются клиенту.

## 17. Авторизация и конфигурация

Local profile слушает loopback, имеет защиту локальных web endpoints от чужих origins и не публикуется автоматически. Remote UI/API/MCP используют HTTPS и авторизацию. Применить готовую auth middleware/провайдер; не писать собственный OAuth server.

Для удалённого MCP закрепить совместимую версию спецификации, resource metadata, token audience/scopes и discovery [S11]. На этапе 0 проверить один воспроизводимый OAuth-profile в реальных целевых ChatGPT/Claude-клиентах [S12]. Наличие OIDC-провайдера само по себе не доказывает поддержку нужного handshake.

Защищать не только страницу UI: REST, Gradio endpoints, viewer/WebSocket, uploads/downloads, signed URL issuance и artifact metadata проверяют права. UI session и MCP token могут различаться, но отображаются на одного владельца и project policies.

Secrets: env/keyring/secret store, ссылки в конфигурации, без значений в проектных пакетах, chat history, logs и image. Для workers — ограниченные credentials с возможностью отзыва; provider credentials относятся к отдельному experimental checkout.

Настройки установки: paths/DB, artifact backend, targets, images, auth, origins, logging, limits, transfer/cloud policies. Поставить `.env.example` без секретов. LLM не изменяет системную конфигурацию через строку команды.

## 18. Научные контрольные примеры

### 18.1. Данные и происхождение

Генераторы синтетических данных входят в репозиторий: `layer_cake`, `dipping_layers`, `single_fault`, `synthetic_seismic`, `geostat_conditioning`, `waterflood_demo`, `invalid_inputs`. Seeds фиксированы, лицензия ясна. Реальные коммерческие данные Petrel не скачивать.

Один reference OPM case взять из upstream test data или другого первичного источника с проверенной лицензией и commit/hash [S13]. Наличие case в репозитории не гарантирует наличие reference results: сформировать baseline прямым запуском закреплённого solver и задокументировать происхождение. Не сравнивать только два вызова одного ошибочного adapter.

### 18.2. Статические объёмы

Независимая заданная сетка: площадь 1000×1000 м, толщина 20 м, весь коллектор выше OWC; NTG=0.8, phi=0.2, Sw=0.25, Bo=1.2.

```text
GRV              = 20 000 000 м³
GRV_oil_interval = 20 000 000 м³
NetRockVolume    = 16 000 000 м³
PV               =  3 200 000 м³
HCPV             =  2 400 000 м³
STOIIP           =  2 000 000 стандартных м³
```

Float64 CPU и CUDA каждый сравнивается с аналитическим результатом, relative error ≤1e-8. Дополнительный контакт в середине ячейки проверяет fractional volume. Missing active values должны блокировать расчёт. Изменение NTG не должно удваивать эффект при simulation export.

### 18.3. Геометрия и GPU

Layer_cake: известные горизонты, положение границы в пределах одного cell step. Dipping layers: три разрешения, оценка и уменьшение ошибки дискретизации на выбранном эталоне. Single fault: известное направление смещения и проверка fault relation.

GemPy CPU/CUDA: для нормализованных scalar fields стартовые допуски `atol=1e-6, rtol=1e-5`; lithology ID совпадает вне полосы одной ячейки около границ. Допуски подтвердить на этапе 0 и записать до полной приёмки. Их изменение требует научного объяснения, а не подгонки под failing test.

GridMapping тестировать на маленькой несимметричной сетке 3×4×2 с уникальными cell values и неактивными ячейками: импорт результата восстанавливает каждое значение в нужной позиции. Симметричная сетка не подходит для выявления перестановки осей.

### 18.4. Сейсмика и геостатистика

Synthetic seismic: constant trace для RMS; синус с известной частотой/амплитудой и integer cycles для envelope; impulse для проверки window/boundary policy. Float64 CPU/CUDA — `atol=1e-8, rtol=1e-6` на определённых валидных samples, границы проверяются отдельно. Coordinate scalar/endian mapping проверяется отдельными fixtures.

Time-depth constant-velocity case: round trip в пределах численной точности; неверное одностороннее/двустороннее время должно обнаруживаться через ожидаемый результат. Picks сохраняются/загружаются в исходном domain.

GSTools exact conditioning fixture: восстановление условных точек после обратного transform с допуском 1e-6×scale; nugget/noisy profile тестируется по другой заявленной модели и не обязан точному прохождению. Проверить фиксированные seeds, holdout по скважине, variogram/распределение ансамбля с предварительно закреплёнными допусками. Не обещать статистическую идентичность для одного случайного поля.

### 18.5. Гидродинамика

Три независимые проверки:

1. **No-flow closed case:** нет wells/flux, initial equilibrium; отсутствие необъяснимого изменения компонентных масс и давления сверх заданной solver tolerance.
2. **Waterflood demo:** сгенерированный 20×20×5 Cartesian case, injector+producer, фиксированные PVT/SCAL/schedule. Проверить initialization, направления потоков, cumulative production/injection, complete report dates и баланс массы.
3. **Upstream black-oil case:** прямой reference CPU run vs adapter CPU run, затем проверенный GPU solver profile vs reference.

Mass balance оценивать по компонентным массам либо эквивалентным conserved component amounts, учитывая compressibility, phase exchange и выбранные стандартные условия. Простая сумма объёмов нефти/воды в разных условиях не является балансом массы.

Исходные приёмочные ориентиры: no-flow drift relative ≤1e-6 на constant-property fixture; normalized component balance residual ≤1e-4 на waterflood fixture; CPU/GPU cumulative metrics relative ≤1e-3 и pressure relative ≤1e-3 на согласованных report dates. Околонулевые значения используют заранее заданные физические absolute tolerances. Зафиксировать формулу residual и знаменатель. Для прямого/adapter CPU run с одинаковым solver/config требовать совпадения в численной точности.

Эти допуски уточняются на этапе 0 по методике и solver profile; не ослаблять их молча после получения результатов. Reference run не заменяет аналитические и conservation checks.

## 19. Критерии приёмки поставок

### 19.1. Поставка A

| ID | Проверка | Результат |
|---|---|---|
| A-01 | Чистая local CPU установка | Demo открывается без LLM/API/cloud credentials |
| A-02 | Импорт/QC | LAS/CSV-профили работают, invalid fixtures дают предметные ошибки |
| A-03 | Units/CRS/depth | Контрольные преобразования верны; unknown datum не угадывается |
| A-04 | Геология | Layer_cake и dipping layers построены реальным GemPy |
| A-05 | Объёмы | Аналитический тест проходит на CPU/CUDA |
| A-06 | Локальный GPU | Подтверждены GemPy и volume CUDA path, precision и метрики |
| A-07 | Remote GPU | Те же inputs выполнены на отдельном хосте, результаты проверены |
| A-08 | Jobs | Idempotency, cancel, timeout, restart reconciliation, cache и fallback корректны |
| A-09 | UI | Сцена, slices, logs, wells и QC доступны в основном сценарии |
| A-10 | Заменено MCP-клиентами | Не входит в обязательную приёмку продукта |
| A-11 | MCP | SDK/Inspector и реальные ChatGPT/Claude: inspect→submit→poll→result |
| A-12 | Version/export | Проект переносится без потери units/revisions/hashes; secrets не экспортируются |

### 19.2. Поставка B

| ID | Проверка | Результат |
|---|---|---|
| B-01 | SEG-Y | Headers/scalars/endianness/geometry проверены; ambiguous profile требует mapping |
| B-02 | Slices/picks | Просмотр с units, сохранение/редактирование picks, повторное открытие без сдвига |
| B-03 | Атрибуты | RMS/envelope CPU/CUDA проходят синтетические тесты |
| B-04 | Time-depth | Transform и round trip проходят; time domain не подменяется depth label |
| B-05 | Разлом | Single fault fixture соответствует геометрии, неподдерживаемый OPM bridge блокируется |
| B-06 | Геостатистика | Variogram, kriging, conditional fields, conditioning/holdout и seeds проверены |
| B-07 | GridMapping | Асимметричный 3×4×2 fixture проходит геология→deck→results |
| B-08 | PVT/SCAL/schedule | Неверные units/таблицы/даты/completions отвергаются |
| B-09 | Initialization | PORV/initial fluid-in-place согласованы с выбранной convention |
| B-10 | Waterflood | Полный generated case реально рассчитывается OPM на CPU |
| B-11 | OPM CUDA | Один supported benchmark проходит GPU path и comparison с CPU |
| B-12 | Conservation | No-flow и waterflood mass-balance checks проходят |
| B-13 | Result analysis | Time slider, pressure/saturation, rates/cumulatives/water cut и comparison корректны |
| B-14 | Interoperability | Exported case запускается вне приложения; результаты открываются в ResInsight |
| B-15 | Сквозной сценарий | Synthetic seismic→picks→depth→слои→свойства→OPM→прогноз без подмены результатов |
| B-16 | MCP coverage | B-операции доступны через общие contracts и подтверждены интеграционным сценарием |

### 19.3. Поставка C

| ID | Проверка | Результат |
|---|---|---|
| C-01 | Ансамбль | 3 property realizations×2 schedules дают 6 корректно учтённых cases |
| C-02 | Статистика | Q/P conventions, pointwise bands и partial failure handling проверены |
| C-03 | Bounded search | Ранжирование явно заданных вариантов с лимитом runs и без заявления global optimum |
| C-04 | Workflow | Save/validate/run/fan-out/fan-in, version pins и typing проверены |
| C-05 | Resume | Completed nodes переиспользуются только при совпадении hashes, зависимые пересчитываются |
| C-06 | Cloud plan/policy | Неразрешённые price/region/count/transfer блокируются; plan конкретен |
| C-07 | Provider lifecycle | Create→ready→job→artifact verification→terminate работает на разрешённом real test |
| C-08 | Orphan/retry | Mock timeout/create ambiguity/crash не создаёт бесконтрольных дубликатов |
| C-09 | Cleanup | Чужие resources не удаляются; cleanup failure виден и не считается полным успехом |
| C-10 | Учёт стоимости | Estimate/actual/unknown раздельны, budget reservation и limits работают |
| C-11 | Experimental cloud policy | Отдельный experimental CLI соблюдает policy; production MCP не содержит cloud tools |
| C-12 | Полная демонстрация | Сохранённый процесс повторён на новых inputs с отчётом результатов, ресурсов и ограничений |

### 19.4. Статусы и стенды

Каждый критерий имеет `PASS/FAIL/NOT RUN`, command/steps, timestamp, environment, evidence и limitations. A-10 имеет статус REPLACED, C-06…C-11 — EXPERIMENTAL; они не обязательны. Без GPU/удалённого сервера/внешних аккаунтов соответствующие проверки получают NOT RUN. Mocks не доказывают real CUDA, real OAuth или real cloud. Отсутствие стенда не мешает завершать независимый код, но полная приёмка v0.2 требует всех обязательных real tests.

Обычный CI: CPU scientific tests, schemas, imports, API/MCP SDK, jobs и workflow. Runpod mocks запускаются отдельно из experimental/runpod/tests с marker experimental. Другие отдельные suites: CUDA, remote GPU, OPM, external MCP clients. Не добавлять бессодержательные тесты, повторяющие реализацию без независимого expected result.

Benchmark profiles: static grids 50×50×30 и 100×100×100, расширенный 200×200×100 при доступной памяти; synthetic seismic с профилями, генерируемыми по фиксированным размерам; OPM small waterflood и один средний reference case. Стенд, размер inputs и настройки публикуются. Для тяжёлого профиля корректный preflight rejection допустим; базовый demo должен исполняться на указанном минимальном стенде.

Рекомендуемый базовый стенд проверки, а не гарантия для любого случая: CPU Linux 16 GB RAM; CUDA Linux 32 GB RAM и GPU с 12 GB VRAM; remote — отдельный host. На этапе 0 подтвердить фактические минимумы и пересмотреть fixtures при необходимости с сохранением смысла проверки. Производительность FP64 и модель GPU указываются явно.

## 20. Установка и эксплуатация

Профили: `local-cpu`, `local-cuda`, `remote-cuda`, `server`; managed-cloud — отдельный эксперимент. CPU local через uv/service launcher; solver/server images через Docker/Compose. WSL2/Linux и macOS CPU инструкции различаются. Не обещать CUDA в Docker на macOS.

Health checks: API, metadata DB, artifact store, executor, solver availability, GPU capabilities, provider connectivity. Отсутствующий GPU не делает CPU profile неисправным.

Логи structured, с project/job/attempt/workflow/lease IDs, operation, stage, durations. Без secrets и полных пользовательских данных. Файловых логов достаточно; observability stack не обязательный prerequisite.

Backup: metadata DB консистентным способом, manifests и durable artifacts; восстановление проверяется на demo. Не считать worker cache резервной копией.

В экспериментальном Runpod контуре состояния вычисления и очистки ресурсов различаются; подробности — experimental/runpod/docs/CLOUD_OPERATIONS.md. Основной продукт не управляет provider leases.

## 21. Порядок реализации для development contributors

### Этап 0. Проверка совместимости и научных границ

Прочитать repository instructions, проверить существующее состояние, сохранить пользовательские изменения. Выполнить доступные spikes из §4.1, закрепить versions/images и auth profile. Зафиксировать математику, grid conventions, solver profiles, baseline fixtures и допуски до большого UI.

Результаты: `COMPATIBILITY.md`, `SUPPORTED_PROFILES.md`, lockfiles, spike scripts и первые scientific tests. При отсутствии hardware/account продолжать доступные проверки, внешние помечать NOT RUN. Никакой автоматической покупки GPU/облака.

### Этап A1. Предметное CPU-ядро

Проекты/версии, imports/QC, GemPy, простые свойства, analytical volumes, artifact export, CLI/REST. Полезный полный CPU-сценарий без LLM.

### Этап A2. Исполнение и интерфейсы

Jobs, local CUDA, remote target/staging/cache/cancel, viewer/UI, MCP/auth, MCP tools/resources и read-only viewer. Закрыть критерии A.

### Этап B1. Сейсмика и свойства

SEG-Y, slices/picks, атрибуты и time-depth; simple fault; GSTools variogram/kriging/conditional fields. Каждый модуль добавляется с independent fixtures.

### Этап B2. Simulation bridge

GridMapping, supported exporter, PVT/SCAL, wells/completions/schedule, initialization QC, OPM CPU run и result reader. Проверить сначала grid/units/conservation, затем performance.

### Этап B3. GPU solver и анализ

Проверенный OPM CUDA profile, comparison, time-series/3D results, ResInsight export, сквозной сценарий B и tools. Закрыть критерии B.

### Этап C1. Workflows и ensembles

Typed DAG, validation, pinned versions, resume/cache, fan-out/fan-in, uncertainty и bounded ranking. Принимать результаты на фиксированном target до добавления managed cloud.

### Этап C2. Эксперимент

Runpod не входит в пакет; его проверки выполняются отдельно с marker experimental.

После каждого этапа приложение остаётся запускаемым. Вести acceptance ledger постоянно. Не останавливаться после A со словами «основа готова», если поручение охватывает весь документ; продолжать доступные этапы B/C. Внешние blockers описывать конкретно и не маскировать.

## 22. Репозиторий и результаты поставки

```text
kanysh-basic/
  README.md
  pyproject.toml
  uv.lock
  THIRD_PARTY.md
  .env.example
  src/opensubsurface/
    api/
    schemas/
    domain/
    adapters/          # las, gempy, segy, gstools, opm, results
    execution/         # targets, resources, subprocesses, job lifecycle
    workflows/
    persistence/       # metadata/migrations/artifact manifests
    mcp/
    ui/
    viewer/
    cli.py
  tests/
    scientific/
    integration/
    gpu/
    e2e/
  experimental/
    runpod/
      cloud/
      tests/           # marker experimental, отдельный запуск
      deploy/profiles/managed-cloud.json
      docs/
        REMOTE_GPU.md
        CLOUD_OPERATIONS.md
  examples/
    generators/
    templates/
    workflows/
  deploy/
    compose.yaml
    images/
    profiles/
  docs/
    ARCHITECTURE.md
    COMPATIBILITY.md
    SUPPORTED_PROFILES.md
    DATA_CONVENTIONS.md
    ACCEPTANCE.md
    BENCHMARKS.md
    MCP_SETUP.md
    FEATURE_COVERAGE.md
    adr/
```

Структуру можно упростить при сохранении границ. Не создавать пустые абстракции для всех будущих модулей Petrel.

Обязательные deliverables: запускаемое приложение; pinned окружения; synthetic generators; контрольные fixtures; templates; инструкции local/remote и ChatGPT/Claude; acceptance/benchmark reports; список ограничений; exportable demo workflow; reproducible case для прямого OPM запуска.

`FEATURE_COVERAGE.md`: функция Petrel/предметный процесс → заявленный scope v0.2 → компонент → поддерживаемые profiles → acceptance IDs → статус. Статусы `implemented/validated/limited/planned` различаются. Полного паритета с Petrel в документации/маркетинговом demo не заявлять.

## 23. Текущий фокус

MCP server for subsurface modeling + local web viewer. Научные методы и валидация сохраняются. Изменения scope закреплены ADR-003; старые указания на собственный чат, голос и обязательный managed cloud заменены.

## 24. Первичные источники

Публичные источники проверялись при подготовке ТЗ 15.10.2026. Они подтверждают возможности компонентов, а не готовность всей системы. Архитектура, ограничения и приёмочные критерии выше являются проектными требованиями. При реализации проверить закреплённые версии; не переносить старые примеры API на новую версию механически.

- **S1 — GemPy:** [репозиторий](https://github.com/gempy-project/gempy), [backend/GPU/dtype](https://docs.gempy.org/_modules/gempy/core/data/gempy_engine_config.html), [fault API](https://docs.gempy.org/GemPy%20API/gempy.set_is_fault.html).
- **S2 — GSTools:** [официальный репозиторий](https://github.com/GeoStat-Framework/GSTools), [kriging](https://geostat-framework.readthedocs.io/projects/gstools/en/stable/examples/05_kriging/index.html). Вариограммы, kriging и conditioned random fields; проверка конкретного алгоритма остаётся частью реализации.
- **S3 — segyio:** [официальный репозиторий](https://github.com/equinor/segyio). Чтение/запись SEG-Y; границы поддерживаемых файлов фиксируются в SUPPORTED_PROFILES.
- **S4 — OPM:** [Flow](https://opm-project.org/?page_id=19), [reference manuals](https://opm-project.org/?page_id=955), [настройка solver и GPU](https://opm-project.org/?page_id=1798). GPU-страница описывает interface 24.10; использовать актуальное руководство выбранного build и реальные tests.
- **S5 — Results:** [resdata](https://github.com/equinor/resdata), [ResInsight Python API](https://resinsight.org/scripting/pythoninterface/index.html), [summary data](https://resinsight.org/import/eclipsesummarydata/index.html), [XTGeo grids](https://xtgeo.readthedocs.io/en/stable/api-grids.html).
- **S6 — Runpod:** [создание Pod](https://docs.runpod.io/api-reference/pods/POST/pods), [удаление Pod](https://docs.runpod.io/api-reference/pods/DELETE/pods/podId), [storage lifecycle](https://www.runpod.io/blog/where-did-my-files-go-a-straight-guide-to-runpod-storage). Цены, доступность, API-version и жизненный цикл конкретного типа диска проверять при реализации.
- **S7 — Dask:** [worker resources](https://distributed.dask.org/en/stable/resources.html), [TLS](https://distributed.dask.org/en/stable/tls.html).
- **S8 — lasio:** [официальная документация](https://lasio.readthedocs.io/en/latest/). LAS для каротажа, не LiDAR.
- **S11 — MCP:** [официальный Python SDK](https://github.com/modelcontextprotocol/python-sdk), [authorization specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/basic/authorization.mdx).
- **S12 — Внешние клиенты:** [ChatGPT MCP Apps](https://developers.openai.com/plugins/build/chatgpt-ui), [Claude remote MCP connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp). Обязательная базовая интеграция использует tools/results/viewer URLs; встроенный 3D UI отложен.
- **S13 — OPM fixtures:** [opm-data](https://github.com/OPM/opm-data). Проверить лицензию выбранного case и pin commit; repository может не содержать reference results.
- **S14 — Viewer:** [PyVista/trame tutorial](https://tutorial.pyvista.org/tutorial/09_trame/a_getting_started.html), [VTK.js](https://kitware.github.io/vtk-js/docs/).
- **S15 — Предметный ориентир:** [Petrel geology/modeling](https://www.slb.com/products-and-services/delivering-digital-at-scale/software/petrel-subsurface-software/petrel/petrel-geology-and-modeling), [Petrel reservoir engineering](https://www.slb.com/products-and-services/delivering-digital-at-scale/software/petrel-subsurface-software/petrel/petrel-reservoir-engineering).
