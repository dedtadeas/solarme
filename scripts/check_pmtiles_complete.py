#!/usr/bin/env python3
"""Completeness gate for a region PMTiles archive.

Usage: check_pmtiles_complete.py FILE lon_min lat_min lon_max lat_max [max_gap_km]

Exit 0 only if BOTH hold:
  1. the archive's header bounds cover the expected AOI (with a small margin)
  2. real tile data begins within max_gap_km of the archive's north edge

Why the north edge: the sweep writes blocks south-to-north, so an archive
built from a partially-written raster has valid southern tiles and nothing in
the north. A due existence check ("the file is there, 55 MB, looks fine")
shipped exactly that failure to the live site once already today.

Why a *measured gap* instead of a fixed probe: publish crops tiles to the data
while the header keeps the AOI extent, so every archive this pipeline builds
carries a small empty band below its declared north edge (~1.3-1.7 km measured
2026-08-12). A probe at a fixed offset just inside the header top lands inside
that band and fails even on known-good archives — the original 0.008 deg probe
rejected the *live* Prague stopgap as well as a sound fresh build. So measure
how far south real data actually starts and fail only when that gap is large
enough to mean a truncated raster rather than ordinary cropping.
"""

from __future__ import annotations

import io
import math
import sys

KM_PER_DEG_LAT = 111.32
DEFAULT_MAX_GAP_KM = 3.0
# Fractions across the archive width to sample; corners are avoided because a
# region's data can legitimately taper there.
SAMPLE_FRACTIONS = (1 / 6, 1 / 3, 1 / 2, 2 / 3, 5 / 6)


def row_top_lat(y: int, z: int) -> float:
    """Latitude of the northern edge of tile row y."""
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2**z))))


def lat_to_row(lat: float, z: int) -> int:
    return int(
        (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi)
        / 2
        * 2**z
    )


def has_pixels(data: bytes) -> bool:
    """True when the tile carries actual pixels rather than a blank stub."""
    from PIL import Image
    import numpy as np

    a = np.array(Image.open(io.BytesIO(data)).convert("RGBA"))
    return bool((a[..., 3] > 0).mean() >= 0.01)


def main() -> int:
    path, lon0, lat0, lon1, lat1 = (
        sys.argv[1],
        float(sys.argv[2]),
        float(sys.argv[3]),
        float(sys.argv[4]),
        float(sys.argv[5]),
    )
    max_gap_km = float(sys.argv[6]) if len(sys.argv) > 6 else DEFAULT_MAX_GAP_KM

    from pmtiles.reader import MmapSource, Reader

    with open(path, "rb") as fh:
        r = Reader(MmapSource(fh))
        h = r.header()

        bounds = (
            h["min_lon_e7"] / 1e7,
            h["min_lat_e7"] / 1e7,
            h["max_lon_e7"] / 1e7,
            h["max_lat_e7"] / 1e7,
        )
        margin = 0.02  # ~1.5 km — publish crops to data, allow that
        if not (
            bounds[0] <= lon0 + margin
            and bounds[1] <= lat0 + margin
            and bounds[2] >= lon1 - margin
            and bounds[3] >= lat1 - margin
        ):
            print(f"GATE FAIL: bounds {bounds} do not cover AOI", file=sys.stderr)
            return 1

        z = h["max_zoom"]
        n = 2**z
        cols = sorted(
            {int((bounds[0] + (bounds[2] - bounds[0]) * f + 180) / 360 * n) for f in SAMPLE_FRACTIONS}
        )

        # Walk south from the declared north edge until a sampled column yields a
        # tile with real pixels. The gap that takes is the number that matters.
        row = lat_to_row(bounds[3], z)
        hit = None
        while True:
            gap_km = (bounds[3] - row_top_lat(row, z)) * KM_PER_DEG_LAT
            if gap_km > max_gap_km:
                print(
                    f"GATE FAIL: no data within {max_gap_km:g} km of the north edge "
                    f"(searched to {gap_km:.2f} km, z{z} rows {lat_to_row(bounds[3], z)}..{row})",
                    file=sys.stderr,
                )
                return 1
            for x in cols:
                data = r.get(z, x, row)
                if data and has_pixels(data):
                    hit = (x, row, gap_km)
                    break
            if hit:
                break
            row += 1

        x, row, gap_km = hit

    print(
        f"gate OK: bounds {bounds}, data starts {gap_km:.2f} km below the north edge "
        f"(limit {max_gap_km:g} km) at z{z}/{x}/{row}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
