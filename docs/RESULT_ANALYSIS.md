> MCP-first: научные операции этого документа выполняются через MCP/CLI/REST; UI содержит только просмотр готовых артефактов.

# Анализ расчётных результатов

Сохранённый simulation_result доступен через `simulation_results` / `artifact_inspect` и REST.
Просмотрщик показывает его происхождение и файлы; расчёт/сравнение запускаются через MCP/CLI/REST.
Результаты настоящего solver появляются только после успешного simulation_submit. На текущем
macOS стенде Flow не установлен; статическое демо Norne не содержит динамического прогноза.

## Сравнение и ограничения

Выберите несколько результатов или один ensemble. По умолчанию partial ensemble отклоняется;
явное allow_partial разрешает анализ завершённых cases с сохранением total/completed/excluded.
Сравнение использует общую календарную область, единицы и одинаковые standard conditions.
Даты задаются с timezone. Rates используют previous hold, cumulatives/pressure — линейную
интерполяцию соседних отсчётов; extrapolation и заполнение null gaps запрещены.

Пример тела `POST /api/v1/operations/simulation_compare`:

```json
{
  "project_id": "PROJECT_ID",
  "results": [{"id": "RESULT_A", "revision": 1}, {"id": "RESULT_B", "revision": 1}],
  "metric": "FOPT",
  "report_at": "2026-07-01T00:00:00+00:00"
}
```

Analysis artifact содержит analysis.json и analysis.csv с pointwise Q10/Q50/Q90,
P90/P50/P10 и sample counts. Bands — статистика по каждой дате; pointwise Q50 не обязательно
совпадает с одним case. Отдельно указан реальный representative case около медианы.
Компактный tool response содержит ref, summary и ranking; полные arrays остаются в файлах.

`development_rank` ранжирует максимум 10 уже рассчитанных явно выбранных результатов.
Это не автоматический поиск новых schedules и не заявление global optimum. Дополните запрос:

```json
{
  "direction": "maximize",
  "constraints": [{"metric": "WATER_CUT", "unit": "fraction", "maximum": 0.8}]
}
```

Ограничения проверяются на том же report_at; feasible cases стоят перед infeasible.
`simulation_snapshot` принимает result ref, report_index, field (pressure/sw/so/sg),
axis и index; возвращает обычный job. `job_logs` показывает ограниченный хвост журнала,
а failed job может ссылаться на diagnostics artifact. Такой artifact не является прогнозом.

## Ансамбль и повторный запуск

`ensemble_plan`/`ensemble_run` получают property_realizations, schedules и подтверждённый
expected_case_count. Сохраняются все сочетания до запуска, seed, входные hashes и child job IDs.
При partial failure job остаётся failed, а result указывает на partial ensemble snapshot.
Для resume передайте прежний запрос и resume_ensemble с ref этого snapshot.
Успешные результаты и подготовленные cases переиспользуются только при проверке целостности
и совпадении inputs, source, library versions/resdata и Flow SHA-256. Остальные cases запускаются снова.

## Проверки и пределы доказательств

- `tests/scientific/test_results.py`: независимые аналитические fixtures alignment, units,
  nulls, Q/P, counts, bounds и component balance.
- `tests/integration/test_resdata.py`: native Summary writer/reader, asymmetric canonical Zarr
  snapshot и искусственный binary EGRID/INIT/two-report UNRST fixture. Отдельный resfo writer
  задаёт keyword arrays; проверяются IJK, pressure/sw/so, даты, inactive restoration и отказ
  при ACTNUM mismatch. Эти файлы не являются выводом solver.
- `tests/integration/test_ensemble_resume.py`: три реальные property artifacts × два реальных
  exporters, injected solver failures и resume; solver в этом тесте явно заменён test double.
- Текущий просмотрщик показывает immutable reports/scenes и метаданные. Прежний интерактивный simulation-workbench удалён; расчёт и анализ вызываются через MCP/CLI/REST.

Native Flow no-flow/waterflood, conservation, solver CPU/GPU equivalence и ResInsight остаются NOT RUN.
Поддержанный аналитикой набор: field rates/cumulatives, FPR, WBHP и water cut; полные per-well
rates/completions, arbitrary PVT и 3-phase import требуют расширения. Component QC выполняется
только для fresh explicit constant-FVF oil-water/incompressible-rock профиля.
