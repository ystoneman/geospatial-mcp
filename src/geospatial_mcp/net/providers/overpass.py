"""Overpass API: query OpenStreetMap features by category and area.

This is what turns "find things near here" into a real capability: fuel
stations along a route, hospitals within a radius, EV chargers in a city,
supermarkets in a catchment. Keyless. Data is ODbL 1.0.

Query hygiene matters because Overpass is a shared, heavily-loaded service:
every query gets an explicit ``[out:json][timeout:]`` header, an ``out center``
so ways and relations come back as a single point rather than a full geometry,
and a hard result cap. The public instance permits roughly 10k requests and
1 GB of transfer per day across all users on an IP.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from ...config import settings
from ...errors import GeoInputError, GeoUpstreamError
from ..client import get_client

__all__ = ["CATEGORY_FILTERS", "GLOBAL_MIRRORS", "around", "in_bbox", "raw_query"]

logger = logging.getLogger("geospatial_mcp.overpass")

#: Overpass instances with **global** coverage, tried in order.
#:
#: Regional instances are deliberately excluded. ``overpass.osm.ch`` holds only
#: Swiss data and answers a query for Paris with HTTP 200 and zero elements --
#: indistinguishable from "there is genuinely nothing here". Failing over to it
#: would turn an outage into a silently wrong answer, which is worse than an
#: error. Only add a mirror here after confirming it serves the full planet.
GLOBAL_MIRRORS: tuple[str, ...] = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

#: Plain-language category -> the OSM tag filters that express it.
#: Deliberately curated: raw OSM tagging is a research project on its own, and
#: a model guessing at tag keys produces empty result sets.
CATEGORY_FILTERS: dict[str, tuple[str, ...]] = {
    "fuel": ('node["amenity"="fuel"]', 'way["amenity"="fuel"]'),
    "ev_charging": ('node["amenity"="charging_station"]',),
    "parking": ('node["amenity"="parking"]', 'way["amenity"="parking"]'),
    "hospital": ('node["amenity"="hospital"]', 'way["amenity"="hospital"]'),
    "pharmacy": ('node["amenity"="pharmacy"]',),
    "clinic": ('node["amenity"="clinic"]', 'node["amenity"="doctors"]'),
    "police": ('node["amenity"="police"]',),
    "fire_station": ('node["amenity"="fire_station"]', 'way["amenity"="fire_station"]'),
    "school": ('node["amenity"="school"]', 'way["amenity"="school"]'),
    "restaurant": ('node["amenity"="restaurant"]',),
    "cafe": ('node["amenity"="cafe"]',),
    "hotel": ('node["tourism"="hotel"]', 'way["tourism"="hotel"]'),
    "supermarket": ('node["shop"="supermarket"]', 'way["shop"="supermarket"]'),
    "bank": ('node["amenity"="bank"]',),
    "atm": ('node["amenity"="atm"]',),
    "toilets": ('node["amenity"="toilets"]',),
    "drinking_water": ('node["amenity"="drinking_water"]',),
    "bus_stop": ('node["highway"="bus_stop"]',),
    "railway_station": ('node["railway"="station"]',),
    "airport": ('node["aeroway"="aerodrome"]', 'way["aeroway"="aerodrome"]'),
    "port": ('node["amenity"="ferry_terminal"]', 'way["harbour"="yes"]'),
    "warehouse": ('way["building"="warehouse"]', 'node["landuse"="industrial"]'),
    "power_substation": ('node["power"="substation"]', 'way["power"="substation"]'),
    "power_tower": ('node["power"="tower"]',),
    "communication_tower": (
        'node["man_made"="mast"]',
        'node["man_made"="communications_tower"]',
        'way["man_made"="mast"]',
    ),
    "water_tower": ('node["man_made"="water_tower"]',),
    "viewpoint": ('node["tourism"="viewpoint"]',),
    "shelter": ('node["amenity"="shelter"]',),
    "campsite": ('node["tourism"="camp_site"]',),
    "peak": ('node["natural"="peak"]',),
    "bridge": ('way["bridge"="yes"]',),
    "farmland": ('way["landuse"="farmland"]',),
}


def _build(filters: Iterable[str], selector: str, limit: int, timeout_s: int) -> str:
    parts = "".join(f"{f}{selector};" for f in filters)
    return f"[out:json][timeout:{timeout_s}];({parts});out center {limit};"


def _endpoints() -> tuple[str, ...]:
    """Endpoints to try, in order.

    An explicitly configured ``OVERPASS_URL`` is used alone: if an operator
    points at their own instance, silently falling back to a public one would
    leak their queries and ignore their intent.
    """
    configured = settings.overpass_url
    if configured and configured not in GLOBAL_MIRRORS:
        return (configured,)
    ordered = [configured] if configured in GLOBAL_MIRRORS else []
    ordered += [m for m in GLOBAL_MIRRORS if m != configured]
    return tuple(ordered)


def _run(query: str, limit: int, timeout_s: int) -> tuple[list[dict[str, Any]], bool]:
    """Execute a query, failing over across global mirrors on transient errors.

    The HTTP timeout must exceed the timeout declared inside the query, or we
    abandon a request Overpass is still honouring -- and still pay for it.
    """
    endpoints = _endpoints()
    last_error: Exception | None = None
    payload: Any = None
    cached = False

    for index, endpoint in enumerate(endpoints):
        try:
            payload, cached = get_client().post_json(
                endpoint,
                data=query.encode("utf-8"),
                headers={"Content-Type": "text/plain; charset=utf-8"},
                provider=f"Overpass ({urlparse(endpoint).hostname})",
                timeout_s=timeout_s + 10.0,
            )
            break
        except GeoInputError:
            # A malformed query fails identically everywhere. Do not burn
            # another mirror's quota proving it.
            raise
        except Exception as exc:  # transient: connect error, timeout, 5xx
            last_error = exc
            logger.info(
                "Overpass mirror %s failed (%s); %s",
                endpoint,
                exc,
                "trying next mirror" if index + 1 < len(endpoints) else "no mirrors left",
            )
    else:
        raise GeoUpstreamError(
            f"All {len(endpoints)} Overpass mirrors failed. Last error: {last_error}. "
            "Overpass is a shared free service and is sometimes saturated; retry "
            "shortly, narrow the query, or set OVERPASS_URL to your own instance."
        )

    if not isinstance(payload, dict) or "elements" not in payload:
        raise GeoUpstreamError("Overpass returned a payload without an 'elements' array.")
    results: list[dict[str, Any]] = []
    for element in payload["elements"][:limit]:
        centre = element.get("center") or {}
        lat = element.get("lat", centre.get("lat"))
        lon = element.get("lon", centre.get("lon"))
        if lat is None or lon is None:
            continue
        tags = element.get("tags") or {}
        results.append(
            {
                "latitude": float(lat),
                "longitude": float(lon),
                "name": tags.get("name"),
                "osm_type": element.get("type"),
                "osm_id": element.get("id"),
                "tags": {
                    k: v
                    for k, v in tags.items()
                    if k
                    in (
                        "name",
                        "amenity",
                        "shop",
                        "tourism",
                        "brand",
                        "operator",
                        "opening_hours",
                        "phone",
                        "website",
                        "addr:street",
                        "addr:housenumber",
                        "addr:city",
                        "addr:postcode",
                        "capacity",
                        "fuel:diesel",
                        "socket:type2",
                        "man_made",
                        "height",
                        "natural",
                        "ele",
                    )
                },
            }
        )
    return results, cached


def category_or_raise(category: str) -> tuple[str, ...]:
    try:
        return CATEGORY_FILTERS[category]
    except KeyError:
        raise GeoInputError.with_example(
            got=category,
            problem=(f"Unknown place category. Available: {', '.join(sorted(CATEGORY_FILTERS))}."),
            example="fuel",
        ) from None


def around(
    lat: float,
    lon: float,
    radius_m: float,
    category: str,
    *,
    limit: int = 50,
    timeout_s: int = 25,
) -> tuple[list[dict[str, Any]], bool]:
    """Find features of ``category`` within ``radius_m`` of a point."""
    if radius_m <= 0 or radius_m > 50_000:
        raise GeoInputError.with_example(
            got=radius_m,
            problem="Search radius must be between 1 and 50000 metres.",
            example="2000  (a 2 km radius)",
        )
    filters = category_or_raise(category)
    selector = f"(around:{radius_m:.0f},{lat:.6f},{lon:.6f})"
    return _run(_build(filters, selector, limit, timeout_s), limit, timeout_s)


def in_bbox(
    bbox: tuple[float, float, float, float],
    category: str,
    *,
    limit: int = 50,
    timeout_s: int = 25,
) -> tuple[list[dict[str, Any]], bool]:
    """Find features of ``category`` inside ``(west, south, east, north)``."""
    west, south, east, north = bbox
    filters = category_or_raise(category)
    selector = f"({south:.6f},{west:.6f},{north:.6f},{east:.6f})"
    return _run(_build(filters, selector, limit, timeout_s), limit, timeout_s)


def raw_query(query: str, *, limit: int = 200) -> tuple[list[dict[str, Any]], bool]:
    """Run a hand-written Overpass QL query. For callers who know the language."""
    if "[out:" not in query:
        raise GeoInputError.with_example(
            got=query[:80],
            problem="Overpass queries must declare an output format and timeout.",
            example='[out:json][timeout:25];node["amenity"="cafe"](around:500,48.86,2.29);out center 20;',
        )
    return _run(query, limit, 25)
