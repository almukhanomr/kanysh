# Локальная графическая станция

Первый целевой профиль пользователей: **Windows + NVIDIA, вычисления через WSL 2 на той же машине**.
Отдельный сервер, cloud account и собственный веб-интерфейс для этого профиля не требуются.
macOS CPU — текущий проверенный стенд; Linux/WSL2 CUDA, Windows launcher и реальные ChatGPT/Claude
подключения ещё требуют испытаний. Native Windows backend не реализован (POSIX process/locking).

## Схема

```text
MCP-клиент / агент
        ↕
локальный постоянный Kanysh Basic MCP/API
        ├── разрешённые папки исходных данных (read only)
        ├── SQLite + snapshots + immutable результаты на локальном диске
        └── локальные CPU / NVIDIA CUDA для поддерживаемых операций
```

Агент видит inventory, QC, статусы, summaries и выбранные результаты. Основные массивы остаются
на станции. Это не полностью offline-чат: если выбран облачный ChatGPT/Claude, переданные агенту
summaries и previews обрабатываются соответствующим провайдером.

## Подготовка Windows / WSL

1. Настроить WSL **2** с Ubuntu и совместимый NVIDIA Windows driver. NVIDIA документирует CUDA
   в WSL2; Linux display driver внутри WSL устанавливать не требуется.
   [NVIDIA guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html).
2. Поместить исходный код проекта в WSL и подготовить Python 3.12 environment из uv.lock:
   `uv sync --frozen --group dev` (или с `--extra solver`, если нужен resdata).
   Для локального просмотрщика добавьте `--extra ui`; для scene_export — `--extra viewer`.
3. Выполнить `./.venv/bin/kanysh-basic doctor` внутри WSL: проверить RAM, CPU, CUDA, GPU/VRAM.
   `cuda_available=true` — обнаружение устройства, не свидетельство численной приёмки.
4. Проверить лимиты памяти WSL: доступная внутри WSL RAM может отличаться от физической RAM станции.
   Настройки RAM/CPU описаны в [Microsoft WSL configuration](https://learn.microsoft.com/en-us/windows/wsl/wsl-config).

Для интенсивных рабочих файлов/БД использовать файловую систему WSL; исходные файлы можно
читать с Windows-диска. При стандартном automount `D:\Geology\FieldA` виден как
`/mnt/d/Geology/FieldA`. Это настраиваемое сопоставление; `wslpath` учитывает конфигурацию.
[Microsoft: filesystem performance](https://learn.microsoft.com/en-us/windows/wsl/filesystems).

## Запуск

Из подготовленного окружения WSL, Linux или macOS:

```bash
./.venv/bin/kanysh-basic --home /path/to/local-state source-add field-a /path/to/geological-data
./.venv/bin/kanysh-basic --home /path/to/local-state sources
./.venv/bin/kanysh-basic --home /path/to/local-state serve --no-ui --mcp-profile agent --port 8765
```

Вместо /path/to/... укажите существующую папку входов и отдельный каталог состояния/результатов.
Общий endpoint: `http://127.0.0.1:8765/mcp/`; REST docs: `http://127.0.0.1:8765/docs`.
Gradio не импортируется и /app отсутствует в этом режиме. Библиотека пока остаётся в base dependencies.
Только один executor может владеть этим каталогом состояния.

Подготовлен также launcher PowerShell (ещё NOT RUN на Windows), запускающий установленное
WSL environment без автоматической установки драйверов/WSL или изменения политики Windows:

```powershell
.\scripts\start-workstation.ps1 `
  -LinuxProjectPath '/home/geologist/kanysh-basic' `
  -StateDirectory '/home/geologist/.local/share/kanysh-basic' `
  -DataDirectory 'D:\Geology\FieldA' `
  -SourceName 'field-a'
```

Если задан Windows environment `OPENSUBSURFACE_TOKEN`, launcher передаёт его через WSLENV,
не через command arguments. HTTP MCP-клиент отправляет `Authorization: Bearer <token>`.
Ключ установки задаёт владелец локально, а не через разговор с агентом.

## Как агент использует папку

Добавление/удаление sources доступно владельцу через CLI, а не MCP tools.

1. `source_list` получает зарегистрированные папки.
2. `source_scan` с source_id/path получает метаданные CSV/LAS/SEG-Y и подкаталогов, без чтения содержимого.
   Одна страница до 200 записей; для следующей нужны offset и listing_revision.
3. `source_inspect` получает ограниченный CSV header/sample; кандидат роли не заменяет интерпретацию данных.
4. `calculation_plan` закрепляет выбранные входы, единицы и научные допущения; `calculation_run`
   запускает workflow с независимыми checks и отчётом. [Полный пример](AGENT_WORKFLOW.md).
5. В full profile `source_upload` создаёт upload_id/content_hash для dataset_import/seismic_import.
   Все операции используют тот же Service.

Пути относительны зарегистрированному source. Скрытые пути, .., symlinks и специальные файлы
запрещены; root identity проверяется. Изменение/отзыв source во время копирования блокирует
публикацию upload. Готовые snapshots сохраняются после отзыва доступа к исходной папке.
Input hash и source revision включаются в provenance импортированного артефакта.
Owner sources не включаются в project ZIP.

Это single-owner local profile, не multi-tenant source ACL. Inventory проверяет до 10 000
записей одной папки. Обычный CSV/LAS/SEG-Y snapshot import ограничен **256 MiB**, GemPy build — 4 млн ячеек.
Отдельный grid_import принимает готовые большие Cartesian массивы из NPY либо экспортированных
GRDECL property files и сохраняет Zarr chunks; объёмы/uncertainty/validation читают их по блокам.
[Форматы, manifest и ограничения](LARGE_MODELS.md). Произвольные Petrel/corner-point файлы не поддержаны.

## Подключение чата

Локальный MCP-клиент может обращаться к localhost или запускать stdio server. Постоянный HTTP
сервис предпочтителен для долгих заданий: отключение MCP conversation не закрывает executor.
При остановке самого сервиса численные jobs останавливаются; после restart используется
сохранённый статус/явный resume, а не обещание продолжения произвольного процесса с той же инструкции.

Для ChatGPT web localhost станции не является доступным endpoint. Нужен отдельный поддержанный
transport, например OpenAI Secure MCP Tunnel с необходимыми permissions. Это не делает compute
облачным: server/данные остаются на станции, а MCP responses проходят к клиенту.
[OpenAI documentation](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

Remote connector Claude также требует endpoint, доступный инфраструктуре клиента. Local/remote
возможности зависят от поверхности Claude; текущая документация отличает локальные plugins
Cowork/Claude Code от remote connectors для chat.
[Claude documentation](https://support.claude.com/en/articles/11725091-when-to-use-desktop-and-web-connectors).
Общий публичный HTTPS/OAuth deployment остаётся незавершённым; loopback listener не публикуется автоматически.

## Проверки

`tests/integration/test_headless.py`: настоящий CLI HTTP daemon + MCP SDK → source scan/upload →
dataset import; завершение после disconnect; Gradio не импортируется; diagnostic sockets loopback.
`tests/integration/test_local_sources.py`: реальные CSV imports, provenance, pagination,
file-change/revocation/escape/symlink/root-replacement и bounded snapshot import.
Эти проверки выполнены на macOS CPU. Большая Cartesian raw-модель18.119GB /402.7M cells прошла
проверку: [результат](LARGE_MODEL_RESULT.md). Windows/WSL CUDA ещё NOT RUN.
Меньший блочный контроль: [benchmark-large-small.json](benchmark-large-small.json).

## Контроль после установки

После запуска daemon зарегистрируйте synthetic папку examples/agent-demo и выполните
`./.venv/bin/python scripts/agent_demo.py --source-id SOURCE_ID` в другом терминале WSL.
Ожидаются analytical_control=PASS, validation=PASS, STOIIP [2000000,1000000,0].
Отчёт и PNG будут в examples/agent-demo/generated. Затем выполните тесты из
[AGENT_WORKFLOW](AGENT_WORKFLOW.md); CUDA тесты запускать отдельно и сохранять их evidence.
Этот пример по умолчанию CPU, даже при наличии NVIDIA.
