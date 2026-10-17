> Заменён [ADR-003: MCP-first](003-mcp-first.md). Ниже историческое решение первого прототипа.

# ADR-002: Временный Plotly preview внутри единого Gradio UI

Принято 2026-10-15. Для запуска и проверки численного ядра реализованы Plotly 3D point preview,
XY/XZ/YZ slices, well curves/map и seismic slices. Preview явно ограничен 25k points;
расчёты используют full arrays. Второй React UI не создаётся.

Это **временное отклонение**, не доказательство объективной несовместимости trame и не полный
replacement FR-04. PyVista/trame integration spike, protected viewer/WebSocket,
selection callbacks и restart snapshots остаются доработкой. Optional dependencies сами по себе
не считаются реализованным viewer. Граница не позволяет закрыть A-09/B-13.
