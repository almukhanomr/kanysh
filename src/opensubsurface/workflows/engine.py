import graphlib

from opensubsurface.errors import require
from opensubsurface.schemas import OPERATION_SCHEMAS

ALLOWED = set(OPERATION_SCHEMAS) - {
    "workflow_save",
    "workflow_run",
    "ensemble_run",
    "ensemble_plan",
    "scene_show",
}


def references(value):
    result = []
    if isinstance(value, dict):
        if set(value) == {"$node"}:
            result.append(value["$node"])
        else:
            for v in value.values():
                result.extend(references(v))
    elif isinstance(value, list):
        for v in value:
            result.extend(references(v))
    return result


def validate(nodes):
    ids = [node["id"] for node in nodes]
    require(len(ids) == len(set(ids)), "INVALID_WORKFLOW", "Duplicate node IDs")
    graph = {}
    for node in nodes:
        require(
            node["operation"] in ALLOWED, "INVALID_WORKFLOW", "Operation is not allowed in a workflow DAG"
        )
        deps = set(node["depends_on"]) | set(references(node["arguments"]))
        require(deps <= set(ids), "INVALID_WORKFLOW", "Unknown dependency")
        graph[node["id"]] = deps
        # Validate fully concrete nodes now. Nodes with references validated after resolution.
    try:
        order = list(graphlib.TopologicalSorter(graph).static_order())
        validate_port_kinds(nodes)
        return order
    except graphlib.CycleError:
        require(False, "INVALID_WORKFLOW", "Cycle in workflow")


def resolve(value, outputs, parameters, run_id="pending-run"):
    if isinstance(value, dict):
        if value == {"$run_id": True}:
            return run_id
        if set(value) == {"$node"}:
            require(value["$node"] in outputs, "INVALID_WORKFLOW", "Dependency output is not available yet")
            return outputs[value["$node"]]
        if set(value) == {"$parameter"}:
            require(value["$parameter"] in parameters, "INVALID_WORKFLOW", "Missing run parameter")
            return parameters[value["$parameter"]]
        return {k: resolve(v, outputs, parameters, run_id) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, outputs, parameters, run_id) for v in value]
    return value


OUTPUT_KINDS = {
    "grid_import": "properties",
    "properties_reference": "properties",
    "dataset_import_snapshot": "dataset",
    "result_validate": "validation",
    "report_export": "calculation_report",
    "dataset_import": "dataset",
    "fault_create": "fault",
    "model_build": "model",
    "properties_assign": "properties",
    "volumetrics_calculate": "volumetrics",
    "scenarios_run": "scenarios",
    "seismic_generate": "seismic",
    "seismic_import": "seismic",
    "seismic_slice": "seismic_slice",
    "seismic_attribute": "seismic",
    "interpretation_save": "interpretation",
    "horizon_convert_domain": "dataset",
    "variogram_fit": "properties",
    "properties_krige": "properties",
    "properties_simulate": "properties",
    "simulation_case_create": "simulation_case",
    "simulation_submit": "simulation_result",
    "simulation_snapshot": "simulation_snapshot",
    "scenarios_compare": "comparison",
    "simulation_compare": "comparison",
    "ensemble_compare": "comparison",
    "development_rank": "comparison",
}
PORT_KINDS = {
    "plan": "calculation_plan",
    "surfaces": "dataset",
    "orientations": "dataset",
    "model": "model",
    "properties": "properties",
    "fault": "fault",
    "volume": "seismic",
    "interpretation": "interpretation",
    "case": "simulation_case",
    "result": "simulation_result",
}


def validate_port_kinds(nodes):
    outputs = {node["id"]: OUTPUT_KINDS[node["operation"]] for node in nodes}
    for node in nodes:
        for key, value in node["arguments"].items():
            if key in PORT_KINDS and isinstance(value, dict) and set(value) == {"$node"}:
                require(
                    outputs[value["$node"]] == PORT_KINDS[key],
                    "TYPE_MISMATCH",
                    f"Wrong link type {value['$node']} -> {node['id']}.{key}",
                )
            if key == "results" and isinstance(value, list):
                kinds = [outputs[v["$node"]] for v in value if isinstance(v, dict) and set(v) == {"$node"}]
                require(
                    all(k in ("volumetrics", "simulation_result") for k in kinds) and len(set(kinds)) <= 1,
                    "TYPE_MISMATCH",
                    "Comparison requires results of one kind",
                )


def artifact_refs(value):
    if isinstance(value, dict):
        if set(value) == {"id", "revision"}:
            yield value
        else:
            for v in value.values():
                yield from artifact_refs(v)
    elif isinstance(value, list):
        for v in value:
            yield from artifact_refs(v)
