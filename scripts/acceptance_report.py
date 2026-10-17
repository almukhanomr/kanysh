"""Conservative acceptance ledger: combined GPU/external criteria are not passed on CPU evidence."""

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

rows = []
for line in Path("docs/VISION.md").read_text().splitlines():
    match = re.match(r"\| ([ABC]-\d\d) \| ([^|]+) \| ([^|]+) \|", line)
    if match:
        rows.append(match.groups())
status = {
    "A-01": (
        "PASS",
        "fresh core wheel install without Gradio/Plotly/LLM SDK: headless API, CPU calculation and offline Norne PASS; docs/core-install-check.json; browser viewer/report proof in MCP_FIRST_RESULT.md",
    ),
    "A-02": (
        "PASS",
        "tests/scientific/test_imports.py; demo wells shared imports; supported CSV/LAS2 scope; LAS1.2 additional fixture pending",
    ),
    "A-03": (
        "PASS",
        "feet→m; invalid datum API; time/Z roundtrip and asymmetric GridMapping; projected metric-only profile",
    ),
    "A-04": ("PASS", "Real GemPy CPU horizontal boundary + 3-resolution dipping convergence"),
    "A-05": ("NOT RUN", "CPU analytical all metrics PASS; CUDA half of combined criterion NOT RUN"),
    "A-06": ("NOT RUN", "No NVIDIA CUDA device; tests/gpu skipped explicitly"),
    "A-07": ("NOT RUN", "No remote host; transport adapter incomplete"),
    "A-08": (
        "PASS",
        "Idempotency, process-group cancel/timeout, interrupted restart, bounded retry/attempt IDs, require-GPU rejection; persistent headless HTTP and metadata-client ownership isolation tests PASS",
    ),
    "A-09": (
        "PASS",
        "Read-only viewer in ui extra: projects/revisions, sandboxed reports/scenes, seismic slices, uploads, offline Norne. No chat/voice or scientific forms; tests/integration/test_viewer_pages.py",
    ),
    "A-10": ("REPLACED", "заменено MCP-клиентами; собственные чат и голос удалены; не обязательная приёмка"),
    "A-11": (
        "NOT RUN",
        "MCP SDK stdio/shared ASGI + actual headless CLI HTTP daemon/source snapshot/import/disconnect PASS; agent profile pinned GemPy/static plan, independent checks, partial/resume and report/image SDK PASS; real ChatGPT/Claude OAuth connectors not tested",
    ),
    "A-12": (
        "PASS",
        "test_store bundle roundtrip/hash/revisions/backup; runtime credentials not included in object bundles",
    ),
    "B-01": (
        "FAIL",
        "IEEE float32 big/little scalar fixtures and direct-source 269.4MB/67.1M-sample float32 Zarr exact comparison PASS; both sorted trace orders/missing mask verified; IBM/affine field geometry acceptance incomplete",
    ),
    "B-02": (
        "FAIL",
        "Pick revisions/domain roundtrip PASS; pixel/polyline picking and interpolation UI incomplete",
    ),
    "B-03": ("NOT RUN", "RMS constant/impulse and sine-envelope CPU PASS; CUDA not run"),
    "B-04": ("PASS", "Constant velocity expected Z=-400m at TWT=.5s,v=2000,origin100; roundtrip atol1e-15"),
    "B-05": (
        "PASS",
        "Real GemPy single planar fault CPU: left -40m/right -60m and valid zones; unsupported OPM bridge rejected",
    ),
    "B-06": (
        "FAIL",
        "GSTools exact/seed/logit/holdout and independent anisotropic covariance PASS; fitted variogram/ensemble statistical acceptance incomplete",
    ),
    "B-07": ("PASS", "Independent 3x4x2 hardcoded I-fast/K-down fixture + inactive cell restoration"),
    "B-08": (
        "FAIL",
        "Basic PVT/SCAL/report dates and explicit STCOND present; complete completions/events/PVT schemas incomplete",
    ),
    "B-09": (
        "NOT RUN",
        "No OPM initialization outputs; static input PORV3.2e6m3 verified only before export",
    ),
    "B-10": ("NOT RUN", "Generated 20x20x5 case exported; Flow executable not installed"),
    "B-11": ("NOT RUN", "No validated CUDA OPM build/device"),
    "B-12": (
        "NOT RUN",
        "Constant-FVF oil-water component balance/PORV/no-flow pressure-drift QC implemented; analytical conservation PASS; native no-flow/waterflood not run",
    ),
    "B-13": (
        "FAIL",
        "Native summary SDK + artificial EGRID/INIT/two-report UNRST fixture and analytical UI/alignment/comparison PASS; real Flow outputs and per-well analysis acceptance incomplete",
    ),
    "B-14": (
        "NOT RUN",
        "Direct OPM/ResInsight external opening unavailable; reproducible generated/reference files supplied",
    ),
    "B-15": ("NOT RUN", "Seismic/picks/depth/property paths available; full solver integration not run"),
    "B-16": ("NOT RUN", "Common contracts exist; real external clients and full B integration not run"),
    "C-01": (
        "NOT RUN",
        "3 real property artifacts x 2 real case exporters; mocked solver 4 success/2 fail then resume only 2 PASS; 6 real Flow cases not run",
    ),
    "C-02": (
        "PASS",
        "Independent analytical Q/P, pointwise bands/sample counts, explicit partial failure policy/total/completed/excluded PASS; real solver inputs separate C-01",
    ),
    "C-03": (
        "PASS",
        "Explicit completed-case ranking <=10, date/unit normalization, constraints/feasibility/direction and no-global-optimum declaration; analytical fixtures PASS",
    ),
    "C-04": (
        "FAIL",
        "Save/run/fan-out/fan-in/resume plus preflight typed artifact ports/missing parameters PASS; advanced multi-port/units coverage incomplete",
    ),
    "C-05": (
        "PASS",
        "Workflow/ensemble resume and interrupted-parent snapshots PASS; verified blobs + input/config/package/source/Flow hashes; failed-only case resume",
    ),
    "C-06": (
        "FAIL",
        "Mock price/region/transfer/unknown policy guards PASS; live quote/private network plan incomplete",
    ),
    "C-07": ("NOT RUN", "No real account/spend authorization; private bootstrap gate blocks launch"),
    "C-08": ("PASS", "Mock create timeout → unknown, no duplicate POST, reconcile matching intent"),
    "C-09": (
        "PASS",
        "Mock foreign ownership retained; cleanup failure persists; delete confirmed by inspect",
    ),
    "C-10": (
        "FAIL",
        "Reservations and estimate/actual-null separated; provider usage/periodic accrual/storage incomplete",
    ),
    "C-11": (
        "NOT RUN",
        "No policy mutation tools; workflow/cloud contract exists, external MCP clients not tested",
    ),
    "C-12": ("FAIL", "Full dynamic process with actual OPM not yet validated; cloud cleanup is experimental"),
}
non_required = {"A-10", "C-06", "C-07", "C-08", "C-09", "C-10", "C-11"}
for criterion in non_required - {"A-10"}:
    status[criterion] = (
        "EXPERIMENTAL",
        "Вынесено в experimental/runpod; не входит в пакет/MCP и обязательную приёмку",
    )

stamp = datetime.now(ZoneInfo("Asia/Almaty")).isoformat(timespec="seconds")
lines = [
    "# Kanysh Advanced — historical vision acceptance ledger",
    "",
    f"Обновлено: {stamp}. Стенд: macOS arm64 / Python3.12.14 / 16GiB / CPU.",
    "",
    "**A–D/O принят пользователем; новых возможностей в публикационную упаковку не добавляется.**",
    "Этот ledger относится к расширенной исторической [VISION](VISION.md), а не к текущему принятому scope. Исторический scope не принят целиком: PASS подкомпонента не повышает комбинированный criterion до PASS.",
    "FAIL — известный программный/приёмочный пробел; NOT RUN — нет необходимого внешнего стенда/аккаунта/выполненного запуска.",
    "Mocks не доказывают real CUDA, OAuth или OPM. Обязательный MCP-first scope исключает A-10 и Runpod; scientific acceptance остаётся открытой.",
    "",
    "## Воспроизведение",
    "",
    "`uv sync --frozen --extra ui --extra viewer --extra solver --group dev`; `uv run --extra ui --extra viewer --extra solver pytest -q --junitxml=docs/test-results.xml`; `uv run ruff check src tests scripts examples/generators`.",
    "UI: запустить `kanysh-basic serve --ui`; проверить read-only просмотрщик и кнопку офлайн Norne.",
    "Solver SDK fixtures: `uv sync --frozen --extra solver --group dev`. Raw evidence: test-results.xml, benchmark-cpu.json, copilot-viewer.png; test names and limitations below.",
    "",
    "| ID | Критерий | Статус | Evidence / limitations |",
    "|---|---|---|---|",
]
for id, name, goal in rows:
    state, evidence = status[id]
    lines.append(f"| {id} | {name.strip()} | **{state}** | {evidence} |")
lines += [
    "",
    "## Отдельные доступные проверки",
    "",
    "- Analytical static volumes: GRV20e6, NetRock16e6, PV3.2e6, HCPV2.4e6, STOIIP2e6; fractional contact half; inactive NaNs excluded.",
    "- Independent 3x4x2 mapping fixture, exact GSTools conditioning/logit/no-clipping/holdout, IEEE SEG-Y endian+scalar, GemPy real CPU boundary.",
    "- Project bundle/backup/restore, idempotency conflict, terminal immutability, controller close, Origin/Host/token/session guards.",
    "- Real MCP stdio/HTTP SDK list/call, shared REST/auth; workflow fan-out/fan-in/resume/invalidation; subprocess-group cancellation.",
    "- Dynamic analytical alignment/units/nulls/pointwise bands/partial accounting/bounded ranking; native resdata Summary writer/reader (не OPM-run).",
    "- Artificial EGRID/INIT/two-report UNRST binary fixture: independent resfo writer, IJK/inactive/ACTNUM/pressure/sw/so/dates PASS; raw test-results-native-reader.xml.",
    "- Ensemble 3x2 real exporters + explicitly mocked solver failures/resume; restart snapshot adoption. Flow binary/resdata changes invalidate runtime fingerprint.",
    "- Runpod mocks вынесены в experimental/runpod/tests; marker experimental и отдельная команда, вне стандартной приёмки.",
    "- Local workstation foundation: serve --no-ui, owner filesystem sources, metadata paging, hash/revision snapshots, traversal/symlink/revocation guards, actual HTTP MCP import after conversation disconnect.",
    "- Agent static profile: source CSV → pinned GemPy plan → 3 OWC → seeded uncertainty → independent layer-integration checks → HTML/JSON/CSV/PNG report; invalid numbers fail parent run; partial report and resume preserve provenance. See tests/integration/test_calculations.py and test_agent_mcp.py.",
    "- Bounded Cartesian NPY/GRDECL property importer and independent chunked volume checks: 8.4M actual cells / 377MB input / 437MiB peak process-tree RSS PASS; raw benchmark-large-small.json. Separate full Cartesian model control PASS: 402.7M cells, seven NPY inputs totaling18.119GB, sampled RSS353.5MiB, import/QC/volume/independent validation PASS; raw benchmark-large.json. Single file/ZIP>15GiB not tested; native Petrel unsupported.",
    "- XTGeo corner-point GRDECL/EGRID/ROFF rotated analytic controls; public Norne all113344 cells/44927 active, original properties/mapping, independent ConvexHull contact clipping, plan/report PASS and full active-cell PyVista/trame scene; docs/PETREL_WORKFLOW.md. XTGeo geometry import uses full RAM, <=2M-cell profile.",
    "- Large SEG-Y source import: actual269422096-byte synthetic IEEE file, all67108864 samples bitwise exact, import sampled peak RSS402.5MiB, working amplitude buffer2MiB; benchmark-seismic.json. No1TiB or Volve claim.",
    "- Published OPM SPE10 model2 input files: 1.122M cells, pinned commit+SHA-256, original PORO/PERMX/PERMZ preserved, independent source-layer sums and numerical validation PASS. NTG/Sw/Bo are explicit static-control settings; no Flow/real field/>15GiB acceptance inferred.",
    "- Windows + NVIDIA via WSL2 is the first user deployment target. PowerShell launcher prepared, NOT RUN on Windows/WSL; no CUDA acceptance inferred from macOS CPU tests.",
    "",
    "## Blockers",
    "",
    "Список программных пробелов и внешних стендов: [ROADMAP.md](ROADMAP.md). Не все FAIL объясняются отсутствием hardware.",
    "OPM deck и SPE1 fixture не имеют reference results: simulator не запускался. Docker recipe не built и не digest-pinned.",
    "Внешний GPU/OPM стенд и реальные HTTPS/OAuth MCP-клиенты ещё требуют проверки. LLM/ASR keys и Runpod не являются требованиями основного продукта.",
    "",
    "## Известные сторонние предупреждения",
    "",
    "GemPy/Pydantic json_encoders, Gradio5 deprecations к Gradio6, Starlette portal alias. Они записаны в raw pytest report; версии удерживаются lockfile.",
]
lines += [
    "",
    "## Copilot alongside Petrel/RMS",
    "",
    "A–D/O implementation, explicit format limits and onboarding evidence: [COPILOT_RESULT.md](COPILOT_RESULT.md).",
    "Publication checks and current CPU regression: [PUBLICATION.md](PUBLICATION.md). Scientific algorithms are unchanged by packaging.",
    "Full Norne DATA static import and 20M synthetic corner-point benchmark passed. SWAT equilibrium, Windows/WSL2/NVIDIA, real Claude/Desktop extension installation and OPM remain NOT RUN.",
    "The updated wheel passed an existing UI-free core environment. A fresh full offline dependency solve was unavailable due incomplete cache; see copilot-core-check.json.",
]
Path("docs/ACCEPTANCE.md").write_text("\n".join(lines) + "\n")
Path("docs/acceptance.json").write_text(
    json.dumps(
        dict(
            timestamp=stamp,
            environment="macOS arm64 Python3.12.14 CPU",
            release_accepted=False,
            acceptance_scope="Kanysh Advanced historical VISION; not the accepted Kanysh Basic A-D/O scope",
            copilot_scope_accepted=True,
            criteria=[
                dict(
                    id=id,
                    name=name.strip(),
                    status=status[id][0],
                    evidence=status[id][1],
                    required=id not in non_required,
                    scope="product"
                    if id not in non_required
                    else "replaced"
                    if id == "A-10"
                    else "experimental",
                )
                for id, name, _ in rows
            ],
        ),
        indent=2,
        ensure_ascii=False,
    )
)
print("Ledger criteria:", len(rows))
