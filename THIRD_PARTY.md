# Third-party components

Versions are pinned in `uv.lock`. This table uses installed distribution metadata; consult the corresponding upstream LICENSE files for complete terms and distribution conditions. This is an inventory, not a legal opinion.

| Component | Locked version | License metadata | Inclusion / limitations |
|---|---|---|---|
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | Python dependency; dynamically imported |
| pandas | 2.3.3 | BSD-3-Clause; see bundled notices | Python dependency; dynamically imported |
| psutil | 7.2.2 | BSD-3-Clause | Python dependency; dynamically imported |
| portalocker | 3.2.0 | BSD-3-Clause | Python dependency; dynamically imported |
| scipy | 1.18.1 | BSD-3-Clause + bundled library notices | Python dependency; dynamically imported |
| pydantic | 2.12.3 | MIT | Python dependency; dynamically imported |
| fastapi | 0.143.2 | MIT | Python dependency; dynamically imported |
| uvicorn | 0.54.0 | BSD-3-Clause | Python dependency; dynamically imported |
| sqlalchemy | 2.1.4 | MIT | Python dependency; dynamically imported |
| alembic | 1.20.0 | MIT | Python dependency; dynamically imported |
| pint | 0.26.1 | BSD | Python dependency; dynamically imported |
| pyproj | 3.8.0 | MIT | Python dependency; dynamically imported |
| lasio | 0.32 | MIT | Python dependency; dynamically imported |
| segyio | 1.9.14 | LGPL-3.0-or-later | Python dependency; dynamically imported |
| gstools | 1.7.0 | LGPL-3.0 | Python dependency; dynamically imported |
| gempy | 2026.0.3 | EUPL-1.2 | Python dependency; dynamically imported |
| gempy-engine | 2026.0.3.post1 | EUPL-1.2 | Python dependency; dynamically imported |
| torch | 2.11.0+cu128 / 2.14.1 / 2.14.1+cpu | Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT | Python dependency; dynamically imported |
| dask | 2026.8.0 | BSD-3-Clause | Python dependency; dynamically imported |
| distributed | 2026.8.0 | BSD-3-Clause | Python dependency; dynamically imported |
| gradio | 5.50.0 | Apache-2.0 | Python dependency; dynamically imported |
| plotly | 6.9.0 | MIT | Python dependency; dynamically imported |
| matplotlib | 3.11.2 | Matplotlib license; bundled library notices apply | Python dependency; dynamically imported |
| mcp | 1.30.0 | MIT | Python dependency; dynamically imported |
| httpx | 0.28.1 | BSD-3-Clause | Python dependency; dynamically imported |
| pyarrow | 23.0.1 | Apache-2.0 | Python dependency; dynamically imported |
| zarr | 2.18.7 | MIT | Python dependency; dynamically imported |
| itsdangerous | 2.2.0 | See upstream LICENSE | Python dependency; dynamically imported |
| resdata | 6.3.5 | Not installed; consult upstream LICENSE before distribution | Optional extra; NOT RUN; presence in the lock does not establish support |
| pyvista | 0.49.1 | MIT | Python dependency; dynamically imported |
| trame | 3.13.2 | Apache License 2.0 | Python dependency; dynamically imported |
| xtgeo | 4.27.0 | LGPL-3.0 | Python dependency; dynamically imported |
| trame-pyvista | 0.2.1 | MIT | Python dependency; dynamically imported |
| nest-asyncio2 | 1.7.4 | BSD | Python dependency; dynamically imported |
| trame-vtk | 2.11.17 | BSD License | Python dependency; dynamically imported |
| python-multipart | 0.0.32 | Apache-2.0 | Python dependency; dynamically imported |
| shapely | 2.2.0 | BSD-3-Clause | Python dependency; dynamically imported |
| openpyxl | 3.1.5 | MIT | Python dependency; dynamically imported |
| reportlab | 4.5.1 | BSD; see upstream license.txt | Python dependency; dynamically imported |
| pypdf | 6.21.0 | BSD-3-Clause | Python dependency; dynamically imported |

## Separate datasets, solver and models

- Project-owned synthetic generators and fixtures: Apache-2.0; documented seeds include 42. They do not use commercial datasets.
- SPE1CASE2.DATA: Statoil 2015, ODbL-1.0 / DbCL-1.0 according to the retained upstream header. Exact commit, SHA-256 and source: examples/reference/manifest.json. Retain the header and review ODbL obligations before redistributing derived databases.
- SPE10 model2: downloaded OPM/opm-data commit eaa2261683a97027e057c2bc49612ad1c86390b3, ODbL-1.0 / DbCL-1.0; original upstream notices retained, full license texts downloaded. Public benchmark, not a field dataset. Sources and SHA-256: examples/reference/spe10model2/sources.json. Static test constants and splitting into separate keywords are documented derivatives, not upstream solver reference results.
- Norne: public OPM/opm-data/Statoil field benchmark, pinned commit eaa2261683a97027e057c2bc49612ad1c86390b3, ODbL-1.0 / DbCL-1.0. Original notices and full license texts retained; geometry+ACTNUM concatenation and extracted static reports are documented derivatives. Source URLs and SHA-256: examples/reference/norne/sources.json; assumptions/evidence: docs/PETREL_WORKFLOW.md. Data license is separate from Apache-2.0 application source.
- OPM Flow: a separate executable; its binary/image is not distributed and its build is not yet pinned. Review the GPL and the selected build's bundled dependencies before container distribution.
- Full installed inventory: docs/dependencies.json; transitive versions and hashes: uv.lock. Container distributions require a separate inventory of bundled binary libraries.
- GemPy uses EUPL-1.2; GSTools/segyio use LGPL licenses. Their integrated/binary distribution terms differ from the Apache-2.0 license of this project's orchestration code.

Sources: package project URLs in the inventory; [OPM data](https://github.com/OPM/opm-data), [ODbL](https://opendatacommons.org/licenses/odbl/1-0/), [DbCL](https://opendatacommons.org/licenses/dbcl/1-0/).

## Exports, polygons and fonts

Copilot exports use OpenPyXL (MIT), ReportLab (BSD) and pypdf (BSD-3-Clause).
Polygon operations use Shapely (BSD-3-Clause); GEOS has its own LGPL notice.
PDFs embed a DejaVu Sans subset resolved from Matplotlib's font assets; the DejaVu/Bitstream Vera font license applies.
The application uses installed dependencies rather than copying them into its source-only extension. Dependency and dataset notices remain separate from the application license.
