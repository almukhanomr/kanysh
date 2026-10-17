import argparse
import json
import os
from pathlib import Path

from opensubsurface.errors import DomainError
from opensubsurface.service import Service


def main():
    parser = argparse.ArgumentParser(
        prog="kanysh-basic", description="Kanysh Basic — subsurface modelling copilot"
    )
    parser.add_argument("--home", default=os.environ.get("OPENSUBSURFACE_HOME", ".data"))
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup", help="Owner: configure Claude clients, create home and open viewer")
    setup.add_argument("--desktop-config", type=Path)
    setup.add_argument("--code-config", type=Path)
    setup.add_argument("--no-viewer", action="store_true")
    setup.add_argument("--no-browser", action="store_true")
    serve = sub.add_parser("serve", help="Локальный API/UI")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--ui", action="store_true", help="Веб-просмотрщик (extra ui)")
    serve.add_argument("--no-ui", action="store_true", help="Постоянный локальный MCP/API без Gradio")
    serve.add_argument("--mcp-profile", choices=["full", "agent"], default="full")
    source = sub.add_parser("source-add", help="Владелец: разрешить чтение папки с исходными данными")
    source.add_argument("name")
    source.add_argument("directory", type=Path)
    sub.add_parser("sources", help="Подключённые локальные папки")
    remove_source = sub.add_parser("source-remove", help="Владелец: отозвать доступ к папке")
    remove_source.add_argument("source_id")
    sub.add_parser("demo", help="Контрольный CPU-проект")
    sub.add_parser("doctor", help="Проверить реальные capabilities")
    sub.add_parser("projects")
    run = sub.add_parser("run", help="Типизированная операция")
    run.add_argument("operation")
    run.add_argument("--json", required=True, type=Path)
    run.add_argument("--wait", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("job_id")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("job_id")
    upload = sub.add_parser("upload")
    upload.add_argument("project_id")
    upload.add_argument("file", type=Path)
    export = sub.add_parser("export")
    export.add_argument("project_id")
    export.add_argument("file", type=Path)
    imp = sub.add_parser("import-project")
    imp.add_argument("file", type=Path)
    backup = sub.add_parser("backup")
    backup.add_argument("directory", type=Path)
    mcp = sub.add_parser("mcp")
    mcp.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    mcp.add_argument("--profile", choices=["full", "agent"], default="full")
    sub.add_parser("benchmark")
    args = parser.parse_args()
    if args.command == "setup" and args.home == ".data" and not os.environ.get("OPENSUBSURFACE_HOME"):
        from opensubsurface.platform_io import default_home

        args.home = str(default_home())
    service = Service(args.home)
    try:
        if args.command == "setup":
            from opensubsurface.setup import setup

            result = setup(
                service, args.desktop_config, args.code_config, not args.no_viewer, not args.no_browser
            )
        elif args.command == "serve":
            import uvicorn

            from opensubsurface.api.app import create_app

            os.environ["OPENSUBSURFACE_PORT"] = str(args.port)
            uvicorn.run(
                create_app(service=service, with_ui=args.ui and not args.no_ui, mcp_profile=args.mcp_profile),
                host="127.0.0.1",
                port=args.port,
            )
            return
        elif args.command == "mcp":
            from opensubsurface.mcp.server import create_mcp

            create_mcp(service, profile=args.profile).run(transport=args.transport)
            return
        elif args.command == "demo":
            result = service.demo()
        elif args.command == "doctor":
            result = service.capabilities()
        elif args.command == "projects":
            result = service.store.list_projects()
        elif args.command in ("source-add", "sources", "source-remove"):
            from opensubsurface.adapters.local_sources import LocalSources

            sources = LocalSources(service.store)
            if args.command == "source-add":
                result = sources.register(args.name, args.directory)
            elif args.command == "source-remove":
                result = sources.remove(args.source_id)
            else:
                result = sources.list()
        elif args.command == "run":
            submission = service.invoke(args.operation, json.loads(args.json.read_text(encoding="utf-8")))
            # CLI owns local worker lifetime; waits for completion before exiting.
            result = service.wait(submission)
        elif args.command == "status":
            result = service.store.job(args.job_id)
        elif args.command == "cancel":
            result = service.cancel(args.job_id)
        elif args.command == "upload":
            with args.file.open("rb") as stream:
                result = service.store.upload(args.project_id, args.file.name, stream)
        elif args.command == "export":
            result = {"file": service.store.export_project(args.project_id, args.file)}
        elif args.command == "import-project":
            result = service.store.import_project(args.file)
        elif args.command == "backup":
            service.store.backup(args.directory)
            result = {"backup": str(args.directory)}
        elif args.command == "benchmark":
            from opensubsurface.benchmark import benchmark

            result = benchmark(service.store.root / "benchmarks")
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except DomainError as e:
        print(json.dumps({"error": e.as_dict()}, ensure_ascii=False))
        raise SystemExit(1)
    finally:
        service.close()


if __name__ == "__main__":
    main()
