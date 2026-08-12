"""Tests for eclipse circumstances.

The geometry is testable without any ephemeris; the ephemeris-backed test skips
cleanly when the kernel is not on disk, so the suite still runs offline.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from sunline.eclipse import _obscuration, circumstances

R_SUN = 0.26  # roughly the solar apparent radius in degrees


def test_no_overlap_is_zero_obscuration() -> None:
    assert _obscuration(1.0, R_SUN, 0.25) == 0.0


def test_full_cover_is_total() -> None:
    """Moon larger than the sun and concentric — a total eclipse."""
    assert _obscuration(0.0, R_SUN, 0.28) == pytest.approx(1.0)


def test_annular_leaves_a_ring() -> None:
    """Moon smaller than the sun and concentric: area ratio, not 1.0."""
    assert _obscuration(0.0, R_SUN, 0.24) == pytest.approx((0.24 / R_SUN) ** 2)


def test_obscuration_is_monotonic_in_separation() -> None:
    seps = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    vals = [_obscuration(s, R_SUN, 0.25) for s in seps]
    assert vals == sorted(vals, reverse=True), vals


def test_grazing_contact_is_near_zero() -> None:
    """At exactly the sum of the radii the discs touch and nothing is hidden."""
    assert _obscuration(R_SUN + 0.25 - 1e-9, R_SUN, 0.25) == pytest.approx(0.0, abs=1e-4)


def test_obscuration_is_below_magnitude_for_a_partial() -> None:
    """Area covered always trails diameter covered — a real, easy-to-invert trap."""
    sep, r_moon = 0.30, 0.25
    magnitude = (R_SUN + r_moon - sep) / (2 * R_SUN)
    assert 0 < _obscuration(sep, R_SUN, r_moon) < magnitude


@pytest.mark.skipif(
    not (Path("data") / "de421.bsp").exists(), reason="DE421 kernel not downloaded"
)
def test_prague_2026_08_12_matches_published_circumstances() -> None:
    """The eclipse this project was built for, from the ephemeris."""
    ec = circumstances(
        50.0643, 14.4658, dt.date(2026, 8, 12), 2.0, ephemeris_dir=Path("data")
    )
    assert ec is not None

    assert ec.first.when.strftime("%H:%M") == "19:19"
    assert ec.maximum.when.strftime("%H:%M") == "20:11"
    assert ec.magnitude == pytest.approx(0.885, abs=0.01)

    # The sun is still up at maximum but sets before the eclipse ends — the
    # fact that drives the whole window design.
    assert ec.maximum_is_visible
    assert ec.ends_after_sunset
    assert ec.maximum.sun_altitude_deg == pytest.approx(1.33, abs=0.1)
