"""Read-only download of a license-declared upstream fixture, pinned by commit and SHA-256."""

import hashlib
import json
from pathlib import Path

import httpx

out = Path("examples/reference")
out.mkdir(exist_ok=True, parents=True)
with httpx.Client(timeout=60, follow_redirects=True) as client:
    response = client.get(
        "https://api.github.com/repos/OPM/opm-data/commits",
        params={"path": "spe1/SPE1CASE2.DATA", "per_page": 1},
    )
    response.raise_for_status()
    commit = response.json()[0]["sha"]
    url = f"https://raw.githubusercontent.com/OPM/opm-data/{commit}/spe1/SPE1CASE2.DATA"
    response = client.get(url)
    response.raise_for_status()
    data = response.content
    assert b"Open Database" in data[:500] and b"Database Contents" in data[:500]
    (out / "SPE1CASE2.DATA").write_bytes(data)
    manifest = dict(
        source=url,
        commit=commit,
        sha256=hashlib.sha256(data).hexdigest(),
        license="ODbL-1.0 / DbCL-1.0; copyright Statoil 2015; original header retained",
        validation="NOT RUN: OPM executable unavailable; no reference results claimed",
    )
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
