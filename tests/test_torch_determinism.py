"""Torch determinism smoke + 1D-CNN bit-identical forward-pass test (EX-5)."""

from __future__ import annotations

import os

import numpy as np
import pytest

torch = pytest.importorskip("torch")


def _set_deterministic() -> None:
    """Apply all torch knobs required for bit-identical CPU operation."""
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "max_split_size_mb:128")
    torch.use_deterministic_algorithms(True, warn_only=False)
    torch.manual_seed(20260420)
    np.random.seed(20260420)


def _make_cnn() -> torch.nn.Module:
    return torch.nn.Sequential(
        torch.nn.Conv1d(in_channels=1, out_channels=4, kernel_size=3, padding=1),
        torch.nn.ReLU(),
        torch.nn.Flatten(),
        torch.nn.Linear(4 * 100, 1),
    )


def test_torch_imports_cleanly():
    assert hasattr(torch, "__version__")


def test_use_deterministic_algorithms_enabled():
    _set_deterministic()
    # Verify the flag is actually set
    assert torch.are_deterministic_algorithms_enabled()


def test_1d_cnn_forward_pass_bit_identical_across_runs():
    """Same input + same seed + deterministic mode → bit-identical output."""

    def run_once() -> torch.Tensor:
        _set_deterministic()
        torch.manual_seed(20260420)
        model = _make_cnn()
        model.eval()
        x = torch.randn(8, 1, 100, generator=torch.Generator().manual_seed(20260420))
        with torch.no_grad():
            return model(x)

    out1 = run_once()
    out2 = run_once()
    assert torch.equal(out1, out2), (
        "1D-CNN forward pass not bit-identical across runs under "
        "torch.use_deterministic_algorithms(True). Investigate fp ops."
    )


def test_1d_cnn_forward_pass_100_samples_smoke():
    """End-to-end smoke: 100-sample batch produces a finite scalar prediction each."""
    _set_deterministic()
    torch.manual_seed(20260420)
    model = _make_cnn()
    model.eval()
    x = torch.randn(100, 1, 100, generator=torch.Generator().manual_seed(20260420))
    with torch.no_grad():
        out = model(x)
    assert out.shape == (100, 1)
    assert torch.isfinite(out).all().item()
