#!/usr/bin/env python3
"""Turn the live service into a self-contained portfolio piece on GitHub Pages.

The site was served from S3 behind CloudFront: 99 regions, 9 GB of PMTiles. A
Pages site has to fit in 1 GB and the archives have to live in the repo, so this
keeps a contiguous subset and drops the rest.

Contiguous on purpose. A scatter of disconnected squares reads as a broken map;
one solid block reads as a finished region. The kept set is grown outward from
Prague and Melnicko by cheapest-neighbour until the budget runs out, so it is
connected by construction.

Both layers are kept only for Prague and Melnicko — the two places the README
screenshots show — because the at-maximum archives cost as much again and the
app already fails soft when one is missing.

Regions that are dropped stay in coverage.geojson as "archived" rather than
vanishing: the map then still shows what the project computed, and a visitor who
zooms to Ostrava sees an outline explaining the absence instead of blank ground.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
BUCKET = "s3://sunline-pilot-774672614717/tiles"
STEP, AX, AY = 26000, -779000, -1059000
BUDGET = 800 * 1024**2
MAX_FOR = {"prague", "north"}          # keep the at-maximum layer only here
SEEDS = {"prague", "north"}
PILOT = {
    "prague": ("visibility", "Praha"),
    "north": ("north", "Mělnicko"),
    "west": ("west", "Berounsko"),
    "northwest": ("northwest", "Kladensko"),
}


def main() -> int:
    src = (ROOT / "web/app.js").read_text()
    blk = re.search(r"const REGIONS = \[(.*?)\]\.map\(", src, re.S).group(1)
    live = dict(re.findall(r'id: "([a-z0-9-]+)", url: "([a-z0-9-]+)\.pmtiles"', blk))

    cell, name = {}, {}
    for p in sorted((ROOT / "configs").glob("*.yaml")):
        cfg = yaml.safe_load(p.read_text())
        a = cfg["aoi"]
        cell[p.stem] = (round((a["xmin"] - AX) / STEP), round((a["ymin"] - AY) / STEP))
        name[p.stem] = (
            PILOT[p.stem][1] if p.stem in PILOT
            else cfg["project"]["name"].split("—")[1].split(",")[0].strip()
        )
    bycell = {c: s for s, c in cell.items() if s in live}

    # Sizes come from S3 rather than the local backup: the full 32 GB sync is
    # still running and does the big cities/ prefix first, so tiles/ is not
    # there yet. The backup is for the author's archive, not a dependency here.
    listing = subprocess.run(["aws", "s3", "ls", BUCKET + "/"],
                             capture_output=True, text=True).stdout
    size = {}
    for ln in listing.splitlines():
        f = ln.split()
        if len(f) >= 4 and f[3].endswith(".pmtiles"):
            size[f[3][: -len(".pmtiles")]] = int(f[2])
    missing = [s for s in live if live[s] not in size]
    if missing:
        print(f"  {len(missing)} archives absent from S3: {missing[:5]}"); return 1

    def cost(s):
        b = live[s]
        return size[b] + (size.get(b + "_max", 0) if s in MAX_FOR else 0)

    chosen, total = set(SEEDS), sum(cost(s) for s in SEEDS)
    while True:
        frontier = set()
        for s in chosen:
            cx, cy = cell[s]
            for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = bycell.get((cx + d[0], cy + d[1]))
                if n and n not in chosen:
                    frontier.add(n)
        opts = sorted((x for x in frontier if total + cost(x) <= BUDGET), key=cost)
        if not opts:
            break
        chosen.add(opts[0]); total += cost(opts[0])

    print(f"  keeping {len(chosen)} contiguous regions, {total/1024**2:.0f} MB")

    # ---- copy the archives into the published folder ----------------------
    for f in (ROOT / "web").glob("*.pmtiles"):
        f.unlink()
    copied = 0
    for s in sorted(chosen):
        b = live[s]
        for arc in [b] + ([b + "_max"] if s in MAX_FOR else []):
            subprocess.run(["aws", "s3", "cp", f"{BUCKET}/{arc}.pmtiles",
                            str(ROOT / "web" / f"{arc}.pmtiles"), "--only-show-errors"],
                           check=True)
            copied += 1
    print(f"  copied {copied} archives into web/")

    # ---- REGIONS ----------------------------------------------------------
    rows = []
    for s in sorted(chosen):
        b = live[s]
        rows.append(f'  {{ id: "{s}", url: "{b}.pmtiles", maxUrl: "{b}_max.pmtiles" }},')
    src = re.sub(r"const REGIONS = \[.*?\]\.map\(",
                 "const REGIONS = [\n" + "\n".join(rows) + "\n].map(", src, count=1, flags=re.S)
    (ROOT / "web/app.js").write_text(src)

    # ---- coverage.geojson: kept = live, the rest = archived ---------------
    tr = Transformer.from_crs("EPSG:5514", "EPSG:4326", always_xy=True)
    feats = []
    for slug in sorted(cell):
        a = yaml.safe_load((ROOT / f"configs/{slug}.yaml").read_text())["aoi"]
        N = 12
        xy = []
        for i in range(N): xy.append((a["xmin"] + (a["xmax"]-a["xmin"])*i/N, a["ymin"]))
        for i in range(N): xy.append((a["xmax"], a["ymin"] + (a["ymax"]-a["ymin"])*i/N))
        for i in range(N): xy.append((a["xmax"] - (a["xmax"]-a["xmin"])*i/N, a["ymax"]))
        for i in range(N): xy.append((a["xmin"], a["ymax"] - (a["ymax"]-a["ymin"])*i/N))
        xy.append(xy[0])
        feats.append({
            "type": "Feature",
            "properties": {"slug": slug, "name": name[slug],
                           "status": "live" if slug in chosen else "archived"},
            "geometry": {"type": "Polygon",
                         "coordinates": [[[round(v, 6) for v in tr.transform(x, y)] for x, y in xy]]},
        })
    (ROOT / "web/coverage.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats},
                   ensure_ascii=False, separators=(",", ":")))
    print(f"  coverage.geojson: {len(chosen)} live, {len(feats)-len(chosen)} archived")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
