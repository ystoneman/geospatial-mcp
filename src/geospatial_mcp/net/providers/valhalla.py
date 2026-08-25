"""Valhalla routing via the keyless FOSSGIS public instance.

This is the default routing backend, replacing a hard dependency on
OpenRouteService that required an API key the previous README never documented.
Valhalla serves routing, isochrones, matrices and map-matching from one engine,
so a single keyless provider covers the whole routing toolset.

Requests are sent as POST with a JSON body. The documented GET form takes the
request as a URL-encoded ``json`` parameter, which is fragile: any whitespace
in the serialised payload produces a bare ``"Failed to parse json request"``.

Public instance courtesy of FOSSGIS e.V.; please respect its 1 request/second
limit (enforced by the shared rate limiter) and set ``VALHALLA_URL`` to a
self-hosted instance for heavy use. Data is ODbL 1.0.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

from ...config import settings
from ...errors import GeoInputError, GeoUpstreamError
from ..client import get_client

__all__ = ["COSTING", "COSTING_DESCRIPTIONS", "isochrone", "matrix", "matrix_pair_cap", "route"]

#: Valhalla costing models, keyed by the plain-language name we expose.
COSTING: dict[str, str] = {
    "car": "auto",
    "truck": "truck",
    "bicycle": "bicycle",
    "walk": "pedestrian",
    "motorcycle": "motorcycle",
    "bus": "bus",
    "taxi": "taxi",
}

#: What each profile is for, in commercial terms.
COSTING_DESCRIPTIONS: dict[str, str] = {
    "car": "Private car or van; standard road network.",
    "truck": "Heavy goods vehicle; respects weight, height, width and hazmat restrictions.",
    "bicycle": "Bicycle; prefers cycleways and quiet roads.",
    "walk": "Walking; footpaths and pedestrian crossings.",
    "motorcycle": "Motorcycle.",
    "bus": "Bus; uses bus-permitted roads.",
    "taxi": "Taxi; may use taxi-only lanes.",
}


def _costing_or_raise(profile: str) -> str:
    try:
        return COSTING[profile]
    except KeyError:
        raise GeoInputError.with_example(
            got=profile,
            problem=f"Unknown travel profile. Valid profiles: {', '.join(sorted(COSTING))}.",
            example="car",
        ) from None


def _post(path: str, body: dict[str, Any], provider: str) -> tuple[dict[str, Any], bool]:
    payload, cached = get_client().post_json(
        f"{settings.valhalla_url}{path}", json_body=body, provider=provider
    )
    if not isinstance(payload, dict):
        raise GeoUpstreamError(f"{provider} returned an unexpected payload type.")
    if "error" in payload:
        raise GeoUpstreamError(
            f"{provider} rejected the request: {payload.get('error')} "
            f"(code {payload.get('error_code')})"
        )
    return payload, cached


def route(
    waypoints: Sequence[tuple[float, float]],
    *,
    profile: str = "car",
    units: str = "kilometers",
    alternates: int = 0,
) -> tuple[dict[str, Any], bool]:
    """Route through two or more ``(lat, lon)`` waypoints in order."""
    if len(waypoints) < 2:
        raise GeoInputError.with_example(
            got=len(waypoints),
            problem="A route needs at least a start and an end.",
            example="two locations, e.g. '48.8584,2.2945' and '48.8606,2.3376'",
        )
    body: dict[str, Any] = {
        "locations": [{"lat": lat, "lon": lon} for lat, lon in waypoints],
        "costing": _costing_or_raise(profile),
        "directions_options": {"units": units},
    }
    if alternates:
        body["alternates"] = max(0, min(alternates, 3))
    payload, cached = _post("/route", body, "Valhalla")
    if "trip" not in payload:
        raise GeoUpstreamError("Valhalla returned no trip. The points may be unroutable.")
    return payload, cached


def isochrone(
    lat: float,
    lon: float,
    *,
    profile: str = "car",
    contours_minutes: Sequence[float] = (15,),
    reverse: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Reachable-area polygons from a point.

    ``reverse=True`` computes the *catchment* -- everywhere that can reach this
    point in the given time, which is the right question for siting a depot or
    a clinic.
    """
    if not contours_minutes:
        raise GeoInputError.with_example(
            got=contours_minutes,
            problem="At least one contour time is required.",
            example="[15] for a 15-minute reachable area",
        )
    body = {
        "locations": [{"lat": lat, "lon": lon}],
        "costing": _costing_or_raise(profile),
        "contours": [{"time": float(m)} for m in sorted(contours_minutes)[:4]],
        "polygons": True,
        "reverse": reverse,
    }
    return _post("/isochrone", body, "Valhalla isochrone")


def matrix_pair_cap() -> int:
    """Largest ``sources x targets`` product the configured instance accepts.

    The FOSSGIS public instances cap a matrix at 100 pairs -- measured, not
    documented: 1 x 100 and 10 x 10 succeed, 10 x 11 fails with error 150,
    "Exceeded max locations". Valhalla's own default, which a self-hosted
    instance inherits, is 2500.
    """
    host = urlparse(settings.valhalla_url).hostname or ""
    return 100 if host.endswith("openstreetmap.de") else 2500


def matrix(
    sources: Sequence[tuple[float, float]],
    targets: Sequence[tuple[float, float]],
    *,
    profile: str = "car",
) -> tuple[dict[str, Any], bool]:
    """Travel time and distance between every source and every target."""
    total = len(sources) * len(targets)
    cap = matrix_pair_cap()
    if total > cap:
        raise GeoInputError.with_example(
            got=f"{len(sources)} origins x {len(targets)} destinations = {total} pairs",
            problem=(
                f"The routing service accepts at most {cap} origin-destination pairs per "
                "request. Split the matrix into smaller calls, or point VALHALLA_URL at a "
                "self-hosted instance for larger ones."
            ),
            example="10 origins x 10 destinations, or 1 origin x 100 destinations",
        )
    body = {
        "sources": [{"lat": lat, "lon": lon} for lat, lon in sources],
        "targets": [{"lat": lat, "lon": lon} for lat, lon in targets],
        "costing": _costing_or_raise(profile),
    }
    return _post("/sources_to_targets", body, "Valhalla matrix")
