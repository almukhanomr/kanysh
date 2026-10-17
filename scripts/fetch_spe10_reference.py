"""Download only pinned, openly published OPM SPE10 model2 files; no code execution."""

import hashlib
import json
from pathlib import Path

import httpx

COMMIT = "eaa2261683a97027e057c2bc49612ad1c86390b3"
ROOT = "https://raw.githubusercontent.com/OPM/opm-data/" + COMMIT + "/"
FILES = [
    "spe10model2/SPE10_MODEL2.DATA",
    "spe10model2/SPE10MODEL2_TOPS.INC",
    "spe10model2/SPE10MODEL2_PHI.INC",
    "spe10model2/SPE10MODEL2_PERM.INC",
    "odbl-10.txt",
    "dbcl-10.txt",
]
EXPECTED_SHA256 = {
    "SPE10_MODEL2.DATA": "74723a59446bdcae34e2b4f86c98216c03b1cf67286d1a6e45dc3134b2a96c63",
    "SPE10MODEL2_TOPS.INC": "55b15a1c6793d02cbc3ff7f5f2d3cd386f0c0363d777d961a8c241a2bca75cc3",
    "SPE10MODEL2_PHI.INC": "1426c8b40c8a1ffd3cce6653aad264685f100f82018d212ca74c8ae6d0bd1295",
    "SPE10MODEL2_PERM.INC": "1829e331b64d2efb416fc40f4d68388087a11e4f7ff5ac6866eb8f1a88f8993d",
    "odbl-10.txt": "1d553feead201a7619788171b43cca12675e82d70b197aa45795986bb8603e72",
    "dbcl-10.txt": "3cbfa990f26df856c6a7d3fff3d1f236e3b0165b1e8257ca0d00f15758754f81",
}
OUTPUT = Path("examples/reference/spe10model2")
MAX_TOTAL = 128 * 1024**2


def main():
    raw = OUTPUT / "raw"
    raw.mkdir(exist_ok=True, parents=True)
    files, total = [], 0
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for relative in FILES:
            url = ROOT + relative
            path = raw / Path(relative).name
            temporary = path.with_suffix(path.suffix + ".part")
            sha, size = hashlib.sha256(), 0
            try:
                with client.stream("GET", url) as response, temporary.open("wb") as stream:
                    response.raise_for_status()
                    for chunk in response.iter_bytes(256 * 1024):
                        total += len(chunk)
                        size += len(chunk)
                        if total > MAX_TOTAL:
                            raise RuntimeError("Download exceeds 128 MiB total limit")
                        sha.update(chunk)
                        stream.write(chunk)
                if sha.hexdigest() != EXPECTED_SHA256[path.name]:
                    raise RuntimeError("Pinned SHA-256 mismatch: " + path.name)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            files.append(dict(path="raw/" + path.name, source=url, bytes=size, sha256=sha.hexdigest()))
            print("Downloaded", path.name, size, "bytes", flush=True)
    manifest = dict(
        repository="https://github.com/OPM/opm-data",
        commit=COMMIT,
        license="ODbL-1.0 database / DbCL-1.0 contents; original files and notices retained",
        description="Upstream public SPE10 benchmark; not a real field dataset or solver reference output",
        files=files,
    )
    (OUTPUT / "sources.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Pinned files:", len(files), "total bytes:", total, flush=True)


if __name__ == "__main__":
    main()
