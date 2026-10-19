from typing import Literal

from pydantic import Field, model_validator

from opensubsurface.schemas import Distribution, Execution, Grid, Ref, Strict, Zone


class SourceInspect(Strict):
    source_id: str
    path: str = Field(min_length=1, max_length=1024)
    file_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    preview_rows: int = Field(default=0, ge=0, le=5)


class Input(Strict):
    kind: Literal["surfaces", "orientations", "collars"]
    source_id: str
    path: str
    file_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    units: dict[str, str] = Field(default_factory=dict)


class Contact(Strict):
    name: str = Field(min_length=1, max_length=80)
    z_m: float


class Uncertainty(Strict):
    contact_name: str
    distributions: dict[Literal["phi", "ntg", "sw", "bo", "contact_z_m"], Distribution] = Field(min_length=1)
    count: int = Field(ge=2, le=200)
    seed: int = Field(ge=0)


class CalculationPlan(Strict):
    project_id: str
    name: str = Field(default="Static volumetrics", min_length=1, max_length=120)
    profile: Literal["static_volumetrics_v1"] = "static_volumetrics_v1"
    properties: Ref | None = None
    grid: Grid | None = None
    method: Literal["horizontal_explicit", "gempy"] | None = None
    horizontal_assumption: bool | None = None
    horizons_z: list[float] = Field(default_factory=list)
    stratigraphic_order: list[str] = Field(default_factory=list)
    inputs: list[Input] = Field(default_factory=list, max_length=6)
    zones: dict[int, Zone] | None = None
    zone_ids: list[int] | None = Field(default=None, min_length=1)
    bo: float | None = Field(default=None, gt=0)
    contacts: list[Contact] | None = Field(default=None, min_length=1, max_length=10)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    uncertainty: Uncertainty | None = None
    execution: Execution = Field(default_factory=Execution)

    @model_validator(mode="after")
    def distinct(self):
        if self.contacts and len({c.name for c in self.contacts}) != len(self.contacts):
            raise ValueError("Contact variant names must be unique")
        if len({i.kind for i in self.inputs}) != len(self.inputs):
            raise ValueError("One file per kind; merge the source tables explicitly")
        if self.zone_ids and (len(set(self.zone_ids)) != len(self.zone_ids) or min(self.zone_ids) < 1):
            raise ValueError("Select unique positive zone_ids")
        return self


class PlanRequest(Strict):
    project_id: str
    plan: Ref


class CalculationRun(PlanRequest):
    idempotency_key: str | None = Field(default=None, max_length=120)
    resume_run: Ref | None = None


class RunRequest(Strict):
    project_id: str
    run_id: str


class ResultPreview(Strict):
    project_id: str
    report: Ref
