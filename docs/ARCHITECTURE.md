# Архитектура MCP-first

```text
External MCP client / CLI / REST
           ↓ typed operations
Application Service → immutable Store / jobs / workflows
           ↓ isolated worker
XTGeo / GemPy / GSTools / NumPy / segyio / OPM adapters
           ↓ validation + artifacts
MCP results/resources → optional local web viewer
```

Просмотрщик потребляет готовые данные: проекты/ревизии, отчёты, сцены, срезы, загрузка файлов
и сохранённый Norne. Он не отправляет научные задания. Core не импортирует Gradio/Plotly;
они находятся в extra `[ui]`.

Service использует Dask/inproc и отдельные worker-процессы. Входы immutable, окружение ограничено,
таймаут/отмена завершают группу процессов. FAIL/INCOMPLETE сохраняют evidence и partial reports.
Store: SQLite WAL/SQLAlchemy/Alembic, SHA-256 blobs и manifests, атомарная публикация, revisions,
backup/import/export. Воспроизводимость включает входы, параметры и runtime fingerprint.
Все каналы вызывают один Service; MCP не предоставляет arbitrary shell/Python/SQL.

`serve` запускает loopback API/MCP. `serve --ui` добавляет Gradio и стабильные viewer pages.
Просмотрщик регистрирует origin, PID и время создания процесса в общем Store. Отдельный stdio
MCP-клиент того же каталога состояния может найти просмотрщик; мёртвый PID или закрытый lifespan
не дают ссылок. URLs добавляются только на границе MCP, не в immutable manifests и не внутрь typed refs.

Host/Origin guard, bearer token и SameSite session защищают API, MCP, страницы и очередь UI.
HTML артефактов отображается в sandbox без same-origin capabilities; токены не добавляются к URL.
MCP resources доступны без UI. Локальные sources проверяют границы папок, symlinks и ревизии.

Large Cartesian backend читает Zarr блоками; XTGeo geometry import требует полного RAM preflight.
Большой SEG-Y импорт пишет float32 плитки; срезы и атрибуты имеют собственные memory guards.

Runpod перенесён в `experimental/runpod`, исключён из wheel/sdist, Service, CLI продукта и MCP registry.
Экспериментальные тесты выполняются отдельной командой.
