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
  { id: "prague", url: "visibility.pmtiles", maxUrl: "visibility_max.pmtiles" },
  { id: "north", url: "north.pmtiles", maxUrl: "north_max.pmtiles" },
  // Built in the cloud; a region whose archive is not uploaded yet fails soft.
  { id: "west", url: "west.pmtiles", maxUrl: "west_max.pmtiles" },
  { id: "northwest", url: "northwest.pmtiles", maxUrl: "northwest_max.pmtiles" },
].map((r) => ({ ...r, url: TILE_BASE + r.url, maxUrl: TILE_BASE + r.maxUrl }));
let activeLayer = "fraction"; // "fraction" | "max"

/* ── i18n ─────────────────────────────────────────────────────────────────
 * Czech first — the map is of Czech streets for a Czech sky. EN kept for the
 * portfolio audience. Strings with markup are trusted static HTML from this
 * file, never user input.
 */
const I18N = {
  cs: {
    htmlTitle: "SunLine — kde Praha uvidí zatmění",
    sub: "Kde Praha — a kraj na sever po Mělník — uvidí zatmělé slunce",
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
    source: "Zdrojový kód", support: "Podpořte mapu",
    missing: "chybí soubor {file} — vytvořte ho příkazem `make demo`.",
    gateDesc: "Mapa ukazuje, odkud v Praze a okolí bude vidět částečné zatmění Slunce 12. srpna 2026 večer — a kde ho zakryjí domy, stromy a kopce. Slunce bude jen 1–9° nad obzorem, takže záleží na každé ulici.",
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
    htmlTitle: "SunLine — where Prague can see the eclipse",
    sub: "Where Prague — and the country north to Mělník — can see the eclipse sun",
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
    source: "Source", support: "Support this map",
    missing: "{file} is missing — run `make demo` to build it.",
    gateDesc: "This map shows where the partial solar eclipse of 12 August 2026 will be visible from in and around Prague — and where buildings, trees and hills block it. The sun will be only 1–9° above the horizon, so every street is different.",
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

map.on("load", async () => {
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
if (DONATION_URL) {
  const a = document.getElementById("kofi");
  a.href = DONATION_URL;
  a.hidden = false;
  document.getElementById("kofi-dot").hidden = false;
}
