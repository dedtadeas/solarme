"""Distant terrain: the horizon beyond the reach of the 1 m sweep.

The near-field DSM stops at the AOI boundary, but a sun at 2-12° is blocked by
things well outside it. Prague sits in a basin; the ridges west of the city and
the uplands 30-80 km out are squarely in the way of a WNW sun this low. Without
them the sweep reads optimistic for every sight-line that leaves the box.

Same model as the near field
----------------------------
The far field is the *same* ČÚZK DMP, requested progressively coarser with
distance, rather than a second dataset. That buys three things:

* **One vertical datum.** Everything is Bpv end to end, so no ray ever compares
  heights across datums.
* **Real crests.** Measured against Copernicus GLO-30 over a ridge 60 km WNW of
  Prague, ČÚZK's true crest sits 6.1 m higher.
* **Resolution where it pays.** A crest error of `h` at distance `d` costs
  `atan(h/d)` of horizon angle, so precision can be spent near and saved far.

Crests, not averages
--------------------
The ImageServer resamples by **averaging** — verified: a 50 m request matches a
local mean-pool to within 0.14 m. Averaging shaves ridge tops (p95 13 m, worst
36 m at 50 m), and a shaved ridge lets the sun through where it should not. So
each ring is requested *finer* than it is marched and max-pooled locally, which
keeps the crest instead of the mean.

Curvature
---------
Not optional at this range: over 100 km the Earth falls away ~785 m, more than
any hill in Bohemia. Standard atmospheric refraction bends the ray back by
roughly 13%, handled the usual surveying way with an effective radius
``R / (1 - k)``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import rasterio
from scipy.ndimage import map_coordinates

from .config import Config
from .fetch import fetch_region
from .sun import SunSample

_R_EARTH = 6_371_000.0
_REFRACTION_K = 0.13  # standard atmosphere; effective radius R/(1-k)
_R_EFF = _R_EARTH / (1.0 - _REFRACTION_K)


@dataclass
class Ring:
    """One distance band of the far field, already max-pooled."""

    inner_m: float
    outer_m: float
    step_m: float
    dem: np.ndarray
    inv_transform: object

    def sample(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        cc, rr = self.inv_transform * (x, y)
        # order=0: never interpolate *below* a crest we deliberately preserved.
        return map_coordinates(self.dem, [rr, cc], order=0, mode="nearest")


def _max_pool(a: np.ndarray, factor: int) -> np.ndarray:
    """Downsample by taking the maximum, so ridge tops survive."""
    if factor <= 1:
        return a
    h = (a.shape[0] // factor) * factor
    w = (a.shape[1] // factor) * factor
    return a[:h, :w].reshape(h // factor, factor, w // factor, factor).max(axis=(1, 3))


def build_rings(cfg: Config, progress=print) -> list[Ring]:
    """Fetch and prepare every distance band."""
    a = cfg.aoi
    rings: list[Ring] = []
    inner_km = cfg.far_field["start_distance_m"] / 1000.0

    for spec in cfg.far_field["rings"]:
        outer_m = spec["outer_km"] * 1000.0
        req_res = float(spec["request_res_m"])
        step = float(spec["march_step_m"])

        bounds = (a.xmin - outer_m, a.ymin - outer_m, a.xmax + outer_m, a.ymax + outer_m)
        name = f"far_{spec['outer_km']}km_{spec['request_res_m']}m"
        vrt = fetch_region(cfg, "surface", bounds, req_res, name, progress=progress)

        with rasterio.open(vrt) as ds:
            dem = ds.read(1).astype(np.float32)
            transform = ds.transform

        factor = int(round(step / req_res))
        pooled = _max_pool(dem, factor)
        pooled_transform = transform * rasterio.Affine.scale(factor, factor)

        voids = float(np.mean(~np.isfinite(pooled)))
        if voids > 0.001:
            progress(
                f"  ring <{spec['outer_km']} km: {100 * voids:.1f}% no data "
                "(outside ČÚZK coverage — those bearings get an open horizon)"
            )
        # A void must not read as a mountain; treat it as open sky.
        pooled = np.nan_to_num(pooled, nan=-9e6, posinf=-9e6, neginf=-9e6)

        progress(
            f"  ring {inner_km:.0f}-{spec['outer_km']} km: requested {req_res} m, "
            f"max-pooled to {step:.0f} m ({pooled.shape[0]}x{pooled.shape[1]})"
        )
        rings.append(
            Ring(
                inner_m=inner_km * 1000.0,
                outer_m=outer_m,
                step_m=step,
                dem=pooled,
                inv_transform=~pooled_transform,
            )
        )
        inner_km = spec["outer_km"]

    return rings


def horizon_grid(
    cfg: Config,
    samples: list[SunSample],
    *,
    spacing_m: float = 2000.0,
    progress=print,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Horizon elevation angle per coarse grid point, per timestamp.

    Returns ``(angles, xs, ys)`` with ``angles`` shaped
    ``(len(samples), len(ys), len(xs))`` in degrees. The horizon varies slowly
    across a 26 km box, so it is solved on a coarse grid and interpolated
    rather than ray-marched from every one of 676 million pixels.
    """
    a = cfg.aoi
    rings = build_rings(cfg, progress)

    xs = np.arange(a.xmin, a.xmax + spacing_m, spacing_m)
    ys = np.arange(a.ymin, a.ymax + spacing_m, spacing_m)
    gx, gy = np.meshgrid(xs, ys)
    px, py = gx.ravel(), gy.ravel()

    # Observer elevation comes from the finest ring, i.e. the same model and
    # datum the ray is measured against.
    z0 = rings[0].sample(px, py)

    angles = np.zeros((len(samples), len(ys), len(xs)), dtype=np.float32)

    for i, smp in enumerate(samples):
        th = np.radians(smp.azimuth)
        sin_th, cos_th = np.sin(th), np.cos(th)
        best = np.full(px.shape, -90.0)

        for ring in rings:
            d = np.arange(ring.inner_m, ring.outer_m, ring.step_m, dtype=np.float64)
            if d.size == 0:
                continue
            drop = (d**2) / (2.0 * _R_EFF)  # curvature, softened by refraction

            z = ring.sample(px[:, None] + sin_th * d, py[:, None] + cos_th * d)
            elev = np.degrees(np.arctan2(z - z0[:, None] - drop[None, :], d[None, :]))
            best = np.maximum(best, elev.max(axis=1))

        angles[i] = np.maximum(best, 0.0).reshape(len(ys), len(xs))

    progress(
        f"far-field horizon {angles.min():.2f}..{angles.max():.2f} deg "
        f"over {len(samples)} timestamps"
    )
    return angles, xs, ys


def _grid_indices(
    xs: np.ndarray, ys: np.ndarray, xmin: float, ymax: float,
    width: int, height: int, res: float,
) -> tuple[np.ndarray, np.ndarray]:
    px = xmin + (np.arange(width, dtype=np.float64) + 0.5) * res
    py = ymax - (np.arange(height, dtype=np.float64) + 0.5) * res
    # `ys` ascends northward while raster rows descend.
    return (py - ys[0]) / (ys[1] - ys[0]), (px - xs[0]) / (xs[1] - xs[0])


# Rows per band when expanding the coarse horizon. Small enough that the
# float64 coordinate arrays stay incidental.
_BAND_ROWS = 1024


def horizon_blocks(
    angle: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    sun_elevation_deg: float,
    *,
    xmin: float,
    ymax: float,
    width: int,
    height: int,
    res: float,
) -> np.ndarray:
    """Boolean mask: is the sun below the distant horizon at this pixel?

    Expanded in row bands and reduced to a mask immediately, never materialised
    as a full float plane. A whole-block `np.meshgrid` is float64 by default —
    at a 10000 x 10000 block that is 1.6 GB of coordinates for a comparison
    whose answer is one bit per pixel, and it was enough to kill workers that
    otherwise had headroom.
    """
    ri, ci = _grid_indices(xs, ys, xmin, ymax, width, height, res)
    out = np.empty((height, width), dtype=bool)

    for r0 in range(0, height, _BAND_ROWS):
        rows = ri[r0 : r0 + _BAND_ROWS]
        rr, cc = np.meshgrid(rows, ci, indexing="ij")
        band = map_coordinates(angle, [rr, cc], order=1, mode="nearest")
        np.greater_equal(band, sun_elevation_deg, out=out[r0 : r0 + _BAND_ROWS])

    return out


def interp_block(
    angle: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    xmin: float,
    ymax: float,
    width: int,
    height: int,
    res: float,
) -> np.ndarray:
    """Bilinearly expand one coarse horizon plane onto a block's pixel grid.

    Kept for inspection and tests; the sweep uses `horizon_blocks`, which does
    the same interpolation without holding a full float plane.
    """
    ri, ci = _grid_indices(xs, ys, xmin, ymax, width, height, res)
    rr, cc = np.meshgrid(ri, ci, indexing="ij")
    return map_coordinates(angle, [rr, cc], order=1, mode="nearest").astype(np.float32)
