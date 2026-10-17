"""MCP onboarding content. No scientific defaults or automatic model selection."""

SCENARIOS = {
    "check_model": (
        "Check model",
        "folder_assess → confirm CRS, datum, units, active mask and import limitations → import → model_qc → job_status → report. Ask which revision and region field to check. Show severity, IJK witnesses and NOT RUN checks; numerical PASS is not geological approval.",
    ),
    "regional_volumes": (
        "Regional volumes",
        "folder_assess → ask user to confirm file/line proposals → import → model_qc → regional_volumes → report. Ask region definition and selection, OWC/GOC sign/datum, Bo/Bg and residual oil/gas saturations, Sw source or explicit height-function parameters, polygon policy if applicable. Do not invent constants. Set parameters_confirmed only after the user's confirmation.",
    ),
    "reconcile_petrel": (
        "Reconcile Petrel/RMS report",
        "Confirm model revision, CSV column mapping, units, region and metric definitions, contacts, Bo and NTG/ACTNUM convention. Run regional checks then volumes_reconcile. Report differences and distinguish evidence from possible causes; do not auto-adjust inputs to match.",
    ),
    "tornado_analysis": (
        "Tornado analysis",
        "Confirm complete regional baseline and each parameter's region, low/high and override/multiplier meaning. Run sensitivity_tornado and inspect independent checks. Ask for distributions, seed and Gaussian-copula correlations separately before uncertainty_monte_carlo. Preserve failed draws; explain P90=Q10 and conditional percentiles.",
    ),
    "compare_versions": (
        "Compare revisions",
        "Ask for two immutable property revisions, equal IJK topology/CRS/datum, region field and numerical tolerances. Run model_diff → report. Show changed properties/cells and GRV/PV/HCPV impacts; contacts and Bo are not implied so STOIIP impact is NOT RUN.",
    ),
}


def welcome(service):
    empty = not service.store.list_projects()
    return dict(
        first_connection=empty,
        message="Kanysh Basic is an AI copilot for geological-model calculations alongside Petrel/RMS. Open exchanged models, run explicit scenarios and independently check numerical results from your MCP chat.",
        next_steps=[
            dict(
                action="demo",
                instruction="Open the local viewer and choose ‘Open Norne demo’. This opens saved public evidence; no fresh calculation is implied.",
            ),
            dict(
                action="own_folder",
                instruction="In the local viewer choose ‘Add folder’, or use owner CLI source-add. Then call source_list and folder_assess.",
            ),
        ],
        safety="Confirm source-derived proposals (file and line) with the user before any plan or calculation. No missing scientific constant is guessed.",
        export_guide="opensubsurface://docs/petrel-export",
        compute_started=False,
        external_client_acceptance="NOT RUN",
    )
