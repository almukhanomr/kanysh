# Upstream SPE10 model2 static acceptance

Downloaded published OPM/opm-data files, pinned at commit
`eaa2261683a97027e057c2bc49612ad1c86390b3`; [sources/SHA-256](sources.json).
This is an external public benchmark, not a real field dataset. Total download77,267,536 bytes
including original DATA, TOPS, PORO, three permeability arrays and license texts.
Original notices retained; database ODbL-1.0 / contents DbCL-1.0 as supplied by OPM.

Reproduce from project root, Python3.12, in WSL on Windows:

```bash
./.venv/bin/python scripts/fetch_spe10_reference.py
./.venv/bin/python scripts/test_spe10_reference.py
```

The download script uses a pinned commit and SHA-256, with a128MiB total transfer cap.
The test does not download anything. Raw/prepared/state folders are local caches excluded from Git;
source metadata and small reports remain available in the repository.

The preparation step verifies original DIMENS60×220×85, FIELD units, constant DX20/DY10/DZ2ft,
and every TOPS layer12000+2*k ft. It splits the fixed PERMX/PERMY/PERMZ file into separate keyword
files without changing numeric values. No arbitrary INCLUDE/EDIT commands are executed.
All source files are checked against sources.json before preparation.

Imported values are compared cell by cell against a separate NumPy reader:
PORO and PERMX exactly; kz_ratio exactly equals original PERMZ/PERMX; original PERMY equals PERMX.
Porosity includes zeros (min0,max.5). These zeros are preserved even though the source header
mentions replacing zeros by1e-7. Permeability Kx ranges.000665…20000mD.

Static numerical-control assumptions: NTG1, Sw.2, Bo1, all cells active, one zone.
These are explicit test settings, not reproduction of the original PVT/equilibration/forecast.
XYZ are local metric, Z=-depth*ft; the physical source depth datum is not claimed to be MSL.

Tested OWC depths12170/12085.5/12000ft (full/fractional/dry controls). GRV, oil interval,
net rock, PV, HCPV and STOIIP are checked against independent layer sums of published porosity,
with explicit feet→metres conversion. Production independent validators also run for properties
and every volume result. Geological fitness still requires specialist review.

[Acceptance JSON](results/acceptance.json) · [HTML report](results/report.html) ·
[CSV](results/volumes.csv) · [PNG](results/volumes.png)

This does not validate OPM Flow, CUDA, a real ChatGPT/Claude client, native Petrel or models>15GiB.

Sources: [OPM open datasets](https://opm-project.org/?page_id=559),
[pinned upstream folder](https://github.com/OPM/opm-data/tree/eaa2261683a97027e057c2bc49612ad1c86390b3/spe10model2).
