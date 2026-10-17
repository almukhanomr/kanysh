# ADR-001: Python 3.12 и один локальный control plane

Принято 2026-10-15. Новый каталог, существующего репозитория Kanysh Basic не было.
Используем Python 3.12 (доступен bundled runtime), uv.lock, FastAPI/Pydantic,
SQLAlchemy/Alembic/SQLite, Gradio и Dask. Системный Python 3.14 не выбран из-за научной
совместимости. Не используются Redis/Celery/Kubernetes. Solver — отдельный процесс.

Совместимость реальных выбранных wheels проверена CPU tests. NVIDIA, Linux worker и Docker
не имитируются на macOS. Images нельзя объявить pinned/validated до отдельного Linux build.
Это development-ограничение, не отмена требований B/C.
