#!/usr/bin/env python3
"""Build web/en/index.html, the English entry point, from web/index.html.

solarme.cz/en/ exists so the map can be shared in English. The language
itself is picked by app.js from the path; this page exists so that a pasted
link also PREVIEWS in English — chat apps and social sites read og:title and
og:description from the HTML and never run the script.

Generated, not committed: the Czech page stays the one source, and the Pages
workflow runs this before deploying. Every replacement must match exactly
once, so an edit to the Czech head that this script no longer recognises
fails the deploy instead of shipping a half-Czech preview.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "index.html"
OUT = ROOT / "web" / "en" / "index.html"

DESC = (
    "A metre-resolution map of where the low eclipsed sun of 12 August 2026 "
    "will be visible — and where buildings, trees and hills block it."
)
OG_DESC = (
    "A metre-by-metre map for 12 August 2026. The sun will be only 1–9° above "
    "the horizon, so every street is different — the map works out what hides "
    "it: buildings, trees, hills."
)
TITLE = "Where you can see the eclipse — street by street"

REPLACEMENTS = [
    ('<html lang="cs">', '<html lang="en">'),
    # Every relative URL — ./app.js, ./style.css, the .pmtiles archives,
    # coverage.geojson — resolves against the site root, not /en/.
    ('<meta charset="utf-8">', '<meta charset="utf-8">\n<base href="/">'),
    ("<title>SolarMe — kde uvidíte zatmění Slunce</title>",
     "<title>SolarMe — where you can see the eclipse</title>"),
    ('<meta property="og:url" content="https://solarme.cz/">',
     '<meta property="og:url" content="https://solarme.cz/en/">'),
    ('<meta property="og:locale" content="cs_CZ">',
     '<meta property="og:locale" content="en_GB">'),
    ('<meta property="og:title" content="Kde uvidíte zatmění Slunce — ulici po ulici">',
     f'<meta property="og:title" content="{TITLE}">'),
    ('<meta name="twitter:title" content="Kde uvidíte zatmění Slunce — ulici po ulici">',
     f'<meta name="twitter:title" content="{TITLE}">'),
]
# Descriptions are long and edited often; match them by their tag, not text.
TAG_REPLACEMENTS = [
    ('<meta name="description" content="', DESC),
    ('<meta property="og:description" content="', OG_DESC),
    ('<meta name="twitter:description" content="', OG_DESC),
    ('<meta property="og:image:alt" content="',
     "A map coloured by where the eclipsed sun will be visible — bright places "
     "will see it, dark ones have it blocked"),
]


def main() -> None:
    html = SRC.read_text(encoding="utf-8")
    for old, new in REPLACEMENTS:
        n = html.count(old)
        if n != 1:
            raise SystemExit(f"expected 1 match, found {n}: {old}")
        html = html.replace(old, new)
    for prefix, text in TAG_REPLACEMENTS:
        if html.count(prefix) != 1:
            raise SystemExit(f"expected 1 match, found {html.count(prefix)}: {prefix}")
        start = html.index(prefix) + len(prefix)
        end = html.index('">', start)
        html = html[:start] + text + html[end:]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
