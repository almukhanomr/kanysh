> Historical implementation record. Current Kanysh Basic publication evidence: [PUBLICATION](PUBLICATION.md) and [Norne demo](DEMO.md). Obsolete pre-MCP viewer screenshots are not published.

# MCP-first: результат проверки

17 октября 2026, macOS arm64, Python 3.12.14, CPU.

Основной продукт — MCP server for subsurface modeling + local web viewer.
Расчёты запускаются через MCP, CLI или REST. Собственный чат, ASR и зависимости
OpenAI/Anthropic/faster-whisper удалены. A-10 заменён MCP-клиентами и исключён
из обязательной приёмки. Runpod находится в experimental/runpod; пакет и MCP
его не загружают.

| Проверка | Результат | Доказательство |
|---|---|---|
| Полная регрессия | 116 passed, 2 CUDA skipped; 389.91 s | [XML](test-results.xml) |
| Runpod отдельно | 4 passed, marker experimental; внешние вызовы замоканы | Historical local experiment; excluded from Basic publication |
| Wheel и sdist | Нет experimental/LLM/ASR; Gradio/Plotly только в ui extra | [JSON](distribution-check.json) |
| Чистая установка wheel без UI | Headless API, 59 MCP tools без cloud, аналитический CPU расчёт и offline Norne PASS | [JSON](core-install-check.json) |
| Новый расчёт полевого Norne через HTTP MCP SDK | Независимая numerical validation PASS; ссылки scene/report HTTP 200; типизированные refs сохранены | [JSON](mcp-viewer-control.json) |
| Браузер | Сцена Norne и отчёт отображаются на страницах просмотрщика | Historical screenshots retired; [current viewer](copilot-viewer.png) |

Просмотрщик содержит проекты/ревизии, сохранённые отчёты и scene_export HTML,
сейсмические срезы, загрузку файлов и кнопку «Open Norne demo».
Открытие демо не запускает скачивание или научные задания. Public Norne bundle
включён в wheel с уведомлениями ODbL/DbCL и происхождением Statoil/OPM.

Активный просмотрщик публикует адрес для MCP-процессов с тем же каталогом состояния.
MCP добавляет viewer_url и viewer_links к отчётам и сценам; ссылки ведут на страницы
просмотрщика, не содержат токены и не меняют ссылки на ревизии. Без просмотрщика
MCP работает с артефактами/resources без viewer URL. Страницы используют общую
Host/Origin/token/session защиту; HTML артефактов изолирован iframe sandbox/CSP.

Перенесённые cloud_* tools доступны только при явном запуске отдельного stdio MCP
из experimental/runpod. Они отсутствуют в основном registry; эксперимент не входит
в wheel/sdist. Установка budget policy через tools не разрешена, private bootstrap gate
проверяется и в экспериментальном MCP.

Численный PASS относится к явным тестовым контактам и допущениям Norne,
а не к оценке запасов месторождения. Подключение настоящих ChatGPT/Claude,
Windows/NVIDIA и OPM Flow end-to-end пока не проверены. Большой Cartesian контроль
18.1 GB и потоковый SEG-Y контроль описаны отдельно в [PETREL_WORKFLOW.md](PETREL_WORKFLOW.md);
они не доказывают поддержку corner-point моделей такого же размера.
