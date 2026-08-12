PY := .venv/bin/python
CFG ?= config.yaml

.PHONY: help venv test sun eclipse fetch composite publish demo serve clean distclean

help:
	@echo "make venv       create .venv and install the package"
	@echo "make test       run the analytic shadow tests"
	@echo "make sun        print the solar geometry, checked against the ephemeris"
	@echo "make eclipse    contact times for the configured date and location"
	@echo "make fetch      download DSM + terrain from CUZK (cached, resumable)"
	@echo "make composite  sweep every timestamp -> visible_fraction.tif"
	@echo "make publish    colorize -> reproject -> PMTiles"
	@echo "make demo       the whole chain end to end"
	@echo "make serve      serve web/ at http://localhost:8000"

venv:
	python3 -m venv .venv
	$(PY) -m pip install -qU pip
	$(PY) -m pip install -q -e ".[dev]"

test:
	$(PY) -m pytest -q

sun:
	$(PY) -m sunline.cli sun -c $(CFG)

# Contact times straight from JPL DE421 — the check that the window is right.
eclipse:
	$(PY) -m sunline.cli eclipse -c $(CFG)

fetch:
	$(PY) -m sunline.cli fetch -c $(CFG)

composite:
	$(PY) -m sunline.cli composite -c $(CFG)

publish:
	$(PY) -m sunline.cli publish -c $(CFG)

# The binary at-maximum-eclipse layer as its own archive.
publish-max:
	$(PY) -m sunline.cli publish-max -c $(CFG)

# The full chain. `fetch` is cached, so re-running is cheap.
demo: test fetch composite publish
	@cp -f data/visibility.pmtiles web/visibility.pmtiles
	@echo ""
	@echo "built web/visibility.pmtiles — 'make serve' to view"

# NOT `python -m http.server`: that answers 200 with the whole body, and
# PMTiles is built on range requests. web/serve.py speaks 206.
serve:
	@python3 web/serve.py 8000

clean:
	rm -rf data/visible_fraction.tif data/visibility_rgba.tif \
	       data/visibility_3857.tif data/visibility.mbtiles data/visibility.pmtiles

# Also drops the cached downloads — a full refetch follows.
distclean: clean
	rm -rf data/raw
