> Current accepted workflows are Kanysh Basic. All unimplemented level 2–3 capabilities
> and further modelling development described below belong to Kanysh Advanced; see [ROADMAP](ROADMAP.md).

> Publication update: the accepted A–D/O scope is described in COPILOT_RESULT.md. Norne now uses three strictly distinct EQUIL-derived interior contacts; see [DEMO.md](DEMO.md). Historical results below describe the earlier scope.

# Corner-point, общая сцена и большая сейсмика

Реализован первый рабочий пакет для импорта существующей модели и расчёта через MCP.
Полный паритет с Petrel, нативные `.pet` проекты и полная приёмка v0.2 не заявляются.

## Что проверено

| Возможность | Результат | Граница проверки |
|---|---|---|
| XTGeo GRDECL/EGRID/ROFF | PASS | Три настоящих формата на вращённой аналитической сетке; COORD/ZCORN, ACTNUM, частичное пересечение ВНК |
| Публичная полевая модель Norne | PASS | Все 113 344 ячейки, 44 927 активных; исходные PORO, NTG, PERMX, FIPNUM, 16 регионов |
| Статические объёмы Norne | PASS | Три явно тестовых ВНК, независимое отсечение SciPy ConvexHull и отчёт; не история разработки или утверждённые запасы |
| PyVista + trame | PASS | Настоящие гексаэдры, свойства, траектории, поверхности и сейсмические срезы; HTML с вращением/масштабом, PNG, настройки сцены |
| Большой SEG-Y из папки | PASS | Реальный синтетический файл 269 422 096 байт; все 67 108 864 отсчёта побитово совпали после импорта в float32 Zarr |
| Volve целиком | NOT RUN | Официальная инструкция требует входа в Databricks Marketplace; набор не скачан и не проверен |
| OpenVDS, CPS-3, Petrel well/tops/polygon exchange | PLANNED | Не следуют автоматически из установки xtgeo |

Norne: [источники и SHA-256](../examples/reference/norne/sources.json),
[приёмка](../examples/reference/norne/results/acceptance.json),
[отчёт](../examples/reference/norne/results/report.html),
[интерактивная сцена](../examples/reference/norne/results/scene.html),
[изображение](../examples/reference/norne/results/scene.png).
Данные OPM/Statoil распространяются по ODbL-1.0/DbCL-1.0; лицензия исходного кода приложения Apache-2.0
не меняет условия данных. Исходные уведомления и тексты лицензий сохраняются при скачивании.

## Запуск

```bash
uv sync --frozen --extra viewer --extra solver --group dev
uv run --extra viewer --extra solver python scripts/fetch_norne_reference.py
uv run --extra viewer --extra solver python scripts/test_norne_reference.py
uv run --extra viewer kanysh-basic serve --no-ui --mcp-profile agent
```

Собственная папка подключается владельцем через `kanysh-basic sources add`.
Агент использует `source_scan → source_inspect → grid_import → job_status`;
полученный immutable properties ref передаётся в `calculation_plan → calculation_run`.
Валидация и отчёт входят в этот процесс. Исходная папка после импорта для расчётов не нужна.

Для своей модели есть CLI-помощник `scripts/make_cornerpoint_manifest.py --help`: он собирает
манифест из явно указанных geometry/shape/units/CRS/datum и `--property` / `--constant`, не читая
всю геометрию. Запускайте его на машине импорта; не переносите stat-ревизии между ОС.

Пример corner-point манифеста (пути относительны папке манифеста, ревизии берутся из `source_scan`):

```json
{
  "format": "opensubsurface.cornerpoint.xtgeo.v1",
  "shape": [46, 112, 22],
  "geometry": {"path": "MODEL.EGRID", "format": "egrid", "file_revision": "<64 hex>"},
  "crs": "LOCAL_METRIC",
  "vertical_datum": "<явно указанный datum>",
  "length_unit": "m",
  "z_direction": "down",
  "units": {"active":"boolean", "zones":"zone_id", "phi":"fraction", "ntg":"fraction", "sw":"fraction", "permeability_md":"mD", "kz_ratio":"fraction"},
  "arrays": {
    "zones": {"constant": 1},
    "phi": {"path":"PORO.grdecl", "keyword":"PORO", "file_revision":"<64 hex>"},
    "ntg": {"constant": 0.8},
    "sw": {"constant": 0.25},
    "permeability_md": {"constant": 100},
    "kz_ratio": {"constant": 0.1}
  },
  "assumptions": ["Замените тестовые константы обоснованными входами"]
}
```

Все шесть объявлений свойств обязательны; ACTNUM берётся из геометрии. Файлы свойств содержат
один GRDECL keyword, порядок I-fast/K-down; импорт переводит в канонический C-order без изменения IJK.
Поддерживаются FIPNUM/SATNUM, PORO, NTG, SWAT, PERMX и PERMZ (последний делится на PERMX).
Константы являются явными допущениями. Дефолтные значения из пропущенных данных не придумываются.
Полные DATA decks, INCLUDE/BOX/EDIT, LGR/refinement и dual porosity не поддерживаются;
LGR отклоняется, чтобы не потерять вложенную сетку незаметно. EGRID профиль — unformatted big-endian.

**RAM:** XTGeo читает геометрию целиком. Перед чтением проверяются размерности, лимит 2 млн ячеек,
оценка памяти и доступный диск. Затем геометрия и свойства сохраняются блоками Zarr;
расчёты читают до 16 384 ячеек за раз. Предел 2 млн — ограничение профиля, не результат теста на 2 млн.
Контроль декартовой модели 402,7 млн ячеек / 18,1 ГБ относится к отдельному Cartesian backend.

Для неплоских граней объём определён шестью тетраэдрами вокруг диагонали углов 0–7.
Это явная геометрическая конвенция, которая может отличаться от усреднённого XTGeo precision=2
или других симуляторов. Независимая проверка использует ту же геометрическую конвенцию,
но другой численный алгоритм. Она не доказывает геологическую пригодность модели.

## Общая 3D-сцена

`scene_show` сохраняет ref, visible, opacity, field, selected, stride, cell_range,
vertical_exaggeration, seismic_axis и slice_index. `scene_inspect` возвращает сохранённое состояние.
`scene_export` создаёт immutable `scene.html`, `scene.png`, `scene.json` с хешами входов и настройками.
Выбор объектов и экспорт сцены выполняются через MCP/CLI/REST; UI показывает готовый scene_export HTML.

По умолчанию максимум 100 тыс. отображаемых ячеек; разрешено до 200 тыс. и 500 тыс. дополнительных точек.
Превышение требует явного stride/cell_range. Обычная UI-кнопка явно записывает stride в настройки.
Все расчёты используют полную модель. Для общей сцены используется единый vertical_exaggeration.
TWT не трактуется как глубина: наложение требует явных velocity_m_s и origin_z_m.
Глубинные SEG-Y samples в этом профиле считаются положительной глубиной в метрах; Z = −depth.
Surface points триангулируются для превью; это не построение структурного каркаса и не восстановление
произвольной топологии/дыр импортированной поверхности.

Встроенный trame создаёт HTML для локального браузерного VTK.js рендера. Это ограниченное
клиентское превью, не постоянный server-rendering/LOD streamer огромной сетки. Экспорт работает
в изолированном процессе; HTML отдаётся через существующую защиту API.

## Потоковый SEG-Y

`seismic_source_import` принимает source_id/path/file_revision, CRS/datum/domain/sample_unit,
coordinate_unit и header mapping. Обычный upload по-прежнему ограничен 256 MiB;
новая операция читает разрешённый файл напрямую и делает проверенную рабочую копию.
После импорта копия удаляется, сохраняются SHA-256 и канонический куб.

Два прохода: проверка заголовков и затем запись float32 Zarr плиток без полного куба или таблицы всех
trace headers в RAM. Поддерживаются сортировки inline-major и crossline-major; результат всегда
inline × crossline × sample. Пропуски — явные NaN, дубли/перестановки трасс отклоняются.
Требуются регулярные оси, zero-offset poststack, фиксированный sample count/interval/origin,
IBM/IEEE float32, длиновые XY coordinates; метры/футы объявляются явно и сверяются с binary header.
IBM и чрезвычайно большие файлы требуют отдельного полевого контроля.

Контракт: до 1 TiB файла/куба, 20 млн трасс, 100 тыс. значений на каждой пространственной оси,
200 тыс. amplitude chunks; эти пределы не являются результатом стресс-теста на 1 TiB.
Нужен диск для исходной рабочей копии, результата и immutable публикации; сжатие не предполагается заранее.
Срез ограничен 4 млн отсчётов до чтения, атрибуты — 50 млн отсчётов куба;
превышение возвращает ошибку до загрузки большого массива. У потребителей есть отдельные ограничения;
импорт большого куба сам по себе не делает любые downstream операции ограниченными по RAM.

Доказательство: [benchmark-seismic.json](benchmark-seismic.json), воспроизведение —
`python scripts/benchmark_seismic.py`. Импорт 269,4 МБ: около 3,5 с, sampled peak process-tree RSS
около 402.5 МиБ на текущем CPU стенде; буфер амплитуд 2 МиБ. Время и RSS зависят от машины;
RSS не включает OS file cache и может пропустить короткие пики. Временные данные удалены.

## Следующие этапы

1. **Volve:** получить доступный экспорт через [официальный канал Equinor](https://www.equinor.com/energy/volve-data-sharing),
   закрепить перечень/лицензии/хеши, проверить один полный grid+properties и согласованный сейсмический куб.
   До этой проверки «Volve целиком» не заявляется.
2. **Petrel exchange:** IRAP binary/ASCII и ZMAP surface roundtrip, RMS/ASCII wells, tops/polygons;
   CPS-3 отдельно — в текущем API xtgeo этот формат поверхностей не заявлен.
3. **Геомоделирование:** интерактивный picking и автотрекинг с контрольными горизонтами;
   multi-horizon/multi-fault fixtures и pillar grid; log blocking; SIS/объектные/MPS реализации,
   тренды и многомерное моделирование свойств; корреляционный планшет.
   Наличие GSTools/MPSlib не означает готовой реализации каждого из этих методов.
4. **Динамика:** pinned Linux OPM Flow, SPE1/Norne end-to-end и материальный баланс;
   затем ES-MDA/ансамбли с независимым линейным контрольным примером, constraints и validation holdout.
5. **Масштабирование:** server-side LOD, произвольный порядок SEG-Y через внешнюю сортировку,
   OpenVDS после отдельного профиля корректности/лицензии/производительности; remote workers/S3,
   облачные ансамбли и GPU после проверки вычислительного ядра на соответствующем стенде.

Windows + NVIDIA/WSL2 остаётся пользовательской проверкой; текущая приёмка выполнена на macOS CPU.

Проверки кода: полный регрессионный прогон113 PASS /2 CUDA SKIP; заключительные13 проверок — PASS; доказательства
новых ограничений/общей сцены и форматов записаны отдельно в [test-results-scene-seismic.xml](test-results-scene-seismic.xml).

Официальная [инструкция Equinor по доступу](https://equinoropendata.blob.core.windows.net/userguides/Equinor%20open%20data%20-%20User%20Guide.pdf) предусматривает login/sign-up и получение набора в каталоге Databricks.
