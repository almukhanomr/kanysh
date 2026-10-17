# Большие модели: локальный блочный профиль

Реализованы импорт готовой **равномерной декартовой сетки**, проверка свойств,
статические объёмы, seeded scalar uncertainty и независимая проверка по блокам.
Данные хранятся в immutable Zarr ZIP, Python worker читает ограниченный блок.
Полный массив XYZ, полная распаковка свойств и копия всей модели на каждый сценарий не создаются.
План, jobs, cancel/resume, hashes и HTML/JSON/CSV/PNG отчёт используют существующий MCP workflow.

## Границы профиля

| Возможность | Поддержка |
|---|---|
| Размер готовой сетки | До 2 млрд ячеек по контракту, до 1 млн по отдельной оси; фактическая возможность зависит от диска/времени |
| Рабочий блок | 1 024–1 048 576 ячеек, default 262 144; максимум 10 000 chunks на массив |
| NumPy | 7 отдельных NPY v1/v2, без object/pickle, C-order (x,y,z), Z вверх; float32/64 принимаются, накопление float64 |
| ECLIPSE/Petrel exchange | Потоковые **раздельные GRDECL таблицы свойств** при явно объявленной равномерной декартовой геометрии |
| Геометрия COORD/ZCORN, EGRID/INIT, native Petrel project, LGR, faults/pinch-outs | Этот большой профиль не импортирует их; подмена геометрии bounding box запрещена |
| GemPy fit/build | Прежний отдельный путь ≤4 млн ячеек; out-of-core fitting не реализован |
| Вычисления | CPU; require_gpu для этого профиля отклоняется, NVIDIA acceptance отдельно |
| Storage/target | Локальная разрешённая папка; S3 и remote workers пока отсутствуют |

Декартовы свойства из Petrel/ECLIPSE можно использовать только если исходная геометрия
соответствует объявленным shape/extent. Если модель corner-point, нужен отдельный геометрический
адаптер или явное инженерное преобразование с контролем объёмов; этот импорт его не выполняет.
Наличие большого файла в source inventory не означает поддержку его формата.

## Разрешённая папка и manifest

Команды из корня проекта, в установленном Python3.12 environment. На Windows выполнять
внутри WSL2. Создавайте manifest на том же хосте/файловой системе, где работает importer:
file_revision включает inode/device/size/mtime/ctime и не переносится между Windows/WSL как hash.

### NumPy

В папке нужны active.npy, zones.npy, phi.npy, ntg.npy, sw.npy, permeability_md.npy, kz_ratio.npy.
Они имеют shape `(nx,ny,nz)` либо flat C order длины nx*ny*nz; последняя ось Z возрастает вверх.
active: bool/0–1; zones: positive integer для активных ячеек. Свойства: phi/NTG/Sw 0…1,
permeability ≥0 mD, 0<kz_ratio≤1. NaN допустимы только вне active.

Пример команды для уже существующих массивов (extent задаёт пользователь):

```bash
./.venv/bin/python scripts/make_grid_manifest.py /path/to/arrays \
  --shape 1024 1024 384 --extent 0 1024 0 1024 -384 0 \
  --crs LOCAL_METRIC --datum FIELD_DATUM
./.venv/bin/kanysh-basic --home .data source-add field-a /path/to/arrays
```

Скрипт читает headers и metadata, не загружает массивы. Он создаёт model.json с единицами,
grid, относительными путями и file_revision каждого файла. Существующий manifest не перезаписывает.
Если входы изменились, создайте новый manifest (`--filename model-v2.json`) и повторите импорт.

### Раздельные свойства GRDECL из ECLIPSE/Petrel

Подготовьте один keyword на файл: ACTNUM.grdecl, FIPNUM.grdecl (zone IDs), PORO.grdecl,
NTG.grdecl, SWAT.grdecl, PERMX.grdecl, PERMZ.grdecl.
Для zones можно явно указать SATNUM вместо FIPNUM в manifest.
PERMZ/PERMX преобразуется в kz_ratio; активные ячейки с неопределённым отношением или
отношением >1 отклоняются данным профилем. Проницаемость в mD, насыщенность и пористость — доли.

Пример при явно принятой геометрии и явных константах для отсутствующих свойств:

```bash
./.venv/bin/python scripts/make_grid_manifest.py /path/to/export \
  --format grdecl --shape 100 120 80 --extent 0 1000 0 1200 -1800 -1000 \
  --crs LOCAL_METRIC --datum FIELD_DATUM \
  --cartesian-basis 'Экспортирована равномерная Cartesian grid; extent и объём проверены геологом' \
  --constant active=1 --constant zones=1 --constant ntg=0.8 \
  --constant sw=0.25 --constant kz_ratio=0.1
```

В этом примере нужны только PORO.grdecl и PERMX.grdecl. Примерные константы не являются
рекомендацией для месторождения; они сохраняются в manifest и требуют обоснования пользователя.
Без --constant соответствующий файл обязателен. Никаких скрытых NTG/Sw/zone defaults нет.

Парсер поддерживает `--` comments, numeric tokens, D/E exponents, `N*value` repeats и `/` terminator.
Число значений каждого массива должно точно равняться nx*ny*nz. Default syntax `N*`, INCLUDE,
BOX/EDIT/EQUALS, дополнительные keywords, COORD/ZCORN и полные DATA decks отклоняются.
Одна строка ≤64 KiB, токен ≤128 bytes. RLE разворачивается прямо в ограниченный numeric buffer.
Свойства сохраняют ECLIPSE порядок I-fast, J-next, K-down; расчёт и независимый validator
учитывают этот порядок без полной транспозиции. Внутренние координаты/контакты остаются Z вверх.

Формат выбран по [OPM PORO](https://opm.github.io/opm-flow-editor-support/keywords/PORO.html)
и [GRDECL conventions от разработчика Cirrus](https://docs.opengosim.com/cirrus/manual/input_deck/grid/grdecl.html).
Это узкий импорт таблиц, а не реализация полного языка ECLIPSE.

## Работа через MCP

Запуск: `kanysh-basic --home .data serve --no-ui --mcp-profile agent --port 8765`.
Agent profile содержит 18 tools. Все arguments имеют оболочку `{"request":{...}}`.

1. source_list → source_scan: выбрать model.json и его file_revision.
2. source_inspect: проверить format, grid, units, headers и input_bytes; numerical jobs ещё не запускаются.
3. grid_import: project_id, source_id, path=model.json, file_revision, block_cells=262144.
   Дождаться job_status=succeeded; result — immutable properties ref.
4. calculation_plan: передать properties:{id,revision}, zone_ids, Bo, contacts, assumptions,
   при необходимости uncertainty. **grid/method/zones/CSV inputs здесь не передавать**:
   геометрия и свойства уже закреплены импортом.
5. plan_validate → calculation_run → calculation_status → result_preview.

Пример plan request после импорта:

```json
{
  "request": {
    "project_id": "PROJECT_ID",
    "properties": {"id": "PROPERTIES_ID", "revision": 1},
    "zone_ids": [1],
    "bo": 1.2,
    "contacts": [{"name": "OWC variant", "z_m": -1500}],
    "assumptions": ["Указать реальные основания геометрии, свойств и контакта"]
  }
}
```

Числа в примере требуют замены данными проекта. Исходный source после успешного grid_import
можно отозвать: расчёты используют самостоятельный snapshot, включая SHA-256 всех исходных файлов
и manifest. Для явных констант сохраняется hash декларации, а не вымышленного исходного файла.
Project ZIP содержит snapshot; обычный ZIP importer пока ограничен 512 MiB распакованного содержимого.
Для больших durable stores использовать owner backup/restore каталога состояния, с запасом диска.
Source registrations/credentials в project ZIP не входят.

## RAM, диск и время

Рабочие массивы зависят от block_cells, а не от полного nx*ny*nz. Оценка block buffers —
192 bytes/cell; runtime библиотек и ограниченный ZIP index добавляют собственную память.
Это оценка буферов, не обещание общего RSS. Импорт проверяет доступную RAM и место для
attempt output + immutable publication без предположения о коэффициенте сжатия.
Для очень большого числа chunks увеличить block_cells: лимит metadata не снимается автоматически.

Независимая проверка использует отдельную interval-overlap integration и компенсированное
суммирование, без вызова рабочего volume kernel. Hash checks и QC читают все данные;
проверка/несколько независимых jobs потребуют дополнительных проходов по диску.
Scalar uncertainty считает все realizations в одном проходе, но время арифметики растёт с их числом.
Отмена/timeout останавливают изолированный worker process group. Уже прочитанный поток внутри
одного import job не возобновляется с середины; workflow resume сохраняет завершённые узлы.

## Воспроизводимый большой контроль

```bash
./.venv/bin/python scripts/benchmark_large.py --output docs/benchmark-large.json
```

Default: shape1024×1024×384, 402 653 184 cells, семь реальных NPY файлов суммарно
18 119 393 280 bytes плюс headers (>15 GiB). Они полностью записываются и fsync выполняется;
это не sparse files и не расчёт по выборке. Проницаемость имеет seeded случайные значения,
остальные свойства постоянны для независимого аналитического контроля объёмов.

Benchmark выполняет import+QC, fractional-contact volumes, independent volume validation и
отдельную property validation. Каждые 20ms измеряет сумму RSS процесса и его children
(shared pages могут учитываться повторно), фиксирует время и logical input/output sizes.
Это не физические device I/O counters. По умолчанию критерий пикового RSS — 1 GiB.
Маленький --shape помечается SMALL_CONTROL_ONLY и не подтверждает >15 GiB.
Временные входы и snapshots удаляются после проверки; --keep-data сохраняет их явно.
Для default нужен запас диска около 60 GiB под реальные входы и худший случай публикации.

Полный >15 GiB CPU Cartesian контроль — **PASS**: 402 653 184 cells,
18 119 394 176 bytes input (16.875 GiB), sampled peak process-tree RSS 353.5 MiB.
Импорт+QC43.76s, объёмы22.43s, independent volume/property validation33.53s;
полный wall с созданием файлов и cleanup124.44s. Sampled disk peak 21.88GiB; временные данные удалены.
[Результаты и точные границы проверки](LARGE_MODEL_RESULT.md) · [raw JSON](benchmark-large.json).
Это сумма семи NPY файлов, не один файл>15GiB; ZIP snapshot2.669GB.
RSS не включает OS file cache;20ms — пауза между опросами, фактический интервал с overhead около50–55ms.
Уменьшенный контроль: [benchmark-large-small.json](benchmark-large-small.json), 8.4M cells / RSS436.5MiB.
Тайминги отдельных прогонов справочные; состав входов влияет на сжатие, а нагрузка ОС — на RSS и время.
Тесты mapping/physical QC/GRDECL/revocation/corruption: [test-results-large.xml](test-results-large.xml).
Windows/WSL2, CUDA, произвольные полевые datasets и corner-point geometry этим CPU benchmark не подтверждаются.


## Сквозной GRDECL MCP пример

[examples/cartesian-grdecl](../examples/cartesian-grdecl/README.md) содержит собственные synthetic PORO/PERMX.
После создания manifest и source регистрации выполните:
`./.venv/bin/python scripts/demo_large_mcp.py --source-id SOURCE_ID`.
Скрипт работает только с указанной synthetic geometry и сохраняет отчёт в
examples/cartesian-grdecl/generated. Это проверка MCP SDK, не реального ChatGPT/Claude.


## Открытые входные файлы из Интернета

Помимо собственных synthetic fixtures выполнен полный статический контроль на опубликованных
[OPM SPE10 model2](../examples/reference/spe10model2/README.md): 1 122 000 cells,
77 267 536 bytes downloaded including licenses, original porosity/permeability preserved.
Import/property QC/independent volume checks and source-porosity layer-sum comparison — PASS.
[Actual report](../examples/reference/spe10model2/results/report.html).
NTG1, Sw.2, Bo1 заданы явно для численного контроля; это не оригинальный динамический прогноз.
Это внешний benchmark, не полевая модель; Norne теперь проверен отдельным XTGeo corner-point адаптером: [полевой контроль](PETREL_WORKFLOW.md).
Проверку файлов>15GiB этот запуск не заменяет.

## Corner-point и сейсмика

См. [PETREL_WORKFLOW](PETREL_WORKFLOW.md): отдельный corner-point RAM import + chunked tetrahedral volumes,
Norne и новый прямой SEG-Y source import. Cartesian benchmark выше не подтверждает масштабы этих адаптеров.
