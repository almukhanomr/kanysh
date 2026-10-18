"""Self-contained MCP input schemas: every $ref inlined, every property described.

Clients that ignore "$defs" must still see field names, units, the Z convention and
allowed enum values. Descriptions are documentation only; validation stays in the
pydantic request models and is never relaxed here.
"""

import copy

Z_UP = "Z is positive upward in metres: depth 2692 m below datum is Z=-2692."

# Owner-specific entries ("Model.field") win over generic field-name entries.
FIELD_DOCS = {
    # Common identifiers and references
    "project_id": "Project id from project_create/project_list, e.g. 'project-…'.",
    "id": "Immutable artifact id exactly as returned by an earlier tool, e.g. 'properties-…'.",
    "revision": "Artifact revision number (integer >= 1) exactly as returned with the id.",
    "Node.id": "Workflow node id: letter followed by up to 63 letters, digits, '_' or '-'.",
    "job_id": "Job id returned by an asynchronous tool (field job_id), e.g. 'job-…'.",
    "run_id": "calculation_run id (run_id returned by calculation_run).",
    "idempotency_key": "Optional client key (<=120 chars); the same key returns the existing job instead of a duplicate.",
    "source_id": "Owner-registered source folder id from source_list.",
    "path": "Path relative to the registered source folder, '/' separated, no '..'.",
    "FolderAssess.path": "Sub-folder relative to the source root to assess; empty string means the root.",
    "SourceScan.path": "Sub-folder relative to the source root to list; empty string means the root.",
    "file_revision": "64-hex file revision from source_scan/folder_assess; rejects files changed since discovery.",
    "upload_id": "Upload id returned by source_upload.",
    "ref": "Artifact reference {id, revision}.",
    "WellLogInput.ref": "Original LAS dataset artifact reference {id, revision}.",
    "properties": "Properties artifact {id, revision} from eclipse_import/grid_import/properties_assign.",
    "other_properties": "Second properties artifact {id, revision} with identical IJK shape.",
    "plan": "calculation_plan artifact {id, revision} with status READY.",
    "artifact": "Artifact {id, revision} to validate independently.",
    "report": "Report artifact {id, revision} (calculation_report or analysis_report).",
    "polygon": "Optional polygons dataset {id, revision} from geodata_import kind=polygons.",
    "trajectory": "Trajectory dataset {id, revision} with XYZ/MD survey.",
    "model": "Model artifact {id, revision} from model_build.",
    "surfaces": "Surfaces dataset {id, revision} (kind=surfaces).",
    "orientations": "Orientations dataset {id, revision} (kind=orientations).",
    "fault": "Optional fault artifact {id, revision} from fault_create.",
    "volume": "Seismic volume artifact {id, revision}.",
    "interpretation": "Interpretation artifact {id, revision}.",
    "previous": "Optional previous interpretation revision to supersede.",
    "case": "Simulation case artifact {id, revision}.",
    "result": "Simulation result artifact {id, revision}.",
    "workflow": "Workflow artifact {id, revision} from workflow_save.",
    "resume_run": "Optional workflow_run snapshot {id, revision} returned as checkpoint, for resume with the same plan.",
    "resume_ensemble": "Optional ensemble artifact {id, revision} to resume.",
    "results": "Explicit result artifacts {id, revision} to compare.",
    "ensemble": "Ensemble artifact {id, revision}; mutually exclusive with results.",
    "property_realizations": "Unique properties artifacts {id, revision}, one per realization.",
    "reports": "Report artifacts {id, revision} to export (1–20).",
    "slices": "Optional seismic_slice artifacts {id, revision} to include (<=10).",
    # Execution
    "execution": "Execution policy. Defaults: local CPU, float64, no fallback, 3600 s timeout.",
    "placement": "Where to run. Allowed: local, remote, auto. Only local is configured.",
    "target_id": "Compute target id from compute_targets_list (only 'local-cpu' or null).",
    "device_policy": "Device policy. Allowed: cpu (default), prefer_gpu (CUDA if the operation supports it; needs allow_cpu_fallback=true to fall back), require_gpu (fail unless a CUDA path exists). See compute_targets_list.device_matrix for GPU-capable operations.",
    "allow_cpu_fallback": "With prefer_gpu: allow CPU when CUDA or a GPU kernel is unavailable (recorded as a warning).",
    "allow_remote": "Permit data transfer to a remote target. Remote targets are not configured; keep false.",
    "precision": "Floating point precision. Allowed: float64 (validated), float32 (rejected until validated).",
    "timeout_seconds": "Worker timeout in seconds, 1–86400.",
    "max_workers": "Maximum CPU block processes, 1–256. Null chooses CPU/RAM-bounded concurrency; CUDA requires null or 1. Immutable block partitions and reduction order are fixed.",
    "keyword": "Explicit ECLIPSE property keyword. Required for a single-property GRDECL file; omitted for INIT.",
    "property_files": "Revision-pinned INIT or single-keyword GRDECL properties for an EGRID import; no implicit defaults or XTGeo full-grid allocation.",
    "max_retries": "Retries after worker crash/timeout, 0–1.",
    # Project / coordinates
    "ProjectCreate.name": "Project name, 1–120 characters.",
    "crs": "Coordinate reference system exactly as confirmed by the user, e.g. 'EPSG:23032' or 'LOCAL_METRIC'. Must equal the project CRS; never inferred.",
    "vertical_datum": "Vertical datum name confirmed by the user, e.g. 'MSL'. Must equal the project datum.",
    "length_unit": "Length unit of the source coordinates. Allowed: m, ft (ft is converted by 0.3048 to stored metres).",
    "ProjectCreate.length_unit": "Project length unit. Allowed: m.",
    "z_direction": "Direction of Z/depth values IN THE SOURCE FILE. Allowed: up (elevation), down (positive depth, e.g. ECLIPSE ZCORN). Stored artifacts are always Z up: z_stored = -depth when down.",
    "coordinate_unit": "SEG-Y trace coordinate unit. Allowed: m, ft.",
    "datum": "Datum name of the converted horizon.",
    # Grid / model
    "grid": "Regular grid definition {shape, extent}.",
    "Grid.shape": "Cell counts [nx, ny, nz], each 1–1000, at most 4 000 000 cells.",
    "Grid.extent": "Grid bounds [xmin, xmax, ymin, ymax, zmin, zmax] in metres. "
    + Z_UP
    + " Example: [0,1000,0,1000,-1040,-1000].",
    "shape": "Array shape.",
    "SyntheticSeismic.shape": "Synthetic cube shape [inlines, crosslines, samples].",
    "method": "Structural method. Allowed: horizontal_explicit (horizons_z only), gempy (surfaces + orientations).",
    "SaturationHeight.method": "Allowed: table (height above OWC in m -> Sw) or leverett_j ((Sw, J) table plus explicit physics).",
    "horizontal_assumption": "Explicitly confirm flat horizontal layering (required for horizontal_explicit).",
    "horizons_z": "Horizon elevations in metres, strictly inside the grid Z extent. " + Z_UP,
    "stratigraphic_order": "Horizon names from top to bottom for GemPy.",
    "zones": "Zone properties keyed by zone id (string integer >=1), e.g. {'2': {phi:0.2, ntg:0.8, sw:0.25, permeability_md:100}}.",
    "phi": "Porosity, fraction 0–1.",
    "ntg": "Net-to-gross, fraction 0–1.",
    "sw": "Water saturation, fraction 0–1.",
    "permeability_md": "Horizontal permeability in millidarcy (>=0).",
    "kz_ratio": "Vertical/horizontal permeability ratio, (0, 1]. Default 0.1.",
    "zone_ids": "Zone ids (positive integers) included in the volume.",
    "zone_id": "Single zone id (>=1).",
    "bo": "Oil formation volume factor Bo, reservoir m3 per standard m3 (>0). User-confirmed; never inferred.",
    "bg": "Gas formation volume factor Bg, reservoir m3 per standard m3 (>0). Required with goc_z_m.",
    "bw": "Water formation volume factor (>0).",
    "contacts": "1–10 named OWC alternatives evaluated separately, no probabilities inferred.",
    "Contact.name": "Unique contact alternative name, e.g. 'full'.",
    "z_m": "Contact elevation in metres. " + Z_UP,
    "contact_z_m": "Oil-water contact elevation in metres. " + Z_UP,
    "contact_name": "Name of one entry in contacts used for the uncertainty run.",
    "inputs": "Source CSV inputs (one per kind): {kind, source_id, path, file_revision, units}.",
    "Input.kind": "Input role. Allowed: surfaces, orientations, collars.",
    "units": "Column unit map, e.g. {'x':'m','y':'m','z':'m'}. Units are declared, never inferred.",
    "profile": "Workflow profile.",
    "CalculationPlan.profile": "Calculation profile. Allowed: static_volumetrics_v1.",
    "SimulationCaseCreate.profile": "Simulation schedule profile. Allowed: waterflood, depletion, no_flow.",
    "CalculationPlan.name": "Plan name, 1–120 characters.",
    "assumptions": "Explicit user-confirmed assumptions recorded in the report (file/line evidence where available).",
    "uncertainty": "Optional seeded scalar Monte Carlo over one contact alternative.",
    "distributions": "Per-parameter distributions. Keys: phi, ntg, sw, bo, contact_z_m (contact Z up, metres).",
    "count": "Number of seeded samples.",
    "seed": "Random seed (>=0) recorded for reproducibility.",
    "kind": "Kind.",
    "Distribution.kind": "Allowed: constant (low only), uniform (low, high), triangular (low, mode, high).",
    "low": "Lower bound (same unit as the parameter).",
    "high": "Upper bound (same unit as the parameter, > low).",
    "mode": "Triangular mode within [low, high].",
    "SensitivityParameter.mode": "Allowed: scalar_override (replace the value) or multiplier (scale the model value). Contacts use scalar_override only.",
    # ECLIPSE / grid import
    "block_cells": "Cells per bounded processing block (memory/speed trade-off).",
    "region_field": "Integer region array used to group cells. Allowed: zones, FIPNUM, EQLNUM, SATNUM, fault_blocks (for eclipse_import: FIPNUM, SATNUM, EQLNUM). 'zones' is the field selected at import.",
    "defaults": "Explicit user-confirmed constants for MISSING properties only, keyed by ECLIPSE name (ACTNUM, PORO, NTG, PERMX, PERMY, PERMZ, SWAT, FIPNUM, SATNUM, EQLNUM). Recorded in the report.",
    # Geodata
    "GeodataImport.kind": "Allowed: surfaces, trajectory, markers, polygons.",
    "format": "Source format. Allowed: irap_ascii, irap_binary, zmap_ascii, cps3_ascii, rms_ascii, petrel_ascii, mapped_ascii, xyz, zmap.",
    "GeodataImport.name": "Dataset name (>=1 character).",
    "well_id": "Well identifier for single-well files.",
    "md_column": "Measured-depth column name (metres along hole).",
    "columns": "Explicit column mapping {role: source column}.",
    "VolumesReconcile.columns": "Map of roles to CSV columns: region_id, metric, value, unit.",
    "column_indices": "Explicit column index mapping {role: 0-based index}, 0–1000.",
    "skiprows": "Header lines to skip, 0–10000.",
    "delimiter": "Single-character delimiter; null means whitespace.",
    "cps_order": "CPS-3 sample order. Allowed: row_major, column_major.",
    "cps_y_first": "CPS-3 first row Y. Allowed: min, max.",
    "GeodataImport.trajectory": "Optional trajectory {id, revision} to locate MD-only tops.",
    # QC / diff
    "small_cluster_cells": "Active IJK clusters with at most this many cells are reported, 1–1 000 000.",
    "max_examples": "Maximum example rows in the JSON response (full witnesses in CSV), 1–1000.",
    "atol": "Absolute tolerance per property for change detection (>=0).",
    "rtol": "Relative tolerance per property for change detection (>=0).",
    # Regional volumes
    "scenarios": "1–100 named scenarios; each lists region cases with explicit contacts/PVT/saturations.",
    "RegionScenario.name": "Unique scenario name, 1–200 characters.",
    "regions": "1–1000 region cases with unique region_id.",
    "region_id": "Region id present in region_field of the properties artifact (see eclipse_import summary region_ids).",
    "owc_z_m": "Oil-water contact elevation in metres. " + Z_UP + " Example: OWC depth 2692 m -> -2692.",
    "goc_z_m": "Optional gas-oil contact elevation in metres, must be >= owc_z_m. "
    + Z_UP
    + " Requires bg and so_in_gas_zone.",
    "sg_in_oil_zone": "Free-gas saturation Sg inside the oil interval (below GOC, above OWC), fraction 0–1. Oil fraction there = 1 - Sw - sg_in_oil_zone. Deprecated alias: oil_gas_saturation.",
    "so_in_gas_zone": "Residual oil saturation So inside the gas cap (above GOC), fraction 0–1; required with goc_z_m. Gas fraction there = 1 - Sw - so_in_gas_zone. Deprecated alias: gas_oil_saturation.",
    "phi_override": "Optional constant porosity (fraction 0–1) replacing the model PORO for this region.",
    "ntg_override": "Optional constant NTG (fraction 0–1) replacing the model NTG.",
    "sw_override": "Optional constant Sw (fraction 0–1). Required when the model has no SWAT and no sw_height is given.",
    "phi_multiplier": "Optional multiplier (>=0) applied to porosity.",
    "ntg_multiplier": "Optional multiplier (>=0) applied to NTG.",
    "sw_multiplier": "Optional multiplier (>=0) applied to Sw; does not supply a missing SWAT.",
    "sw_height": "Optional saturation-height function evaluated at the mean cell corner height above OWC.",
    "table": "Table rows: method=table -> [height_above_owc_m, Sw]; method=leverett_j -> [Sw, J].",
    "extrapolation": "Outside the table range. Allowed: clamp, reject.",
    "density_difference_kg_m3": "Water-oil density difference in kg/m3 (Leverett J only).",
    "surface_tension_mN_m": "Interfacial tension in mN/m (Leverett J only).",
    "contact_angle_deg": "Contact angle in degrees, -90 < angle < 90 (Leverett J only).",
    "gravity_m_s2": "Gravity acceleration in m/s2 (Leverett J only).",
    "polygon_ids": "Exterior polygon ring ids to select.",
    "polygon_hole_ids": "Hole ring ids subtracted from the exteriors.",
    "polygon_selection": "Allowed: corner_mean_whole_cell (whole cells by mean corner XY).",
    "polygon_boundary": "Cells exactly on the polygon boundary. Allowed: include, exclude.",
    "geometry_policy": "Cells flagged invalid by geometry QC (twisted, inverted, degenerate). Allowed: strict (default, reject the run) or exclude_flagged (skip them; requires parameters_confirmed=true; excluded count, bounding GRV/PV and share are reported and validation_status becomes PASS_WITH_EXCLUSIONS).",
    "parameters_confirmed": "Must be true: the user explicitly confirmed every contact, PVT, saturation and policy value in this request.",
    # Reconcile
    "reference_scenario": "Scenario name in scenarios compared with the CSV.",
    "reference_region_definition": "User statement of how the reference report defines regions.",
    "metric_definitions": "User statement of each reference metric definition, keyed by metric.",
    "relative_tolerance": "Relative difference treated as agreement, 0–1.",
    # Wells vs model
    "logs": "LAS inputs with explicit curve and unit mappings.",
    "md_curve": "LAS measured-depth curve mnemonic.",
    "property_curves": "Map of model property (phi, ntg) to LAS curve mnemonic.",
    "property_units": "Map of property to curve unit. Allowed: fraction, percent.",
    "max_survey_gap_m": "Maximum MD gap (m) between survey stations for interpolation (>0).",
    "boundary_policy": "Samples on shared cell faces. Allowed: lowest_ijk, reject.",
    "sample_every_n": "Use every n-th LAS sample, 1–1 000 000.",
    # Sensitivity / uncertainty
    "parameters": "Parameters.",
    "SensitivityTornado.parameters": "1–30 unique (region_id, field) parameters with explicit low/high.",
    "UncertaintyMonteCarlo.parameters": "1–30 unique (region_id, field) parameters with explicit bounds and distribution.",
    "WorkflowRun.parameters": "Workflow parameter values referenced by nodes.",
    "field": "Field.",
    "SensitivityParameter.field": "Varied quantity. Allowed: phi, ntg, sw (fractions), owc_z_m, goc_z_m (Z up, metres), bo, bg.",
    "SceneShow.field": "Displayed property. Allowed: zones, phi, ntg, sw, permeability_md, kz_ratio.",
    "Geostat.field": "Property to model. Allowed: phi, permeability_md.",
    "SimulationSnapshot.field": "Allowed: pressure, sw, so, sg.",
    "distribution": "Marginal distribution. Allowed: uniform, triangular, truncated_normal, truncated_lognormal.",
    "mean": "Normal mean (truncated_normal).",
    "stddev": "Normal standard deviation (>0).",
    "mode_value": "Triangular mode within [low, high].",
    "mean_log": "Mean of ln(value) (truncated_lognormal).",
    "stddev_log": "Standard deviation of ln(value) (>0).",
    "metric": "Metric.",
    "SensitivityTornado.metric": "Ranked metric. Allowed: STOIIP, GIIP (standard m3).",
    "UncertaintyMonteCarlo.metric": "Statistic metric. Allowed: STOIIP, GIIP (standard m3).",
    "Compare.metric": "Allowed: auto, STOIIP, FOPT, FWPT, FWIT, WATER_CUT, FPR.",
    "DevelopmentRank.metric": "Allowed: auto, STOIIP, FOPT, FWPT, FWIT, WATER_CUT, FPR.",
    "MetricConstraint.metric": "Allowed: FOPT, FWPT, FWIT, WATER_CUT, FPR.",
    "max_cell_scenario_evaluations": "Work budget: cells x evaluated scenarios.",
    "samples": "Number of Monte Carlo draws, 2–10000.",
    "correlation": "Square latent correlation matrix, one row per parameter.",
    "correlation_space": "Allowed: gaussian_copula.",
    # Scene
    "visible": "Show the artifact in the scene.",
    "opacity": "Opacity 0–1.",
    "vertical_exaggeration": "Vertical exaggeration factor (0, 100].",
    "selected": "Highlight in the scene.",
    "stride": "Display every n-th cell (>=1); does not change data.",
    "cell_range": "Optional [start, end) cell index range to display.",
    "seismic_axis": "Allowed: inline, crossline, sample.",
    "slice_index": "Seismic slice index (>=0).",
    "velocity_m_s": "Constant velocity in m/s (>0) for TWT conversion.",
    "origin_z_m": "Z of time zero in metres. " + Z_UP,
    "max_cells": "Preview cell budget.",
    "max_points": "Preview point budget.",
    # Seismic
    "domain": "Sample domain. Allowed: twt (ms), depth (m).",
    "sample_unit": "Sample unit. Allowed: ms (twt), m (depth).",
    "endian": "SEG-Y byte order. Allowed: big, little.",
    "inline_byte": "Trace header byte of the inline number, 1–237.",
    "crossline_byte": "Trace header byte of the crossline number, 1–237.",
    "axis": "Axis.",
    "SeismicSlice.axis": "Allowed: inline, crossline, sample.",
    "SimulationSnapshot.axis": "Allowed: XY, XZ, YZ.",
    "index": "Slice index (>=0).",
    "attribute": "Allowed: rms, envelope.",
    "window": "Odd window length in samples, 1–1001.",
    "dt_seconds": "Sample interval in seconds (>0).",
    "picks": "Horizon picks (1–10000).",
    "inline": "Inline number.",
    "crossline": "Crossline number.",
    "sample_index": "Fractional sample index (>=0).",
    "InterpretationSave.name": "Interpretation name, 1–100 characters.",
    "time_depth_table": "Strictly increasing [[TWT seconds, depth difference m], ...].",
    # Geostat
    "conditioning": "Well conditioning data.",
    "positions": "Conditioning XYZ positions in metres (Z up).",
    "values": "Conditioning values (same order as positions).",
    "well_ids": "Well id per conditioning value.",
    "variance": "Variogram variance (>0).",
    "length_scale_m": "Variogram length scale in metres (>0).",
    "anisotropy": "Anisotropy ratios (>0).",
    # Simulation
    "fluid": "Fluid and SCAL definition.",
    "standard_temperature_c": "Standard temperature, deg C.",
    "standard_pressure_bara": "Standard pressure, bara.",
    "oil_density_kg_m3": "Oil density, kg/m3.",
    "water_density_kg_m3": "Water density, kg/m3.",
    "oil_viscosity_cp": "Oil viscosity, cP.",
    "water_viscosity_cp": "Water viscosity, cP.",
    "reference_pressure_bara": "Reference pressure, bara.",
    "rock_compressibility_per_bar": "Rock compressibility, 1/bar.",
    "swof": "SWOF rows [Sw, krw, kro, Pc_bar]; Sw strictly increasing.",
    "demo_assumptions_accepted": "Explicitly accept demo schedule assumptions.",
    "start_date": "Simulation start date (YYYY-MM-DD).",
    "report_days": "Strictly increasing positive report days.",
    "producer_rate_sm3_day": "Producer rate, standard m3/day.",
    "injector_rate_sm3_day": "Injector rate, standard m3/day.",
    "producer_bhp_bara": "Producer BHP limit, bara.",
    "injector_bhp_bara": "Injector BHP limit, bara.",
    "report_index": "Report step index (>=0).",
    "schedules": "Simulation schedules (1–10).",
    "expected_case_count": "Confirmed realizations x schedules count.",
    # Workflow
    "WorkflowSave.name": "Workflow name.",
    "nodes": "Workflow nodes (1–100).",
    "operation": "Tool/operation name executed by this node.",
    "arguments": "Operation arguments; {'$node': id} references another node's output.",
    "depends_on": "Node ids that must finish first.",
    # Compare
    "allow_partial": "Allow comparison when some cases failed (failures stay visible).",
    "dates": "Explicit timezone-aware report dates.",
    "report_at": "Timezone-aware date for ranking.",
    "direction": "Allowed: maximize, minimize.",
    "constraints": "Metric constraints (<=10).",
    "unit": "Metric unit.",
    "minimum": "Lower bound.",
    "maximum": "Upper bound.",
    # Fault
    "FaultCreate.name": "Fault name, 1–80 characters.",
    "points": "3–64 coplanar XYZ points in metres (Z up).",
    "normal": "Unit plane normal [nx, ny, nz].",
    "relation": "Allowed: offset_stratigraphy.",
    # Discovery / sources
    "offset": "Listing offset (>=0).",
    "limit": "Page size 1–200.",
    "listing_revision": "listing_revision from the previous page.",
    "max_depth": "Maximum sub-folder depth 0–8.",
    "max_files": "Maximum files inspected 1–500.",
    "preview_rows": "CSV sample rows to return, 0–5.",
    "input_index": "Plan input index 0–5.",
    # Export
    "formats": "Export formats. Allowed: xlsx, pdf.",
    "title": "Document title.",
    "max_pdf_rows_per_table": "PDF row limit per table, 1–1000 (full tables in XLSX/JSON).",
    "notes": "User notes added to the export.",
    "verbose": "Return the full stored job record (payload, attempts). Default false returns a compact status.",
    "lines": "Number of trailing startup.log lines to return, 1–500.",
    "pressure_reference": "Allowed: absolute, gauge.",
    "SimulationDeckRun.path": "Main ECLIPSE-format deck (.DATA) relative to the source folder; INCLUDE files are copied with it.",
    "SimulationDeckRun.file_revision": "64-hex revision of the .DATA file from folder_assess/source_scan.",
    "threads": "OPM Flow threads per process (--threads-per-process), 1..logical CPUs.",
    "parsing_strictness": "OPM input parsing. Allowed: normal (default: stop on unsupported critical keywords), low (continue; OPM ignores them, they are listed in the report and status becomes PASS_WITH_IGNORED_KEYWORDS). Use low only with the user's explicit agreement.",
    "keep_restart": "Also publish the UNRST restart file (can be large). Default false.",
    "reference": "Optional user reference results (e.g. ECLIPSE SMSPEC + UNSMRY in the same source) to compare against.",
    "smspec_path": "Reference .SMSPEC path relative to the source folder.",
    "smspec_revision": "64-hex revision of the reference .SMSPEC.",
    "data_path": "Reference .UNSMRY (unified) path relative to the source folder.",
    "data_revision": "64-hex revision of the reference .UNSMRY.",
    "vectors": "Summary vectors to compare, e.g. FOPT, FWPT, FGPT, WOPR:B-2H.",
    "SimulationReference.relative_tolerance": "User-chosen agreement threshold for max |result-reference|/max|reference| (0..1]; reported, never tuned.",
    "rate_reference": "Allowed: standard, reservoir.",
    "DatasetImport.kind": "Allowed: collars, trajectory, markers, surfaces, orientations, production, las.",
}

EXAMPLES = {
    "RegionalVolumes.scenarios": [
        {
            "name": "base",
            "regions": [
                {
                    "region_id": 1,
                    "owc_z_m": -2692.0,
                    "goc_z_m": -2582.0,
                    "bo": 1.33,
                    "bg": 0.004737,
                    "sg_in_oil_zone": 0.0,
                    "so_in_gas_zone": 0.05,
                    "sw_override": 0.2,
                }
            ],
        }
    ],
    "RegionScenario.regions": [
        {"region_id": 2, "owc_z_m": -2585.5, "bo": 1.30, "sg_in_oil_zone": 0.0, "sw_override": 0.2}
    ],
    "CalculationPlan.contacts": [
        {"name": "full", "z_m": -1040.0},
        {"name": "mid", "z_m": -1030.0},
        {"name": "top", "z_m": -1020.0},
    ],
    "CalculationPlan.zones": {
        "1": {"phi": 0.0, "permeability_md": 0.0, "ntg": 0.0, "sw": 1.0},
        "2": {"phi": 0.2, "permeability_md": 100.0, "ntg": 0.8, "sw": 0.25},
    },
    "CalculationPlan.inputs": [
        {
            "kind": "surfaces",
            "source_id": "source-…",
            "path": "surfaces.csv",
            "file_revision": "<64 hex from source_scan>",
            "units": {"x": "m", "y": "m", "z": "m"},
        }
    ],
}
for _name in ("SensitivityTornado", "UncertaintyMonteCarlo", "VolumesReconcile"):
    EXAMPLES[_name + ".scenarios"] = EXAMPLES["RegionalVolumes.scenarios"]


def _enum_note(schema):
    values = schema.get("enum")
    if values is None and "const" in schema:
        values = [schema["const"]]
    if values is None:
        return ""
    return " Allowed: " + ", ".join(map(str, values)) + "."


def _describe(owner, name, prop):
    text = FIELD_DOCS.get(f"{owner}.{name}") or FIELD_DOCS.get(name)
    if not text:
        return
    variants = [prop, *prop.get("anyOf", [])]
    for variant in variants:
        note = _enum_note(variant)
        if note and "Allowed:" not in text:
            text += note
    prop["description"] = text


def resolve(schema):
    """Return a deep copy with all local $refs inlined and documented, without $defs."""
    defs = schema.get("$defs", {})

    def walk(node, owner, stack):
        if isinstance(node, list):
            return [walk(item, owner, stack) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            if name in stack:
                raise ValueError("Recursive schema cannot be inlined: " + name)
            merged = dict(copy.deepcopy(defs[name]), **{k: v for k, v in node.items() if k != "$ref"})
            return walk(merged, name, stack | {name})
        owner = node.get("title", owner) if "properties" in node else owner
        out = {}
        for key, value in node.items():
            if key == "$defs":
                continue
            if key == "properties":
                props = {}
                for name, prop in value.items():
                    resolved = walk(prop, owner, stack)
                    if "description" not in resolved:
                        _describe(owner, name, resolved)
                    example = EXAMPLES.get(f"{owner}.{name}")
                    if example is not None:
                        resolved["examples"] = [example]
                    props[name] = resolved
                out[key] = props
            else:
                out[key] = walk(value, owner, stack)
        return out

    return walk(schema, schema.get("title", ""), frozenset())


# Old names stay accepted (pydantic AliasChoices); published so strict clients do not drop them.
DEPRECATED_ALIASES = {
    "RegionCase": {"oil_gas_saturation": "sg_in_oil_zone", "gas_oil_saturation": "so_in_gas_zone"}
}


def _publish_aliases(node):
    if isinstance(node, list):
        for item in node:
            _publish_aliases(item)
        return
    if not isinstance(node, dict):
        return
    aliases = DEPRECATED_ALIASES.get(node.get("title")) if "properties" in node else None
    if aliases:
        required = node.get("required", [])
        alternatives = []
        for old, new in aliases.items():
            prop = dict(node["properties"][new], deprecated=True)
            prop["description"] = f"DEPRECATED alias of {new}; send {new} instead. " + prop["description"]
            prop.pop("examples", None)
            node["properties"][old] = prop
            if new in required:
                required.remove(new)
                alternatives.append({"anyOf": [{"required": [new]}, {"required": [old]}]})
        if alternatives:
            node["allOf"] = node.get("allOf", []) + alternatives
    for value in node.values():
        _publish_aliases(value)


def tool_input_schema(model):
    request = resolve(model.model_json_schema(mode="validation"))
    _publish_aliases(request)
    request["description"] = "Tool arguments object (all fields documented; Z is positive upward)."
    return {
        "type": "object",
        "properties": {"request": request},
        "required": ["request"],
        "additionalProperties": False,
        "title": model.__name__ + "Arguments",
    }


def unresolved_refs(schema):
    found = []

    def walk(node, path):
        if isinstance(node, dict):
            if "$ref" in node:
                found.append(path)
            for key, value in node.items():
                walk(value, path + "/" + key)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}/{index}")

    walk(schema, "")
    return found


def undocumented(schema):
    """JSON paths of object properties (at any depth) that lack a description."""
    missing = []

    def walk(node, path):
        if not isinstance(node, dict):
            return
        for name, prop in (node.get("properties") or {}).items():
            if not prop.get("description"):
                missing.append(path + "." + name)
            walk(prop, path + "." + name)
        for key in ("items", "additionalProperties"):
            if isinstance(node.get(key), dict):
                walk(node[key], path + "[]")
        for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
            for child in node.get(key) or []:
                walk(child, path)

    walk(schema, "")
    return missing
