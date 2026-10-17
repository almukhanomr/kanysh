# Synthetic ECLIPSE property exchange example

Own synthetic data, Apache-2.0. This is a uniform Cartesian model, not a field/corner-point Petrel project.
Shape13×17×19; extent X=0…13, Y=0…17, Z=-19…0m; LOCAL_METRIC / SYNTHETIC_MSL.
Explicit constants: active1, zone1, NTG.8, Sw.25, kz_ratio.1; Bo1.2 for volumes.
Expected STOIIP:419.9 standard m³ at OWC=-19m,221 at OWC=-10m,0 at OWC=0m.

Generate machine-specific revisions inside WSL/Linux/macOS:

```bash
./.venv/bin/python scripts/make_grid_manifest.py examples/cartesian-grdecl \
  --format grdecl --shape 13 17 19 --extent 0 13 0 17 -19 0 \
  --crs LOCAL_METRIC --datum SYNTHETIC_MSL \
  --cartesian-basis 'Synthetic uniform Cartesian analytical control' \
  --constant active=1 --constant zones=1 --constant ntg=0.8 --constant sw=0.25 --constant kz_ratio=0.1
./.venv/bin/opensubsurface --home .data source-add cartesian-demo examples/cartesian-grdecl
```

Then source_scan → source_inspect(model.json) → grid_import → calculation_plan(properties ref) → calculation_run.
See docs/LARGE_MODELS.md for contracts, limits and the larger benchmark.
