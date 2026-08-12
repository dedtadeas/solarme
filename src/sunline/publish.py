"""Turn the visible-fraction raster into a PMTiles archive for static hosting.

Chain: float32 (EPSG:5514) -> paletted uint8 -> reproject to 3857 -> MBTiles
+ overviews -> PMTiles. PMTiles is a single file served over HTTP range
requests, which GitHub Pages supports — verified with a 206 Partial Content
response — so the map needs no tile server, no backend and no database.

Why paletted rather than RGBA
-----------------------------
The sweep takes N timestamps, so the output has exactly N+1 possible values,
not 256. Writing RGBA spends four bytes a pixel encoding 36 states and lands
around 143 MB for the Prague box — past GitHub's 100 MB per-file limit. One
paletted band with an N+1 entry colour table carries the identical information
in roughly a third of the space.

That choice constrains resampling: palette *indices* must never be averaged, so
the warp uses nearest and the overviews use mode.

Colour: the brief asked for green-to-red, the one pairing ~8% of men cannot
read. `magma` carries the same "open vs blocked" reading through lightness
alone, so it survives greyscale and every CVD type.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import rasterio
from matplotlib import colormaps

from .config import Config, load_config

# Index 0 is reserved for "no standing room here" (under a roof or canopy).
_NODATA_INDEX = 0

# Leave headroom under GitHub's hard 100 MB per-file limit.
_SIZE_BUDGET_MB = 95


def build_palette(levels: int, cmap_name: str = "magma") -> dict[int, tuple[int, int, int, int]]:
    """Colour table with one entry per attainable visible-fraction value."""
    ramp = (np.asarray(colormaps[cmap_name](np.linspace(0, 1, levels + 1)))[:, :3] * 255).astype(int)
    table = {_NODATA_INDEX: (0, 0, 0, 0)}
    for i, rgb in enumerate(ramp):
        table[i + 1] = (int(rgb[0]), int(rgb[1]), int(rgb[2]), 255)
    return table


def to_paletted(src: Path, dst: Path, levels: int, cmap_name: str, progress=print) -> Path:
    """Float fraction -> single paletted band, still in the source CRS.

    Opacity is left at 255 and handled by the map's raster-opacity slider; a
    constant partial alpha baked into every tile would only cost bytes.
    """
    table = build_palette(levels, cmap_name)

    with rasterio.open(src) as ds:
        profile = ds.profile.copy()
        profile.update(
            count=1, dtype="uint8", nodata=_NODATA_INDEX,
            compress="deflate", tiled=True, blockxsize=512, blockysize=512,
            BIGTIFF="IF_SAFER",
        )
        with rasterio.open(dst, "w", **profile) as out:
            out.update_tags(**ds.tags())
            for _, win in ds.block_windows(1):
                a = ds.read(1, window=win)
                idx = np.where(
                    np.isfinite(a),
                    np.rint(np.nan_to_num(a) * levels) + 1,
                    _NODATA_INDEX,
                ).astype(np.uint8)
                out.write(idx, 1, window=win)
            out.write_colormap(1, table)

    progress(f"paletted ({levels + 1} levels) -> {dst}")
    return dst


def _run(cmd: list[str], progress) -> None:
    progress("  $ " + " ".join(cmd[:3]) + (" ..." if len(cmd) > 3 else ""))
    subprocess.run(cmd, check=True, capture_output=True)


def to_pmtiles(
    cfg: Config,
    paletted: Path,
    max_zoom: int,
    progress=print,
    *,
    stem: str = "visibility",
    pmtiles_name: str | None = None,
) -> Path:
    """Reproject to Web Mercator, tile to MBTiles, convert to PMTiles."""
    out = cfg.out_dir
    merc = out / f"{stem}_3857.tif"
    mbt = out / f"{stem}.mbtiles"
    pmt = out / (pmtiles_name or cfg.output["pmtiles_name"])
    for stale in (merc, mbt, pmt):
        stale.unlink(missing_ok=True)

    min_zoom = cfg.output["tiles"]["min_zoom"]

    _run(
        [
            "gdalwarp", "-overwrite",
            "-t_srs", "EPSG:3857",
            "-r", "near",  # palette indices must never be interpolated
            "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES", "-co", "BIGTIFF=IF_SAFER",
            "-multi", "-wo", "NUM_THREADS=ALL_CPUS",
            str(paletted), str(merc),
        ],
        progress,
    )

    _run(
        [
            "gdal_translate", "-of", "MBTiles",
            "-co", f"MINZOOM={min_zoom}", "-co", f"MAXZOOM={max_zoom}",
            "-co", "TILE_FORMAT=PNG8",
            "-co", f"NAME={cfg.raw['project']['name']}",
            "-co", f"DESCRIPTION={cfg.raw['attribution']}",
            str(merc), str(mbt),
        ],
        progress,
    )
    # mode, not average: these are palette indices, not intensities.
    levels = [str(2**i) for i in range(1, max_zoom - min_zoom + 1)]
    _run(["gdaladdo", "-r", "mode", str(mbt), *levels], progress)

    from pmtiles import convert as pmconvert

    pmconvert.mbtiles_to_pmtiles(str(mbt), str(pmt), maxzoom=max_zoom)
    return pmt


def run(cfg: Config, progress=print) -> Path:
    src = cfg.out_dir / "visible_fraction.tif"
    if not src.exists():
        raise SystemExit(f"missing {src} — run `sunline composite` first")

    with rasterio.open(src) as ds:
        levels = int(ds.tags().get("samples", 35))

    paletted = to_paletted(
        src, cfg.out_dir / "visibility_pal.tif",
        levels, cfg.output["tiles"]["colormap"], progress,
    )

    max_zoom = cfg.output["tiles"]["max_zoom"]
    pmt = to_pmtiles(cfg, paletted, max_zoom, progress)
    size_mb = pmt.stat().st_size / 2**20
    progress(f"wrote {pmt}  ({size_mb:.1f} MB) at z{max_zoom}")

    # One automatic step back rather than shipping a file Pages will reject.
    if size_mb > _SIZE_BUDGET_MB and max_zoom > cfg.output["tiles"]["min_zoom"]:
        progress(
            f"  over the {_SIZE_BUDGET_MB} MB budget — rebuilding at z{max_zoom - 1}"
        )
        pmt = to_pmtiles(cfg, paletted, max_zoom - 1, progress)
        size_mb = pmt.stat().st_size / 2**20
        progress(f"wrote {pmt}  ({size_mb:.1f} MB) at z{max_zoom - 1}")

    if size_mb > 100:
        progress("  WARNING: still over GitHub's 100 MB per-file limit — host it off-repo")
    return pmt


def run_max(cfg: Config, progress=print) -> Path:
    """Publish the binary at-maximum-eclipse layer as its own archive.

    `visible_at_max.tif` is already an index raster (0 = blocked, 1 = visible,
    255 = no standing room), so no quantisation happens here — only a colour
    table and the same warp -> MBTiles -> PMTiles chain, into files named
    `visibility_max.*` so nothing collides with the fraction layer.

    The palette reuses the fraction ramp's endpoints (magma 0.15 / 0.95): the
    at-max view must read as "same map, hardest moment", not a new colour
    language to learn.
    """
    src = cfg.out_dir / "visible_at_max.tif"
    if not src.exists():
        raise SystemExit(f"missing {src} — run `sunline composite` first")

    ramp = colormaps[cfg.output["tiles"]["colormap"]]
    blocked = tuple(int(v * 255) for v in ramp(0.15)[:3])
    visible = tuple(int(v * 255) for v in ramp(0.95)[:3])
    table = {0: (*blocked, 255), 1: (*visible, 255), 255: (0, 0, 0, 0)}

    paletted = cfg.out_dir / "visibility_max_pal.tif"
    with rasterio.open(src) as ds:
        profile = ds.profile.copy()
        profile.update(
            compress="deflate", tiled=True, blockxsize=512, blockysize=512,
            BIGTIFF="IF_SAFER", nodata=255,
        )
        with rasterio.open(paletted, "w", **profile) as out:
            out.update_tags(**ds.tags())
            for _, win in ds.block_windows(1):
                out.write(ds.read(1, window=win), 1, window=win)
            out.write_colormap(1, table)
    progress(f"paletted (binary) -> {paletted}")

    max_zoom = cfg.output["tiles"]["max_zoom"]
    name = cfg.output["pmtiles_name"].replace(".pmtiles", "_max.pmtiles")
    pmt = to_pmtiles(cfg, paletted, max_zoom, progress, stem="visibility_max", pmtiles_name=name)
    size_mb = pmt.stat().st_size / 2**20
    progress(f"wrote {pmt}  ({size_mb:.1f} MB) at z{max_zoom}")

    if size_mb > _SIZE_BUDGET_MB and max_zoom > cfg.output["tiles"]["min_zoom"]:
        progress(f"  over the {_SIZE_BUDGET_MB} MB budget — rebuilding at z{max_zoom - 1}")
        pmt = to_pmtiles(cfg, paletted, max_zoom - 1, progress, stem="visibility_max", pmtiles_name=name)
        progress(f"wrote {pmt}  ({pmt.stat().st_size / 2**20:.1f} MB) at z{max_zoom - 1}")
    return pmt


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    run(load_config(argv[0] if argv else "config.yaml"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
