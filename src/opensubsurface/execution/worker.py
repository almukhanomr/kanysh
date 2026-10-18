import importlib.metadata
import json
import os
import platform
import sys
import time
from pathlib import Path

from opensubsurface.errors import DomainError
from opensubsurface.execution.tasks import run


def main():
    directory = Path(sys.argv[1])
    start = time.monotonic()
    request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
    from opensubsurface.execution import progress

    progress.attach(directory)
    progress.log(f"worker started: operation={request['operation']} device={request['device']}")
    try:
        from opensubsurface.execution.device import select_device

        request["device"], _ = select_device(request["device"])
        kind, summary, files = run(request, directory / "output")
        progress.report(1.0, "completed", force=True)
        versions = {}
        for package in ("numpy", "scipy", "gempy", "gstools", "torch", "segyio", "matplotlib", "xtgeo"):
            versions[package] = importlib.metadata.version(package)
        result = dict(
            ok=True,
            kind=kind,
            summary=summary,
            files={k: str(v) for k, v in files.items()},
            elapsed_seconds=time.monotonic() - start,
            environment=dict(
                python=platform.python_version(),
                platform=platform.platform(),
                versions=versions,
                device=request["device"],
                precision=request["payload"]["execution"]["precision"],
            ),
        )
    except DomainError as e:
        result = dict(ok=False, error=e.as_dict())
    except Exception as e:
        # Local developer log only. Never send traceback/user data to API or LLM.
        import traceback

        traceback.print_exc()
        result = dict(
            ok=False,
            error=dict(
                code="COMPUTE_FAILED",
                message="Ошибка вычислительного адаптера: " + type(e).__name__,
                field="",
                remediation="Проверьте локальный worker.log и совместимость входов",
            ),
        )
    progress.log(
        "worker finished: "
        + ("ok" if result["ok"] else f"error={result['error']['code']} {result['error']['message']}")
    )
    if not result["ok"]:
        output = directory / "output"
        output.mkdir(exist_ok=True)
        diagnostic = output / "error.json"
        diagnostic.write_text(json.dumps(dict(error=result["error"]), ensure_ascii=False), encoding="utf-8")
        files = {"error.json": str(diagnostic)}
        if (output / "qc_report.json").is_file():
            files["qc_report.json"] = str(output / "qc_report.json")
        result["diagnostics"] = files
    path = directory / "result.tmp"
    path.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    os.replace(path, directory / "result.json")


if __name__ == "__main__":
    main()
