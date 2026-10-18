# Benchmarks

Фактический отчёт: `benchmark-cpu.json` (UTC timestamp внутри), 15 октября 2026, macOS arm64,
16 GiB, 10 logical CPUs, Python 3.12.14, NumPy 2.5.4, float64.

| Сетка | Ячеек | Подготовка | Вычисление | Full kernel wall | STOIIP relative error |
|---|---:|---:|---:|---:|---:|
| 50×50×30 | 75 000 | 0.00027 с | 0.00505 с | 0.00533 с | 1.16e−16 |
| 100×100×100 | 1 000 000 | 0.00416 с | 0.04022 с | 0.04438 с | 2.33e−16 |

Это измерения **только NumPy static-volume kernel** с подготовкой массивов, не всей платформы,
не GemPy, не cold start Python, не OPM. Process RSS во втором профиле ~295 MB, не peak RAM.
Один запуск не является статистически устойчивой оценкой производительности.

Повтор: `uv run kanysh-basic benchmark`. Отчёт включает hardware, package version, grid,
precision, preparation/compute/full timings и error против аналитических 2e6 standard_m3.
200×200×100, CUDA, remote, synthetic seismic performance, OPM small/medium — NOT RUN.
Никаких заявлений об ускорении GPU или полной производительности solver пока нет.

## Блочный Cartesian профиль

[benchmark-large-small.json](benchmark-large-small.json): реальный полный input из 7 NPY файлов,
8 388 608 cells, 377 488 256 bytes; import+QC, fractional OWC, independent volume/property checks PASS.
RSS (parent+children, sample20ms): peak457 670 656 bytes (~436.5MiB). Модель не downsampled,
permeability seeded random, другие свойства аналитически постоянны; данные/temporary snapshots удалены.
Тайминги справочные, прогон мог совпадать с полной регрессией. Это уменьшенный контроль,
**не evidence файлов >15GiB**. Отдельный полный контроль теперь выполнен: [результат](LARGE_MODEL_RESULT.md).
Форматы, команды, память и ограничения: [LARGE_MODELS](LARGE_MODELS.md).

## Полный raw-модель>15GiB контроль

[Raw JSON](benchmark-large.json): 402 653 184 cells, семь non-sparse NPY файлов,
18 119 394 176 bytes input (16.875GiB), sampled max process-tree RSS353.5MiB.
Import+QC43.76s, volume22.43s, independent volume+property validation33.53s;
полный wall124.44s. Disk peak21.88GiB, temporary data removed.
Все численные, integrity/physical, memory/size/disk controls PASS.
Это synthetic Cartesian CPU профиль; модель состоит из семи файлов, snapshot ZIP2.669GB.
Один input/ZIP>15GiB, CUDA, corner-point/Petrel native и полевые geometry-fitting задачи не проверены.
Метод измерения, допущения и ограничения: [LARGE_MODEL_RESULT](LARGE_MODEL_RESULT.md).

## Масштабирование corner-point, 18 октября 2026

Windows 11 build 26300, Python 3.12.14, 64 GB установленной RAM
(67 927 195 648 bytes видимы ОС), 8 физических / 16 логических ядер,
NVIDIA RTX 3080 Ti Laptop, 16 GB VRAM. Это фактически доступный ноутбук;
проверка на 16 **физических** ядрах или Linux не выполнялась.
Пулы CPU: 8 процессов после изменений, один процесс в исходной версии.
До — код HEAD `98dd32863c39ae57a41eca3404c81f9d105c201c`, извлечённый `git archive`, после — текущие исходники;
точные SHA256 кода и генератора записаны в JSON. Коммитов для замеров не создавалось.

Каждый размер — отдельный процесс и настоящая DATA/COORD/ZCORN модель:
смещённые пиллары, pinch-out, три скрученные ячейки, пять регионов, OWC через
10% обычных ячеек. GRV и STOIIP сверяются с рациональными аналитическими ожиданиями.
Выбранные `exclude_flagged` и `parameters_confirmed=true` явно отражены в результатах:
региональные результаты имеют `PASS_WITH_EXCLUSIONS`, ровно три исключения на сценарий.
QC ожидаемо сообщает `ISSUES`, его integrity validation проходит. Полный calculation_run
использует явно выбранные чистые зоны 2–5. Scene — явный preview `[100,1000)`, stride=1;
объёмные расчёты используют все ячейки выбранных регионов.

RSS — sampled peak суммы RSS координатора и его дочерних процессов, интервал 100 мс,
GiB=2^30 bytes. Общие страницы могут учитываться несколько раз. Это один запуск
на размер, часть замеров выполнялась одновременно с другими проверками и конкурировала
за CPU/диск. Значения характеризуют этот прогон и не являются гарантированным throughput.

### Независимая проверка и Norne

| Профиль, CPU max_workers=1 | До, с / peak GiB | После, с / peak GiB |
|---|---:|---:|
| Независимый интеграл, 113 000 ячеек | 102,770 / 0,186 | 0,361 / 0,173 |
| Norne regional_volumes, 113 344 ячейки, 44 927 активных | 28,329 / 0,153 | 2,877 / 0,153 |

Источники: [integral до](benchmark-scaling-reference-before.json),
[после](benchmark-scaling-reference-after.json), [Norne до](benchmark-scaling-norne-before.json),
[после](benchmark-scaling-norne-after.json). В Norne один явно исключённый дефект;
результат остаётся `PASS_WITH_EXCLUSIONS`, STOIIP до/после одинаков.
[Профиль исходной версии](benchmark-scaling-norne-before-profile.json) зарегистрировал
16 626 вызовов `mkstemp`, cumulative 24,94 с из полного профилированного прогона 33,23 с.
После изменений независимый интеграл не вызывает Qhull и не создаёт его временные файлы.
[Актуальный cProfile](benchmark-scaling-profile-after.json) содержит стадии полного
прогона на 100 000 ячеек и top cumulative, с включённой стоимостью профилирования.

[Norne CUDA](benchmark-scaling-norne-cuda.json): 11,575 с / 0,999 GiB, включая холодный
запуск Torch/CUDA и обязательную CPU-сверку. На этом профиле CUDA **медленнее CPU**;
ускорение полного расчёта на GPU не заявляется. Это проверка численного соответствия.

### Границы доказательств и NOT RUN

* Исходные большие прогоны явно выбрали `--stages generate import model_qc`.
  Старые regional 1/5, tornado, calculation_run и scene для 10/50/100 млн — `NOT RUN`:
  полные профили этих стадий исходной версии не запускались. Нельзя подменять их
  экстраполяцией измерений Norne или выдавать общий полный baseline за PASS.
* Пять сценариев в большом профиле имеют одинаковые OWC и свойства, отдельные имена
  и редукции. Измеряется повторное использование геометрии. Performance пяти разных
  уровней контакта — `NOT RUN`; корректность разных контактов покрывают тесты.
* Большой полевой EGRID/INIT и GPU 10–200 млн — `NOT RUN`: в окружении нет большого
  полевого набора; большой synthetic профиль измеряет ASCII CPU. Бинарная корректность
  проверена на обоих endian, INIT active/full, GRDECL и настоящем EGRID, созданном XTGeo;
  во время потокового импорта вызов XTGeo запрещён тестом.
* Linux, OPM и внешние сервисы в этой Windows-сессии не запускались. Полный CPU-набор
  использует оговорённые маркеры `not gpu and not opm and not external`.
* Разработческие JSON `after-*` (кроме отдельно указанного 200 млн), `final-*`,
  `verified-*`, `import-*`, `batched-*` сохранены как промежуточные измерения.
  Название `final` не означает успешную приёмку: там есть FAIL Windows Queue/WinError6.
  Общая Queue заменена отдельными Pipe; приёмочные повторные прогоны имеют имя `pipe-*`.
  Ошибка процесса не маскируется повторным запуском или сменой численного алгоритма.

Реализация и команды: [SCALING.md](SCALING.md). Автоматические отчёты тестов:
[CPU](test-results-scaling.xml), [CUDA](test-results-scaling-gpu.xml).
CPU: **211 passed, 13 skipped**; CUDA: **10 passed, 1 skipped**.
После последней правки освобождения mmap отдельно повторены import/scaling-тесты:
25 passed, 4 skipped, 1 deselected. CPU-пропуски: права создания Windows symlink,
Linux-only OPM preflight, CUDA-only fallback на хосте с CUDA и необязательный внешний
Norne deck. Общий collection skip относится к исключённым экспериментальным тестам.
