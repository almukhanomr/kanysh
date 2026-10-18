"""Memory preflight must admit what fits and refuse what does not (CI macOS runner: ~3.5 GB free)."""

from types import SimpleNamespace

import pytest

from opensubsurface.errors import DomainError
from opensubsurface.execution import resources


@pytest.fixture
def small_host(monkeypatch):
    monkeypatch.setattr(resources.psutil, "virtual_memory", lambda: SimpleNamespace(available=3_482_206_208))


def test_serial_large_block_fits_small_host(small_host):
    config = resources.plan(4_198_400, 262_144, max_workers=1)
    assert config["max_workers"] == 1
    # One in-process worker: no separate coordinator copy is budgeted.
    assert config["estimated_peak_bytes"] == resources.PROCESS_BYTES + 262_144 * resources.BYTES_PER_CELL


def test_parallel_counts_coordinator_and_refuses_oversubscription(small_host):
    config = resources.plan(4_198_400, 16_384, max_workers=2)
    assert config["estimated_peak_bytes"] == 3 * (resources.PROCESS_BYTES + 16_384 * resources.BYTES_PER_CELL)
    with pytest.raises(DomainError) as raised:
        resources.plan(4_198_400, 262_144, max_workers=4)
    assert raised.value.code == "INSUFFICIENT_MEMORY" and raised.value.field == "execution.max_workers"
