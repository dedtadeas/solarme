"""Guards on the handoff between the near-field sweep and the far-field rings.

The two models must butt together exactly. An earlier config left a 1.2-3 km
band that neither covered — the sweep only reads `aoi.buffer_m` around each
block, and the rings did not start until 3 km. Nothing errored; the map was
just quietly wrong, contributing up to 9.5 deg of missing horizon and leaving
12% of locations wrong for at least one timestamp.

That is the kind of bug a unit test has to catch, because the output still
looks entirely plausible.
"""

from __future__ import annotations

import numpy as np
import pytest

from sunline.config import load_config
from sunline.far_field import _R_EFF

CONFIG = "config.yaml"


@pytest.fixture(scope="module")
def cfg():
    return load_config(CONFIG)


def test_coarse_sweep_reaches_the_first_ring(cfg) -> None:
    """No unmodelled band between the coarse sweep and the ring march."""
    halo = float(cfg.raw["sweep"]["coarse"]["halo_m"])
    ring_start = float(cfg.far_field["start_distance_m"])
    assert halo >= ring_start, (
        f"gap of {ring_start - halo:.0f} m between the coarse sweep's reach "
        f"({halo:.0f} m) and the first ring ({ring_start:.0f} m). "
        "Blockers in that band are modelled by nothing."
    )


def test_coarse_halo_covers_the_tallest_structure(cfg) -> None:
    """A structure taller than tan(floor) * halo outruns even the coarse pass.

    This is the truncation that shipped once already: the fine halo capped
    blocker height at 52 m and every tower and spire above that had its shadow
    end abruptly at 3 km. The coarse halo must clear the tallest thing in or
    near the AOI (Žižkov TV tower, 216 m) at the elevation floor.
    """
    cc = cfg.raw["sweep"]["coarse"]
    floor = np.radians(float(cfg.sun["min_elevation_deg"]))
    reach = float(cc["max_structure_m"]) / np.tan(floor)
    assert float(cc["halo_m"]) >= reach, (
        f"a {cc['max_structure_m']} m structure reaches {reach:.0f} m at the "
        f"floor, past the {cc['halo_m']} m coarse halo — its shadow gets cut off"
    )


def test_coarse_res_is_integer_multiple_of_fine(cfg) -> None:
    """The coarse mask is upsampled by np.repeat, which needs a whole factor."""
    ratio = float(cfg.raw["sweep"]["coarse"]["res"]) / cfg.aoi.resolution
    assert ratio == int(ratio) and ratio >= 1


def test_rings_are_contiguous_and_ordered(cfg) -> None:
    """Each ring must start where the previous one ended."""
    rings = cfg.far_field["rings"]
    outers = [r["outer_km"] for r in rings]
    assert outers == sorted(outers), f"rings out of order: {outers}"
    assert outers[-1] * 1000 <= cfg.far_field["radius_km"] * 1000 + 1


def test_flat_earth_fine_sweep_stays_inside_the_strict_budget(cfg) -> None:
    """The fine sweep ignores curvature; at 3 km that is 0.012 deg — fine."""
    d = cfg.aoi.buffer_m
    drop = d**2 / (2.0 * _R_EFF)
    angle = np.degrees(np.arctan2(drop, d))
    assert angle < 0.02, (
        f"at {d:.0f} m the ignored curvature drop is {drop:.2f} m ({angle:.3f} deg), "
        "past the 0.02 deg budget — add curvature to the sweep or shorten the buffer"
    )


def test_flat_earth_coarse_sweep_stays_inside_its_documented_tolerance(cfg) -> None:
    """The coarse sweep is flat-earth too, over a much deeper halo.

    At 13 km the ignored drop is ~11.6 m = 0.05 deg. That error OVER-blocks
    (distant blockers look taller than they are), so it is pessimistic, never
    optimistic — accepted and documented in config.yaml at up to 0.06 deg.
    """
    d = float(cfg.raw["sweep"]["coarse"]["halo_m"])
    drop = d**2 / (2.0 * _R_EFF)
    angle = np.degrees(np.arctan2(drop, d))
    assert angle < 0.06, (
        f"coarse halo {d:.0f} m ignores {drop:.1f} m of curvature ({angle:.3f} deg) — "
        "past even the relaxed tolerance; the coarse pass needs a curvature term"
    )


def test_ring_grid_is_fine_enough_for_its_start_distance(cfg) -> None:
    """The horizon grid is interpolated, so it must be well inside the ring start.

    If the grid spacing approaches the distance at which terrain starts
    contributing, one location's nearby hill smears onto its neighbour.
    """
    spacing = float(cfg.far_field["grid_spacing_m"])
    start = float(cfg.far_field["start_distance_m"])
    assert start / spacing >= 2.0, (
        f"grid spacing {spacing:.0f} m is too coarse for a ring starting at "
        f"{start:.0f} m (ratio {start / spacing:.1f}, want >= 2)"
    )


def test_buffer_covers_the_tallest_plausible_blocker_at_the_floor(cfg) -> None:
    """Sanity: the buffer should clear an ordinary tall building at the floor.

    Not the binding constraint any more — meeting the rings is — but if this
    ever fails the elevation floor and the buffer have drifted apart.
    """
    floor = np.radians(float(cfg.sun["min_elevation_deg"]))
    reach = 40.0 / np.tan(floor)
    assert cfg.aoi.buffer_m >= reach, (
        f"a 40 m blocker reaches {reach:.0f} m at the {cfg.sun['min_elevation_deg']} deg "
        f"floor, past the {cfg.aoi.buffer_m:.0f} m buffer"
    )


def test_halo_beyond_the_fetched_extent_does_not_poison(tmp_path) -> None:
    """The all-black bug: NaN boundless-fill entering the running maximum.

    The coarse pass reads a 13 km halo from a cache fetched with 3 km margins,
    so the outer band of every read is fill values. With NaN fill,
    np.maximum.accumulate([1, nan, ...]) turns the whole row NaN, every
    comparison with NaN is False, and the entire map silently scores "never
    sees the sun". This builds a raw cache SMALLER than the requested halo and
    checks open ground still sees an unobstructed sun.
    """
    import rasterio

    from sunline.composite import _NOTHING, _read_bounds
    from sunline.shadow import min_eye_elevation

    # A 1 km flat DSM at z=200 m, centred on (0, 0).
    size, res = 1000, 1.0
    transform = rasterio.transform.from_origin(-size / 2, size / 2, res, res)
    path = tmp_path / "surface.tif"
    with rasterio.open(
        path, "w", driver="GTiff", width=size, height=size, count=1,
        dtype="float32", crs="EPSG:5514", transform=transform,
    ) as ds:
        ds.write(np.full((size, size), 200.0, dtype=np.float32), 1)

    # Read with a halo far beyond the raster, as the coarse pass does.
    bounds = (-3000, -3000, 3000, 3000)
    surface = _read_bounds(
        path, bounds, (1200, 1200), rasterio.enums.Resampling.max, fill=_NOTHING
    )
    assert np.isfinite(surface).all(), "fill must be finite before the sweep"

    m = min_eye_elevation(surface, 5.0, azimuth_deg=285.0, elevation_deg=3.0)
    centre = m[590:610, 590:610]  # the real data, observer at 201.6 m
    assert not np.isnan(centre).any(), "NaN reached the sweep output"
    assert (201.6 > centre).all(), (
        "flat open ground reads as blocked — the halo fill is poisoning the row"
    )
