"""Fetch the pinned, unmodified Norne DATA and its complete INCLUDE closure."""

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

import httpx
from fetch_norne_reference import COMMIT, ROOT

DEST = Path("examples/reference/norne/full")


def main():
    pending = ["norne/NORNE_ATW2013.DATA", "norne/README", "odbl-10.txt", "dbcl-10.txt"]
    done, total = {}, 0
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        while pending:
            relative = pending.pop(0)
            if relative in done:
                continue
            path = DEST / relative
            if path.is_file():
                content = path.read_bytes()
            else:
                response = client.get(ROOT + relative)
                response.raise_for_status()
                content = response.content
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            total += len(content)
            if total > 2 * 1024**3:
                raise RuntimeError("Norne closure exceeds 2 GiB")
            done[relative] = dict(
                path=relative,
                bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                source=ROOT + relative,
            )
            text = re.sub(r"--[^\n]*", "", content.decode("latin-1"))
            for item in re.findall(r"\bINCLUDE\s+'([^']+)'\s*/", text, re.I):
                # Norne deck INCLUDE paths are relative to the master deck directory.
                combined = PurePosixPath("norne") / item
                if ".." in combined.parts or combined.is_absolute():
                    raise RuntimeError("Unexpected upstream INCLUDE path")
                pending.append(str(combined))
            print(relative, len(content), flush=True)
    DEST.mkdir(exist_ok=True, parents=True)
    (DEST / "sources.json").write_text(
        json.dumps(
            dict(commit=COMMIT, files=list(done.values()), total_bytes=total, license="ODbL-1.0 / DbCL-1.0"),
            indent=2,
        )
        + "\n"
    )
    print("Complete INCLUDE closure:", len(done), "files", total, "bytes", flush=True)


if __name__ == "__main__":
    main()
