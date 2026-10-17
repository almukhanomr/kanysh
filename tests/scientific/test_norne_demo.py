"""Publication regression: saved field-data sensitivity must actually change volumes."""

import json
import zipfile
from importlib.resources import files


def test_bundled_norne_contacts_are_in_reservoir_and_strictly_different():
    folder = files("opensubsurface").joinpath("data/norne")
    declaration = json.loads(folder.joinpath("demo.json").read_text())
    selection = declaration["contact_selection"]
    lo, hi = selection["active_depth_range_m"]
    depths = selection["depths_m"]
    assert len(set(depths)) == 3 and all(lo < depth < hi for depth in depths)
    assert selection["evidence"] and all(row["line"] > 0 for row in selection["evidence"])
    with zipfile.ZipFile(folder.joinpath("project.zip")) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        reports = [obj for obj in manifest["objects"] if obj["kind"] == "calculation_report"]
        report = json.loads(bundle.read("blobs/" + reports[-1]["files"]["report.json"]))
    assert report["validation_status"] == "PASS"
    rows = sorted(report["contacts"], key=lambda r: -r["contact_z_m"])
    assert [-r["contact_z_m"] for r in rows] == depths
    assert all(a["STOIIP"] < b["STOIIP"] for a, b in zip(rows, rows[1:]))
    assert all(a["GRV_oil_interval"] < b["GRV_oil_interval"] for a, b in zip(rows, rows[1:]))
    assert [r["STOIIP"] for r in rows] == declaration["contact_distinction"]["stoiip_standard_m3"]
