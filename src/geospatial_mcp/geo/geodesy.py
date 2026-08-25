"""Geodesic calculations on the WGS84 ellipsoid.

All distance, bearing, destination and area maths goes through
:class:`pyproj.Geod`, which implements Karney's algorithms (the same ones
behind GeographicLib) and is accurate to round-off at any distance, including
near-antipodal pairs where Vincenty's method fails to converge.

Nothing here uses the flat-earth shortcut that this domain invites::

    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(latitude_rad)

Those are equirectangular approximations. They are accurate to a few parts per
thousand over short east-west spans at mid latitudes, and badly wrong at high
latitudes, across long distances, or anywhere near a pole. Because the error is
smooth and plausible-looking, nothing surfaces it -- which is precisely why the
tests in ``tests/geo/test_geodesy.py`` pin the correct answers.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from pyproj import Geod

__all__ = [
    "GEOD",
    "bearing_deg",
    "compass_point",
    "cross_track_distance_m",
    "densify",
    "destination",
    "distance_m",
    "inverse",
    "midpoint",
    "normalize_bearing",
    "path_length_m",
    "polygon_area_m2",
]

#: WGS84 ellipsoid. Shared and stateless; ``Geod`` methods are pure.
GEOD = Geod(ellps="WGS84")


def inverse(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float, float]:
    """Solve the inverse geodesic problem.

    Returns ``(forward_azimuth_deg, back_azimuth_deg, distance_m)``. Azimuths
    are normalised to ``[0, 360)`` rather than pyproj's ``(-180, 180]``,
    because compass bearings are what callers expect.
    """
    fwd, back, dist = GEOD.inv(lon1, lat1, lon2, lat2)
    return normalize_bearing(fwd), normalize_bearing(back), dist


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Geodesic distance in metres between two WGS84 points."""
    return GEOD.inv(lon1, lat1, lon2, lat2)[2]


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing in degrees, ``[0, 360)``, true north.

    Note this is the *initial* bearing: along a long geodesic the bearing
    changes continuously, so the value at the destination differs. Use
    :func:`inverse` when you need both ends.
    """
    return normalize_bearing(GEOD.inv(lon1, lat1, lon2, lat2)[0])


def destination(lat: float, lon: float, bearing: float, distance_m: float) -> tuple[float, float]:
    """Solve the direct geodesic problem: where do you end up?

    Returns ``(latitude, longitude)`` after travelling ``distance_m`` along
    ``bearing`` degrees from the start point.
    """
    lon2, lat2, _ = GEOD.fwd(lon, lat, bearing, distance_m)
    return lat2, lon2


def midpoint(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    """The point halfway along the geodesic between two points."""
    fwd, _, dist = GEOD.inv(lon1, lat1, lon2, lat2)
    lon, lat, _ = GEOD.fwd(lon1, lat1, fwd, dist / 2.0)
    return lat, lon


def densify(
    lat1: float, lon1: float, lat2: float, lon2: float, num_points: int
) -> list[tuple[float, float, float]]:
    """Sample ``num_points`` equally-spaced points along a geodesic.

    Returns ``(lat, lon, distance_from_start_m)`` triples, inclusive of both
    endpoints.

    This walks the true geodesic. Linearly interpolating latitude and longitude
    instead is the tempting shortcut, and it draws a straight line in *degree
    space* rather than on the ellipsoid. The two diverge measurably on east-west
    paths away from the equator -- exactly the case that matters for a terrain
    profile or a line-of-sight check.
    """
    if num_points < 2:
        raise ValueError("num_points must be at least 2")
    total = GEOD.inv(lon1, lat1, lon2, lat2)[2]
    if total == 0.0:
        return [(lat1, lon1, 0.0)] * num_points
    # npts returns only the intermediate points, so ask for num_points - 2.
    intermediate = GEOD.npts(lon1, lat1, lon2, lat2, num_points - 2) if num_points > 2 else []
    out: list[tuple[float, float, float]] = [(lat1, lon1, 0.0)]
    for i, (lon, lat) in enumerate(intermediate, start=1):
        out.append((lat, lon, total * i / (num_points - 1)))
    out.append((lat2, lon2, total))
    return out


def path_length_m(points: Iterable[tuple[float, float]]) -> float:
    """Total geodesic length of a polyline given as ``(lat, lon)`` pairs."""
    pts = list(points)
    if len(pts) < 2:
        return 0.0
    lons = [p[1] for p in pts]
    lats = [p[0] for p in pts]
    return float(GEOD.line_length(lons, lats))


def polygon_area_m2(ring: Iterable[tuple[float, float]]) -> tuple[float, float]:
    """Geodesic area and perimeter of a polygon ring of ``(lat, lon)`` pairs.

    Returns ``(area_m2, perimeter_m)``. Area is unsigned. Computing this on the
    ellipsoid matters: planar area in degree space is wrong by the cosine of
    the latitude and gets worse toward the poles.
    """
    pts = list(ring)
    if len(pts) < 3:
        return 0.0, 0.0
    lons = [p[1] for p in pts]
    lats = [p[0] for p in pts]
    area, perimeter = GEOD.polygon_area_perimeter(lons, lats)
    return abs(area), perimeter


def cross_track_distance_m(
    lat: float, lon: float, lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Signed perpendicular distance from a point to the great circle A->B.

    Positive means the point lies left of the A->B track, negative right.
    Uses the spherical formula, which is accurate to well under a metre for the
    off-track distances this is used for (corridor checks, route deviation).
    """
    r = 6371008.8  # mean Earth radius, metres
    d13 = distance_m(lat1, lon1, lat, lon) / r
    theta13 = math.radians(bearing_deg(lat1, lon1, lat, lon))
    theta12 = math.radians(bearing_deg(lat1, lon1, lat2, lon2))
    return math.asin(math.sin(d13) * math.sin(theta13 - theta12)) * r


def normalize_bearing(deg: float) -> float:
    """Wrap a bearing into ``[0, 360)``."""
    return deg % 360.0


_COMPASS = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)


def compass_point(bearing: float) -> str:
    """Nearest 16-point compass abbreviation for a bearing in degrees."""
    return _COMPASS[int((normalize_bearing(bearing) + 11.25) % 360.0 / 22.5)]
