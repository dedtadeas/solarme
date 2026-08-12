"""Fetch elevation rasters from the ČÚZK ArcGIS ImageServer endpoints.

The project brief assumed DMP 1G had to come as ~2000 zipped XYZ sheets from the
Atom feeds — roughly 300 GB of text for a Prague-sized box, days of downloading.
ČÚZK also publishes the same models as ImageServer services:

    https://ags.cuzk.gov.cz/arcgis/rest/services/3D/dmp     0.5 m, Float32
    https://ags.cuzk.gov.cz/arcgis/rest/services/3D/dmr5g   2.0 m, Float32

Both accept `exportImage`, so a bbox comes back as a Float32 GeoTIFF already in
EPSG:5514. A 26 km box drops from ~300 GB to ~3 GB and from days to minutes.

Deliberately stdlib-only (urllib + concurrent.futures) so the download can start
before the scientific stack is installed. Mosaicking shells out to gdalbuildvrt.
"""

from __future__ import annotations

import concurrent.futures as cf
import math
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import Config, load_config

# ImageServer returns a TIFF body on success and a JSON error body on failure,
# both with HTTP 200. Sniffing the magic bytes is the only reliable check.
_TIFF_MAGIC = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")


@dataclass(frozen=True)
class Tile:
    """One exportImage request: a bbox and the pixel grid it maps to."""

    ix: int
    iy: int
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    width: int
    height: int

    @property
    def name(self) -> str:
        return f"tile_{self.iy:03d}_{self.ix:03d}.tif"


def snap(value: float, res: float, *, up: bool) -> float:
    """Snap a coordinate onto the resolution grid so tiles share pixel edges."""
    f = math.ceil if up else math.floor
    return f(value / res) * res


def plan_tiles(
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
    res: float,
    tile_px: tuple[int, int],
) -> list[Tile]:
    """Split a bbox into exportImage-sized tiles aligned to the res grid.

    Tiles are generated edge-to-edge with no overlap: every request lands on the
    same global pixel grid, so the mosaic is exact rather than resampled.
    """
    xmin = snap(xmin, res, up=False)
    ymin = snap(ymin, res, up=False)
    xmax = snap(xmax, res, up=True)
    ymax = snap(ymax, res, up=True)

    total_w = int(round((xmax - xmin) / res))
    total_h = int(round((ymax - ymin) / res))
    tw, th = tile_px

    tiles: list[Tile] = []
    for iy, y0 in enumerate(range(0, total_h, th)):
        h = min(th, total_h - y0)
        for ix, x0 in enumerate(range(0, total_w, tw)):
            w = min(tw, total_w - x0)
            tiles.append(
                Tile(
                    ix=ix,
                    iy=iy,
                    xmin=xmin + x0 * res,
                    # Pixel rows run north-to-south; tile row 0 is the top.
                    ymin=ymax - (y0 + h) * res,
                    xmax=xmin + (x0 + w) * res,
                    ymax=ymax - y0 * res,
                    width=w,
                    height=h,
                )
            )
    return tiles


def _export_url(service_url: str, tile: Tile, crs_code: int) -> str:
    params = {
        "bbox": f"{tile.xmin},{tile.ymin},{tile.xmax},{tile.ymax}",
        "bboxSR": crs_code,
        "imageSR": crs_code,
        "size": f"{tile.width},{tile.height}",
        "format": "tiff",
        "pixelType": "F32",
        "interpolation": "RSP_BilinearInterpolation",
        "noDataInterpretation": "esriNoDataMatchAny",
        "f": "image",
    }
    return f"{service_url}/exportImage?{urllib.parse.urlencode(params)}"


def _download_tile(
    service_url: str,
    tile: Tile,
    dest: Path,
    crs_code: int,
    timeout: float,
    retries: int,
) -> tuple[Tile, str]:
    """Download one tile, skipping it if a valid TIFF is already cached."""
    if dest.exists() and dest.stat().st_size > 0:
        with dest.open("rb") as fh:
            if fh.read(4) in _TIFF_MAGIC:
                return tile, "cached"
        dest.unlink()  # truncated or an error body from a previous run

    url = _export_url(service_url, tile, crs_code)
    last: Exception | None = None

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                body = resp.read()
            if body[:4] not in _TIFF_MAGIC:
                # Server reported failure in a 200 response — surface its text.
                raise RuntimeError(f"non-TIFF response: {body[:200]!r}")
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(body)
            tmp.replace(dest)  # atomic, so an interrupted run resumes cleanly
            return tile, "ok"
        except (urllib.error.URLError, RuntimeError, TimeoutError, OSError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(2**attempt)  # back off; the service throttles

    raise RuntimeError(f"{tile.name} failed after {retries} attempts: {last}")


def fetch_layer(
    cfg: Config,
    layer: str,
    *,
    res: float | None = None,
    workers: int = 6,
    progress=print,
) -> Path:
    """Download one elevation layer over the buffered AOI and mosaic it.

    Returns the path to the mosaic VRT. Tiles are cached under
    `<output.dir>/raw/<layer>/`, so re-running only fetches what is missing.
    """
    source = cfg.sources[layer]
    res = res if res is not None else source.get("native_res", cfg.aoi.resolution)
    if layer == "surface":
        res = cfg.aoi.resolution  # blockers must land on the analysis grid

    buf = cfg.aoi.buffer_m
    tiles = plan_tiles(
        cfg.aoi.xmin - buf,
        cfg.aoi.ymin - buf,
        cfg.aoi.xmax + buf,
        cfg.aoi.ymax + buf,
        res,
        tuple(cfg.sources["tile_px"]),
    )

    out_dir = cfg.raw_dir / layer
    out_dir.mkdir(parents=True, exist_ok=True)

    px = sum(t.width * t.height for t in tiles)
    progress(
        f"[{layer}] {len(tiles)} tiles @ {res} m — "
        f"{px / 1e6:.0f} Mpx, ~{px * 4 / 2**30:.1f} GiB"
    )

    done = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _download_tile,
                source["url"],
                t,
                out_dir / t.name,
                cfg.aoi.crs_code,
                cfg.sources["timeout_s"],
                cfg.sources["max_retries"],
            ): t
            for t in tiles
        }
        for fut in cf.as_completed(futures):
            tile, status = fut.result()
            done += 1
            progress(f"[{layer}] {done}/{len(tiles)} {tile.name} {status}")

    vrt = cfg.raw_dir / f"{layer}.vrt"
    subprocess.run(
        ["gdalbuildvrt", "-overwrite", "-a_srs", cfg.aoi.crs, str(vrt)]
        + [str(out_dir / t.name) for t in tiles],
        check=True,
        capture_output=True,
    )
    progress(f"[{layer}] mosaic -> {vrt}")
    return vrt


def fetch_region(
    cfg: Config,
    layer: str,
    bounds: tuple[float, float, float, float],
    res: float,
    name: str,
    *,
    workers: int = 6,
    progress=print,
) -> Path:
    """Fetch an arbitrary bbox at an arbitrary resolution into one VRT.

    Same tiling, caching and retry path as `fetch_layer`, but with the extent
    and pixel size given explicitly — the far-field rings need the whole
    country at 25 m, not the AOI at 1 m.

    Coordinates are clamped to the service extent so a ring that overhangs the
    border requests only what exists.
    """
    source = cfg.sources[layer]
    ext = cfg.sources.get("service_extent")
    if ext:
        bounds = (
            max(bounds[0], ext[0]), max(bounds[1], ext[1]),
            min(bounds[2], ext[2]), min(bounds[3], ext[3]),
        )

    tiles = plan_tiles(*bounds, res, tuple(cfg.sources["tile_px"]))
    out_dir = cfg.raw_dir / name
    out_dir.mkdir(parents=True, exist_ok=True)

    px = sum(t.width * t.height for t in tiles)
    progress(
        f"[{name}] {len(tiles)} tiles @ {res} m — "
        f"{px / 1e6:.0f} Mpx, ~{px * 4 / 2**30:.2f} GiB"
    )

    done = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _download_tile,
                source["url"], t, out_dir / t.name, cfg.aoi.crs_code,
                cfg.sources["timeout_s"], cfg.sources["max_retries"],
            )
            for t in tiles
        ]
        for fut in cf.as_completed(futures):
            fut.result()
            done += 1
            if done % 5 == 0 or done == len(tiles):
                progress(f"[{name}] {done}/{len(tiles)}")

    vrt = cfg.raw_dir / f"{name}.vrt"
    subprocess.run(
        ["gdalbuildvrt", "-overwrite", "-a_srs", cfg.aoi.crs, str(vrt)]
        + [str(out_dir / t.name) for t in tiles],
        check=True,
        capture_output=True,
    )
    return vrt


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cfg = load_config(argv[0] if argv else "config.yaml")
    for layer in ("surface", "terrain"):
        fetch_layer(cfg, layer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
