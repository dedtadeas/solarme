/* SunLine — static MapLibre viewer over a PMTiles raster.
 *
 * No backend, no key, no build step. The whole visibility layer is one
 * .pmtiles file read with HTTP range requests, which GitHub Pages serves.
 */

// One archive per region; they tile edge-to-edge. A region whose archive is
// not built yet fails soft: its source errors are logged, the rest of the map
// works, and only a missing FIRST region gets the on-page hint.
// Archives are served from object storage, not from this repo: a region pair is
// ~90 MB and national coverage is ~17 GB. PMTiles is read over HTTP range
// requests, so S3 serves it with no tile server. window.TILE_BASE is set in
// index.html at deploy time; "./" keeps web/serve.py working for local dev.
// The bucket needs CORS allowing GET and the Range header, or the browser
// silently gets nothing.
const TILE_BASE = window.TILE_BASE || "./";
const REGIONS = [
  { id: "blansko", url: "blansko.pmtiles", maxUrl: "blansko_max.pmtiles" },
  { id: "brno", url: "brno.pmtiles", maxUrl: "brno_max.pmtiles" },
  { id: "brno-jih", url: "brno-jih.pmtiles", maxUrl: "brno-jih_max.pmtiles" },
  { id: "ceska-lipa", url: "ceska-lipa.pmtiles", maxUrl: "ceska-lipa_max.pmtiles" },
  { id: "ceske-budejovice", url: "ceske-budejovice.pmtiles", maxUrl: "ceske-budejovice_max.pmtiles" },
  { id: "cheb", url: "cheb.pmtiles", maxUrl: "cheb_max.pmtiles" },
  { id: "chomutov", url: "chomutov.pmtiles", maxUrl: "chomutov_max.pmtiles" },
  { id: "decin", url: "decin.pmtiles", maxUrl: "decin_max.pmtiles" },
  { id: "dvur-kralove", url: "dvur-kralove.pmtiles", maxUrl: "dvur-kralove_max.pmtiles" },
  { id: "frydek-mistek", url: "frydek-mistek.pmtiles", maxUrl: "frydek-mistek_max.pmtiles" },
  { id: "havirov", url: "havirov.pmtiles", maxUrl: "havirov_max.pmtiles" },
  { id: "hradec-kralove", url: "hradec-kralove.pmtiles", maxUrl: "hradec-kralove_max.pmtiles" },
  { id: "hronov", url: "hronov.pmtiles", maxUrl: "hronov_max.pmtiles" },
  { id: "jablonec", url: "jablonec.pmtiles", maxUrl: "jablonec_max.pmtiles" },
  { id: "jihlava", url: "jihlava.pmtiles", maxUrl: "jihlava_max.pmtiles" },
  { id: "karlovy-vary", url: "karlovy-vary.pmtiles", maxUrl: "karlovy-vary_max.pmtiles" },
  { id: "kolin", url: "kolin.pmtiles", maxUrl: "kolin_max.pmtiles" },
  { id: "liberec", url: "liberec.pmtiles", maxUrl: "liberec_max.pmtiles" },
  { id: "mlada-boleslav", url: "mlada-boleslav.pmtiles", maxUrl: "mlada-boleslav_max.pmtiles" },
  { id: "most", url: "most.pmtiles", maxUrl: "most_max.pmtiles" },
  { id: "north", url: "north.pmtiles", maxUrl: "north_max.pmtiles" },
  { id: "northwest", url: "northwest.pmtiles", maxUrl: "northwest_max.pmtiles" },
  { id: "olomouc", url: "olomouc.pmtiles", maxUrl: "olomouc_max.pmtiles" },
  { id: "opava", url: "opava.pmtiles", maxUrl: "opava_max.pmtiles" },
  { id: "ostrava", url: "ostrava.pmtiles", maxUrl: "ostrava_max.pmtiles" },
  { id: "pardubice", url: "pardubice.pmtiles", maxUrl: "pardubice_max.pmtiles" },
  { id: "pisek", url: "pisek.pmtiles", maxUrl: "pisek_max.pmtiles" },
  { id: "plzen", url: "plzen.pmtiles", maxUrl: "plzen_max.pmtiles" },
  { id: "prague", url: "visibility.pmtiles", maxUrl: "visibility_max.pmtiles" },
  { id: "prerov", url: "prerov.pmtiles", maxUrl: "prerov_max.pmtiles" },
  { id: "pribram", url: "pribram.pmtiles", maxUrl: "pribram_max.pmtiles" },
  { id: "prostejov", url: "prostejov.pmtiles", maxUrl: "prostejov_max.pmtiles" },
  { id: "slapanice", url: "slapanice.pmtiles", maxUrl: "slapanice_max.pmtiles" },
  { id: "sumperk", url: "sumperk.pmtiles", maxUrl: "sumperk_max.pmtiles" },
  { id: "tabor", url: "tabor.pmtiles", maxUrl: "tabor_max.pmtiles" },
  { id: "teplice", url: "teplice.pmtiles", maxUrl: "teplice_max.pmtiles" },
  { id: "trebic", url: "trebic.pmtiles", maxUrl: "trebic_max.pmtiles" },
  { id: "trinec", url: "trinec.pmtiles", maxUrl: "trinec_max.pmtiles" },
  { id: "trutnov", url: "trutnov.pmtiles", maxUrl: "trutnov_max.pmtiles" },
  { id: "usti", url: "usti.pmtiles", maxUrl: "usti_max.pmtiles" },
  { id: "vsetin", url: "vsetin.pmtiles", maxUrl: "vsetin_max.pmtiles" },
  { id: "west", url: "west.pmtiles", maxUrl: "west_max.pmtiles" },
  { id: "zlin", url: "zlin.pmtiles", maxUrl: "zlin_max.pmtiles" },
  { id: "znojmo", url: "znojmo.pmtiles", maxUrl: "znojmo_max.pmtiles" },
].map((r) => ({ ...r, url: TILE_BASE + r.url, maxUrl: TILE_BASE + r.maxUrl }));
let activeLayer = "fraction"; // "fraction" | "max"

/* ── i18n ─────────────────────────────────────────────────────────────────
 * Czech first — the map is of Czech streets for a Czech sky. EN kept for the
 * portfolio audience. Strings with markup are trusted static HTML from this
 * file, never user input.
 */
const I18N = {
  cs: {
    htmlTitle: "SolarMe — kde uvidíte zatmění Slunce",
    sub: "Kde uvidíte zatmělé slunce — ulici po ulici",
    when: "12. 8. 2026 · 19:20–20:16 · maximum 20:12",
    warn: "<strong>Chraňte si zrak.</strong> Pohled do slunce spálí sítnici — bezbolestně a trvale, i takhle nízko, i z většiny zakryté. Použijte brýle na zatmění s certifikací ISO 12312-2, nebo svářečské sklo č. 13–14. Sluneční brýle, CD, diskety, fotografický film ani začouzené sklo zrak <em>nechrání</em>.",
    legendHead: "Viditelnost slunce",
    guideBtn: "Co to vlastně vidím?",
    rampNever: "nikdy", rampHalf: "půlku okna", rampWhole: "celé okno",
    opacity: "Průhlednost vrstvy",
    show: "Zobrazit",
    layerFraction: "Celé okno",
    layerFractionTip: "Podíl času, kdy je slunce vidět",
    layerMax: "V maximu",
    layerMaxTip: "Vidět, nebo zakryto v maximu zatmění ve 20:12",
    basemap: "Podklad",
    baseDark: "Tmavý", baseSat: "Satelitní",
    terrain: "3D terén",
    terrainTip: "Položí mapu na skutečný reliéf — naklánějte tahem pravým tlačítkem",
    exaggeration: "Převýšení",
    on: "Zap", off: "Vyp",
    note1: "Od prvního kontaktu do západu slunce. Oči 1,6 m nad zemí; slunce 9,4°–1,1° nad obzorem, ZSZ. Maximum zatmění 20:11:45, magnituda 0,885.",
    note2: "Model povrchu: lidar ČÚZK — obsahuje stavby dokončené nejméně do roku 2022 (ověřeno na budovách z let 2018 a 2022). Novější mohou chybět.",
    skip: "Přeskočit", next: "Další", done: "Rozumím",
    source: "Zdrojový kód", support: "Podpořit", controlsBtn: "Nastavení mapy",
    coverageNote: "Rámečky ukazují, kde je metrová analýza spočítaná. Přibližte se do některého z nich. Čárkované se právě počítají.",
    searchPlaceholder: "Najít adresu nebo místo…",
    searchNoResults: "Nic jsme nenašli. Zkuste jiný zápis.",
    searchOutside: "Tady zatím analýza spočítaná není — vyberte místo v některém z rámečků.",
    gateSupport: "Praha je hotová. Aby mapa pokryla celou republiku, zbývá spočítat 157 dlaždic 26 × 26 km.",
    gateSupportLink: "Zaplatit další dlaždici",
    missing: "chybí soubor {file} — vytvořte ho příkazem `make demo`.",
    gateDesc: "Mapa ukazuje, odkud bude vidět částečné zatmění Slunce 12. srpna 2026 večer — a kde ho zakryjí domy, stromy a kopce. Slunce bude jen 1–9° nad obzorem, takže záleží na každé ulici.",
    gateOk: "Rozumím, budu si chránit zrak",
    steps: [
      "Nejdřív oči: do slunce se nikdy nedívejte bez brýlí s certifikací ISO 12312-2 nebo svářečského skla č. 13–14 — i z většiny zakryté slunce spálí sítnici, bezbolestně. Že se do něj dá pohodlně dívat, neznamená, že je to bezpečné. Sluneční brýle, CD, diskety, fotografický film ani začouzené sklo nechrání — a fotoaparát či dalekohled bez předního slunečního filtru je ještě horší.",
      "Světlá místa vidí zatmění po většinu okna — od prvního kontaktu v 19:20 do západu ve 20:20. Tmavá místa mají něco v cestě: dům, stromořadí nebo kopec.",
      "Slunce tu klesá z 9° na 1° nad obzor, na západoseverozápadě. Při 1° vrhá jediný dvacetimetrový dům přes kilometr dlouhý stín — proto tmavnou celé ulice najednou.",
      "Maximum zatmění nastává ve 20:11:45, zakryto bude 86 % slunce — a to už bude jen 1,3° nad obzorem. Právě pro tuhle chvíli si vybírejte místo.",
      "Proč je moje ulice tmavá? Podívejte se na západoseverozápad. Mapa počítá s očima 1,6 m nad zemí — v cestě je všechno vyšší mezi vámi a obzorem. Přepněte na satelitní podklad a uvidíte, co přesně tam stojí.",
    ],
  },
  en: {
    htmlTitle: "SolarMe — where you can see the eclipse",
    sub: "Where you can see the eclipsed sun — street by street",
    when: "12 Aug 2026 · 19:20–20:16 · max 20:12",
    warn: "<strong>Protect your eyes.</strong> Looking at the sun burns the retina — painlessly and permanently, even this low, even mostly eclipsed. Use ISO 12312-2 eclipse glasses or welder's glass shade 13–14. Sunglasses, CDs, floppy disks, photo film or smoked glass do <em>not</em> protect you.",
    legendHead: "Sun visible",
    guideBtn: "What am I looking at?",
    rampNever: "never", rampHalf: "half the window", rampWhole: "whole window",
    opacity: "Layer opacity",
    show: "Show",
    layerFraction: "Whole window",
    layerFractionTip: "Fraction of the window with the sun visible",
    layerMax: "At maximum",
    layerMaxTip: "Visible or blocked at maximum eclipse, 20:12",
    basemap: "Base map",
    baseDark: "Dark", baseSat: "Satellite",
    terrain: "3D terrain",
    terrainTip: "Drape the map over real elevation — tilt with right-drag",
    exaggeration: "Exaggeration",
    on: "On", off: "Off",
    note1: "First contact to sunset. Eye height 1.6 m above ground; sun 9.4° down to 1.1°, WNW. Maximum eclipse 20:11:45, magnitude 0.885.",
    note2: "Surface model: ČÚZK national lidar — includes construction through at least 2022 (checked against buildings finished in 2018 and 2022). Anything newer may be missing.",
    skip: "Skip", next: "Next", done: "Got it",
    source: "Source", support: "Support", controlsBtn: "Map settings",
    coverageNote: "Outlines show where the 1 m analysis exists. Zoom into one. Dashed outlines are still building.",
    searchPlaceholder: "Find an address or place…",
    searchNoResults: "Nothing found. Try a different spelling.",
    searchOutside: "No analysis here yet — pick a place inside one of the outlined areas.",
    gateSupport: "Prague is done. Covering the whole country means computing 157 more tiles of 26 × 26 km.",
    gateSupportLink: "Pay for the next tile",
    missing: "{file} is missing — run `make demo` to build it.",
    gateDesc: "This map shows where the partial solar eclipse of 12 August 2026 will be visible from — and where buildings, trees and hills block it. The sun will be only 1–9° above the horizon, so every street is different.",
    gateOk: "I understand — I will protect my eyes",
    steps: [
      "First, your eyes: never look at the sun without ISO 12312-2 eclipse glasses or welder's glass shade 13–14 — a mostly-covered sun still burns the retina, painlessly, and feeling comfortable to look at does not mean it is safe. Sunglasses, CDs, floppy disks, photo film and smoked glass do not protect you, and cameras or binoculars without a front solar filter are worse, not better.",
      "Bright means you can see the eclipse for most of the window — first contact at 19:20 through sunset at 20:20. Dark means something is in the way: a building, a tree line, or a hill.",
      "The sun drops from 9° to 1° above the horizon here, in the west-north-west. At 1° a single 20 m block throws a shadow over a kilometre long, which is why whole streets go dark at once.",
      "Maximum eclipse is 20:11:45, with 86% of the sun covered — and by then it is only 1.3° up. That is the hardest moment to have a clear line to, and the one worth picking a spot for.",
      "Why is my street dark? Look west-north-west. The map puts your eyes 1.6 m above the ground, so anything taller between you and the horizon counts. Switch to the satellite base map to see what is actually in the way.",
    ],
  },
};

const LANG_KEY = "sunline.lang";
let LANG = (() => {
  try { return localStorage.getItem(LANG_KEY) === "en" ? "en" : "cs"; }
  catch { return "cs"; }
})();

function t(key) {
  return I18N[LANG][key] ?? I18N.en[key] ?? key;
}

function applyLang(lang) {
  LANG = lang;
  try { localStorage.setItem(LANG_KEY, lang); } catch { /* private mode */ }
  document.documentElement.lang = lang;
  document.title = t("htmlTitle");
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.innerHTML = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.dataset.i18nTitle);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  document.querySelectorAll("[data-lang]").forEach((b) => {
    b.classList.toggle("on", b.dataset.lang === lang);
  });
  // Live widgets that hold their own text
  const tb = document.getElementById("terrain-toggle");
  if (tb) tb.textContent = t(typeof terrainOn !== "undefined" && terrainOn ? "on" : "off");
  if (!hintEl?.hidden) render(); // re-render an open guide in the new language
}

document.querySelectorAll("[data-lang]").forEach((b) => {
  b.addEventListener("click", () => applyLang(b.dataset.lang));
});
const PRAGUE = { lng: 14.4658, lat: 50.0643 };
const DONATION_URL = "https://ko-fi.com/ruderalista"; // same Ko-fi as the alley kit

/* ── basemaps ────────────────────────────────────────────────────────────
 * Two keyless options, both free:
 *   dark      — CARTO, quiet enough that the magma ramp carries the page
 *   satellite — Esri World Imagery, for checking the model against what is
 *               actually on the ground (a courtyard, a tree line, a new block
 *               the 2009-2013 lidar never saw)
 *
 * Both are declared up front and switched by visibility rather than by
 * swapping the whole style — restyling would tear down the PMTiles source and
 * refetch the archive on every toggle.
 *
 * Labels ride above the visibility overlay in each case, so street names stay
 * readable instead of being buried by it.
 */
const BASEMAPS = {
  dark: { base: "base-dark", labels: "labels-dark" },
  satellite: { base: "base-sat", labels: "labels-sat" },
};

// Esri's tile endpoint is /tile/{level}/{row}/{col}, i.e. {z}/{y}/{x} —
// transposed from the usual XYZ order. Getting this backwards silently serves
// tiles from the wrong hemisphere.
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";

const style = {
  version: 8,
  sources: {
    "base-dark": {
      type: "raster",
      tiles: ["https://basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}@2x.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>',
    },
    "labels-dark": {
      type: "raster",
      tiles: ["https://basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}@2x.png"],
      tileSize: 256,
      maxzoom: 19,
    },
    "base-sat": {
      type: "raster",
      tiles: [`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`],
      tileSize: 256,
      maxzoom: 19,
      attribution:
        "Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    },
    "labels-sat": {
      type: "raster",
      tiles: [`${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`],
      tileSize: 256,
      maxzoom: 19,
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#14100e" } },
    { id: "base-dark", type: "raster", source: "base-dark" },
    {
      id: "base-sat",
      type: "raster",
      source: "base-sat",
      layout: { visibility: "none" },
    },
  ],
};

const protocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

const map = new maplibregl.Map({
  container: "map",
  style,
  center: [PRAGUE.lng, PRAGUE.lat],
  zoom: 12.4,
  maxZoom: 17,
  maxPitch: 85, // default 60 flattens terrain; 85 lets the valleys read
  attributionControl: { compact: true },
});

// Compass shows yaw (and pitch, as needle tilt); clicking it resets the view
// to north-up, pitch 0 — the "get me back to normal" affordance for 3D mode.
map.addControl(
  new maplibregl.NavigationControl({ showCompass: true, visualizePitch: true }),
  "top-right"
);
// Live tracking, not a one-shot: on eclipse evening people walk with this
// map open, comparing their street to the next one. High accuracy matters at
// 1 m data; heading shows which way they face. Requires https or localhost.
map.addControl(
  new maplibregl.GeolocateControl({
    positionOptions: { enableHighAccuracy: true },
    trackUserLocation: true,
    showUserHeading: true,
  }),
  "top-right"
);
map.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: "metric" }));

/* Hourglass drawn to a canvas: an icon needs no glyph stack, whereas a text
 * field would need a `glyphs` URL this style does not have. Amber on nothing,
 * so it reads on both the dark and the satellite basemap. */
function hourglassIcon(size = 44) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  const m = size * 0.24, top = size * 0.16, bot = size * 0.84, mid = size * 0.5;
  g.lineWidth = size * 0.075;
  g.lineJoin = "round";
  g.lineCap = "round";
  // Dark halo first, so the shape survives a bright satellite tile underneath.
  g.strokeStyle = "rgba(20, 16, 14, 0.85)";
  g.lineWidth = size * 0.16;
  for (const y of [top, bot]) {
    g.beginPath(); g.moveTo(m, y); g.lineTo(size - m, y); g.lineTo(mid, mid); g.closePath(); g.stroke();
  }
  g.strokeStyle = "#f0a04b";
  g.fillStyle = "rgba(240, 160, 75, 0.8)";
  g.lineWidth = size * 0.075;
  for (const y of [top, bot]) {
    g.beginPath(); g.moveTo(m, y); g.lineTo(size - m, y); g.lineTo(mid, mid); g.closePath();
    g.fill(); g.stroke();
  }
  return g.getImageData(0, 0, size, size);
}

map.on("load", async () => {
  /* ── coverage footprints ────────────────────────────────────────────────
   * The archives only carry z12 and up, so zooming out to see the country
   * gives an empty map with no hint that data exists anywhere. These
   * footprints answer "where has this been computed?" and fade out at z12.5,
   * exactly where the real rasters take over. Added first so every raster
   * layer sits above them.
   */
  map.addSource("coverage", { type: "geojson", data: "./coverage.geojson" });
  const fade = (from, to) => ["interpolate", ["linear"], ["zoom"], 10.5, from, 12.5, to];
  map.addLayer({
    id: "coverage-fill",
    type: "fill",
    source: "coverage",
    filter: ["==", ["get", "status"], "live"],
    paint: { "fill-color": "#f0a04b", "fill-opacity": fade(0.13, 0) },
  });
  // Two line layers, not one: line-dasharray cannot be driven by a property,
  // so "computed" and "still building" need separate layers to differ.
  map.addLayer({
    id: "coverage-line",
    type: "line",
    source: "coverage",
    filter: ["==", ["get", "status"], "live"],
    paint: { "line-color": "#f0a04b", "line-width": 1.2, "line-opacity": fade(0.8, 0) },
  });
  map.addLayer({
    id: "coverage-fill-soon",
    type: "fill",
    source: "coverage",
    filter: ["!=", ["get", "status"], "live"],
    paint: { "fill-color": "#f0a04b", "fill-opacity": fade(0.05, 0) },
  });
  map.addLayer({
    id: "coverage-line-soon",
    type: "line",
    source: "coverage",
    filter: ["!=", ["get", "status"], "live"],
    paint: {
      "line-color": "#f0a04b",
      "line-width": 1,
      "line-dasharray": [2, 2],
      "line-opacity": fade(0.45, 0),
    },
  });

  // An hourglass at the centre of each region still building. Drawn to a
  // canvas rather than set as text, because this style carries no `glyphs`
  // URL and a symbol layer with a text-field would silently render nothing.
  map.addImage("hourglass", hourglassIcon(), { pixelRatio: 2 });
  map.addLayer({
    id: "coverage-pending-icon",
    type: "symbol",
    source: "coverage",
    filter: ["!=", ["get", "status"], "live"],
    layout: {
      "icon-image": "hourglass",
      "icon-size": 1,
      "icon-allow-overlap": true, // adjacent city tiles must not hide each other
    },
    paint: { "icon-opacity": fade(0.95, 0) },
  });

  for (const region of REGIONS) {
    map.addSource(`visibility-${region.id}`, {
      type: "raster",
      url: `pmtiles://${region.url}`,
      tileSize: 256,
      attribution: "Podkladová data © ČÚZK, CC BY 4.0",
    });
    map.addLayer({
      id: `visibility-${region.id}`,
      type: "raster",
      source: `visibility-${region.id}`,
      paint: { "raster-opacity": 0.9, "raster-resampling": "nearest" },
    });
  }

  // The at-maximum archives are optional (built by `make publish-max`). Probe
  // before adding: a source whose archive 404s spams tile errors, and a toggle
  // to an empty layer reads as a broken map rather than a missing build.
  let anyMax = false;
  for (const region of REGIONS) {
    try {
      const head = await fetch(region.maxUrl, { headers: { Range: "bytes=0-13" } });
      if (!head.ok) continue;
      map.addSource(`max-${region.id}`, {
        type: "raster",
        url: `pmtiles://${region.maxUrl}`,
        tileSize: 256,
      });
      map.addLayer({
        id: `max-${region.id}`,
        type: "raster",
        source: `max-${region.id}`,
        layout: { visibility: "none" },
        paint: { "raster-opacity": 0.9, "raster-resampling": "nearest" },
      });
      anyMax = true;
    } catch {
      /* archive not built yet — toggle stays disabled */
    }
  }
  const maxBtn = document.getElementById("max-toggle");
  if (!anyMax) {
    maxBtn.disabled = true;
    maxBtn.title = "Not built yet — run `make publish-max`";
    maxBtn.style.opacity = "0.4";
  }

  // Labels sit above the overlay so the map stays navigable.
  map.addLayer({ id: "labels-dark", type: "raster", source: "labels-dark" });
  map.addLayer({
    id: "labels-sat",
    type: "raster",
    source: "labels-sat",
    layout: { visibility: "none" },
  });

});

/* ── landing gate ──
 * Shown once per browser SESSION, not once ever: a safety notice should
 * resurface in a new tab tomorrow, but not on every reload while comparing
 * streets today.
 */
const gateEl = document.getElementById("gate");
let gateSeen = false;
try { gateSeen = sessionStorage.getItem("sunline.gate.seen") === "1"; } catch { /* show it */ }
if (!gateSeen) gateEl.hidden = false;
document.getElementById("gate-ok").addEventListener("click", () => {
  gateEl.hidden = true;
  try { sessionStorage.setItem("sunline.gate.seen", "1"); } catch { /* fine */ }
});

map.on("error", (e) => {
  const msg = String(e?.error?.message || "");
  // A missing archive is the one failure a visitor is likely to hit on a
  // fresh clone. Only the primary region earns the on-page hint; a secondary
  // region that is not built yet just logs and the rest of the map works.
  if (msg.includes(REGIONS[0].url.replace("./", ""))) {
    document.getElementById("hint-text").textContent =
      t("missing").replace("{file}", REGIONS[0].url.replace("./", ""));
    document.getElementById("hint").hidden = false;
  } else if (REGIONS.some((r) => msg.includes(r.url.replace("./", "")))) {
    console.warn("region archive not available:", msg);
  }
});

/* ── 3D terrain (testing) ─────────────────────────────────────────────────
 * Not Mapbox — the stack is MapLibre precisely because it needs no token, and
 * Mapbox's terrain source is billed. AWS's open Terrarium tiles provide free
 * global elevation; MapLibre drapes every layer over it, so tilting the map
 * shows the visibility raster ON the hills that cause it — the Vltava valley
 * walls explain their own shadows.
 *
 * The DEM is ~30 m and unrelated to the 1 m analysis: a viewing aid, not the
 * model. Hence the "test" tag in the UI.
 */
const terrainBtn = document.getElementById("terrain-toggle");
const exWrap = document.getElementById("terrain-ex-wrap");
const exSlider = document.getElementById("terrain-ex");
const exValue = document.getElementById("terrain-ex-value");
let terrainOn = false;

// Bohemian relief is subtle — ~250 m across the whole Prague box — so 1x
// reads flat from any camera. 2.5x is where the valley walls that cause the
// shadows start to look like walls; the slider is there because the right
// number depends on zoom and taste, not physics.
function applyTerrain() {
  const ex = Number(exSlider.value) / 10;
  exValue.textContent = `${ex.toFixed(1)}×`;
  map.setTerrain(terrainOn ? { source: "dem", exaggeration: ex } : null);
}

terrainBtn.addEventListener("click", () => {
  terrainOn = !terrainOn;
  if (terrainOn && !map.getSource("dem")) {
    map.addSource("dem", {
      type: "raster-dem",
      encoding: "terrarium",
      tiles: ["https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 15,
      attribution: "Terrain: Mapzen/AWS Open Data",
    });
  }
  applyTerrain();
  map.easeTo({ pitch: terrainOn ? 72 : 0, duration: 900 });
  terrainBtn.textContent = t(terrainOn ? "on" : "off");
  terrainBtn.classList.toggle("on", terrainOn);
  exWrap.hidden = !terrainOn;
});

exSlider.addEventListener("input", applyTerrain);

/* ── layer toggle: whole-window fraction vs the single at-maximum moment ── */
function setLayer(name) {
  activeLayer = name;
  for (const region of REGIONS) {
    const frac = `visibility-${region.id}`;
    const max = `max-${region.id}`;
    if (map.getLayer(frac)) {
      map.setLayoutProperty(frac, "visibility", name === "fraction" ? "visible" : "none");
    }
    if (map.getLayer(max)) {
      map.setLayoutProperty(max, "visibility", name === "max" ? "visible" : "none");
    }
  }
  document.querySelectorAll("[data-layer]").forEach((b) => {
    b.classList.toggle("on", b.dataset.layer === name);
  });
}
document.querySelectorAll("[data-layer]").forEach((b) => {
  b.addEventListener("click", () => !b.disabled && setLayer(b.dataset.layer));
});

/* ── basemap switch ──
 * Satellite is busy and bright, so the overlay needs to be more opaque over it
 * to stay readable; dark tiles need less. The slider is nudged on switch
 * rather than pinned, so a deliberate choice is not overridden on every click.
 */
let lastAutoOpacity = null;

function setBasemap(name) {
  const choice = BASEMAPS[name];
  if (!choice || !map.getLayer(choice.base)) return;

  for (const [key, layers] of Object.entries(BASEMAPS)) {
    const on = key === name ? "visible" : "none";
    for (const id of Object.values(layers)) {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on);
    }
  }

  const slider = document.getElementById("opacity");
  const suggested = name === "satellite" ? 75 : 90;
  if (lastAutoOpacity === null || Number(slider.value) === lastAutoOpacity) {
    slider.value = String(suggested);
    slider.dispatchEvent(new Event("input"));
  }
  lastAutoOpacity = suggested;

  document.querySelectorAll(".seg button").forEach((b) => {
    b.classList.toggle("on", b.dataset.base === name);
  });
}

document.querySelectorAll(".seg button").forEach((b) => {
  b.addEventListener("click", () => setBasemap(b.dataset.base));
});

/* ── opacity ── */
document.getElementById("opacity").addEventListener("input", (e) => {
  for (const region of REGIONS) {
    for (const id of [`visibility-${region.id}`, `max-${region.id}`]) {
      if (map.getLayer(id)) {
        map.setPaintProperty(id, "raster-opacity", e.target.value / 100);
      }
    }
  }
});

/* ── guided hints ─────────────────────────────────────────────────────────
 * Same shape as the alley kit's SiteGuideModal: a short stepper on first
 * visit, dismissible, re-openable from the "?" button, remembered in
 * localStorage so it never nags a returning visitor.
 */
// Guide text lives in I18N.<lang>.steps.

const SEEN_KEY = "sunline.guide.seen";
let step = 0;

const hintEl = document.getElementById("hint");
const textEl = document.getElementById("hint-text");
const stepEl = document.getElementById("hint-step");
const nextEl = document.getElementById("hint-next");

function render() {
  const steps = I18N[LANG].steps;
  textEl.textContent = steps[step];
  stepEl.textContent = `${step + 1} / ${steps.length}`;
  nextEl.textContent = step === steps.length - 1 ? t("done") : t("next");
  hintEl.hidden = false;
}

function close() {
  hintEl.hidden = true;
  try {
    localStorage.setItem(SEEN_KEY, "1");
  } catch {
    /* private mode — the guide simply shows again next time */
  }
}

function startGuide(force = false) {
  let seen = false;
  try {
    seen = localStorage.getItem(SEEN_KEY) === "1";
  } catch {
    seen = false;
  }
  if (seen && !force) return;
  step = 0;
  render();
}

nextEl.addEventListener("click", () => {
  if (step === I18N[LANG].steps.length - 1) close();
  else {
    step += 1;
    render();
  }
});
document.getElementById("hint-skip").addEventListener("click", close);
document.getElementById("guide-open").addEventListener("click", () => startGuide(true));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !hintEl.hidden) close();
});

/* ── first paint of all strings (guide element refs exist by now) ── */
applyLang(LANG);

/* ── donation link — hidden until a URL is set, as in the alley kit ── */
/* ── legend collapse, phones only ─────────────────────────────────────────
 * The panel is the ramp plus five control groups and two notes. That is fine
 * in a 286 px desktop column and far too much on a phone held outdoors, where
 * the map is the entire product. The ramp stays visible because it is the
 * legend; the settings fold away. Desktop is untouched — the button is
 * display:none above 620 px.
 */
const legendEl = document.getElementById("legend");
const legendToggle = document.getElementById("legend-toggle");
const phoneQuery = window.matchMedia("(max-width: 620px)");

function setLegendOpen(open) {
  legendEl.classList.toggle("collapsed", !open);
  legendToggle.setAttribute("aria-expanded", String(open));
  legendToggle.textContent = open ? "▴" : "▾";
}
setLegendOpen(!phoneQuery.matches);
legendToggle.addEventListener("click", () =>
  setLegendOpen(legendEl.classList.contains("collapsed")),
);
// Rotating the phone must not leave it collapsed on a wide screen.
phoneQuery.addEventListener("change", (e) => setLegendOpen(!e.matches));

if (DONATION_URL) {
  for (const id of ["kofi", "gate-kofi"]) {
    const a = document.getElementById(id);
    a.href = DONATION_URL;
    a.hidden = false;
  }
  // The whole row is hidden, not just the link, so the explanatory sentence
  // never appears without something to click.
  document.getElementById("gate-support").hidden = false;
}

/* ── place search ─────────────────────────────────────────────────────────
 * "Which street am I on?" is the first question this map gets asked, so the
 * box sits in the title panel above every layer control.
 *
 * Photon rather than Nominatim: it sends Access-Control-Allow-Origin (checked
 * — Nominatim did not), it is built for as-you-type queries, and its operators
 * ask for autocomplete traffic rather than forbidding it. Results are biased
 * to the current view and clipped to a Czech bbox, because every archive here
 * is Czech and a hit in Slovakia would only waste a tap.
 */
const CZ_BBOX = "12.09,48.55,18.86,51.06";
const qEl = document.getElementById("q");
const qList = document.getElementById("q-results");
const qNote = document.getElementById("q-note");
const qClear = document.getElementById("q-clear");
let qTimer = null;
let qMarker = null;
let qSeq = 0; // guards against a slow early request overwriting a newer one

// Loaded once so a picked point can be told "there is no data here yet"
// instead of flying to a black square.
let coverage = null;
fetch("./coverage.geojson").then((r) => r.json()).then((d) => (coverage = d)).catch(() => {});

function inCoverage(lon, lat) {
  if (!coverage) return true; // unknown — say nothing rather than mislead
  return coverage.features.some((f) => {
    if (f.properties.status !== "live") return false;
    const ring = f.geometry.coordinates[0];
    let hit = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) hit = !hit;
    }
    return hit;
  });
}

function closeResults() {
  qList.hidden = true;
  qList.innerHTML = "";
  qEl.setAttribute("aria-expanded", "false");
}

function label(p) {
  const line1 = [p.name, p.housenumber].filter(Boolean).join(" ");
  const line2 = [p.street, p.district, p.city, p.state].filter((v) => v && v !== line1);
  return [line1 || p.street || p.city, [...new Set(line2)].join(", ")];
}

function pick(lon, lat, title) {
  closeResults();
  qEl.value = title;
  qClear.hidden = false;
  map.flyTo({ center: [lon, lat], zoom: 16, speed: 1.4 });
  if (qMarker) qMarker.remove();
  qMarker = new maplibregl.Marker({ color: "#f0a04b" }).setLngLat([lon, lat]).addTo(map);
  qNote.textContent = inCoverage(lon, lat) ? "" : t("searchOutside");
  qNote.hidden = !qNote.textContent;
}

async function search(text) {
  const seq = ++qSeq;
  const c = map.getCenter();
  const url =
    `https://photon.komoot.io/api/?q=${encodeURIComponent(text)}` +
    `&limit=12&bbox=${CZ_BBOX}&lat=${c.lat.toFixed(3)}&lon=${c.lng.toFixed(3)}`;
  let feats = [];
  try {
    const r = await fetch(url);
    if (r.ok) feats = (await r.json()).features || [];
  } catch {
    /* offline or the service is down — fall through to "nothing found" */
  }
  if (seq !== qSeq) return; // a newer keystroke already won

  // Photon returns one hit per OSM node, so a long street arrives three or
  // four times over. Collapse by rendered label — the user cannot tell those
  // apart anyway, and a list of identical rows reads as a broken search.
  const seen = new Set();
  feats = feats.filter((f) => {
    const key = label(f.properties).join("|");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  qList.innerHTML = "";
  if (!feats.length) {
    const li = document.createElement("li");
    li.className = "hit-sub";
    li.style.padding = "6px 8px";
    li.textContent = t("searchNoResults");
    qList.append(li);
  }
  for (const f of feats.slice(0, 6)) {
    const [lon, lat] = f.geometry.coordinates;
    const [main, sub] = label(f.properties);
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = main || "";
    if (sub) {
      const s = document.createElement("span");
      s.className = "hit-sub";
      s.textContent = sub;
      b.append(s);
    }
    b.addEventListener("click", () => pick(lon, lat, main || sub));
    li.append(b);
    qList.append(li);
  }
  qList.hidden = false;
  qEl.setAttribute("aria-expanded", "true");
}

qEl.addEventListener("input", () => {
  qNote.hidden = true;
  qClear.hidden = !qEl.value;
  clearTimeout(qTimer);
  const text = qEl.value.trim();
  if (text.length < 3) return closeResults();
  qTimer = setTimeout(() => search(text), 250); // one request per pause, not per key
});

qEl.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closeResults(); qEl.blur(); }
  if (e.key === "ArrowDown") { e.preventDefault(); qList.querySelector("button")?.focus(); }
  if (e.key === "Enter") { e.preventDefault(); qList.querySelector("button")?.click(); }
});

qClear.addEventListener("click", () => {
  qEl.value = "";
  qClear.hidden = true;
  qNote.hidden = true;
  closeResults();
  if (qMarker) { qMarker.remove(); qMarker = null; }
  qEl.focus();
});

document.addEventListener("click", (e) => {
  if (!e.target.closest(".search")) closeResults();
});
