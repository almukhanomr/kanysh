# Basic pre-publication audit

This audit concerns files selected for GitHub publication, not a new product feature.
The working directory intentionally still contains ignored local owner data and virtual
environments. Publish through Git so `.gitignore` applies; do not upload or zip the
entire working directory using a file browser.

## Cleanup

- Removed unreferenced `spike_gempy.py`, `spike_fault.py` and the old
  `build_demo_bundle.py` from public scripts. Local copies are retained under ignored
  `test-results/pre-publication-archive`; numerical fixtures and supported demo scripts remain.
- Moved the well-data helper used only by a test out of the installed package into
  `tests/conftest.py`. Its import/marker/LAS integration test remains.
- Moved unused remote-staging primitives and their test out of Basic into local
  Advanced experiments. No production caller used them.
- Excluded local `experimental/` Advanced work from Basic GitHub publication as well
  as package distribution. Removed it from Basic CI lint paths.
- Retired four obsolete viewer screenshots, including the old UI and superseded
  contact demonstration. Current viewer and numerical evidence remain linked.
- Expanded Git/Docker exclusions for state directories, virtual environments,
  downloaded model caches, builds, credentials, private keys and OS/editor files.
- Added Git attributes to preserve reference input/archive bytes across platforms.
- Translated THIRD_PARTY.md and its generator into English, retained dataset/font
  notices and expanded the inventory to include the export dependencies.
- Replaced the short license header with the full Apache-2.0 text from the official
  [Apache site](https://www.apache.org/licenses/LICENSE-2.0.txt). Project attribution is retained in NOTICE, which is included in the MCPB.

## Audit procedure

Run:

```bash
uv run --no-sync python scripts/check_publication.py --report test-results/publication-audit.json
```

Before Git initialization, the script uses a temporary Git index to apply the actual
ignore rules. In an existing repository, it includes tracked files too: adding a
secret to `.gitignore` does not hide an already staged/tracked secret from the guard.
The audit inspects nested ZIP contents without extracting them or printing matching
secret values. It rejects local state, private-key/token signatures, personal checkout
paths, symlinks and individual files above the 50 MiB publication policy limit.
The same guard runs in CI.

The import graph, CLI/MCP operation registry, test callers and Alembic dynamic loading
were reviewed before removing files. Scientific adapters, migrations, negative test
fixtures, benchmark evidence, the offline Norne bundle and upstream license notices
are intentional content, not removable clutter. Public dependencies are used by
these paths; transitive use alone was not treated as proof that a dependency is unused.

The [current machine-readable result](publication-audit.json) describes the working
files and nested archives. It does not scan Git history and cannot identify every
possible secret format. There was no existing Git history in the project directory
when this audit began. No public repository was created or pushed.

The publication guard has three integration controls: ignored owner data before Git
initialization, a forced-tracked ignored credential, and a secret nested inside an
archive plus an external symlink. All three pass. Twelve representative owner/cache/
credential/Advanced/build paths were also checked against Git's actual ignore engine.

Final CPU regression after cleanup: **150 passed, 2 deselected**, zero failures/errors,
420.60 s. See [portable JUnit](test-results.xml). Ruff lint/format, frozen lock, real
MCPB SDK execution and the updated UI-free core wheel checks pass. External hardware
and actual Desktop installation remain NOT RUN.
