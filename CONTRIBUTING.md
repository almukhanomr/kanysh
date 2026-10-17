# Contributing

Kanysh Basic is a local MCP copilot alongside Petrel/RMS. The A–D and O1–O6
feature set is accepted; current work is publication, portability and reproducibility.
New capabilities belong to Kanysh Advanced: discuss them against docs/ROADMAP.md.
Keep Kanysh Basic publication and maintenance work within its accepted scope.

## Development

Use Python 3.12 and uv. From the checkout:

```bash
uv sync --frozen --extra ui --extra viewer --extra solver --group dev
uv run --no-sync ruff check src tests scripts examples/generators
uv run --no-sync pytest -q -m "not gpu and not opm and not external" --junitxml=test-results/junit.xml
```

CI runs the same CPU selection on Ubuntu and macOS. Native Windows is not the
supported process/filesystem profile; Windows users use WSL2. Hardware acceptance
and real external MCP clients are separate from SDK fixtures.

## Scientific changes

- Keep scientific inputs explicit. Never infer missing contacts, Bo/Bg, saturation,
  units or datum just to make a workflow run.
- Add a meaningful analytic or independent reference test for numerical changes.
  A reader/writer roundtrip alone is not independent geological validation.
- Preserve FAIL, INCOMPLETE and NOT RUN. Numerical PASS is not geological approval.
- Keep immutable revisions, source hashes, IJK ordering and unsupported-keyword evidence.
- Do not edit runtime Python sources while a pinned calculation is running.
- Do not relax tolerances, change active masks or silently drop failed realizations.

## Data and privacy

Use synthetic or openly licensed data in tests. Keep upstream attribution and hashes.
Do not commit private model files, owner source registrations, tokens, home directories,
virtual environments or machine-specific paths. Generated JUnit reports are made portable
by the test hook; `python scripts/publication.py` sanitizes public JSON/XML evidence.
It does not rewrite immutable project blobs or scientific values.

To regenerate public Norne evidence, see [DEMO](docs/DEMO.md). Large upstream downloads
are explicit script steps and are not run in CI. Norne is ODbL/DbCL, separate from the
Apache-2.0 application licence. Changes to the bundled snapshot must update its SHA-256
and pass the three-distinct-contact regression.

## Pull requests

Explain the problem, resulting behaviour, assumptions and relevant test evidence.
State which OS and external checks were actually run. Keep publication fixes separate
from new modelling features. Avoid unrelated dependency upgrades and generated data churn.
Local Advanced experiments in `experimental/` are excluded from Basic GitHub publication and distribution. Their tests are outside the product suite.

## Before publishing

Run `uv run --no-sync python scripts/check_publication.py`. It audits actual tracked
and non-ignored files, including nested ZIP contents, and never prints matching secret
values. It also works before `git init` using a temporary Git index. Tracked secrets
remain a failure even if an ignore pattern was added later. The guard scans the
working tree, not Git history; it cannot detect every possible secret format.

Commit through Git so `.gitignore` applies. Do not upload the entire local working
folder through a browser or zip it wholesale: it contains ignored owner state and
virtual environments. See [pre-publication audit](docs/PRE_PUBLICATION_AUDIT.md).
