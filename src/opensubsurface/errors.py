# Agents act on remediation; codes raised without one get a generic next step.
DEFAULT_REMEDIATION = {
    "NOT_FOUND": "Use ids exactly as returned earlier: project_list, project_inspect (artifacts and jobs) or the job_id of the submitting tool.",
    "INPUT_REVISION_CONFLICT": "Use {id, revision} exactly as listed by project_inspect or returned by the producing tool; artifacts are immutable and revisions are not guessed.",
    "INVALID_SOURCE_PATH": "Use a '/'-separated path relative to the source root as listed by source_scan or folder_assess.",
    "SOURCE_CHANGED": "The file changed since discovery: run source_scan or folder_assess again and use the new file_revision.",
    "QC_FAILED": "The input failed a scientific check named in the message; correct the source data or ask the user for the missing or corrected value. Checks are never relaxed and values are never inferred.",
    "INVALID_FORMAT": "The file does not match the declared format; check it with source_inspect and declare the correct format or export it again from the source application.",
    "UNSUPPORTED_PROFILE": "The input is outside the supported profile named in the message; convert or export it to a supported profile (see the tool description) instead of retrying unchanged.",
    "TYPE_MISMATCH": "Pass an artifact of the kind named in the message; check kinds with project_inspect or artifact_inspect.",
    "GRID_MAPPING_ERROR": "Grid dimensions, ACTNUM or cell mapping disagree between inputs; use inputs produced from the same model revision and check them with model_qc.",
    "INVALID_RESULTS": "The result data failed validation; inspect job_logs for the producing job and rerun it with corrected inputs. Invalid results are not repaired automatically.",
    "INVALID_UNITS": "Declare the unit of every value explicitly (see this tool's inputSchema); units are never inferred.",
    "INVALID_ARCHIVE": "The project archive is malformed or unsafe; export it again from the source installation and import the unmodified ZIP.",
    "INTEGRITY_ERROR": "Stored bytes do not match their recorded hash; restore the durable store from a backup or recreate the artifact from its sources.",
    "INCOMPLETE_OUTPUT": "The run did not produce all required outputs; inspect job_logs and rerun. Incomplete outputs stay marked INCOMPLETE and are never promoted.",
    "INVALID_PLAN": "Create a new plan with calculation_plan, answer every NEEDS_INPUT question with the user, then validate it with plan_validate.",
    "INVALID_ARGUMENTS": "Correct the named field; every field, unit and allowed value is described in this tool's inputSchema.",
    "UNSUPPORTED_FORMAT": "Use one of the file formats listed in the tool description; check the file with source_scan.",
    "INVALID_CRS": "Ask the user for the project's projected metric CRS (EPSG code or WKT); it is never inferred.",
    "MISSING_DATUM": "Ask the user for the vertical datum and pass the same datum as the project; it is never inferred.",
    "PERMISSION_DENIED": "Use refs that belong to the same project (project_inspect lists them).",
    "INVALID_WORKFLOW": "Fix the workflow definition named in the message: unique node ids, allowed operations, known dependencies and no cycles.",
    "SOURCE_ACCESS_DENIED": "The owner must register a regular folder (no symlinks) with `kanysh-basic source-add`; then use source_list.",
    "UNSUPPORTED_GRID_BRIDGE": "This grid cannot be passed to the Cartesian OPM bridge; use a supported model or run the user's own deck with simulation_deck_run.",
    "INVALID_COMPARISON": "Select explicit, distinct cases with a common calendar range and consistent standard conditions; allow a partial report only if the user agrees.",
    "INVALID_PVT": "Ask the user for physically valid PVT inputs; PVT values are never inferred.",
    "AMBIGUOUS_GEOMETRY": "Declare the header mapping or geometry rule explicitly; ambiguous geometry is not resolved automatically.",
    "UPLOAD_TOO_LARGE": "Use a file within the stated limit or a streaming import (grid_import, eclipse_import, seismic_source_import) that reads directly from the source.",
    "RESULT_READER_UNAVAILABLE": "Install Kanysh Basic with the solver extra (resdata); see diagnostics for installed components.",
    "MISSING_VECTOR": "The requested vector or field is not in the result; list the available ones with artifact_inspect.",
    "UNSUPPORTED_OPERATION": "Use an operation listed by this server's tools; check spelling against the tool description.",
    "MISSING_ORIENTATIONS": "Provide orientations, or set horizontal_assumption=true only after the user explicitly confirms horizontal layers.",
    "NO_RESULTS": "No completed results are available for the selection; check job_status of each case and rerun failed ones.",
    "HEADER_TOO_LARGE": "The CSV header line is too large to read safely; check that the file is a CSV with a normal header line.",
    "INVALID_CSV": "Use a UTF-8 CSV with a header row; check it with source_inspect.",
    "RUN_NOT_READY": "Wait until job_status shows the run is running or finished, then retry.",
    "INVALID_PATH": "Use a plain file name without directory components.",
    "IDEMPOTENCY_CONFLICT": "Use a new idempotency key for a different request, or resend the original request unchanged.",
    "CONTROL_PLANE_ACTIVE": "Another Kanysh Basic control plane is running for this store; use it, or stop it before starting a new one.",
    "TIMEOUT": "The job is still running; check job_status later instead of waiting synchronously.",
    "CANCELLED": "The job was cancelled; submit it again if the result is still needed.",
    "ENSEMBLE_FAILED": "Inspect job_logs of the ensemble job; partial results remain marked and can be resumed with resume_ensemble.",
    "CANCEL_TIMEOUT": "Child jobs did not confirm stopping; check job_status of the listed jobs and cancel them with job_cancel.",
    "RESOURCE_TOO_LARGE": "Use results_export or report_export for large outputs instead of reading the resource directly.",
}


class DomainError(Exception):
    def __init__(self, code: str, message: str, field: str = "", remediation: str = "", details=None):
        super().__init__(message)
        self.code, self.message, self.field, self.remediation = code, message, field, remediation
        self.details = details

    def __reduce__(self):
        # Process workers must preserve structured domain errors across spawn/IPC.
        return type(self), (self.code, self.message, self.field, self.remediation, self.details)

    def as_dict(self):
        result = {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "remediation": self.remediation or DEFAULT_REMEDIATION.get(self.code, ""),
        }
        if self.details is not None:
            result["details"] = self.details
        return result


def require(condition, code, message, field="", remediation="", details=None):
    if not condition:
        raise DomainError(code, message, field, remediation, details)


def json_path(loc):
    path = ""
    for part in loc:
        path += f"[{part}]" if isinstance(part, int) else ("." if path else "") + str(part)
    return path


def validation_error(error):
    """Name every offending field by JSON path; model validators prefix messages with the field."""
    import re

    fields = []
    for item in error.errors(include_url=False):
        loc = [part for part in item["loc"] if part not in ("function-after", "function-before")]
        message = item["msg"].removeprefix("Value error, ")
        named = re.match(r"^([a-z][a-z0-9_]*): (.+)$", message, re.S)
        if named and item["type"] == "value_error":
            loc, message = [*loc, named[1]], named[2]
        fields.append(dict(field=json_path(loc), message=message, type=item["type"]))
    return dict(
        code="INVALID_ARGUMENTS",
        message="; ".join(f"{f['field'] or 'request'}: {f['message']}" for f in fields),
        field=fields[0]["field"] if fields else "",
        fields=fields,
        remediation="Correct the listed fields; every field, unit and allowed value is described in this "
        "tool's inputSchema. Z is positive upward (depth 2692 m -> -2692).",
    )
