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
