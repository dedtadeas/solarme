# SunLine — Eclipse & Low-Sun Visibility Map

Project brief for Claude Code. Build a data pipeline + static web map showing
where a low-on-the-horizon sun (e.g. the 12 Aug 2026 partial eclipse over Czechia,
sun ~5–10° high near sunset) is actually visible, and where buildings, trees, and
terrain block it. Precision matters: at 10° elevation a 20 m building shades ~115 m
behind it.

## Goals

- Precise: 1 m resolution using Czech national lidar DSM
- Free end-to-end: open data (CC BY 4.0), free hosting, no paid APIs
- Publishable & resume-quality: clean repo, README with screenshots, live demo
- Reusable: eclipse is just a time window config — works for any sunset/sunrise visibility question

## Data sources

- **ČÚZK DMP 1G** (Digitální model povrchu 1G) — surface model incl. buildings & vegetation,
  ~1 pt/m², open data CC BY 4.0, downloadable per map sheet from the ČÚZK Geoportal
  (Atom feeds), XYZ text format, CRS S-JTSK / EPSG:5514.
  Caveat to note in README: lidar 2009–2013, so tree heights are approximate.
- **ČÚZK DMR 5G** (terrain only) or Copernicus GLO-30 — optional far-field horizon
  (hills 10–50 km away matter at 5–10° sun elevation). v2 if time allows.
- Attribution required everywhere the map is shown: "Podkladová data ČÚZK, CC BY 4.0".

## Pipeline (Python, in `src/`)

1. `fetch` — download + cache DMP 1G sheets covering a configured bbox
2. `rasterize` — points → 1 m GeoTIFF via GDAL (gdal_grid or PDAL), EPSG:5514
3. `sun` — solar azimuth/elevation series (pvlib or astropy) for a configured
   time window, step 2–5 min; eclipse contact times live in `config.yaml`
4. `shadow` — core algorithm, per timestamp:
   - rotate/resample raster so rows align with sun azimuth
   - single cumulative-max sweep of projected horizon angle per row → O(N) total,
     NO per-pixel ray casting
   - observer eye height: compare against DSM + 1.6 m
5. `composite` — per-pixel fraction of the time window with visible sun
   (0 = never see it, 1 = full eclipse visible); also a binary layer at max eclipse
6. `publish` — GeoTIFF → colorized COG → PMTiles (rio-cogeo + pmtiles) for static serving

Everything reproducible: `make demo` runs the full chain on the test bbox.
Unit-test the shadow sweep on a synthetic ramp + single-box scene where the
answer is known analytically.

## Frontend (static, `web/`)

- MapLibre GL JS + pmtiles protocol, plain HTML/JS, deployed to GitHub Pages
- Basemap: any free OSM style; visibility layer on top with opacity slider
- Legend: green = full eclipse visible → red = blocked
- Guided hints like in the Memory Alley kit, but simplified: a small intro panel
  ("what am I looking at", "why is my street red") with 2–3 dismissible hint steps
- Footer: ČÚZK CC BY 4.0 attribution, GitHub repo link, and a Ko-fi support link
  (placeholder `https://ko-fi.com/USERNAME` — same sustainability model as Memory Alley)

## Non-goals for v1

- No Cesium / Google Photorealistic 3D Tiles view (v2 demo only, quota-capped)
- No whole-country processing — start with one ~10×10 km bbox (make it a config value)
- No accounts, no backend, no database — fully static output

## First tasks

1. Scaffold repo: `pyproject.toml`, `src/`, `web/`, `Makefile`, `config.yaml`, README skeleton
2. Implement `fetch` + `rasterize` for the test bbox; verify GeoTIFF in QGIS-compatible form
3. Implement `sun` + `shadow` sweep with the synthetic-scene unit tests
4. Run the eclipse window from config, produce the composite layer, export PMTiles
5. Wire up the MapLibre page with overlay, legend, hints, footer; `make demo` end to end

## Constraints

- Free stack only: Python 3.11+, GDAL/rasterio, numpy, pvlib; GitHub Pages hosting
- Keep the shadow sweep pure numpy (vectorized) — this is the performance-critical path
- All geodata intermediate files git-ignored; only code + small test fixtures in repo
