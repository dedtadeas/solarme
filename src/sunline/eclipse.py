"""Eclipse contact times from a real ephemeris.

pvlib models where the sun *is*; it knows nothing about the moon. Contact times
therefore cannot come from the solar-position code, and hand-entering them into
`config.yaml` is how this project shipped a window that began 19 minutes before
first contact and ended 4 minutes before maximum.

This module closes that loop: it computes the circumstances with JPL DE421 and
`sunline eclipse` prints them, so the configured window can be checked against
the sky rather than against a guess.

Geometry: the eclipse is in progress while the apparent angular separation of
the two centres is smaller than the sum of their apparent radii. First contact
is when that first becomes true, maximum is the separation minimum, last
contact when it stops.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_SUN_RADIUS_KM = 696_000.0
_MOON_RADIUS_KM = 1_737.4


@dataclass(frozen=True)
class Contact:
    when: dt.datetime
    sun_altitude_deg: float          # geometric, before refraction

    def __str__(self) -> str:
        return f"{self.when:%H:%M:%S} (sun {self.sun_altitude_deg:+.2f} deg)"


@dataclass(frozen=True)
class Circumstances:
    first: Contact
    maximum: Contact
    last: Contact
    magnitude: float                 # fraction of the solar *diameter* covered
    obscuration: float               # fraction of the solar *area* covered
    sunset: dt.datetime

    @property
    def maximum_is_visible(self) -> bool:
        return self.maximum.sun_altitude_deg > 0.0

    @property
    def ends_after_sunset(self) -> bool:
        return self.last.sun_altitude_deg <= 0.0


def _obscuration(sep: float, r_sun: float, r_moon: float) -> float:
    """Fraction of the solar disc's *area* hidden — two overlapping circles."""
    if sep >= r_sun + r_moon:
        return 0.0
    if sep <= abs(r_moon - r_sun):
        return 1.0 if r_moon >= r_sun else (r_moon / r_sun) ** 2

    d, r, R = sep, r_sun, r_moon
    a1 = r**2 * np.arccos((d**2 + r**2 - R**2) / (2 * d * r))
    a2 = R**2 * np.arccos((d**2 + R**2 - r**2) / (2 * d * R))
    a3 = 0.5 * np.sqrt(
        max(0.0, (-d + r + R) * (d + r - R) * (d - r + R) * (d + r + R))
    )
    return float((a1 + a2 - a3) / (np.pi * r**2))


def circumstances(
    lat: float,
    lon: float,
    date: dt.date,
    tz_offset_hours: float,
    *,
    elevation_m: float = 200.0,
    ephemeris_dir: Path | None = None,
    step_seconds: float = 15.0,
) -> Circumstances | None:
    """Local circumstances of any solar eclipse on `date`, or None if there is none."""
    from skyfield.api import Loader, wgs84

    load = Loader(str(ephemeris_dir), verbose=False) if ephemeris_dir else __import__(
        "skyfield.api", fromlist=["load"]
    ).load
    ts = load.timescale()
    eph = load("de421.bsp")
    sun, moon, earth = eph["sun"], eph["moon"], eph["earth"]
    site = earth + wgs84.latlon(lat, lon, elevation_m=elevation_m)

    # Sweep the whole local day; an eclipse anywhere in it will be found.
    minutes = np.arange(0, 24 * 60, step_seconds / 60.0)
    t = ts.utc(date.year, date.month, date.day, -tz_offset_hours, minutes)

    astro_sun = site.at(t).observe(sun).apparent()
    astro_moon = site.at(t).observe(moon).apparent()

    sep = astro_sun.separation_from(astro_moon).degrees
    r_sun = np.degrees(np.arcsin(_SUN_RADIUS_KM / astro_sun.distance().km))
    r_moon = np.degrees(np.arcsin(_MOON_RADIUS_KM / astro_moon.distance().km))
    alt = astro_sun.altaz()[0].degrees

    covered = sep < (r_sun + r_moon)
    if not covered.any():
        return None

    def local(i: int) -> dt.datetime:
        """Naive local wall-clock time.

        Shifting a tz-aware UTC datetime by the offset gives the right clock
        face but keeps `tzinfo=UTC`, which then lies about what it is. Dropping
        tzinfo makes it honestly naive-local, and the caller re-localises.
        """
        shifted = t[int(i)].utc_datetime() + dt.timedelta(hours=tz_offset_hours)
        return shifted.replace(tzinfo=None)

    idx = np.flatnonzero(covered)
    i_max = int(np.argmin(sep))

    mag = (r_sun[i_max] + r_moon[i_max] - sep[i_max]) / (2 * r_sun[i_max])
    obsc = _obscuration(sep[i_max], r_sun[i_max], r_moon[i_max])

    # Sunset: last sample of the day with the sun still up.
    up = np.flatnonzero(alt > 0)
    sunset = local(up[-1]) if up.size else local(i_max)

    return Circumstances(
        first=Contact(local(idx[0]), float(alt[idx[0]])),
        maximum=Contact(local(i_max), float(alt[i_max])),
        last=Contact(local(idx[-1]), float(alt[idx[-1]])),
        magnitude=float(mag),
        obscuration=obsc,
        sunset=sunset,
    )
