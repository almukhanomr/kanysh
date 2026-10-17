# Synthetic agent control dataset

Own synthetic inputs; Apache-2.0. Metres, Z up, LOCAL_METRIC, SYNTHETIC_MSL.
One horizontal horizon at Z=-1020 m. Grid extent Z=-1040…-1000 m.
GemPy zone 2 below the horizon is the reservoir; zone 1 above is excluded.
Reservoir phi=.2, NTG=.8, Sw=.25, Bo=1.2, permeability=100 mD.

Expected STOIIP at OWC Z=-1040/-1030/-1020 m: 2,000,000 / 1,000,000 / 0 standard m³.
Scalar uncertainty uses phi uniform [.15,.25], seed 42, 30 samples at the full contact.
These are analytical controls, not field forecasts or OPM results.

See `docs/AGENT_WORKFLOW.md` and `scripts/agent_demo.py`.
