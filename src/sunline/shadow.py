"""The shadow sweep — the performance-critical core.

Geometry
--------
The sun sits at azimuth ``A`` (degrees clockwise from north) and apparent
elevation ``e``. Rotate the raster so the horizontal direction *toward* the sun
runs along -x; then every pixel in a row shares one sight-line and ``s``, the
distance along that row, increases *away* from the sun.

A ray leaving a point at ``(s_i, z_i)`` toward the sun climbs at ``tan e``, so a
blocker at ``s_j < s_i`` (nearer the sun) with height ``z_j`` occludes it when::

    z_j > z_i + (s_i - s_j) * tan e
    z_j + s_j * tan e  >  z_i + s_i * tan e

Substituting ``g = z + s * tan e`` collapses that to ``max_{j<i} g_j > g_i`` — a
plain running maximum. One pass per row, O(N) for the whole raster, no per-pixel
ray casting.

Rather than return a boolean mask, the sweep returns::

    M_i = (exclusive running max of g)_i - s_i * tan e

``M`` is the *minimum eye elevation, in metres a.s.l., needed to see the sun at
this pixel*. It is a physical height, so it is independent of the rotated frame:
rotate the surface in, rotate ``M`` back out, and compare against the observer
in the original grid. That halves the rotation work (the observer raster never
gets rotated) and gives an intermediate that is directly interpretable — "your
window needs to be N metres up".

Observer height
---------------
Eye height is added to the *terrain*, never to the surface model. Standing on
the DSM means standing on the tree canopy and the rooftops, which would report
a clear view of the sun for someone in fact underneath a lime tree.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

# Padding introduced by rotation must never occlude anything. Rotation with
# order=0 does not interpolate, so this sentinel stays exactly this value.
_PAD = np.float32(-9e6)


def _rotation_deg(azimuth_deg: float) -> float:
    """Rotation that brings the toward-sun direction onto the -x axis.

    Raster convention: row 0 is north, column 0 is west, so +col is east and
    +row is south. The unit vector toward the sun is ``(sin A, cos A)`` in map
    coordinates (east, north), which sits at standard math angle ``90 - A``.
    Bringing it onto -x (west, angle 180) needs a counter-clockwise turn of
    ``180 - (90 - A) = 90 + A``.

    `scipy.ndimage.rotate` takes a positive angle as counter-clockwise in map
    orientation — verified by rotating a marker due east of centre through +90
    and watching it land due north — so the value passes straight through.
    """
    return 90.0 + azimuth_deg


def _rotate(a: np.ndarray, angle: float) -> np.ndarray:
    """Rotate height-preserving (nearest neighbour, never interpolated).

    Bilinear resampling would round off roof edges and shorten every shadow, so
    order=0 is a correctness requirement here, not a speed choice.
    """
    return ndimage.rotate(
        a, angle, reshape=True, order=0, mode="constant", cval=_PAD, prefilter=False
    )


def _unrotate(a: np.ndarray, angle: float, shape: tuple[int, int]) -> np.ndarray:
    """Undo `_rotate` and centre-crop back to the original shape.

    `reshape=False` matters for memory, not just tidiness: the forward rotation
    already grew the canvas to the diagonal, and letting the reverse grow it
    again would double the largest array in the pipeline for no gain. The
    original extent is centred inside `a`, so cropping recovers it exactly.
    """
    back = ndimage.rotate(
        a, -angle, reshape=False, order=0, mode="constant", cval=_PAD, prefilter=False
    )
    r0 = (back.shape[0] - shape[0]) // 2
    c0 = (back.shape[1] - shape[1]) // 2
    return back[r0 : r0 + shape[0], c0 : c0 + shape[1]]


def min_eye_elevation(
    surface: np.ndarray,
    res: float,
    azimuth_deg: float,
    elevation_deg: float,
) -> np.ndarray:
    """Minimum eye elevation (m a.s.l.) needed to see the sun, per pixel.

    Parameters
    ----------
    surface : 2-D float array of blocker heights in metres a.s.l. (the DSM).
    res : pixel size in metres.
    azimuth_deg : solar azimuth, degrees clockwise from north.
    elevation_deg : *apparent* (refracted) solar elevation in degrees.

    Returns an array shaped like `surface`. Pixels that need no help at all come
    back as -inf-ish; compare with ``observer_z > result`` to get visibility.
    """
    if elevation_deg <= 0:
        # Sun is below the horizon: nothing anywhere can see it.
        return np.full(surface.shape, np.inf, dtype=np.float32)

    angle = _rotation_deg(azimuth_deg)
    g = _rotate(np.asarray(surface, dtype=np.float32), angle)

    tan_e = np.float32(np.tan(np.radians(elevation_deg)))
    # s increases along +col, away from the sun.
    s = (np.arange(g.shape[1], dtype=np.float32) * np.float32(res))[None, :]

    # Every step below is in place. The rotated array is the largest thing in
    # the pipeline — at a 3 km halo it is 14142^2 float32, 800 MB — and a single
    # `g = rot + s * tan_e` would hold two of them at once. That doubling is
    # what broke the process pool the first time this ran.
    g += s * tan_e

    # Exclusive running max: a pixel cannot shadow itself. The shift is done
    # per row-band because `g[:, 1:] = g[:, :-1]` on overlapping slices makes
    # NumPy materialise a full-size temporary.
    np.maximum.accumulate(g, axis=1, out=g)
    for r0 in range(0, g.shape[0], 2048):
        band = g[r0 : r0 + 2048]
        band[:, 1:] = band[:, :-1].copy()
    g[:, 0] = _PAD

    g -= s * tan_e  # -> M, back in metres a.s.l.

    m = _unrotate(g, angle, surface.shape)
    del g
    # Rotation padding that leaked into the crop means "unknown, assume open".
    m[m <= _PAD * 0.5] = -np.inf
    return m


def visible(
    surface: np.ndarray,
    terrain: np.ndarray,
    res: float,
    azimuth_deg: float,
    elevation_deg: float,
    eye_height_m: float = 1.6,
) -> np.ndarray:
    """Boolean mask: can an observer of `eye_height_m` here see the sun?"""
    m = min_eye_elevation(surface, res, azimuth_deg, elevation_deg)
    observer_z = np.asarray(terrain, dtype=np.float32) + np.float32(eye_height_m)
    return observer_z > m
