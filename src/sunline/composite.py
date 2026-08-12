"""Sweep every timestamp over the AOI and composite the result.

The AOI is processed in blocks rather than as one array. A 26 km box at 1 m is
676 Mpx; rotating that whole grid per timestamp would need ~5 GB of float32 in
flight on a 15 GB machine, and there are 35 timestamps.

Each block is read with `aoi.buffer_m` of margin on every side so that blockers
just outside it still cast into it, then cropped back after the sweep. That
halo is what bounds a pixel's sight-line — not the fetched extent — so it is
sized in config to meet the far-field rings exactly.

Memory is the binding constraint, not CPU. With a 3 km halo a 4 km block reads
10000^2 and rotates to 14142^2, so peak is ~3.4 GB per worker and only three
fit alongside each other. Two earlier attempts died with BrokenProcessPool:
once because `min_eye_elevation` held two rotated arrays at once, and once
because the far-field expansion built float64 meshgrids at full block size.
Both are fixed at the source; if this needs tuning again, measure peak RSS with
the far-field branch *firing* (the last few timestamps) rather than without it.
"""

from __future__ import annotations

import concurrent.futures as cf
import multiprocessing as mp
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window, from_bounds

from .config import Config, load_config
from .far_field import horizon_blocks, horizon_grid
from .shadow import min_eye_elevation
from .sun import SunSample, sun_series


@dataclass(frozen=True)
class Block:
    """One AOI sub-rectangle, in map coordinates."""

    row: int
    col: int
    xmin: float
    ymin: float
    xmax: float
    ymax: float


def plan_blocks(cfg: Config, block_m: float) -> list[Block]:
    a = cfg.aoi
    blocks: list[Block] = []
    ny = int(np.ceil((a.ymax - a.ymin) / block_m))
    nx = int(np.ceil((a.xmax - a.xmin) / block_m))
    for r in range(ny):
        for c in range(nx):
            blocks.append(
                Block(
                    row=r,
                    col=c,
                    xmin=a.xmin + c * block_m,
                    ymin=a.ymin + r * block_m,
                    xmax=min(a.xmin + (c + 1) * block_m, a.xmax),
                    ymax=min(a.ymin + (r + 1) * block_m, a.ymax),
                )
            )
    return blocks


# Fill for BLOCKER reads outside the fetched extent: "nothing there, blocks
# nothing". It must be finite — a NaN entering the sweep's running maximum
# propagates down the whole row (np.maximum.accumulate([1, nan, 2]) is
# [1, nan, nan]) and, because every comparison with NaN is False, silently
# scores the entire block "never sees the sun". The coarse pass reads a 13 km
# halo from a cache fetched with 3 km margins, so it *always* touches this
# region; at country scale the outermost blocks always will too.
_NOTHING = np.float32(-9e6)


def _read_bounds(path: Path, bounds, out_shape, resampling, fill: float) -> np.ndarray:
    """Read a geographic window, resampled onto the analysis grid.

    `fill` is the value for pixels beyond the raster: `_NOTHING` for blocker
    surfaces (see above), NaN for observer terrain — terrain NaN only ever
    lands outside the block crop, and it keeps the covered/nodata semantics
    honest if that assumption is ever broken.
    """
    with rasterio.open(path) as ds:
        win = from_bounds(*bounds, transform=ds.transform)
        out = ds.read(
            1,
            window=win,
            out_shape=out_shape,
            resampling=resampling,
            boundless=True,
            fill_value=fill,
        ).astype(np.float32)
    # The service itself can also hand back NaN nodata (outside ČÚZK coverage);
    # for a blocker read those must become "nothing" too, not poison.
    if not np.isnan(fill):
        np.nan_to_num(out, copy=False, nan=fill, posinf=fill, neginf=fill)
    return out


def _coarse_pass(
    cfg: Config, block: Block, samples: list[SunSample]
) -> tuple[np.ndarray, int]:
    """Long-tail shadows from tall structures, at coarse resolution.

    The fine sweep's halo caps blocker height at tan(floor) * buffer_m — 52 m
    for the defaults — and Prague is full of taller things: the Žižkov tower
    (216 m) shadows 12.4 km at a 1 deg sun, the Pankrác towers 6+ km, church
    spires 3.4-5.7 km. Their tails were being cut off at the halo edge, visible
    on the map as shadows that simply stop. (Spotted by looking at the real
    horizon, not the code: a low sun that sets behind something tall stays set
    for kilometres, and the map disagreed.)

    This pass re-runs the same cummax sweep on a max-pooled DSM with a much
    deeper halo and returns a per-timestamp visibility stack over the block
    only. Max-pooling (Resampling.max) keeps crests, consistent with the
    far-field rings; a mean would shave every rooftop. The stack for a 4 km
    block at 5 m is ~19 MB of bool — and because this runs *before* the fine
    arrays are allocated, worker peak memory does not grow.

    Costs accepted: shadow edges gain up to one coarse cell (~5 m horizontal
    = 0.09 m of eye height at 1 deg), and flat-earth over 13 km over-blocks by
    up to 0.05 deg — pessimistic, never optimistic.
    """
    cc = cfg.raw["sweep"]["coarse"]
    cres = float(cc["res"])
    halo = float(cc["halo_m"])
    ratio = cres / cfg.aoi.resolution
    assert ratio == int(ratio), "coarse res must be an integer multiple of fine"

    bounds = (block.xmin - halo, block.ymin - halo, block.xmax + halo, block.ymax + halo)
    w = int(round((bounds[2] - bounds[0]) / cres))
    h = int(round((bounds[3] - bounds[1]) / cres))

    surface = _read_bounds(cfg.raw_dir / "surface.vrt", bounds, (h, w), Resampling.max, fill=_NOTHING)
    terrain = _read_bounds(cfg.raw_dir / "terrain.vrt", bounds, (h, w), Resampling.bilinear, fill=float("nan"))
    observer_z = terrain + np.float32(cfg.observer["eye_height_m"])
    del terrain

    r0 = int(round(halo / cres))
    rows = int(round((block.ymax - block.ymin) / cres))
    cols = int(round((block.xmax - block.xmin) / cres))
    crop = (slice(r0, r0 + rows), slice(r0, r0 + cols))

    vis = np.empty((len(samples), rows, cols), dtype=bool)
    for i, smp in enumerate(samples):
        m = min_eye_elevation(surface, cres, smp.azimuth, smp.elevation)
        vis[i] = (observer_z > m)[crop]
    return vis, int(ratio)


def _sweep_block(
    args: tuple[Config, Block, list[SunSample], tuple | None, int],
) -> tuple[Block, np.ndarray, np.ndarray, int]:
    """Per pixel: fraction of timestamps the sun is visible, and at maximum."""
    cfg, block, samples, horizon, i_max = args
    res = cfg.aoi.resolution
    buf = cfg.aoi.buffer_m

    # Coarse pass first — see _coarse_pass for why it exists and why first.
    coarse_vis, ratio = _coarse_pass(cfg, block, samples)

    bounds = (block.xmin - buf, block.ymin - buf, block.xmax + buf, block.ymax + buf)
    w = int(round((bounds[2] - bounds[0]) / res))
    h = int(round((bounds[3] - bounds[1]) / res))

    surface = _read_bounds(cfg.raw_dir / "surface.vrt", bounds, (h, w), Resampling.nearest, fill=_NOTHING)
    # Terrain is 2 m native and genuinely smooth, so bilinear upsampling onto
    # the 1 m grid is both cheap and faithful.
    terrain = _read_bounds(cfg.raw_dir / "terrain.vrt", bounds, (h, w), Resampling.bilinear, fill=float("nan"))

    observer_z = terrain + np.float32(cfg.observer["eye_height_m"])
    # Anything directly overhead means there is no standing room here.
    covered = (surface - terrain) > np.float32(cfg.observer["covered_threshold_m"])
    del terrain

    # Everything below accumulates on the block extent, not the halo extent.
    r0 = int(round(buf / res))
    rows = int(round((block.ymax - block.ymin) / res))
    cols = int(round((block.xmax - block.xmin) / res))
    crop = (slice(r0, r0 + rows), slice(r0, r0 + cols))
    obs_block = observer_z[crop]
    covered_block = covered[crop]

    count = np.zeros((rows, cols), dtype=np.uint16)
    at_max = np.zeros((rows, cols), dtype=np.uint8)
    for i, smp in enumerate(samples):
        m = min_eye_elevation(surface, res, smp.azimuth, smp.elevation)
        seen = obs_block > m[crop]

        # Long-tail blockers, upsampled from the coarse grid. Nearest (repeat)
        # keeps the mask conservative; bilinear would soften real shadow.
        cv = coarse_vis[i]
        seen &= np.repeat(np.repeat(cv, ratio, axis=0), ratio, axis=1)[:rows, :cols]

        if horizon is not None:
            angle, xs, ys = horizon[0][i], horizon[1], horizon[2]
            # Most timestamps clear the highest distant ridge outright; only
            # near sunset is the expansion worth doing at all.
            if smp.elevation <= float(angle.max()):
                seen &= ~horizon_blocks(
                    angle, xs, ys, smp.elevation,
                    xmin=block.xmin, ymax=block.ymax, width=cols, height=rows, res=res,
                )

        count += seen
        if i == i_max:
            # The deepest moment of the eclipse gets its own layer: "fraction
            # of the window" averages away the one instant most people care
            # about being able to see.
            at_max = seen.astype(np.uint8)

    fraction = count / np.float32(len(samples))
    fraction[covered_block] = np.nan  # masked out, not scored zero
    at_max[covered_block] = 255       # 255 = no standing room, 0/1 = blocked/visible

    return block, fraction, at_max, len(samples)


def run(cfg: Config, *, block_m: float = 4000.0, workers: int | None = None, progress=print) -> Path:
    """Produce the visible-fraction raster for the whole AOI."""
    samples = sun_series(cfg)
    if not samples:
        raise SystemExit("no sun samples above the elevation floor — check config.sun")

    horizon = None
    if cfg.far_field.get("enabled"):
        angles, hxs, hys = horizon_grid(
            cfg, samples, spacing_m=cfg.far_field["grid_spacing_m"], progress=progress
        )
        horizon = (angles, hxs, hys)
        progress(
            f"far-field horizon {angles.min():.2f}..{angles.max():.2f} deg "
            f"from {cfg.far_field['start_distance_m'] / 1000:.0f} km out"
        )

    # Which sample sits closest to maximum eclipse? -1 if there is no eclipse
    # (a plain sunset run), in which case no max layer is written.
    i_max = -1
    try:
        from .sun import eclipse_circumstances

        ec = eclipse_circumstances(cfg)
        if ec is not None:
            import pandas as pd

            peak = pd.Timestamp(ec.maximum.when).tz_localize(cfg.sun["timezone"])
            offsets = [abs((s.when - peak).total_seconds()) for s in samples]
            i_max = int(np.argmin(offsets))
            progress(
                f"maximum eclipse {ec.maximum.when:%H:%M:%S} (mag {ec.magnitude:.3f}, "
                f"obscuration {ec.obscuration:.3f}) -> sample {i_max} "
                f"at {samples[i_max].when:%H:%M}, {offsets[i_max] / 60:.1f} min away, "
                f"sun {samples[i_max].elevation:.2f} deg"
            )
    except Exception as exc:
        progress(f"maximum-eclipse layer skipped: {exc}")

    blocks = plan_blocks(cfg, block_m)
    workers = workers or min(6, os.cpu_count() or 1)
    progress(
        f"sweep: {len(blocks)} blocks x {len(samples)} timestamps "
        f"on {workers} workers"
    )

    a = cfg.aoi
    dst = cfg.out_dir / "visible_fraction.tif"
    dst_max = cfg.out_dir / "visible_at_max.tif"
    transform = rasterio.transform.from_origin(a.xmin, a.ymax, a.resolution, a.resolution)

    profile = dict(
        driver="GTiff", height=a.height_px, width=a.width_px, count=1,
        crs=a.crs, transform=transform, compress="deflate",
        tiled=True, blockxsize=512, blockysize=512, BIGTIFF="IF_SAFER",
    )

    # Blocks are written straight into the GeoTIFF as they land. Holding the
    # whole 676 Mpx grid in the parent would cost 2.7 GB on top of every
    # worker's own working set, which is what pushed the first run to the edge
    # of memory.
    n_open = n_zero = n_full = n_total = 0
    total_sum = 0.0

    n_max_seen = n_max_open = 0

    with rasterio.open(
        dst, "w", dtype="float32", predictor=2,
        nodata=float("nan"),   # the covered mask — no standing room here
        **profile,
    ) as ds, rasterio.open(
        dst_max, "w", dtype="uint8", nodata=255, **profile
    ) as ds_max:
        done = 0
        # "spawn", not the Linux default "fork". The far-field rings are
        # downloaded through a thread pool just above this, and forking a
        # process that has already run threads through GDAL deadlocks: the
        # children inherit a lock no surviving thread will ever release, and
        # every worker sits at 0% CPU forever. Spawn starts them clean.
        with cf.ProcessPoolExecutor(
            max_workers=workers, mp_context=mp.get_context("spawn")
        ) as pool:
            for block, fraction, at_max, _n in pool.map(
                _sweep_block, [(cfg, b, samples, horizon, i_max) for b in blocks]
            ):
                r0 = int(round((a.ymax - block.ymax) / a.resolution))
                c0 = int(round((block.xmin - a.xmin) / a.resolution))
                win = Window(c0, r0, fraction.shape[1], fraction.shape[0])
                ds.write(fraction, 1, window=win)
                ds_max.write(at_max, 1, window=win)

                stands = at_max != 255
                n_max_open += int(stands.sum())
                n_max_seen += int((at_max == 1).sum())

                open_ground = np.isfinite(fraction)
                vals = fraction[open_ground]
                n_open += int(open_ground.sum())
                n_total += fraction.size
                n_zero += int((vals == 0).sum())
                n_full += int((vals == 1).sum())
                total_sum += float(vals.sum())

                done += 1
                progress(f"  block {done}/{len(blocks)} [{block.row},{block.col}]")

        if n_max_open and i_max >= 0:
            progress(
                f"at maximum eclipse ({samples[i_max].when:%H:%M}): "
                f"{100 * n_max_seen / n_max_open:.1f}% of open ground sees the sun"
            )

        if n_open:
            progress(
                f"open ground {100 * n_open / n_total:.0f}% of AOI — "
                f"never visible {100 * n_zero / n_open:.0f}%, "
                f"whole window {100 * n_full / n_open:.0f}%, "
                f"mean {total_sum / n_open:.3f}"
            )

        ds.update_tags(
            window_start=cfg.sun["window"]["start"],
            window_end=cfg.sun["window"]["end"],
            samples=str(len(samples)),
            min_elevation_deg=str(cfg.sun["min_elevation_deg"]),
            eye_height_m=str(cfg.observer["eye_height_m"]),
            attribution=cfg.raw["attribution"],
        )

    progress(f"wrote {dst}")
    if i_max >= 0:
        progress(f"wrote {dst_max}")
    return dst


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    run(load_config(argv[0] if argv else "config.yaml"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
