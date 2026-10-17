# Единицы, координаты и численные соглашения

- Каноническая геология: `(nx, ny, nz)`, `indexing=ij`, Z возрастает вверх; XYZ в метрах.
- Extent: `[xmin,xmax,ymin,ymax,zmin,zmax]`. Centers = min + (index+0.5)×spacing.
- CRS — projected metric EPSG/WKT или явно `LOCAL_METRIC`. Datum обязателен.
  Разные CRS/datum входа и проекта блокируются; автоматического datum transform нет.
- CSV length values преобразуются Pint в m. MD строго возрастает по скважине.
  Markers интерполируются по XYZ/MD trajectory в её диапазоне, без extrapolation.
- LAS nulls остаются NaN; глубина требует явной единицы, рекомендуемый mapping `DEPT:m`.
  Кривые не получают автоматической петрофизической интерпретации.
- Пористость/NTG/Sw в [0,1]; K в mD и ≥0; positive Bo. Missing active values блокируют volumes.
- Объём ячейки dx×dy×dz. Reservoir zone membership по центру; пересечение горизонтального
  OWC дробное: `clip((z_top-contact_z)/dz,0,1)`.
- `STOIIP=sum(V*f*NTG*phi*(1-Sw))/Bo`, standard_m3. K не участвует в статической формуле.
- Scalar sample table создаётся CPU RNG с seed, затем те же samples используются CPU/CUDA.
  Квантили NumPy `method=linear`; `P90=Q10`, `P50=Q50`, `P10=Q90`.
- Сейсмический TWT хранится в s, глубина в m, это разные domain. Z=origin−velocity×TWT/2.
  Табличный профиль: строго монотонные TWT(s)/depth_difference(m), piecewise linear,
  без extrapolation. Time picks не передаются в глубинную модель без явного transform.
- RMS: centered odd window, nearest boundary. Envelope: Hilbert/FFT по полной sample-axis.
  Любой missing sample маскирует всю trace. Это консервативная declared mask policy.
- GSTools exact Exponential, nugget=0; phi logit, K log (>0). No clipping. Геометрическая
  анизотропия задаётся двумя положительными ratios; модель отдельно по зоне. phi/K независимы.
- OPM: I fastest, затем J, K сверху вниз. `to_opm = a[:,:,::-1].ravel(order='F')`.
  Z-up→depth-down: depth=−Z при общем datum=0. GridMapping содержит обе нумерации и centers.
  NTG отдельный keyword; PORO — net-rock, не PORO×NTG.
- Generated deck METRIC; density kg/m³; viscosity cP; K mD; pressure **absolute bar**;
  rates surface m³/day. Формирование real PVT неизвестных данных запрещено: текущий exporter
  требует явного принятия synthetic demo template.
- STCOND записан явно: по умолчанию 15.56°C / 1.01325 bara; в series сохраняются K/Pa.
  Разные термодинамические standard conditions блокируют comparison; перевод STB→м³
  не заменяет PVT-пересчёт при разных условиях.
- OPM explicit pressure/sw initialization — development профиль, ещё без conservation acceptance.
  No-flow hydrostatic approximation не доказывает равновесие solver.
- Water cut=surface water/(oil+water); zero liquid → undefined (JSON null).
- Series: timezone-aware даты, UTC canonical output, strictly increasing timestamps; rates
  выравниваются предыдущим значением, cumulatives/pressure — линейно между соседними отсчётами.
  Нет extrapolation или интерполяции через null. Water cut вычисляется после alignment rates.
- Comparison использует общую календарную область, явный report_at или её конец. Частичный
  ensemble требует allow_partial=true; total/completed/excluded и sample_count видны в отчёте.
  Pointwise Q50 не называется одной физической realization; representative case — реальный case.
- Component balance поддержан только для constant-FVF oil-water/incompressible-rock профиля:
  residual=(stock−stock0+production_delta−injection_delta)/max(abs(stock0),abs(production_delta),
  abs(injection_delta),floor). Все слагаемые одной компоненты имеют одинаковые standard units.
  Отдельно проверяется no-flow pressure drift. Compressible profile возвращает unsupported,
  недостающие vectors — NOT RUN. Аналитические тесты не доказывают conservation настоящего Flow.

Допуски scientific fixtures сохранены из ТЗ: volumes float64 rel≤1e−8; time-depth atol1e−15;
conditioning abs≤1e−6 scale; attributes CPU/CUDA atol1e−8/rtol1e−6.
GPU fixtures пропускаются явно, если CUDA отсутствует; MPS не подменяет NVIDIA CUDA.
