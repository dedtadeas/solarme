#!/usr/bin/env python3
"""Publish every finished region: S3 -> serving prefix -> site.

Run it whenever archives land. It is idempotent, so running it twice costs a
couple of S3 listings and changes nothing.

  1. copy each completed <region>.pmtiles (and _max) from the per-wave results
     prefix to tiles/, which is the only prefix the bucket policy makes public
  2. rewrite web/coverage.geojson so finished regions flip from "computing" to
     "live" — that is what removes the hourglass and switches the dashed
     outline to solid
  3. rewrite the REGIONS array in web/app.js to match

Deliberately regenerates from what is actually IN the bucket rather than from
a list kept by hand: the map should claim coverage only where an archive
really exists, or a visitor gets a black square and no explanation.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml
from pyproj import Transformer

BUCKET = "sunline-pilot-774672614717"
ROOT = Path(__file__).resolve().parent.parent
# The four pilot regions predate the city wave and use their own archive names.
PILOT = {
    "prague": ("visibility.pmtiles", "visibility_max.pmtiles", "Praha"),
    "north": ("north.pmtiles", "north_max.pmtiles", "Mělnicko"),
    "west": ("west.pmtiles", "west_max.pmtiles", "Berounsko"),
    "northwest": ("northwest.pmtiles", "northwest_max.pmtiles", "Kladensko"),
}


def s3(*args: str) -> str:
    return subprocess.run(
        ["aws", "s3", *args], capture_output=True, text=True, check=False
    ).stdout


def main() -> int:
    listing = s3("ls", f"s3://{BUCKET}/cities/", "--recursive")
    found: dict[str, set[str]] = {}
    for line in listing.splitlines():
        m = re.search(r"cities/w\d+/results/([a-z-]+)/([a-z-]+(?:_max)?)\.pmtiles$", line)
        if m:
            found.setdefault(m.group(1), set()).add(m.group(2))

    serving = {ln.split()[-1].removesuffix(".pmtiles")
               for ln in s3("ls", f"s3://{BUCKET}/tiles/").splitlines() if ln.strip()}
    published: list[str] = []
    for region, archives in sorted(found.items()):
        if region not in archives:  # the base archive is mandatory
            print(f"  {region}: _max only, skipping until the base lands")
            continue
        src_wave = next(
            l.split()[-1].rsplit("/", 3)[0]
            for l in listing.splitlines()
            if f"/results/{region}/{region}.pmtiles" in l
        )
        # Only copy what is not already serving. Re-copying every archive on
        # every run turned a 5-second script into a 2-minute one once there
        # were 39 regions, for no benefit — the sources never change.
        todo = sorted(a for a in archives if a not in serving)
        for a in todo:
            s3(
                "cp",
                f"s3://{BUCKET}/{src_wave}/results/{region}/{a}.pmtiles",
                f"s3://{BUCKET}/tiles/{a}.pmtiles",
                "--only-show-errors",
            )
        published.append(region)
        if todo:
            print(f"  published {region} ({len(todo)} new archive(s))")

    live = set(PILOT) | set(published)

    # ---- coverage.geojson -------------------------------------------------
    tr = Transformer.from_crs("EPSG:5514", "EPSG:4326", always_xy=True)
    feats = []
    for p in sorted((ROOT / "configs").glob("*.yaml")):
        slug = p.stem
        cfg = yaml.safe_load(p.read_text())
        a = cfg["aoi"]
        name = (
            PILOT[slug][2]
            if slug in PILOT
            else cfg["project"]["name"].split("—")[1].split(",")[0].strip()
        )
        N = 12
        xy = []
        for i in range(N): xy.append((a["xmin"] + (a["xmax"] - a["xmin"]) * i / N, a["ymin"]))
        for i in range(N): xy.append((a["xmax"], a["ymin"] + (a["ymax"] - a["ymin"]) * i / N))
        for i in range(N): xy.append((a["xmax"] - (a["xmax"] - a["xmin"]) * i / N, a["ymax"]))
        for i in range(N): xy.append((a["xmin"], a["ymax"] - (a["ymax"] - a["ymin"]) * i / N))
        xy.append(xy[0])
        feats.append({
            "type": "Feature",
            "properties": {"slug": slug, "name": name,
                           "status": "live" if slug in live else "computing"},
            "geometry": {"type": "Polygon",
                         "coordinates": [[[round(v, 6) for v in tr.transform(x, y)] for x, y in xy]]},
        })
    (ROOT / "web/coverage.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats},
                   ensure_ascii=False, separators=(",", ":")))

    # ---- REGIONS in app.js -----------------------------------------------
    rows = []
    for slug in sorted(live):
        base, mx, _ = PILOT.get(slug, (f"{slug}.pmtiles", f"{slug}_max.pmtiles", ""))
        rows.append(f'  {{ id: "{slug}", url: "{base}", maxUrl: "{mx}" }},')
    app = ROOT / "web/app.js"
    src = app.read_text()
    new = "const REGIONS = [\n" + "\n".join(rows) + "\n].map("
    src = re.sub(r"const REGIONS = \[.*?\]\.map\(", new, src, count=1, flags=re.S)
    app.write_text(src)

    print(f"\n  live regions: {len(live)}  ({', '.join(sorted(live))})")
    print(f"  still computing: {len(feats) - len(live)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
