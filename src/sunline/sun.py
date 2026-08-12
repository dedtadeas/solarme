"""Solar position over the analysis window.

Refraction matters here in a way it does not for a midday sun study. At 5°
elevation the atmosphere lifts the apparent disc by roughly 0.17°, and at the
horizon by ~0.57° — against a sun this low that is the difference between a
street being lit or not, so the sweep uses pvlib's *apparent* elevation.

Eclipse contact times are not computed here — pvlib models the sun's position,
not the moon's. They live in `sunline.eclipse`, which uses a JPL ephemeris, and
`describe()` checks the configured window against them so a hand-entered window
cannot silently miss the event it was written for.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pvlib

from .config import Config


@dataclass(frozen=True)
class SunSample:
    """One timestamp in the window."""

    when: pd.Timestamp
    azimuth: float
    elevation: float  # apparent (refracted) unless config says otherwise

    @property
    def above_horizon(self) -> bool:
        return self.elevation > 0.0


def aoi_centre_lonlat(cfg: Config) -> tuple[float, float]:
    """AOI centre in WGS84 — the reference point for solar position.

    A 26 km box spans ~0.02° of solar azimuth end to end, far below the
    resolution that matters here, so one position series covers the whole grid.
    """
    from pyproj import Transformer

    a = cfg.aoi
    tf = Transformer.from_crs(a.crs, "EPSG:4326", always_xy=True)
    lon, lat = tf.transform((a.xmin + a.xmax) / 2, (a.ymin + a.ymax) / 2)
    return lon, lat


def sun_series(cfg: Config) -> list[SunSample]:
    """Sample solar position across the configured window.

    Samples with the sun at or below `min_elevation_deg` are dropped. They are
    excluded from the composite denominator too: if the window runs past sunset,
    keeping those timestamps would cap every pixel below 1.0 and make a fully
    open field look partly blocked.
    """
    s = cfg.sun
    lon, lat = aoi_centre_lonlat(cfg)

    times = pd.date_range(
        start=s["window"]["start"],
        end=s["window"]["end"],
        freq=f"{s['step_minutes']}min",
        tz=s["timezone"],
    )

    pos = pvlib.solarposition.get_solarposition(times, lat, lon)
    elev_col = "apparent_elevation" if s.get("use_apparent_elevation", True) else "elevation"

    floor = float(s.get("min_elevation_deg", 0.0))
    return [
        SunSample(when=t, azimuth=float(pos.azimuth[t]), elevation=float(pos[elev_col][t]))
        for t in times
        if float(pos[elev_col][t]) > floor
    ]


def eclipse_circumstances(cfg: Config):
    """Local eclipse circumstances for the AOI centre, or None if there is none."""
    import datetime as dt

    from .eclipse import circumstances

    lon, lat = aoi_centre_lonlat(cfg)
    day = pd.Timestamp(cfg.sun["window"]["start"]).date()
    offset = (
        pd.Timestamp(cfg.sun["window"]["start"], tz=cfg.sun["timezone"]).utcoffset()
        or dt.timedelta()
    ).total_seconds() / 3600.0
    return circumstances(lat, lon, day, offset, ephemeris_dir=cfg.out_dir)


def describe(cfg: Config) -> str:
    """Human-readable summary of the window — used by `make demo` and the CLI."""
    lon, lat = aoi_centre_lonlat(cfg)
    samples = sun_series(cfg)
    if not samples:
        return "no samples above the horizon in the configured window"

    first, last = samples[0], samples[-1]
    lines = [
        f"AOI centre       {lat:.4f} N, {lon:.4f} E",
        f"window           {cfg.sun['window']['start']} .. {cfg.sun['window']['end']}"
        f"  ({cfg.sun['timezone']})",
        f"step             {cfg.sun['step_minutes']} min",
        f"usable samples   {len(samples)} above {cfg.sun.get('min_elevation_deg', 0.0)}deg",
        f"first            {first.when:%H:%M}  az {first.azimuth:6.2f}  elev {first.elevation:5.2f}",
        f"last             {last.when:%H:%M}  az {last.azimuth:6.2f}  elev {last.elevation:5.2f}",
    ]

    # How far a 20 m building reaches at the extremes — the precision claim.
    for tag, smp in (("first", first), ("last", last)):
        reach = 20.0 / np.tan(np.radians(max(smp.elevation, 0.01)))
        lines.append(f"20 m block casts {reach:8.0f} m at {tag} sample")

    lines.append("")
    lines.extend(_check_against_ephemeris(cfg, samples))
    return "\n".join(lines)


def _check_against_ephemeris(cfg: Config, samples: list[SunSample]) -> list[str]:
    """Compare the configured window with the real eclipse, and complain.

    The window is hand-entered. Without this check an earlier config began 19
    minutes before first contact and stopped 4 minutes before maximum — the map
    counted un-eclipsed sunshine and discarded the deepest moment, and nothing
    in the pipeline objected.
    """
    try:
        ec = eclipse_circumstances(cfg)
    except Exception as exc:  # ephemeris unavailable — say so, do not fail
        return [f"eclipse check     skipped ({exc})"]

    if ec is None:
        return ["eclipse check     no solar eclipse on this date (plain sunset run)"]

    out = [
        f"eclipse (DE421)   first {ec.first.when:%H:%M:%S}  max {ec.maximum.when:%H:%M:%S}"
        f"  last {ec.last.when:%H:%M:%S}",
        f"                  magnitude {ec.magnitude:.3f}, obscuration {ec.obscuration:.3f},"
        f" sunset {ec.sunset:%H:%M:%S}",
    ]

    covered = [s.when for s in samples]
    start, end = covered[0], covered[-1]
    max_t = pd.Timestamp(ec.maximum.when).tz_localize(cfg.sun["timezone"])
    first_t = pd.Timestamp(ec.first.when).tz_localize(cfg.sun["timezone"])

    step = pd.Timedelta(minutes=cfg.sun["step_minutes"])
    if not (start - step <= max_t <= end + step):
        out.append(
            f"  !! MAXIMUM ECLIPSE IS OUTSIDE THE WINDOW ({start:%H:%M}-{end:%H:%M}) —"
            " the deepest moment is not being modelled"
        )
    if start < first_t - step:
        wasted = (first_t - start).total_seconds() / 60.0
        out.append(
            f"  !! window starts {wasted:.0f} min before first contact —"
            " that time is ordinary sunshine, not eclipse"
        )
    if ec.ends_after_sunset:
        out.append(
            "  note: the eclipse outlasts sunset here, so last contact is never visible"
        )
    return out
