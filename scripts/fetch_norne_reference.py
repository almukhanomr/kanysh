"""Download only pinned, openly published OPM Norne files; no code execution."""

import hashlib
import json
from pathlib import Path

import httpx

COMMIT = "eaa2261683a97027e057c2bc49612ad1c86390b3"
ROOT = "https://raw.githubusercontent.com/OPM/opm-data/" + COMMIT + "/"
FILES = [
    "norne/INCLUDE/GRID/IRAP_1005.GRDECL",
    "norne/INCLUDE/GRID/ACTNUM_0704.prop",
    "norne/NORNE_ATW2013.DATA",
    "norne/README",
    "norne/INCLUDE/PETRO/PORO_0704.prop",
    "norne/INCLUDE/PETRO/PERM_0704.prop",
    "norne/INCLUDE/PETRO/NTG_0704.prop",
    "norne/INCLUDE/PETRO/FIPNUM_0704.prop",
    "odbl-10.txt",
    "dbcl-10.txt",
]
EXPECTED_SHA256 = {
    "IRAP_1005.GRDECL": "21d156ac65ff5e473601384cc4b5462a295acfc7e837a93e74ecae9f63c2f34f",
    "ACTNUM_0704.prop": "32e590467b04ca31e487a94d62ff6e91ffb87844ad2af5c40d713cef633f664f",
    "NORNE_ATW2013.DATA": "f346c910f68a80b41ee54606bd434dc9e2993fffa7a2469235f396c2c0a9e080",
    "README": "73be5dd043960904321c8ccc62de52a03036669364c588b3e5de1decce049842",
    "PORO_0704.prop": "e5147647a2fbee651b9df27e1db4a7a70e8b3ee8231b92f93f7fb6a69a03e8cd",
    "PERM_0704.prop": "bce56f7ff702dffe6ae2837bdda4ab4f6fa1d54c0be178cccd24005ded787eac",
    "NTG_0704.prop": "b5b6a556f0edf6d9767a418adcba3a2821359fdf8ce374bc79cefc50bbe87496",
    "FIPNUM_0704.prop": "cc39524ab6abd8f017624209b9b30c49842c665b15158cd95d9274df6d371de7",
    "odbl-10.txt": "1d553feead201a7619788171b43cca12675e82d70b197aa45795986bb8603e72",
    "dbcl-10.txt": "3cbfa990f26df856c6a7d3fff3d1f236e3b0165b1e8257ca0d00f15758754f81",
}
OUTPUT = Path("examples/reference/norne")
MAX_TOTAL = 32 * 1024**2


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
                            raise RuntimeError("Download exceeds 32 MiB total limit")
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
        description="Public Norne field corner-point benchmark; not native Petrel project or solver reference output",
        files=files,
    )
    (OUTPUT / "sources.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Pinned files:", len(files), "total bytes:", total, flush=True)


if __name__ == "__main__":
    main()
