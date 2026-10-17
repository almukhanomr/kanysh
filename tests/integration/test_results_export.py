import json

import numpy as np
import pytest

from opensubsurface.adapters.results_export import export


def fixture(out):
    from matplotlib import pyplot as plt

    from opensubsurface.adapters.copilot_report import write_report

    result = dict(
        operation="regional_volumes",
        status="PARTIAL",
        validation_status="NOT RUN",
        assumptions=["Явное допущение пользователя", "=1+1", "<script>data</script>"],
        limitations=["Synthetic data; no geological acceptance"],
        scope="Serialization fixture only",
        independent_checks=[dict(name="unavailable", status="NOT RUN")],
        metric_definitions=dict(STOIIP="Initial oil (sm3), not recoverable reserves"),
        tables=dict(
            scenarios=[dict(scenario="база", STOIIP=1234.567, GIIP=None)],
            regions=[
                dict(scenario="база", region_id=1, STOIIP=1000.0),
                dict(scenario="база", region_id=2, STOIIP=234.567),
            ],
            tornado=[dict(parameter="phi", metric_low=900, metric_high=1600)],
            percentiles=[dict(metric="STOIIP", P90=900, P50=1234, P10=1600)],
        ),
    )
    write_report(out, "Source fixture", result)
    for filename, title in (("tornado.png", "Synthetic tornado"), ("s_curve.png", "Synthetic S curve")):
        fig, ax = plt.subplots(figsize=(6, 2))
        ax.plot([900, 1234, 1600], [0.9, 0.5, 0.1])
        ax.set_title(title)
        fig.savefig(out / filename)
        plt.close(fig)
    obj = dict(
        id="analysis-report-fixture",
        revision=2,
        content_hash="a" * 64,
        paths={name: str(out / name) for name in ("report.json", "tornado.png", "s_curve.png")},
    )
    np.save(out / "slice.npy", np.arange(24, dtype=float).reshape(6, 4))
    section = dict(
        id="seismic-slice-fixture",
        revision=1,
        content_hash="b" * 64,
        paths={"slice.npy": str(out / "slice.npy")},
        summary=dict(axis="inline", index=0, domain="twt"),
    )
    return obj, section


def test_export_preserves_every_number_null_status_and_untrusted_text(tmp_path):
    pytest.importorskip("openpyxl")
    pytest.importorskip("reportlab")
    pytest.importorskip("pypdf")
    from openpyxl import load_workbook
    from pypdf import PdfReader

    source, out = tmp_path / "source", tmp_path / "export"
    source.mkdir()
    out.mkdir()
    obj, section = fixture(source)
    _, summary, files = export(
        [obj],
        dict(
            formats=["xlsx", "pdf"],
            title="Расчёт по модели / Model results",
            max_pdf_rows_per_table=1,
            notes=["Test only"],
        ),
        out,
        slices=[section],
    )
    evidence = json.loads(files["report.json"].read_text())
    assert summary["scientific_validation"].startswith("See source_statuses")
    assert evidence["source_statuses"][0]["validation_status"] == "NOT RUN"
    assert evidence["export_checks"]["xlsx"]["status"] == "PASS"
    assert evidence["export_checks"]["pdf"]["presentation_truncations"] == [
        dict(table="regions", shown=1, total=2)
    ]
    book = load_workbook(files["results.xlsx"], data_only=False)
    assert book["Scenarios"]["E2"].value == 1234.567
    assert book["Scenarios"]["F2"].value == "NOT AVAILABLE"
    assert book["Assumptions"]["B3"].value == "=1+1" and book["Assumptions"]["B3"].data_type == "s"
    assert len(list(book["Regions"].values)) == 3
    assert "NOT RUN" in str(list(book["Checks"].values))
    text = "\n".join(page.extract_text() for page in PdfReader(files["results.pdf"]).pages)
    assert "Явное допущение" in text and "NOT RUN" in text and "Seismic slice 1" in text
    assert "Showing 1 of 2" in text and "seismic-slice-fixture" in text
    assert "<script>" not in files["report.html"].read_text()
