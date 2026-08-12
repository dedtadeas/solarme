"""Analytic tests for the shadow sweep.

Every case here has a closed-form answer, so these catch the two failure modes
that would otherwise be invisible on a real DSM: a shadow cast toward the sun
instead of away from it, and a shadow of the wrong length.
"""

from __future__ import annotations

import numpy as np
import pytest

from sunline.shadow import min_eye_elevation, visible

BOX_H = 20.0
CENTRE = slice(95, 106)  # rows/cols 95..105 inclusive

# `visible()` blocks on `observer_z > m`, so a ground-level observer (z=0) is in
# shadow whenever M >= 0 — including the grazing tip where M is exactly 0.
def shadowed(m: np.ndarray, ground_z: float = 0.0) -> np.ndarray:
    return m >= ground_z


def flat_with_box(n: int = 200) -> np.ndarray:
    surface = np.zeros((n, n), dtype=np.float32)
    surface[CENTRE, CENTRE] = BOX_H
    return surface


# Azimuth -> the (row, col) step that walks *away* from the sun, i.e. the
# direction the shadow must fall. Azimuth is clockwise from north.
AWAY = {
    0.0: (1, 0),  # sun in the north  -> shadow runs south (+row)
    90.0: (0, -1),  # sun in the east   -> shadow runs west  (-col)
    180.0: (-1, 0),  # sun in the south  -> shadow runs north (-row)
    270.0: (0, 1),  # sun in the west   -> shadow runs east  (+col)
}


@pytest.mark.parametrize("azimuth", sorted(AWAY))
def test_shadow_falls_away_from_the_sun(azimuth: float) -> None:
    """The single failure mode a real DSM would never make obvious."""
    m = min_eye_elevation(flat_with_box(), res=1.0, azimuth_deg=azimuth, elevation_deg=45.0)
    drow, dcol = AWAY[azimuth]

    # A ground pixel 5 m beyond the box, on the shadow side, must be dark...
    shaded = m[100 + drow * 10, 100 + dcol * 10]
    assert shadowed(shaded), f"azimuth {azimuth}: expected shadow at +10 px, got M={shaded}"

    # ...and its mirror image on the sunlit side must be clear.
    lit = m[100 - drow * 10, 100 - dcol * 10]
    assert not shadowed(lit), f"azimuth {azimuth}: sunlit side is shadowed, M={lit}"


@pytest.mark.parametrize("elev_deg", [15.0, 30.0, 45.0, 60.0])
def test_shadow_length_matches_h_over_tan(elev_deg: float) -> None:
    """A 20 m box at elevation e shadows exactly h/tan(e) metres of ground."""
    m = min_eye_elevation(flat_with_box(), res=1.0, azimuth_deg=270.0, elevation_deg=elev_deg)

    row = m[100, 106:]  # ground running east from the box edge at col 105
    dark = np.flatnonzero(shadowed(row))
    reach = dark.max() + 1 if dark.size else 0

    expected = BOX_H / np.tan(np.radians(elev_deg))
    assert reach == pytest.approx(expected, abs=1.5), (
        f"elevation {elev_deg}: shadow reached {reach} m, expected {expected:.1f} m"
    )


def test_shadow_is_contiguous_from_the_box() -> None:
    """No gaps: the shadow starts at the box and runs unbroken to its tip."""
    m = min_eye_elevation(flat_with_box(), res=1.0, azimuth_deg=270.0, elevation_deg=45.0)
    row = shadowed(m[100, 106:126])
    assert row.all(), f"shadow has holes: {(~row).nonzero()[0]}"


def test_required_eye_height_decays_linearly() -> None:
    """M is a height, not a flag: it should fall by tan(e) per metre travelled."""
    m = min_eye_elevation(flat_with_box(), res=1.0, azimuth_deg=270.0, elevation_deg=45.0)
    # At 45 deg, needing 20 m at the box edge means needing 20-d at distance d.
    for d in (2, 5, 10, 15):
        assert m[100, 105 + d] == pytest.approx(BOX_H - d, abs=1.0)


def test_flat_ground_is_never_shadowed() -> None:
    flat = np.zeros((64, 64), dtype=np.float32)
    m = min_eye_elevation(flat, res=1.0, azimuth_deg=225.0, elevation_deg=10.0)
    assert not shadowed(m[8:-8, 8:-8]).any()


def test_sun_below_horizon_blocks_everything() -> None:
    m = min_eye_elevation(flat_with_box(), res=1.0, azimuth_deg=270.0, elevation_deg=-0.5)
    assert np.isinf(m).all()


@pytest.mark.parametrize("slope_deg,sun_deg,expect_lit", [(5.0, 20.0, True), (25.0, 10.0, False)])
def test_uniform_ramp_facing_the_sun(slope_deg: float, sun_deg: float, expect_lit: bool) -> None:
    """A constant slope is lit iff the sun clears the slope angle.

    Ramp rises toward the west (-col), sun in the west at azimuth 270.
    """
    n = 300
    cols = np.arange(n, dtype=np.float32)
    ramp = np.tile((n - cols) * np.tan(np.radians(slope_deg)), (n, 1)).astype(np.float32)

    m = min_eye_elevation(ramp, res=1.0, azimuth_deg=270.0, elevation_deg=sun_deg)
    interior = m[100:200, 100:200]
    ground = ramp[100:200, 100:200]

    lit = bool((ground >= interior).all())
    assert lit == expect_lit, (
        f"slope {slope_deg} vs sun {sun_deg}: expected lit={expect_lit}"
    )


def test_observer_stands_on_terrain_not_canopy() -> None:
    """The bug the brief's 'DSM + 1.6 m' would have shipped.

    A 15 m tree canopy over flat ground: someone underneath it must not be
    reported as seeing a sun that only the treetop can see.
    """
    n = 120
    terrain = np.zeros((n, n), dtype=np.float32)
    surface = terrain.copy()
    surface[:, 40:60] = 15.0  # a belt of trees

    # Sun low in the west; the observer sits east of the belt, in its shadow.
    seen = visible(surface, terrain, res=1.0, azimuth_deg=270.0, elevation_deg=10.0, eye_height_m=1.6)
    assert not seen[60, 70], "observer under/behind canopy wrongly sees the sun"

    # Same scene, but the observer is on a 20 m terrace that clears the belt.
    terrace = terrain.copy()
    terrace[:, 65:75] = 20.0
    surface_t = np.maximum(surface, terrace)
    seen_t = visible(surface_t, terrace, res=1.0, azimuth_deg=270.0, elevation_deg=10.0, eye_height_m=1.6)
    assert seen_t[60, 70], "observer above the canopy wrongly reported as blocked"


def test_tall_tower_shadow_is_not_truncated_at_coarse_scale() -> None:
    """The bug a user spotted from the real horizon, pinned at the geometry level.

    A 216 m tower (Žižkov) at a 1.5 deg sun shadows 8.2 km. The fine sweep's
    3 km halo cannot see that far — the coarse pass exists precisely for this,
    so the same sweep at 5 m resolution must carry the shadow to full length.
    """
    res, height, elev = 5.0, 216.0, 1.5
    n = 2000  # 10 km at 5 m
    surface = np.zeros((41, n), dtype=np.float32)
    surface[15:26, 100:106] = height  # a 30 m wide tower near the sun-side edge

    m = min_eye_elevation(surface, res=res, azimuth_deg=270.0, elevation_deg=elev)

    expected_px = int(height / np.tan(np.radians(elev)) / res)  # ~1650 px
    row = m[20, 106:]
    dark = np.flatnonzero(row >= 0.0)
    reach_px = dark.max() + 1 if dark.size else 0

    assert reach_px == pytest.approx(expected_px, abs=3), (
        f"216 m tower at {elev} deg: shadow reached {reach_px * res:.0f} m, "
        f"expected {expected_px * res:.0f} m"
    )
    # And the tail is present far beyond the fine sweep's 3 km halo.
    assert row[int(5000 / res)] >= 0.0, "shadow missing at 5 km — tail truncated"
