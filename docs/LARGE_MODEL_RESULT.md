# Большая модель: фактический контроль PASS

Выполнено 16.10.2026 16:32:49 Asia/Almaty. macOS arm64, CPU, 16 GiB RAM, 10 logical CPUs.

Сетка1024×1024×384: **402,653,184 ячейки**. Входы **18,119,394,176 bytes** (18.119 GB / 16.875 GiB).

Замеренный максимум RSS parent+children: **353.5 MiB**. Полный wall time с подготовкой и cleanup: **124.44s**.
Максимальное замеренное выделение диска в рабочем каталоге: **21.88 GiB**, бюджет60 GiB. Временные данные удалены и отсутствие каталога проверено.

| Этап | Wall time, s | Sampled peak process-tree RSS, MiB |
|---|---:|---:|
| Запись семи NPY файлов | 20.96 | 165.4 |
| Блочный импорт и полный QC свойств | 43.76 | 353.5 |
| Статические объёмы | 22.43 | 320.0 |
| Независимая проверка объёмов и свойств | 33.53 | 314.6 |

| Метрика | Аналитическое значение | Результат | Абсолютная ошибка |
|---|---:|---:|---:|
| GRV | 402653184 | 402653184 | 0 |
| GRV_oil_interval | 201850880 | 201850880 | 0 |
| NetRockVolume | 161480704 | 161480704 | 0 |
| PV | 32296140.8 | 32296140.8 | 7.45e-09 |
| HCPV | 24222105.6 | 24222105.6 | 7.45e-09 |
| STOIIP | 20185088 | 20185088 | 3.73e-09 |

GRV/NetRock/PV/HCPV — m³, STOIIP — standard m³. OWC Z=-192.5m, дробное пересечение слоя; Bo1.2.

**PASS:** analytical volumes, независимая numerical validation, property validation, размер>15GiB, non-sparse input, RSS≤1GiB и disk≤60GiB.

## Что именно проверено

- Семь полностью записанных NPY файлов, с fsync; st_blocks подтверждает реальное выделение диска. Это сумма файлов модели>15GiB, **не один файл>15GiB**. Максимальный отдельный NPY — около3.22GB.
- Snapshot Zarr ZIP: 2,668,518,262 bytes (2.669GB). Чтение/проверка одного ZIP>15GiB этим тестом не покрыты.
- Synthetic uniform Cartesian grid: active1, zone1, phi.2, NTG.8, Sw.25; permeability uniform random90…110mD, seed42. Все402.7M cells обработаны, downsampling не применяется.
- Volume worker и отдельные validators работают через настоящий persistent Service/job engine в изолированных процессах. Это не реальный ChatGPT/Claude client acceptance.
- Для RSS используется20ms ожидание между опросами; фактический интервал включает затраты psutil/сбора metadata и составляет примерно50–55ms на этом стенде. Короткие пики могут быть пропущены; shared pages считаются повторно. OS file cache не входит в RSS процессов.
- Disk peak также sampled; сохранены logical input/output sizes, **не physical device I/O counters**. Тайминги одного прогона не являются гарантией производительности.
- Проверены импорт, QC, один fractional-contact volume и независимые volume/property checks. Scalar uncertainty проверена на меньших fixtures; на этой сетке не запускалась.
- Это CPU Cartesian acceptance: corner-point/native Petrel, GemPy fitting, Windows/WSL, CUDA и реальные полевые модели требуют своей проверки.

## Evidence и повтор

[Raw JSON со всеми SHA-256 и runtime fingerprint](benchmark-large.json). Уменьшенный контроль: [benchmark-large-small.json](benchmark-large-small.json). Внешний SPE10: [отчёт](../examples/reference/spe10model2/results/report.html).

```bash
./.venv/bin/python scripts/benchmark_large.py --output docs/benchmark-large.json
```

По умолчанию временные входы/snapshots удаляются; --keep-data сохраняет их явно.
