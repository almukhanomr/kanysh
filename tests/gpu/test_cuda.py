import numpy as np
import pytest
import torch

from opensubsurface.domain.numerics import seismic_attribute, volumes

pytestmark = [
    pytest.mark.gpu,
    pytest.mark.skipif(not torch.cuda.is_available(), reason="NVIDIA CUDA отсутствует"),
]


def test_cuda_volume_against_analytic():
    shape = (10, 10, 2)
    arrays = dict(
        active=np.ones(shape, bool),
        zones=np.ones(shape, int),
        phi=np.full(shape, 0.2),
        ntg=np.full(shape, 0.8),
        sw=np.full(shape, 0.25),
        permeability_md=np.full(shape, 100.0),
    )
    grid = dict(shape=shape, extent=[0, 1000, 0, 1000, -1020, -1000])
    assert volumes(arrays, grid, [1], -1020, 1.2, "cuda")["values"]["STOIIP"] == pytest.approx(2e6, rel=1e-8)


def test_cuda_attributes_against_analytic():
    x = 2.5 * np.sin(2 * np.pi * 8 * np.arange(128) / 128)
    np.testing.assert_allclose(seismic_attribute(x[None, None, :], "envelope", device="cuda"), 2.5, atol=1e-8)
    np.testing.assert_allclose(seismic_attribute(np.full((2, 3, 64), 4.0), "rms", 5, "cuda"), 4.0, atol=1e-8)
