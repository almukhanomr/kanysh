import copy
import io
import struct

import numpy as np
import pytest
import zarr
from test_copilot_analyses import model, params, sensitivity_params

from opensubsurface.adapters.eclipse_binary import records
from opensubsurface.adapters.eclipse_import import import_deck
from opensubsurface.adapters.local_sources import LocalSources, path_revision
from opensubsurface.adapters.model_diff import run as diff
from opensubsurface.adapters.model_qc import run as qc
from opensubsurface.adapters.regional_volumes import evaluate, evaluate_many
from opensubsurface.calculations.cornerpoint_reference import integral, reference
from opensubsurface.errors import DomainError
from opensubsurface.execution.resources import disk_check, memory_check, plan


def partitioned(tmp_path):
    obj = model(tmp_path)
    path = tmp_path / "partitioned.zip"
    with zarr.ZipStore(obj["paths"]["grid.zip"], mode="r") as old, zarr.ZipStore(str(path), mode="w") as new:
        source = zarr.open_group(old)
        target = zarr.group(new)
        target.attrs.update(dict(source.attrs))
        for name, array in source.arrays():
            target.create_dataset(name, data=array[:], chunks=(2, 8, 3) if name == "corners" else (2,))
    obj["paths"]["grid.zip"] = str(path)
    obj["summary"]["block_cells"] = 2
    return obj


def _abrupt_block(start, data, order):
    import os

    if start == 2:
        os._exit(17)
    return start


def _delayed_block(start, data, order):
    import time

    time.sleep((6 - start) * 0.03)
    return start


def test_process_channels_order_and_abrupt_exit_cleanup(tmp_path):
    import multiprocessing

    from opensubsurface.execution.blocks import mapped

    obj = partitioned(tmp_path)
    before = {p.pid for p in multiprocessing.active_children()}
    assert list(mapped(obj, _delayed_block, execution=dict(max_workers=3))) == [0, 2, 4]
    with pytest.raises(DomainError) as error:
        list(mapped(obj, _abrupt_block, execution=dict(max_workers=3)))
    assert error.value.code == "WORKER_CRASH"
    assert error.value.field == "execution.max_workers"
    assert not ({p.pid for p in multiprocessing.active_children()} - before)


def test_regional_and_reference_bitwise_workers(tmp_path):
    obj = partitioned(tmp_path)
    p = params()
    p["execution"] = dict(max_workers=1)
    one = evaluate(obj, p)
    p["execution"]["max_workers"] = 3
    many = evaluate(obj, p)
    assert one["tables"] == many["tables"]
    assert one["independent_checks"] == many["independent_checks"]
    from opensubsurface.execution.blocks import settings

    case = [dict(zone_ids=[1, 2], contact_z_m=5.0, bo=1.2)]
    token = settings.set(dict(max_workers=1))
    try:
        a = reference(obj, case)
        settings.set(dict(max_workers=3))
        assert a == reference(obj, case)
    finally:
        settings.reset(token)


def test_qc_diff_determinism_including_csv(tmp_path):
    obj = partitioned(tmp_path)
    for run, p, filename in (
        (
            lambda p, out: qc(obj, p, out),
            dict(region_field="FIPNUM", small_cluster_cells=6, max_examples=100, assumptions=[]),
            "issues.csv",
        ),
        (
            lambda p, out: diff(obj, obj, p, out),
            dict(region_field="FIPNUM", max_examples=100, rtol=1e-8, atol=1e-7, assumptions=[]),
            "changed_cells.csv",
        ),
    ):
        results = []
        for workers in (1, 3):
            out = tmp_path / f"{filename}-{workers}"
            out.mkdir()
            results.append(
                (run(dict(p, execution=dict(max_workers=workers)), out), (out / filename).read_bytes())
            )
        assert results[0] == results[1]


def test_evaluate_many_reads_one_pass_and_keeps_invalid_draws(tmp_path, monkeypatch):
    from opensubsurface.adapters import model_arrays

    obj = partitioned(tmp_path)
    good = params()
    good["execution"] = dict(max_workers=1)
    bad = copy.deepcopy(good)
    bad["scenarios"][0]["regions"][0]["phi_override"] = 2
    original, calls = model_arrays.iterate, []

    def counted(obj, **kwargs):
        calls.append(1)
        yield from original(obj, **kwargs)

    monkeypatch.setattr(model_arrays, "iterate", counted)
    result = evaluate_many(obj, [good, bad, good])
    assert len(calls) == 1
    assert result[0] == result[2]
    assert isinstance(result[1], DomainError) and result[1].code == "INVALID_PROPERTY"


def write_binary(path, entries, endian=">"):
    with path.open("wb") as stream:

        def record(data):
            marker = struct.pack(endian + "i", len(data))
            stream.write(marker + data + marker)

        for key, kind, values in entries:
            dtype = {"INTE": "i4", "REAL": "f4", "DOUB": "f8", "CHAR": "S8"}[kind]
            array = np.asarray(values, dtype=(dtype if kind == "CHAR" else endian + dtype))
            record(key.encode().ljust(8) + struct.pack(endian + "i", len(array)) + kind.encode())
            for start in range(0, len(array), 7):  # deliberately cross keyword/logical block boundaries
                record(array[start : start + 7].tobytes())


@pytest.mark.parametrize("endian", [">", "<"])
def test_streaming_egrid_init_active_mapping(service, tmp_path, endian):
    root = tmp_path / "binary"
    root.mkdir()
    path, init = root / "MODEL.EGRID", root / "MODEL.INIT"
    filehead = np.zeros(100, np.int32)
    gridhead = filehead.copy()
    gridhead[[0, 1, 2, 3, 24]] = [1, 2, 1, 1, 1]
    coord = [v for j in range(2) for i in range(3) for v in (i * 10, j * 20, 100, i * 10, j * 20, 110)]
    write_binary(
        path,
        [
            ("FILEHEAD", "INTE", filehead),
            ("GRIDUNIT", "CHAR", [b"METRES", b""]),
            ("GRIDHEAD", "INTE", gridhead),
            ("COORD", "REAL", coord),
            ("ZCORN", "DOUB", [100] * 8 + [110] * 8),
            ("ACTNUM", "INTE", [0, 1]),
        ],
        endian,
    )
    intehead = np.zeros(100, np.int32)
    intehead[[2, 8, 9, 10, 11]] = [1, 2, 1, 1, 1]
    write_binary(
        init,
        [
            ("INTEHEAD", "INTE", intehead),
            ("PORO", "REAL", [0.25]),
            ("NTG", "DOUB", [0.8]),
            ("PERMX", "REAL", [100]),
            ("PERMZ", "REAL", [10]),
            ("EQLNUM", "INTE", [5]),
        ],
        endian,
    )
    swat = root / "SWAT.INC"
    swat.write_text("SWAT\n2*0.2 /\n", encoding="ascii")
    source = LocalSources(service.store).register("binary test", root)
    p = dict(
        path=path.name,
        file_revision=path_revision(path),
        length_unit="m",
        z_direction="down",
        defaults={},
        region_field="EQLNUM",
        crs="LOCAL_METRIC",
        vertical_datum="TEST",
        assumptions=["Explicit binary fixture"],
        block_cells=1,
        property_files=[
            dict(path=init.name, file_revision=path_revision(init), format="init"),
            dict(path=swat.name, file_revision=path_revision(swat), format="grdecl", keyword="SWAT"),
        ],
    )
    out = tmp_path / "imported"
    out.mkdir()
    _, summary, files = import_deck(dict(source=source), p, out)
    assert summary["region_ids"]["EQLNUM"] == [5]
    assert summary["z_convention"]["stored_z_direction"] == "up"
    assert summary["import_validation"] == "PASS"
    with zarr.ZipStore(str(files["grid.zip"]), mode="r") as store:
        g = zarr.open_group(store)
        assert g["phi"][1] == 0.25 and np.isnan(g["phi"][0])
        assert g["kz_ratio"][1] == 0.1
        assert integral(g["corners"][1:2])[0] == pytest.approx(2000)
    pid = service.invoke("project_create", dict(name="Binary validation", vertical_datum="TEST"))["id"]
    published = service.store.publish(pid, "properties", summary, files)
    checked = service.wait(
        service.invoke(
            "result_validate",
            dict(project_id=pid, artifact=dict(id=published["id"], revision=published["revision"])),
        )
    )
    assert checked["summary"]["status"] == "PASS"
    p["property_files"][0]["file_revision"] = "0" * 64
    second = tmp_path / "changed"
    second.mkdir()
    with pytest.raises(DomainError, match="source changed"):
        import_deck(dict(source=source), p, second)


@pytest.mark.parametrize(
    "raw",
    [
        b"\0",
        struct.pack(">i", 16) + b"x" * 16 + b"bad!",
        struct.pack(">i", 16) + b"COORD   " + struct.pack(">i", -1) + b"REAL" + struct.pack(">i", 16),
    ],
)
def test_corrupt_binary_rejected(raw):
    with pytest.raises(DomainError):
        list(records(io.BytesIO(raw)))


def test_resource_errors_are_actionable(tmp_path, monkeypatch):
    with pytest.raises(DomainError) as error:
        memory_check(100, available=100)
    assert error.value.code == "INSUFFICIENT_MEMORY" and error.value.field and error.value.remediation
    with pytest.raises(DomainError) as error:
        disk_check(tmp_path, 10**20)
    assert error.value.code == "INSUFFICIENT_DISK" and error.value.details["required_bytes"] == 10**20
    from opensubsurface.execution import resources

    monkeypatch.setattr(resources.psutil, "virtual_memory", lambda: type("RAM", (), {"available": 1024**3})())
    with pytest.raises(DomainError):
        plan(10_000_000, max_workers=16)


def test_compute_target_model_estimate_and_diagnostics(service, tmp_path):
    obj = partitioned(tmp_path)
    pid = service.invoke("project_create", dict(name="Estimate", vertical_datum="TEST"))["id"]
    published = service.store.publish(pid, "properties", obj["summary"], obj["paths"])
    query = dict(
        project_id=pid,
        properties=dict(id=published["id"], revision=published["revision"]),
        operation="model_qc",
        execution=dict(max_workers=1),
    )
    target = service.invoke("compute_targets_list", query)[0]
    assert target["resources"]["logical_cores"] >= 1
    assert target["resources"]["home_disk_free_bytes"] > 0
    assert target["model_estimate"]["cells"] == 6
    assert target["model_estimate"]["time_estimate_status"] == "NOT RUN"
    assert target["model_estimate"]["estimated_seconds"] is None


def test_parallel_domain_error_preserves_diagnostics(tmp_path):
    obj = partitioned(tmp_path)
    p = params()
    p["execution"] = dict(max_workers=3)
    p["scenarios"][0]["regions"][0]["phi_override"] = 2
    with pytest.raises(DomainError) as error:
        evaluate(obj, p)
    assert error.value.code == "INVALID_PROPERTY"
    assert error.value.field.endswith("phi_override") and error.value.remediation


def test_tornado_and_mc_bitwise_across_workers(tmp_path):
    from opensubsurface.adapters.sensitivity import monte_carlo, tornado

    obj = partitioned(tmp_path)
    p = sensitivity_params()
    p.update(samples=8, seed=173, correlation=[[1.0, 0.75], [0.75, 1.0]], correlation_space="gaussian_copula")
    for function in (tornado, monte_carlo):
        results = []
        for workers in (1, 3):
            out = tmp_path / f"{function.__name__}-{workers}"
            out.mkdir()
            result = function(obj, dict(p, execution=dict(max_workers=workers)), out)
            csv = (out / "mc_samples.csv").read_bytes() if function == monte_carlo else None
            results.append((result["tables"], result["independent_checks"], result["failures"], csv))
        assert results[0] == results[1]


def test_ensemble_keeps_confirmed_geometry_exclusions_visible(tmp_path):
    from opensubsurface.adapters.sensitivity import monte_carlo, tornado

    def twist(arrays):
        arrays["corners"][0, [0, 1]] = arrays["corners"][0, [1, 0]]

    obj = model(tmp_path, changes=twist)
    p = sensitivity_params()
    p.update(
        execution=dict(max_workers=1),
        geometry_policy="exclude_flagged",
        parameters_confirmed=True,
        samples=4,
        seed=173,
        correlation=[[1.0]],
        correlation_space="gaussian_copula",
    )
    p["parameters"] = p["parameters"][:1]
    for function in (tornado, monte_carlo):
        out = tmp_path / function.__name__
        out.mkdir()
        result = function(obj, p, out)
        assert result["status"] == result["validation_status"] == "PASS_WITH_EXCLUSIONS"
        assert result["geometry_exclusions"]["excluded_cells"] == 1


def test_well_boundary_assignments_bitwise_across_workers(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from opensubsurface.adapters.wells_vs_model import run

    obj = partitioned(tmp_path)
    trajectory, log = tmp_path / "survey.parquet", tmp_path / "las.parquet"
    pq.write_table(
        pa.table(dict(well_id=["A", "A"], md=[0.0, 30.0], x=[5.0, 5.0], y=[5.0, 5.0], z=[30.0, 0.0])),
        trajectory,
    )
    pq.write_table(pa.table(dict(DEPT=[15.0, 20.0, 25.0], PHI=[22.0, 20.0, 18.0], NTG=[0.7, 0.8, 0.9])), log)
    survey = dict(
        id="survey",
        revision=1,
        content_hash="b" * 64,
        summary=dict(kind="trajectory"),
        paths={"data.parquet": str(trajectory)},
    )
    las = dict(
        id="las",
        revision=1,
        content_hash="c" * 64,
        summary=dict(kind="las", well_id="A", units=dict(DEPT="m")),
        paths={"data.parquet": str(log)},
    )
    p = dict(
        logs=[
            dict(
                md_curve="DEPT",
                property_curves=dict(phi="PHI", ntg="NTG"),
                property_units=dict(phi="percent", ntg="fraction"),
            )
        ],
        region_field="FIPNUM",
        max_survey_gap_m=31.0,
        boundary_policy="lowest_ijk",
        sample_every_n=1,
        assumptions=["Explicit boundary test"],
    )
    results = []
    for workers in (1, 3):
        out = tmp_path / f"well-{workers}"
        out.mkdir()
        result = run(obj, survey, [las], dict(p, execution=dict(max_workers=workers)), out)
        results.append(
            (
                result["tables"],
                result["boundary_samples"],
                result["independent_checks"],
                (out / "well_samples.csv").read_bytes(),
            )
        )
    assert results[0] == results[1]


def test_small_expansion_matches_fsum_in_any_order():
    import math

    from opensubsurface.execution.reduction import Fsum

    values = np.random.default_rng(84).normal(size=10000) * np.logspace(-50, 50, 10000)
    expected = math.fsum(values)
    for sequence in (values, values[::-1], np.random.default_rng(2).permutation(values)):
        total = Fsum()
        total.extend(sequence)
        assert math.fsum(total) == expected
        # One partial per float64 exponent bin is a data-size-independent bound.
        assert len(total.partials) <= 2098


def test_numeric_only_include_batches_keep_record_and_box_order(service, tmp_path):
    from opensubsurface.adapters.eclipse_deck import Interpreter

    root = tmp_path / "batched"
    root.mkdir()
    values = np.linspace(0.1, 0.3, 100000)
    # Several text batches, D exponents and an INCLUDE containing numeric data only.
    text = "\n".join(" ".join(f"{v:.17e}".replace("e", "D") for v in row) for row in values.reshape(-1, 16))
    (root / "poro.inc").write_text(text + "\n", encoding="ascii")
    path = root / "MODEL.DATA"
    path.write_text(
        "DIMENS\n100 100 10 /\nGRID\nPORO\nINCLUDE\n'poro.inc' /\n/\n"
        "NTG\n100000*0.8 /\nBOX\n1 2 1 1 1 1 /\nPORO\n0.4 0.5 /\nENDBOX\nEND\n",
        encoding="ascii",
    )
    source = LocalSources(service.store).register("Batched arrays", root)
    out = tmp_path / "parsed"
    out.mkdir()
    deck = Interpreter(source, path.name, out, path_revision(path)).parse()
    try:
        values[:2] = [0.4, 0.5]
        np.testing.assert_array_equal(deck.arrays["PORO"], values)
        np.testing.assert_array_equal(deck.arrays["NTG"], np.full(100000, 0.8))
        assert len(deck.files) == 2
    finally:
        for array in deck.arrays.values():
            array._mmap.close()


def test_numeric_batch_never_ignores_values_after_non_ascii_space(service, tmp_path):
    from opensubsurface.adapters.eclipse_deck import Interpreter

    root = tmp_path / "spacing"
    root.mkdir()
    path = root / "MODEL.DATA"
    path.write_text("DIMENS\n1 1 1 /\nGRID\nPORO\n0.1\u00a00.2 /\nEND\n", encoding="latin-1")
    source = LocalSources(service.store).register("Strict numeric count", root)
    out = tmp_path / "spacing-parsed"
    out.mkdir()
    deck = Interpreter(source, path.name, out)
    try:
        with pytest.raises(DomainError) as error:
            deck.parse()
        assert error.value.code == "GRID_MAPPING_ERROR"
    finally:
        for array in deck.arrays.values():
            array._mmap.close()


@pytest.mark.parametrize("device,workers", [("cpu", 8), ("require_gpu", 1)])
def test_plan_validation_workers_follow_explicit_plan_policy(device, workers):
    from opensubsurface.calculations.planning import compile_nodes
    from opensubsurface.schemas import Execution

    plan = dict(
        id="plan",
        revision=1,
        project_id="p",
        parameters=dict(
            project_id="p",
            properties=dict(id="props", revision=1),
            contacts=[dict(name="c", z_m=-5)],
            zone_ids=[1],
            bo=1.2,
            uncertainty=None,
            execution=Execution(device_policy=device, max_workers=workers).model_dump(),
        ),
    )
    checks = [node for node in compile_nodes(plan) if node["operation"] == "result_validate"]
    assert len(checks) == 2
    assert all(node["arguments"]["execution"]["max_workers"] == workers for node in checks)
    assert all(node["arguments"]["execution"]["device_policy"] == "cpu" for node in checks)


def test_real_xtgeo_egrid_matches_native_geometry_without_native_import(service, tmp_path, monkeypatch):
    import xtgeo

    root = tmp_path / "native-binary"
    root.mkdir()
    path = root / "MODEL.EGRID"
    native = xtgeo.create_box_grid((3, 4, 2), origin=(100, 200, 1000), increment=(10, 20, 5), rotation=27)
    native.to_file(path, fformat="egrid")
    native = xtgeo.grid_from_file(path, fformat="egrid")
    expected = np.stack([a.values.ravel(order="F") for a in native.get_xyz_corners()], axis=1).reshape(
        -1, 8, 3
    )
    expected[:, :, 2] *= -1

    def forbidden(*args, **kwargs):
        raise AssertionError("Streaming import must not call XTGeo")

    monkeypatch.setattr(xtgeo, "grid_from_file", forbidden)
    source = LocalSources(service.store).register("Native EGRID", root)
    out = tmp_path / "native-import"
    out.mkdir()
    p = dict(
        path=path.name,
        file_revision=path_revision(path),
        length_unit="m",
        z_direction="down",
        defaults=dict(ACTNUM=1, PORO=0.2, NTG=0.8, SWAT=0.25, PERMX=100, PERMZ=10, FIPNUM=1),
        region_field="FIPNUM",
        crs="LOCAL_METRIC",
        vertical_datum="TEST",
        assumptions=["Explicit synthetic properties"],
        block_cells=7,
    )
    _, summary, files = import_deck(dict(source=source), p, out)
    assert summary["active_cells"] == 24
    with zarr.ZipStore(str(files["grid.zip"]), mode="r") as store:
        actual = zarr.open_group(store)["corners"][:]
    np.testing.assert_array_equal(actual, expected)


@pytest.mark.gpu
def test_imported_regional_and_plan_cuda(service, tmp_path):
    import torch

    if not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    obj = partitioned(tmp_path)
    pid = service.invoke("project_create", dict(name="CUDA import", vertical_datum="TEST"))["id"]
    import hashlib

    # Explicit generated source-array hashes let the full plan validate this fixture.
    with zarr.ZipStore(obj["paths"]["grid.zip"], mode="r") as store:
        group = zarr.open_group(store)
        names = (set(obj["summary"]["units"]) - {"active"}) | {"geometry"}
        obj["summary"]["source_sha256"] = {
            name: hashlib.sha256(group["corners" if name == "geometry" else name][:].tobytes()).hexdigest()
            for name in names
        }
    published = service.store.publish(pid, "properties", obj["summary"], obj["paths"])
    ref = dict(id=published["id"], revision=published["revision"])
    p = dict(params(), project_id=pid, properties=ref, execution=dict(device_policy="require_gpu"))
    result = service.wait(service.invoke("regional_volumes", p))
    assert result["summary"]["validation_status"] == "PASS"
    plan = service.invoke(
        "calculation_plan",
        dict(
            project_id=pid,
            properties=ref,
            zone_ids=[1, 2],
            bo=1.2,
            contacts=[dict(name="OWC", z_m=5.0)],
            assumptions=["Explicit CUDA check"],
            execution=dict(device_policy="require_gpu"),
        ),
    )
    run = service.invoke(
        "calculation_run", dict(project_id=pid, plan=dict(id=plan["id"], revision=plan["revision"]))
    )
    service.wait(run)
    status = service.invoke("calculation_status", dict(project_id=pid, run_id=run["run_id"]))
    report = service.store.object(pid, status["report"])
    assert report["summary"]["validation_status"] == "PASS"
