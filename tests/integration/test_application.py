import pytest

from opensubsurface.errors import DomainError
from opensubsurface.service import ref


def test_demo_job_provenance_and_scenarios(service, demo):
    pid = demo["project"]["id"]
    assert demo["volumetrics"]["summary"]["values"]["STOIIP"] == pytest.approx(2e6)
    result = service.wait(
        service.invoke(
            "scenarios_run",
            dict(
                project_id=pid,
                properties=demo["properties"],
                distributions={"phi": dict(kind="uniform", low=0.15, high=0.25)},
                count=30,
                seed=8,
            ),
        )
    )
    result2 = service.wait(
        service.invoke(
            "scenarios_run",
            dict(
                project_id=pid,
                properties=demo["properties"],
                distributions={"phi": dict(kind="uniform", low=0.15, high=0.25)},
                count=30,
                seed=8,
            ),
        )
    )
    assert result["files"]["samples.json"] == result2["files"]["samples.json"]
    assert result["parameters"]["environment"]["device"] == "cpu"
    assert result["summary"]["statistics"]["P90"] < result["summary"]["statistics"]["P10"]


def test_seismic_picks_and_conversion(service, demo):
    pid = demo["project"]["id"]
    volume = service.wait(service.invoke("seismic_generate", dict(project_id=pid)))
    pick = service.wait(
        service.invoke(
            "interpretation_save",
            dict(
                project_id=pid,
                volume=ref(volume),
                name="H1",
                picks=[dict(inline=1, crossline=2, sample_index=25)],
            ),
        )
    )
    converted = service.wait(
        service.invoke(
            "horizon_convert_domain",
            dict(
                project_id=pid,
                interpretation=ref(pick),
                velocity_m_s=2000,
                origin_z_m=0,
                datum="SYNTHETIC_ORIGIN",
            ),
        )
    )
    import pyarrow.parquet as pq

    table = pq.read_table(service.store.path(converted, "data.parquet")).to_pylist()
    assert table[0]["z"] == pytest.approx(-100)
    revised = service.wait(
        service.invoke(
            "interpretation_save",
            dict(
                project_id=pid,
                volume=ref(volume),
                name="H1",
                previous=ref(pick),
                picks=[dict(inline=1, crossline=2, sample_index=30)],
            ),
        )
    )
    assert revised["id"] == pick["id"] and revised["revision"] == 2
    assert service.store.object(pid, ref(pick))["revision"] == 1


def test_workflow_fanout_resume_and_input_invalidation(service, demo):
    pid = demo["project"]["id"]
    definition = service.invoke(
        "workflow_save",
        dict(
            project_id=pid,
            name="Two contacts",
            nodes=[
                dict(
                    id="a",
                    operation="volumetrics_calculate",
                    arguments=dict(
                        project_id=pid,
                        properties={"$parameter": "properties"},
                        contact_z_m={"$parameter": "contact"},
                        bo=1.2,
                    ),
                ),
                dict(
                    id="b",
                    operation="volumetrics_calculate",
                    arguments=dict(project_id=pid, properties=demo["properties"], contact_z_m=-1010, bo=1.2),
                ),
                dict(
                    id="compare",
                    operation="scenarios_compare",
                    depends_on=["a", "b"],
                    arguments=dict(project_id=pid, results=[{"$node": "a"}, {"$node": "b"}]),
                ),
            ],
        ),
    )
    args = dict(
        project_id=pid,
        workflow=ref(definition),
        parameters=dict(properties=demo["properties"], contact=-1020),
    )
    first = service.wait(service.invoke("workflow_run", args))
    second = service.wait(service.invoke("workflow_run", dict(args, resume_run=ref(first))))
    assert all(n["reused"] for n in second["summary"]["nodes"].values())
    changed = dict(
        args, parameters=dict(properties=demo["properties"], contact=-1015), resume_run=ref(second)
    )
    third = service.wait(service.invoke("workflow_run", changed))
    assert third["summary"]["nodes"]["b"]["reused"]
    assert not third["summary"]["nodes"]["a"]["reused"]
    assert not third["summary"]["nodes"]["compare"]["reused"]


def test_invalid_workflow_and_no_silent_gpu_fallback(service, demo):
    pid = demo["project"]["id"]
    with pytest.raises(DomainError, match="Цикл"):
        service.invoke(
            "workflow_save",
            dict(
                project_id=pid,
                name="Cycle",
                nodes=[
                    dict(id="a", operation="volumetrics_calculate", arguments={}, depends_on=["b"]),
                    dict(id="b", operation="volumetrics_calculate", arguments={}, depends_on=["a"]),
                ],
            ),
        )
    with pytest.raises(DomainError, match="CUDA"):
        service.invoke(
            "properties_assign",
            dict(project_id=pid, model=demo["model"], zones={}, execution=dict(device_policy="require_gpu")),
        )


def test_opm_export_ntg_and_unavailable_solver(service, demo, monkeypatch):
    pid = demo["project"]["id"]
    case = service.wait(
        service.invoke(
            "simulation_case_create",
            dict(project_id=pid, properties=demo["properties"], demo_assumptions_accepted=True),
        )
    )
    text = service.store.path(case, "CASE.DATA").read_text()
    assert "NTG\n" in text and "PORO\n" in text and "WCONINJE" in text
    assert case["summary"]["input_pore_volume_m3"] == pytest.approx(3.2e6)
    monkeypatch.setenv("OPENSUBSURFACE_FLOW_EXECUTABLE", "no-such-flow-binary")
    with pytest.raises(DomainError, match="не установлен|requires Linux/WSL"):
        service.wait(service.invoke("simulation_submit", dict(project_id=pid, case=ref(case))))


def test_demo_wells_shared_import_and_marker_xyz(service, demo_wells):
    import pyarrow.parquet as pq

    project = service.invoke("project_create", dict(name="Wells", vertical_datum="SYNTHETIC_MSL"))
    result = demo_wells(service, project["id"])
    assert len(result["created"]) == 5
    objects = service.store.list_objects(project["id"])
    markers = next(o for o in objects if o["summary"].get("kind") == "markers")
    rows = pq.read_table(service.store.path(markers, "data.parquet")).to_pylist()
    assert rows[0]["z"] == -1000 and rows[0]["x"] == 250
    logs = [o for o in objects if o["summary"].get("kind") == "las"]
    assert len(logs) == 2
    assert all(o["summary"]["null_fraction"]["PHI"] > 0 for o in logs)


def test_workflow_rejects_wrong_ports_and_missing_params_before_children(service, demo):
    pid = demo["project"]["id"]
    with pytest.raises(DomainError, match="тип связи"):
        service.invoke(
            "workflow_save",
            dict(
                project_id=pid,
                name="Bad ports",
                nodes=[
                    dict(
                        id="m",
                        operation="model_build",
                        arguments=dict(project_id=pid, horizontal_assumption=True),
                    ),
                    dict(
                        id="v",
                        operation="volumetrics_calculate",
                        arguments=dict(project_id=pid, properties={"$node": "m"}, bo=1.2, contact_z_m=-1020),
                    ),
                ],
            ),
        )
    workflow = service.invoke(
        "workflow_save",
        dict(
            project_id=pid,
            name="Missing parameter",
            nodes=[
                dict(
                    id="v",
                    operation="volumetrics_calculate",
                    arguments=dict(
                        project_id=pid, properties={"$parameter": "props"}, bo=1.2, contact_z_m=-1020
                    ),
                )
            ],
        ),
    )
    before = len(service.store.list_jobs(pid))
    with pytest.raises(DomainError, match="параметра"):
        service.invoke("workflow_run", dict(project_id=pid, workflow=ref(workflow)))
    assert len(service.store.list_jobs(pid)) == before


def test_bounded_retry_preserves_request_and_attempt_ledger(service, monkeypatch):
    from pathlib import Path

    import opensubsurface.service as service_module
    from opensubsurface.execution.runner import run_isolated as real_runner

    def once_crashing(directory, timeout):
        marker = Path(directory).parent / "crashed-once"
        if not marker.exists():
            marker.touch()
            return dict(ok=False, error=dict(code="WORKER_CRASH", message="Injected transient worker crash"))
        return real_runner(directory, timeout)

    monkeypatch.setattr(service_module, "run_isolated", once_crashing)
    project = service.invoke("project_create", dict(name="Retry", vertical_datum="TEST"))
    submission = service.invoke(
        "model_build",
        dict(project_id=project["id"], horizontal_assumption=True, execution=dict(max_retries=1)),
    )
    service.wait(submission)
    job = service.store.job(submission["job_id"])
    assert len(job["attempts"]) == 2
    assert job["attempts"][0]["status"] == "failed"
    assert job["attempts"][0]["id"] != job["attempts"][1]["id"]
    requests = [
        (service.store.root / "attempts" / a["id"] / "request.json").read_bytes() for a in job["attempts"]
    ]
    assert requests[0] == requests[1]


def test_lost_job_becomes_interrupted_after_restart(service):
    project = service.invoke("project_create", dict(name="Restart", vertical_datum="TEST"))
    job, _ = service.store.put_job("model_build", dict(project_id=project["id"], horizontal_assumption=True))
    service.store.update_job(job["id"], status="running")
    service.start()
    assert service.store.job(job["id"])["status"] == "interrupted"
