"""Tests for the distant-horizon geometry.

Curvature is the part that is easy to get wrong and impossible to eyeball on a
real DEM: over 100 km the Earth drops ~785 m, which is more than any Bohemian
hill. Getting it backwards, or omitting it, silently lifts distant terrain into
the sky.
"""

from __future__ import annotations

import numpy as np
import pytest

from sunline.far_field import _R_EFF, _max_pool, interp_block


def drop(d: float) -> float:
    return d**2 / (2.0 * _R_EFF)


def test_curvature_drop_matches_the_textbook_values() -> None:
    """Standard refraction (k=0.13) gives ~6.8 cm/km^2."""
    assert drop(1_000) == pytest.approx(0.068, abs=0.005)
    assert drop(10_000) == pytest.approx(6.8, rel=0.05)
    assert drop(50_000) == pytest.approx(170.0, rel=0.05)


def test_refraction_lowers_the_drop_against_a_bare_sphere() -> None:
    """Refraction bends the ray down, so terrain falls away more slowly."""
    bare = 100_000**2 / (2 * 6_371_000.0)
    assert drop(100_000) < bare
    assert drop(100_000) == pytest.approx(bare * (1 - 0.13), rel=1e-6)


def test_a_distant_hill_is_pushed_below_the_horizon() -> None:
    """A 300 m hill 80 km away sits below a flat horizon once curvature applies."""
    d, height = 80_000.0, 300.0
    naive = np.degrees(np.arctan2(height, d))
    real = np.degrees(np.arctan2(height - drop(d), d))
    assert naive > 0, "sanity: without curvature the hill appears above the horizon"
    assert real < 0, f"with curvature the hill must drop below the horizon, got {real:.3f}deg"


def test_max_pool_keeps_the_crest_not_the_mean() -> None:
    """The whole reason rings are requested finer than they are marched.

    Server-side downsampling averages, which shaves ridge tops and lets the sun
    through where it should not.
    """
    a = np.zeros((6, 6), dtype=np.float32)
    a[2, 2] = 100.0  # a lone summit

    pooled = _max_pool(a, 3)
    assert pooled.shape == (2, 2)
    assert pooled[0, 0] == 100.0, "max-pool must carry the summit through"
    assert a.reshape(2, 3, 2, 3).mean(axis=(1, 3))[0, 0] < 12.0, (
        "sanity: averaging would have lost it"
    )


def test_max_pool_factor_one_is_a_no_op() -> None:
    a = np.arange(16, dtype=np.float32).reshape(4, 4)
    assert np.array_equal(_max_pool(a, 1), a)


def test_interp_block_reproduces_a_known_plane() -> None:
    """Bilinear expansion of a linear ramp must stay linear."""
    xs = np.array([0.0, 1000.0, 2000.0])
    ys = np.array([0.0, 1000.0, 2000.0])
    # angle = x / 1000, independent of y
    angle = np.tile(xs / 1000.0, (3, 1)).astype(np.float32)

    out = interp_block(angle, xs, ys, xmin=0.0, ymax=2000.0, width=4, height=4, res=500.0)

    expected_cols = (np.arange(4) * 500.0 + 250.0) / 1000.0
    for c, want in enumerate(expected_cols):
        assert out[:, c] == pytest.approx(want, abs=1e-4)


def test_interp_block_respects_north_up_row_order() -> None:
    """Rows descend northward; a north-high ramp must stay high in row 0."""
    xs = np.array([0.0, 1000.0, 2000.0])
    ys = np.array([0.0, 1000.0, 2000.0])
    # angle grows with y (northward); ys[0] is the southern edge.
    angle = np.tile((ys / 1000.0)[:, None], (1, 3)).astype(np.float32)

    out = interp_block(angle, xs, ys, xmin=0.0, ymax=2000.0, width=4, height=4, res=500.0)
    assert out[0, 0] > out[-1, 0], "north edge (row 0) should carry the higher horizon"
