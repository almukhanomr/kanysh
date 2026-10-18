import numpy as np
import pytest
import torch

from opensubsurface.adapters.cornerpoint import cell_volumes as cpu
from opensubsurface.errors import DomainError
from opensubsurface.execution.cornerpoint_gpu import cell_volumes as gpu

pytestmark = [pytest.mark.gpu, pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA unavailable")]


@pytest.mark.parametrize("contact", [None, -2.0, 0.0, 0.5, 2.0])
def test_tetra6_float64_cpu_reference(contact):
    corners = np.random.default_rng(813).normal(size=(1000, 8, 3))
    # Includes repeated depths and exact plane vertices.
    corners[0, :, 2] = [0, 0, 1, 1, -1, -1, 0, 0]
    np.testing.assert_allclose(gpu(corners, contact), cpu(corners, contact), rtol=1e-8, atol=1e-7)


def test_gpu_mismatch_is_failure(monkeypatch):
    from opensubsurface.adapters import cornerpoint

    monkeypatch.setattr(cornerpoint, "cell_volumes", lambda c, contact: np.zeros(len(c)))
    with pytest.raises(DomainError) as error:
        gpu(np.random.default_rng(1).normal(size=(100, 8, 3)), 0.1)
    assert error.value.code == "VALIDATION_FAILED"
