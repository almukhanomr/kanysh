from __future__ import annotations

import math
from datetime import date
from typing import Literal

from pydantic import AliasChoices, AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Ref(Strict):
    id: str
    revision: int = Field(ge=1)


class Execution(Strict):
    placement: Literal["local", "remote", "auto"] = "local"
    target_id: str | None = None
    device_policy: Literal["cpu", "prefer_gpu", "require_gpu"] = "cpu"
    allow_cpu_fallback: bool = False
    allow_remote: bool = False
    precision: Literal["float64", "float32"] = "float64"
    timeout_seconds: int = Field(default=3600, ge=1, le=86400)
    max_retries: int = Field(default=0, ge=0, le=1)
    max_workers: int | None = Field(default=None, ge=1, le=256)


class Command(Strict):
    project_id: str
    execution: Execution = Field(default_factory=Execution)
    idempotency_key: str | None = Field(default=None, max_length=120)


class ProjectCreate(Strict):
    name: str = Field(min_length=1, max_length=120)
    crs: str = "LOCAL_METRIC"
    vertical_datum: str
    length_unit: Literal["m"] = "m"


class DatasetImport(Command):
    upload_id: str
    kind: Literal["collars", "trajectory", "markers", "surfaces", "orientations", "production", "las"]
    units: dict[str, str]
    well_id: str | None = None
    pressure_reference: Literal["absolute", "gauge"] | None = None
    rate_reference: Literal["standard", "reservoir"] | None = None
    crs: str
    vertical_datum: str


class Grid(Strict):
    shape: tuple[int, int, int] = (20, 20, 5)
    extent: tuple[float, float, float, float, float, float] = (0, 1000, 0, 1000, -1020, -1000)

    @model_validator(mode="after")
    def valid(self):
        if any(n < 1 or n > 1000 for n in self.shape) or math.prod(self.shape) > 4_000_000:
            raise ValueError("Разрешено 1–4 000 000 ячеек; размер каждой оси 1–1000")
        if any(self.extent[i] >= self.extent[i + 1] for i in (0, 2, 4)):
            raise ValueError("Минимумы extent должны быть меньше максимумов")
        return self


class ModelBuild(Command):
    grid: Grid = Field(default_factory=Grid)
    method: Literal["horizontal_explicit", "gempy"] = "horizontal_explicit"
    horizontal_assumption: bool = False
    horizons_z: list[float] = Field(default_factory=list)
    stratigraphic_order: list[str] = Field(default_factory=list)
    surfaces: Ref | None = None
    orientations: Ref | None = None
    fault: Ref | None = None


class Zone(Strict):
    phi: float = Field(ge=0, le=1)
    permeability_md: float = Field(ge=0)
    ntg: float = Field(ge=0, le=1)
    sw: float = Field(ge=0, le=1)
    kz_ratio: float = Field(default=0.1, gt=0, le=1)


class FaultCreate(Command):
    name: str = Field(min_length=1, max_length=80)
    points: list[tuple[float, float, float]] = Field(min_length=3, max_length=64)
    normal: tuple[float, float, float]
    relation: Literal["offset_stratigraphy"] = "offset_stratigraphy"

    @model_validator(mode="after")
    def planar(self):
        if not math.isclose(sum(x * x for x in self.normal), 1, abs_tol=1e-6):
            raise ValueError("Нормаль разлома должна быть единичной")
        if len(set(self.points)) != len(self.points):
            raise ValueError("Дубли точек разлома")
        return self


class PropertiesAssign(Command):
    model: Ref
    zones: dict[int, Zone]


class LargeGrid(Strict):
    shape: tuple[int, int, int]
    extent: tuple[float, float, float, float, float, float]

    @model_validator(mode="after")
    def valid(self):
        if any(n < 1 or n > 1_000_000 for n in self.shape) or math.prod(self.shape) > 2_000_000_000:
            raise ValueError("Out-of-core profile: 1–2 billion cells, each axis <=1 million")
        if any(self.extent[i] >= self.extent[i + 1] for i in (0, 2, 4)):
            raise ValueError("Минимумы extent должны быть меньше максимумов")
        return self


class GridImport(Command):
    source_id: str
    path: str = Field(min_length=1, max_length=1024)
    file_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    block_cells: int = Field(default=262144, ge=1024, le=1048576)


class EclipsePropertyFile(Strict):
    path: str = Field(min_length=1, max_length=1024)
    file_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    format: Literal["init", "grdecl"]
    keyword: (
        Literal["PORO", "NTG", "PERMX", "PERMY", "PERMZ", "SWAT", "FIPNUM", "SATNUM", "EQLNUM", "PVTNUM"]
        | None
    ) = None

    @model_validator(mode="after")
    def declared_keyword(self):
        if (self.format == "grdecl") != (self.keyword is not None):
            raise ValueError("keyword is required only for a single-property GRDECL file")
        return self


class EclipseImport(Command):
    format: Literal["auto", "ascii", "egrid"] = "auto"
    property_files: list[EclipsePropertyFile] = Field(default_factory=list, max_length=32)
    source_id: str
    path: str = Field(min_length=1, max_length=1024)
    file_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    crs: str
    vertical_datum: str
    length_unit: Literal["m", "ft"]
    z_direction: Literal["up", "down"]
    region_field: Literal["FIPNUM", "SATNUM", "EQLNUM"] = "FIPNUM"
    defaults: dict[str, float] = Field(default_factory=dict)
    assumptions: list[str] = Field(min_length=1, max_length=100)
    block_cells: int = Field(default=16384, ge=1024, le=16384)

    @model_validator(mode="after")
    def explicit_defaults(self):
        if not self.defaults.keys() <= {
            "ACTNUM",
            "PORO",
            "NTG",
            "PERMX",
            "PERMY",
            "PERMZ",
            "SWAT",
            "FIPNUM",
            "SATNUM",
            "EQLNUM",
        }:
            raise ValueError("Defaults only for declared static properties")
        if any(not math.isfinite(v) for v in self.defaults.values()):
            raise ValueError("Finite explicit defaults required")
        return self


class GeodataImport(Command):
    source_id: str
    path: str = Field(min_length=1, max_length=1024)
    file_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    crs: str
    vertical_datum: str
    kind: Literal["surfaces", "trajectory", "markers", "polygons"]
    format: Literal[
        "irap_ascii",
        "irap_binary",
        "zmap_ascii",
        "cps3_ascii",
        "rms_ascii",
        "petrel_ascii",
        "mapped_ascii",
        "xyz",
        "zmap",
    ]
    name: str = Field(min_length=1)
    well_id: str | None = None
    md_column: str | None = None
    length_unit: Literal["m", "ft"]
    z_direction: Literal["up", "down"]
    columns: dict[str, str] = Field(default_factory=dict)
    column_indices: dict[str, int] = Field(default_factory=dict)
    skiprows: int = Field(default=0, ge=0, le=10000)
    delimiter: str | None = Field(default=None, min_length=1, max_length=1)
    cps_order: Literal["row_major", "column_major"] | None = None
    cps_y_first: Literal["min", "max"] | None = None
    trajectory: Ref | None = None
    assumptions: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def indices(self):
        if any(v < 0 or v > 1000 for v in self.column_indices.values()):
            raise ValueError("Column index must be 0..1000")
        return self


class ModelQC(Command):
    properties: Ref
    region_field: Literal["zones", "FIPNUM", "EQLNUM", "SATNUM", "fault_blocks"] = "zones"
    small_cluster_cells: int = Field(default=1, ge=1, le=1000000)
    max_examples: int = Field(default=100, ge=1, le=1000)
    assumptions: list[str] = Field(default_factory=list, max_length=100)


class SaturationHeight(Strict):
    method: Literal["table", "leverett_j"]
    table: list[tuple[float, float]] = Field(min_length=2, max_length=10000)
    extrapolation: Literal["clamp", "reject"]
    density_difference_kg_m3: float | None = Field(default=None, gt=0)
    surface_tension_mN_m: float | None = Field(default=None, gt=0)
    contact_angle_deg: float | None = None
    gravity_m_s2: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def physical(self):
        if any(self.table[i][0] >= self.table[i + 1][0] for i in range(len(self.table) - 1)):
            raise ValueError("Table first coordinate must strictly increase")
        if self.method == "table":
            if any(not 0 <= sw <= 1 or h < 0 for h, sw in self.table):
                raise ValueError("Height >=0 m and 0<=Sw<=1 required")
            if any(self.table[i][1] < self.table[i + 1][1] for i in range(len(self.table) - 1)):
                raise ValueError("Sw must not increase with height")
        else:
            if any(
                v is None
                for v in (
                    self.density_difference_kg_m3,
                    self.surface_tension_mN_m,
                    self.contact_angle_deg,
                    self.gravity_m_s2,
                )
            ):
                raise ValueError("Leverett J requires explicit density contrast, tension, angle and gravity")
            if not -90 < self.contact_angle_deg < 90 or any(
                not 0 <= sw <= 1 or j < 0 for sw, j in self.table
            ):
                raise ValueError("J table requires (Sw,J), Sw fraction and J>=0, cos(angle)>0")
            if any(self.table[i][1] <= self.table[i + 1][1] for i in range(len(self.table) - 1)):
                raise ValueError("Leverett J must strictly decrease with Sw for inversion")
        return self


class RegionCase(Strict):
    """One region's explicit contacts, PVT and residual phase saturations (Z positive upward).

    Saturation semantics used by regional_volumes.evaluate:
    oil interval (OWC < Z < GOC) oil fraction = 1 - Sw - sg_in_oil_zone;
    gas cap (Z > GOC) gas fraction = 1 - Sw - so_in_gas_zone.
    Old names oil_gas_saturation / gas_oil_saturation remain accepted as deprecated aliases.
    """

    region_id: int
    owc_z_m: float
    bo: float = Field(gt=0)
    sg_in_oil_zone: float = Field(
        ge=0, le=1, validation_alias=AliasChoices("sg_in_oil_zone", "oil_gas_saturation")
    )
    goc_z_m: float | None = None
    bg: float | None = Field(default=None, gt=0)
    so_in_gas_zone: float | None = Field(
        default=None, ge=0, le=1, validation_alias=AliasChoices("so_in_gas_zone", "gas_oil_saturation")
    )
    phi_override: float | None = Field(default=None, ge=0, le=1)
    ntg_override: float | None = Field(default=None, ge=0, le=1)
    sw_override: float | None = Field(default=None, ge=0, le=1)
    phi_multiplier: float | None = Field(default=None, ge=0)
    ntg_multiplier: float | None = Field(default=None, ge=0)
    sw_multiplier: float | None = Field(default=None, ge=0)
    sw_height: SaturationHeight | None = None

    @model_validator(mode="before")
    @classmethod
    def single_name(cls, data):
        if isinstance(data, dict):
            for new, old in (
                ("sg_in_oil_zone", "oil_gas_saturation"),
                ("so_in_gas_zone", "gas_oil_saturation"),
            ):
                if new in data and old in data:
                    raise ValueError(f"{old}: deprecated alias of {new}; send only {new}")
        return data

    # Messages start with "<field>: " so the MCP layer reports the exact JSON path.
    @model_validator(mode="after")
    def phases(self):
        if self.goc_z_m is not None:
            if self.goc_z_m < self.owc_z_m:
                raise ValueError(
                    f"goc_z_m: Z is positive upward, so GOC ({self.goc_z_m}) must be >= OWC ({self.owc_z_m});"
                    " depth 2582 m -> -2582"
                )
            if self.bg is None:
                raise ValueError("bg: gas formation volume factor is required when goc_z_m is set")
            if self.so_in_gas_zone is None:
                raise ValueError(
                    "so_in_gas_zone: residual oil saturation in the gas cap is required when goc_z_m is set"
                )
        elif self.bg is not None:
            raise ValueError("goc_z_m: bg was given without a gas-oil contact")
        elif self.so_in_gas_zone is not None:
            raise ValueError("goc_z_m: so_in_gas_zone was given without a gas-oil contact")
        if self.sw_override is not None and self.sw_height is not None:
            raise ValueError("sw_height: choose either sw_override or sw_height, not both")
        return self


class RegionScenario(Strict):
    name: str = Field(min_length=1, max_length=200)
    regions: list[RegionCase] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_regions(self):
        if len({r.region_id for r in self.regions}) != len(self.regions):
            raise ValueError("regions: unique region_id values required within a scenario")
        return self


class RegionalVolumes(Command):
    properties: Ref
    scenarios: list[RegionScenario] = Field(min_length=1, max_length=100)
    region_field: Literal["zones", "FIPNUM", "EQLNUM", "SATNUM", "fault_blocks"]
    polygon: Ref | None = None
    polygon_ids: list[str] = Field(default_factory=list, max_length=1000)
    polygon_hole_ids: list[str] = Field(default_factory=list, max_length=1000)
    polygon_selection: Literal["corner_mean_whole_cell"] | None = None
    polygon_boundary: Literal["include", "exclude"] | None = None
    # strict keeps the established behaviour; exclude_flagged is an explicit, reported relaxation.
    geometry_policy: Literal["strict", "exclude_flagged"] = "strict"
    parameters_confirmed: Literal[True]
    assumptions: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def explicit_polygon(self):
        if self.polygon is not None:
            for name in ("polygon_ids", "polygon_selection", "polygon_boundary"):
                if not getattr(self, name):
                    raise ValueError(
                        f"{name}: confirm polygon rings, whole-cell corner-mean selection and boundary policy"
                    )
        if self.polygon_hole_ids and set(self.polygon_ids) & set(self.polygon_hole_ids):
            raise ValueError("polygon_hole_ids: polygon exterior/hole IDs overlap")
        return self


class VolumesReconcile(RegionalVolumes):
    source_id: str
    path: str
    file_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    reference_scenario: str
    columns: dict[str, str]
    reference_region_definition: str = Field(min_length=1)
    metric_definitions: dict[str, str]
    relative_tolerance: float = Field(ge=0, le=1)


class ModelDiff(Command):
    properties: Ref
    other_properties: Ref
    region_field: Literal["zones", "FIPNUM", "EQLNUM", "SATNUM", "fault_blocks"]
    atol: float = Field(ge=0)
    rtol: float = Field(ge=0)
    max_examples: int = Field(default=100, ge=1, le=1000)
    assumptions: list[str] = Field(default_factory=list, max_length=100)


class PropertiesReference(Command):
    properties: Ref


class Volumetrics(Command):
    properties: Ref
    zone_ids: list[int] = Field(default_factory=lambda: [1], min_length=1)
    contact_z_m: float
    bo: float = Field(gt=0)


class Distribution(Strict):
    kind: Literal["constant", "uniform", "triangular"]
    low: float
    high: float | None = None
    mode: float | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.kind != "constant" and (self.high is None or self.high <= self.low):
            raise ValueError("high должен быть больше low")
        if self.kind == "triangular" and (self.mode is None or not self.low <= self.mode <= self.high):
            raise ValueError("mode вне low/high")
        return self


class ScenariosRun(Command):
    properties: Ref
    zone_ids: list[int] = [1]
    distributions: dict[Literal["phi", "ntg", "sw", "bo", "contact_z_m"], Distribution]
    count: int = Field(default=30, ge=1, le=1000)
    seed: int = Field(default=42, ge=0)
    bo: float = Field(default=1.2, gt=0)
    contact_z_m: float = -1020


class WellLogInput(Strict):
    ref: Ref
    md_curve: str
    property_curves: dict[Literal["phi", "ntg"], str]
    property_units: dict[Literal["phi", "ntg"], Literal["fraction", "percent"]]

    @model_validator(mode="after")
    def mappings(self):
        if not self.property_curves or self.property_curves.keys() != self.property_units.keys():
            raise ValueError("Explicit LAS curve and unit mapping required for each property")
        return self


class WellsVsModel(Command):
    properties: Ref
    trajectory: Ref
    logs: list[WellLogInput] = Field(min_length=1, max_length=1000)
    region_field: Literal["zones", "FIPNUM", "EQLNUM", "SATNUM", "fault_blocks"]
    max_survey_gap_m: float = Field(gt=0)
    boundary_policy: Literal["lowest_ijk", "reject"]
    sample_every_n: int = Field(default=1, ge=1, le=1000000)
    parameters_confirmed: Literal[True]
    assumptions: list[str] = Field(min_length=1, max_length=100)


class SensitivityParameter(Strict):
    region_id: int
    field: Literal["phi", "ntg", "sw", "owc_z_m", "goc_z_m", "bo", "bg"]
    mode: Literal["scalar_override", "multiplier"]
    low: float
    high: float
    distribution: Literal["uniform", "triangular", "truncated_normal", "truncated_lognormal"] | None = None
    mean: float | None = None
    stddev: float | None = Field(default=None, gt=0)
    mode_value: float | None = None
    mean_log: float | None = None
    stddev_log: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def bounds(self):
        if self.low >= self.high:
            raise ValueError("Parameter low must be below high")
        if self.field in {"bo", "bg"} and self.low <= 0:
            raise ValueError("Formation volume factors must be positive")
        if self.field in {"owc_z_m", "goc_z_m"} and self.mode != "scalar_override":
            raise ValueError("Contacts use explicit Z values, not datum-dependent multipliers")
        if self.field in {"phi", "ntg", "sw"} and (
            self.low < 0 or (self.mode == "scalar_override" and self.high > 1)
        ):
            raise ValueError("Property values must be fractions; multipliers nonnegative")
        if self.distribution == "triangular" and (
            self.mode_value is None or not self.low <= self.mode_value <= self.high
        ):
            raise ValueError("Triangular mode must be explicitly within bounds")
        if self.distribution == "truncated_normal" and (self.mean is None or self.stddev is None):
            raise ValueError("Normal mean and stddev required")
        if self.distribution == "truncated_lognormal" and (
            self.mean_log is None or self.stddev_log is None or self.low <= 0
        ):
            raise ValueError("Lognormal needs explicit log mean/stddev and positive lower bound")
        return self


class SensitivityTornado(RegionalVolumes):
    parameters: list[SensitivityParameter] = Field(min_length=1, max_length=30)
    metric: Literal["STOIIP", "GIIP"]
    max_cell_scenario_evaluations: int = Field(default=100000000, ge=1, le=1000000000000)

    @model_validator(mode="after")
    def baseline(self):
        if len(self.scenarios) != 1:
            raise ValueError("Choose exactly one explicit baseline scenario")
        regions = {r.region_id for r in self.scenarios[0].regions}
        keys = [(p.region_id, p.field) for p in self.parameters]
        if len(set(keys)) != len(keys) or any(p.region_id not in regions for p in self.parameters):
            raise ValueError("Unique parameters must reference baseline regions")
        return self


class UncertaintyMonteCarlo(SensitivityTornado):
    samples: int = Field(ge=2, le=10000)
    seed: int = Field(ge=0, le=9223372036854775807)
    correlation: list[list[float]]
    correlation_space: Literal["gaussian_copula"]

    @model_validator(mode="after")
    def distributions(self):
        n = len(self.parameters)
        if len(self.correlation) != n or any(len(row) != n for row in self.correlation):
            raise ValueError("Correlation matrix must match parameter count")
        if any(p.distribution is None for p in self.parameters):
            raise ValueError("Every Monte Carlo marginal distribution must be explicit")
        return self


class SyntheticSeismic(Command):
    shape: tuple[int, int, int] = (12, 16, 128)
    dt_seconds: float = Field(default=0.004, gt=0)
    velocity_m_s: float = Field(default=2000, gt=0)
    seed: int = Field(default=42, ge=0)

    @model_validator(mode="after")
    def limit(self):
        if any(n < 2 for n in self.shape) or math.prod(self.shape) > 10_000_000:
            raise ValueError("Недопустимый размер сейсмического куба")
        return self


class SeismicImport(Command):
    upload_id: str
    crs: str
    vertical_datum: str
    domain: Literal["twt", "depth"]
    sample_unit: Literal["ms", "m"]
    endian: Literal["big", "little"] = "big"
    inline_byte: int = Field(default=189, ge=1, le=237)
    crossline_byte: int = Field(default=193, ge=1, le=237)
    coordinate_unit: Literal["m", "ft"] = "m"

    @model_validator(mode="after")
    def domain_unit(self):
        if (self.domain == "twt") != (self.sample_unit == "ms"):
            raise ValueError("TWT требует ms, depth требует m")
        return self


class SeismicSourceImport(SeismicImport):
    upload_id: None = None
    source_id: str
    path: str = Field(min_length=1, max_length=1024)
    file_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class SeismicSlice(Command):
    volume: Ref
    axis: Literal["inline", "crossline", "sample"]
    index: int = Field(ge=0)


class SeismicAttribute(Command):
    volume: Ref
    attribute: Literal["rms", "envelope"]
    window: int = Field(default=9, ge=1, le=1001)

    @model_validator(mode="after")
    def odd(self):
        if self.window % 2 == 0:
            raise ValueError("Окно должно быть нечётным")
        return self


class Pick(Strict):
    inline: int
    crossline: int
    sample_index: float = Field(ge=0)


class InterpretationSave(Command):
    volume: Ref
    name: str = Field(min_length=1, max_length=100)
    picks: list[Pick] = Field(min_length=1, max_length=10000)
    previous: Ref | None = None


class HorizonConvert(Command):
    interpretation: Ref
    velocity_m_s: float | None = Field(default=None, gt=0)
    time_depth_table: list[tuple[float, float]] | None = None
    origin_z_m: float
    datum: str

    @model_validator(mode="after")
    def velocity_profile(self):
        if (self.velocity_m_s is None) == (self.time_depth_table is None):
            raise ValueError("Выберите constant velocity или одну time-depth table")
        if self.time_depth_table is not None:
            rows = self.time_depth_table
            if (
                len(rows) < 2
                or rows[0][0] < 0
                or rows[0][1] < 0
                or any(a[0] >= b[0] or a[1] >= b[1] for a, b in zip(rows, rows[1:]))
            ):
                raise ValueError("Time-depth table должна строго возрастать по TWT(s) и depth_difference(m)")
        return self


class Conditioning(Strict):
    positions: list[tuple[float, float, float]] = Field(min_length=2, max_length=2000)
    values: list[float]
    well_ids: list[str]

    @model_validator(mode="after")
    def lengths(self):
        if len(self.positions) != len(self.values) or len(self.values) != len(self.well_ids):
            raise ValueError("Длины conditioning arrays не совпадают")
        if len(set(self.positions)) != len(self.positions):
            raise ValueError("Дубли conditioning: предварительно выберите агрегацию")
        return self


class Geostat(Command):
    properties: Ref
    zone_id: int = Field(ge=1)
    field: Literal["phi", "permeability_md"]
    conditioning: Conditioning
    variance: float = Field(default=1, gt=0)
    length_scale_m: float = Field(default=300, gt=0)
    anisotropy: tuple[float, float] = (1, 1)
    seed: int = Field(default=42, ge=0)

    @model_validator(mode="after")
    def bounds(self):
        if any(v <= 0 for v in self.anisotropy):
            raise ValueError("Анизотропия должна быть положительной")
        if self.field == "phi" and any(not 0 < v < 1 for v in self.conditioning.values):
            raise ValueError("logit transform требует 0 < phi < 1")
        if self.field == "permeability_md" and any(v <= 0 for v in self.conditioning.values):
            raise ValueError("log transform требует K > 0; нули не подменяются")
        return self


class Fluid(Strict):
    standard_temperature_c: float = Field(default=15.56, gt=-273.15)
    standard_pressure_bara: float = Field(default=1.01325, gt=0)
    oil_density_kg_m3: float = Field(default=800, gt=0)
    water_density_kg_m3: float = Field(default=1000, gt=0)
    oil_viscosity_cp: float = Field(default=2, gt=0)
    water_viscosity_cp: float = Field(default=0.5, gt=0)
    bo: float = Field(default=1.2, gt=0)
    bw: float = Field(default=1, gt=0)
    reference_pressure_bara: float = Field(default=200, gt=0)
    rock_compressibility_per_bar: float = Field(default=0, ge=0)
    swof: list[tuple[float, float, float, float]] = [(0.2, 0, 1, 0), (1, 1, 0, 0)]

    @model_validator(mode="after")
    def scal(self):
        if len(self.swof) < 2 or any(a[0] >= b[0] for a, b in zip(self.swof, self.swof[1:])):
            raise ValueError("SWOF: минимум 2 строки, Sw строго возрастает")
        if any(not 0 <= v <= 1 for row in self.swof for v in row[:3]):
            raise ValueError("SWOF: Sw/krw/kro вне [0,1]")
        if any(b[1] < a[1] or b[2] > a[2] for a, b in zip(self.swof, self.swof[1:])):
            raise ValueError("SWOF: krw возрастает, kro убывает")
        return self


class SimulationCaseCreate(Command):
    properties: Ref
    profile: Literal["waterflood", "depletion", "no_flow"] = "waterflood"
    fluid: Fluid = Field(default_factory=Fluid)
    demo_assumptions_accepted: bool = False
    start_date: date = date(2026, 1, 1)
    report_days: list[float] = [30, 60, 90, 180, 365]
    producer_rate_sm3_day: float = Field(default=100, gt=0)
    injector_rate_sm3_day: float = Field(default=100, gt=0)
    producer_bhp_bara: float = Field(default=50, gt=0)
    injector_bhp_bara: float = Field(default=350, gt=0)

    @model_validator(mode="after")
    def schedule(self):
        if (
            not self.report_days
            or self.report_days[0] <= 0
            or any(a >= b for a, b in zip(self.report_days, self.report_days[1:]))
        ):
            raise ValueError("Даты отчётов положительные и строго возрастают")
        if self.producer_bhp_bara >= self.injector_bhp_bara:
            raise ValueError("BHP producer должен быть ниже BHP injector")
        return self


class SimulationSubmit(Command):
    case: Ref


class SimulationReference(Strict):
    """User-supplied reference summary (e.g. ECLIPSE results) in the same source folder."""

    smspec_path: str = Field(min_length=1, max_length=1024)
    smspec_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    data_path: str = Field(min_length=1, max_length=1024)
    data_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    vectors: list[str] = Field(min_length=1, max_length=200)
    relative_tolerance: float = Field(gt=0, le=1)


class SimulationDeckRun(Command):
    source_id: str
    path: str = Field(min_length=1, max_length=1024)
    file_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    threads: int = Field(default=1, ge=1, le=256)
    keep_restart: bool = False
    # low: OPM continues past unsupported keywords (it ignores them). Explicit, reported, never default.
    parsing_strictness: Literal["normal", "low"] = "normal"
    reference: SimulationReference | None = None
    parameters_confirmed: Literal[True]
    assumptions: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def deck_only(self):
        if not self.path.upper().endswith(".DATA"):
            raise ValueError("path: the main ECLIPSE-format deck must be a .DATA file")
        if self.reference and not self.reference.smspec_path.upper().endswith(".SMSPEC"):
            raise ValueError("reference: smspec_path must name an unformatted .SMSPEC file")
        return self


class SimulationSnapshot(Command):
    result: Ref
    report_index: int = Field(ge=0)
    field: Literal["pressure", "sw", "so", "sg"] = "pressure"
    axis: Literal["XY", "XZ", "YZ"] = "XY"
    index: int = Field(default=0, ge=0)


class Node(Strict):
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    operation: str
    arguments: dict
    depends_on: list[str] = []


class WorkflowSave(Command):
    name: str
    nodes: list[Node] = Field(min_length=1, max_length=100)


class WorkflowRun(Command):
    workflow: Ref
    parameters: dict = {}
    resume_run: Ref | None = None


class EnsemblePlan(Command):
    property_realizations: list[Ref] = Field(min_length=1, max_length=10)
    schedules: list[SimulationCaseCreate] = Field(min_length=1, max_length=10)
    expected_case_count: int = Field(ge=1, le=100)
    resume_ensemble: Ref | None = None

    @model_validator(mode="after")
    def explicit_product(self):
        refs = [(r.id, r.revision) for r in self.property_realizations]
        if len(refs) != len(set(refs)):
            raise ValueError("Property realization refs должны быть уникальны")
        if len(self.property_realizations) * len(self.schedules) != self.expected_case_count:
            raise ValueError("Подтвердите точное число сочетаний реализаций и schedules")
        return self


class Inspect(Strict):
    project_id: str
    ref: Ref


class JobRequest(Strict):
    job_id: str


class JobStatus(JobRequest):
    verbose: bool = False


class Diagnostics(Strict):
    lines: int = Field(default=60, ge=1, le=500)


class ComputeTargets(Strict):
    project_id: str | None = None
    properties: Ref | None = None
    operation: Literal[
        "model_qc",
        "model_diff",
        "regional_volumes",
        "volumes_reconcile",
        "sensitivity_tornado",
        "uncertainty_monte_carlo",
        "wells_vs_model",
        "volumetrics_calculate",
        "result_validate",
    ] = "regional_volumes"
    execution: Execution = Field(default_factory=Execution)

    @model_validator(mode="after")
    def project_required(self):
        if self.properties is not None and self.project_id is None:
            raise ValueError("project_id is required with properties")
        return self


class ProjectRequest(Strict):
    project_id: str


class SourceScan(Strict):
    source_id: str
    path: str = Field(default="", max_length=1024)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=200)
    listing_revision: str | None = None


class FolderAssess(Strict):
    source_id: str
    path: str = Field(default="", max_length=1024)
    max_depth: int = Field(default=3, ge=0, le=8)
    max_files: int = Field(default=200, ge=1, le=500)


class SourceUpload(Strict):
    project_id: str
    source_id: str
    path: str = Field(min_length=1, max_length=1024)
    file_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class MetricConstraint(Strict):
    metric: Literal["FOPT", "FWPT", "FWIT", "WATER_CUT", "FPR"]
    unit: str
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def bounds(self):
        if self.minimum is None and self.maximum is None:
            raise ValueError("Нужна минимум одна граница ограничения")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum больше maximum")
        return self


class Compare(Command):
    results: list[Ref] = Field(default_factory=list, max_length=100)
    ensemble: Ref | None = None
    allow_partial: bool = False
    metric: Literal["auto", "STOIIP", "FOPT", "FWPT", "FWIT", "WATER_CUT", "FPR"] = "auto"
    dates: list[AwareDatetime] | None = Field(default=None, min_length=1, max_length=1000)
    report_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def selection(self):
        if bool(self.results) == bool(self.ensemble):
            raise ValueError("Выберите явные results или один ensemble")
        return self


class DevelopmentRank(Compare):
    direction: Literal["maximize", "minimize"] = "maximize"
    constraints: list[MetricConstraint] = Field(default_factory=list, max_length=10)
    results: list[Ref] = Field(min_length=1, max_length=10)
    ensemble: None = None


class SceneShow(Command):
    ref: Ref
    visible: bool = True
    opacity: float = Field(default=1, ge=0, le=1)
    vertical_exaggeration: float = Field(default=1, gt=0, le=100)
    field: Literal["zones", "phi", "ntg", "sw", "permeability_md", "kz_ratio"] = "zones"
    selected: bool = False
    stride: int = Field(default=1, ge=1, le=1000000)
    cell_range: tuple[int, int] | None = None
    seismic_axis: Literal["inline", "crossline", "sample"] = "inline"
    slice_index: int = Field(default=0, ge=0)
    velocity_m_s: float | None = Field(default=None, gt=0)
    origin_z_m: float | None = None

    @model_validator(mode="after")
    def selection(self):
        if self.cell_range and not 0 <= self.cell_range[0] < self.cell_range[1]:
            raise ValueError("cell_range needs 0 <= start < end")
        return self


class SceneExport(Command):
    max_cells: int = Field(default=100000, ge=1, le=200000)
    max_points: int = Field(default=250000, ge=1, le=500000)


class SnapshotImport(Command):
    plan: Ref
    input_index: int = Field(ge=0, le=5)


class ResultValidate(Command):
    artifact: Ref


class ResultsExport(Command):
    slices: list[Ref] = Field(default_factory=list, max_length=10)
    reports: list[Ref] = Field(min_length=1, max_length=20)
    formats: list[Literal["xlsx", "pdf"]] = Field(
        default_factory=lambda: ["xlsx", "pdf"], min_length=1, max_length=2
    )
    title: str = Field(default="Kanysh Basic results", min_length=1, max_length=200)
    max_pdf_rows_per_table: int = Field(default=100, ge=1, le=1000)
    notes: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_formats(self):
        if len(set(self.formats)) != len(self.formats):
            raise ValueError("Duplicate export formats")
        return self


class ReportExport(Command):
    run_id: str


OPERATION_SCHEMAS = {
    "results_export": ResultsExport,
    "sensitivity_tornado": SensitivityTornado,
    "uncertainty_monte_carlo": UncertaintyMonteCarlo,
    "wells_vs_model": WellsVsModel,
    "regional_volumes": RegionalVolumes,
    "volumes_reconcile": VolumesReconcile,
    "model_diff": ModelDiff,
    "model_qc": ModelQC,
    "geodata_import": GeodataImport,
    "eclipse_import": EclipseImport,
    "scene_export": SceneExport,
    "seismic_source_import": SeismicSourceImport,
    "grid_import": GridImport,
    "properties_reference": PropertiesReference,
    "dataset_import_snapshot": SnapshotImport,
    "result_validate": ResultValidate,
    "report_export": ReportExport,
    "dataset_import": DatasetImport,
    "model_build": ModelBuild,
    "fault_create": FaultCreate,
    "properties_assign": PropertiesAssign,
    "volumetrics_calculate": Volumetrics,
    "scenarios_run": ScenariosRun,
    "seismic_generate": SyntheticSeismic,
    "seismic_import": SeismicImport,
    "seismic_slice": SeismicSlice,
    "seismic_attribute": SeismicAttribute,
    "interpretation_save": InterpretationSave,
    "horizon_convert_domain": HorizonConvert,
    "variogram_fit": Geostat,
    "properties_krige": Geostat,
    "properties_simulate": Geostat,
    "simulation_case_create": SimulationCaseCreate,
    "simulation_submit": SimulationSubmit,
    "simulation_deck_run": SimulationDeckRun,
    "simulation_snapshot": SimulationSnapshot,
    "workflow_save": WorkflowSave,
    "workflow_run": WorkflowRun,
    "ensemble_plan": EnsemblePlan,
    "ensemble_run": EnsemblePlan,
    "scenarios_compare": Compare,
    "simulation_compare": Compare,
    "development_rank": DevelopmentRank,
    "ensemble_compare": Compare,
    "scene_show": SceneShow,
}
