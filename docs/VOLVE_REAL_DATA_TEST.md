# Real-data test: Equinor Volve (2026-10-18)

Data: Equinor Volve Data Village (Databricks Marketplace, Equinor Open Data Licence) —
`Volve_Reservoir_Model-Eclipse_model.zip` (VOLVE_2016 simulation deck and ECLIPSE output),
`Volve_Reservoir_Model-RMS_model.zip`, `Volve_Geophysical_Interpretations.zip`. Data are not
redistributed with Kanysh. Hardware: laptop, 16 cores, 64 GB RAM, RTX 3080 Ti Laptop; OPM Flow
2026.04 in the `kanysh-opm` WSL2 distribution. CRS ED50/UTM31N (EPSG:23031, confirmed by the
interpretation file headers); vertical datum MSL is a tester assumption.

## Results

| Step | Outcome |
|---|---|
| `folder_assess` (63 files) | 0.3 s; 12 EQUIL records with lines, 13 RSVD tables, METRIC. GOC 500 m (placeholder) is now flagged, not proposed. |
| `eclipse_import` of `VOLVE_2016.DATA` (ASCII) | Found real syntax gaps: `MAXVALUE`/`MINVALUE` and unquoted edit records (now applied), region edits `MULTIREG` (now reported per record). Deck uses `ADDZCORN` (manual faults, 10–90 m): import now refuses instead of publishing a grid without them. |
| `eclipse_import` of ECLIPSE output `VOLVE_2016.GRID` + `.INIT` (new legacy GRID reader) | 26 s; 680 400 cells, 183 545 active (= ECLIPSE after MINPV/PINCH). Cell-centre depths equal INIT `DEPTH` (max 0.000 m). Bulk/pore volume vs ECLIPSE `PORV`: median 3.4e-5 after applying the deck's own `MULTIPLY PORV` boxes; all remaining 7 526 cells differ by exactly 0.91 = `MULTIREG PORV` regions 6/10. Without those history-match multipliers the static pore volume is 5.3 % below the simulator's. |
| `model_qc` | 11 s; 0 degenerate, 0 twisted, 122 valid pinch-outs, 329 cells with kv/kh > 1 (data observation), SWAT absent (`missing_property:sw`). On the raw ASCII deck QC reported 154 475 degenerate cells: cells the simulator deactivates via MINPV/PINCH. |
| `regional_volumes` (11 EQLNUM regions, OWC from EQUIL) | Without Sw: synchronous `MISSING_PROPERTY` (field `scenarios[*].regions[*].sw_override`) in 2.8 s. With explicit Sw/Bo assumptions: 11 s, independent integral PASS; oil-interval pore volume 32.6 million rm3. STOIIP is not compared with ECLIPSE FOIP: that needs the simulator's equilibrium Sw (not inferred). |
| `simulation_deck_run`, deck as supplied | OPM refuses: 13th `ROCK` record (TABDIMS NTPVT=12), 13th `RSVD` table (EQLDIMS NTEQUL=12), well records without a keyword in a `.SCH` file, unsupported `PRIORITY`. ECLIPSE tolerated these. |
| `simulation_deck_run`, tester-adjusted copy (3 documented edits) + `parsing_strictness=low` | 2 073 s (34.6 min), 339 report steps to 2016. Status `PASS_WITH_IGNORED_KEYWORDS`; OPM ignored ADDZCORN, PRIORITY, EQLOPTS options and output keywords. vs ECLIPSE 2016: initial FOIP/FWIP equal (0.00 %), FPR max deviation 0.46 %, FOPT/FWPT/FGPT ≤ 0.9 %, FOIP ≤ 0.39 % (production is history-rate controlled, so cumulatives are weak evidence). Well BHP: median 0.7–5 bar for most wells; P-F-1C and I-F-1B 16–21 bar, in the north-west block where the ignored ADDZCORN faults are. |
| RMS archive | Native RMS 2012 projects (not supported by design); 2003 grid only as RESCUE; horizons as scattered x/y/z points; RMS binary horizons. Nothing directly importable. |
| Interpretation horizons | OpenWorks ASCII point sets (inline, xline, x, y, z). `geodata_import` surfaces accept regular grids only: not importable without an explicit gridding method. |

## Gaps found (follow-up work)

1. ADDZCORN in the ASCII importer (needs the exact ECLIPSE semantics; until then use simulator output).
2. Explicit import of the simulator's initial SWAT (UNRST step 0) as a user-confirmed property.
3. Scattered-point surfaces (OpenWorks/RMS points) with an explicit gridding method; RESCUE grids.
4. OPM runs: MPI processes and output on the WSL file system (the run used 8 threads via /mnt/c).
