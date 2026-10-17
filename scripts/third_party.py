import importlib.metadata as metadata
import json
import tomllib
from pathlib import Path

lock = tomllib.loads(Path("uv.lock").read_text())
versions = {p["name"]: p["version"] for p in lock["package"]}
primary = [
    "numpy",
    "pandas",
    "psutil",
    "scipy",
    "pydantic",
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "alembic",
    "pint",
    "pyproj",
    "lasio",
    "segyio",
    "gstools",
    "gempy",
    "gempy-engine",
    "torch",
    "dask",
    "distributed",
    "gradio",
    "plotly",
    "matplotlib",
    "mcp",
    "httpx",
    "pyarrow",
    "zarr",
    "itsdangerous",
    "resdata",
    "pyvista",
    "trame",
    "xtgeo",
    "trame-pyvista",
    "nest-asyncio2",
    "trame-vtk",
    "python-multipart",
    "shapely",
    "openpyxl",
    "reportlab",
    "pypdf",
]
inventory = []
for dist in metadata.distributions():
    m = dist.metadata
    inventory.append(
        dict(
            name=m["Name"],
            version=m["Version"],
            license_expression=m.get("License-Expression"),
            license_text=m.get("License"),
            project_urls=m.get_all("Project-URL", []),
        )
    )
Path("docs/dependencies.json").write_text(
    json.dumps(sorted(inventory, key=lambda p: p["name"].lower()), indent=2)
)
lines = [
    "# Third-party components",
    "",
    "Versions are pinned in `uv.lock`. This table uses installed distribution metadata; consult the corresponding upstream LICENSE files for complete terms and distribution conditions. This is an inventory, not a legal opinion.",
    "",
    "| Component | Locked version | License metadata | Inclusion / limitations |",
    "|---|---|---|---|",
]
for name in primary:
    try:
        m = metadata.metadata(name)
        lic = m.get("License-Expression") or m.get("License") or "See upstream LICENSE"
        if name == "scipy":
            lic = "BSD-3-Clause + bundled library notices"
        if name == "matplotlib":
            lic = "Matplotlib license; bundled library notices apply"
        if name == "pandas":
            lic = "BSD-3-Clause; see bundled notices"
        if name == "reportlab":
            lic = "BSD; see upstream license.txt"
        lic = lic.replace("\n", " ").replace("|", "\\|")[:170]
        status = "Python dependency; dynamically imported"
    except metadata.PackageNotFoundError:
        lic = "Not installed; consult upstream LICENSE before distribution"
        status = "Optional extra; NOT RUN; presence in the lock does not establish support"
    lines.append(f"| {name} | {versions.get(name, '—')} | {lic} | {status} |")
lines += [
    "",
    "## Separate datasets, solver and models",
    "",
    "- Project-owned synthetic generators and fixtures: Apache-2.0; documented seeds include 42. They do not use commercial datasets.",
    "- SPE1CASE2.DATA: Statoil 2015, ODbL-1.0 / DbCL-1.0 according to the retained upstream header. Exact commit, SHA-256 and source: examples/reference/manifest.json. Retain the header and review ODbL obligations before redistributing derived databases.",
    "- SPE10 model2: downloaded OPM/opm-data commit eaa2261683a97027e057c2bc49612ad1c86390b3, ODbL-1.0 / DbCL-1.0; original upstream notices retained, full license texts downloaded. Public benchmark, not a field dataset. Sources and SHA-256: examples/reference/spe10model2/sources.json. Static test constants and splitting into separate keywords are documented derivatives, not upstream solver reference results.",
    "- Norne: public OPM/opm-data/Statoil field benchmark, pinned commit eaa2261683a97027e057c2bc49612ad1c86390b3, ODbL-1.0 / DbCL-1.0. Original notices and full license texts retained; geometry+ACTNUM concatenation and extracted static reports are documented derivatives. Source URLs and SHA-256: examples/reference/norne/sources.json; assumptions/evidence: docs/PETREL_WORKFLOW.md. Data license is separate from Apache-2.0 application source.",
    "- OPM Flow: a separate executable; its binary/image is not distributed and its build is not yet pinned. Review the GPL and the selected build's bundled dependencies before container distribution.",
    "- Full installed inventory: docs/dependencies.json; transitive versions and hashes: uv.lock. Container distributions require a separate inventory of bundled binary libraries.",
    "- GemPy uses EUPL-1.2; GSTools/segyio use LGPL licenses. Their integrated/binary distribution terms differ from the Apache-2.0 license of this project's orchestration code.",
    "",
    "Sources: package project URLs in the inventory; [OPM data](https://github.com/OPM/opm-data), [ODbL](https://opendatacommons.org/licenses/odbl/1-0/), [DbCL](https://opendatacommons.org/licenses/dbcl/1-0/).",
]
lines += [
    "",
    "## Exports, polygons and fonts",
    "",
    "Copilot exports use OpenPyXL (MIT), ReportLab (BSD) and pypdf (BSD-3-Clause).",
    "Polygon operations use Shapely (BSD-3-Clause); GEOS has its own LGPL notice.",
    "PDFs embed a DejaVu Sans subset resolved from Matplotlib's font assets; the DejaVu/Bitstream Vera font license applies.",
    "The application uses installed dependencies rather than copying them into its source-only extension. Dependency and dataset notices remain separate from the application license.",
]
Path("THIRD_PARTY.md").write_text("\n".join(lines) + "\n")
