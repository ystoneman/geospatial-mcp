"""OpenStreetMap Nominatim: forward and reverse geocoding.

Usage policy (https://operations.osmfoundation.org/policies/nominatim/) that
this module is built to respect:

* Maximum one request per second -- enforced by the shared rate limiter.
* A descriptive User-Agent identifying the application -- set on the client.
* Results must be cached -- handled by the shared response cache.
* **Autocomplete is explicitly forbidden.** Route as-you-type or fuzzy lookups
  to Photon instead; :mod:`..providers.photon` exists for exactly this.

Data is ODbL 1.0 and requires attribution wherever results are displayed.
"""

from __future__ import annotations

from typing import Any

from ...config import settings
from ...errors import GeoNoResults, GeoUpstreamError
from ..client import get_client

__all__ = ["CANDIDATES", "geocode", "reverse"]

#: Candidates requested upstream on every forward geocode, however many the
#: caller wants back.
#:
#: The disk cache keys on the request parameters, so if ``resolve()`` asked for
#: five and ``place_geocode`` for one, the same toponym would occupy two cache
#: entries and cost two requests against a 1 request/second public service.
#: Asking for the same number everywhere keeps it to one. Five is enough to see
#: whether a name is ambiguous.
CANDIDATES = 5

_ADDRESS_FIELDS = (
    "house_number",
    "road",
    "neighbourhood",
    "suburb",
    "city",
    "town",
    "village",
    "municipality",
    "county",
    "state",
    "postcode",
    "country",
    "country_code",
)


def _address_of(raw: dict[str, Any]) -> dict[str, str]:
    address = raw.get("address") or {}
    return {k: address[k] for k in _ADDRESS_FIELDS if address.get(k)}


def geocode(
    query: str,
    *,
    limit: int = 1,
    country_codes: str | None = None,
    viewbox: tuple[float, float, float, float] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Forward-geocode a free-text query. Returns ``(results, was_cached)``."""
    params: dict[str, Any] = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": max(CANDIDATES, min(limit, 40)),
    }
    if country_codes:
        params["countrycodes"] = country_codes
    if viewbox:
        west, south, east, north = viewbox
        params["viewbox"] = f"{west},{north},{east},{south}"
        params["bounded"] = 1

    payload, cached = get_client().get_json(
        f"{settings.nominatim_url}/search", params=params, provider="Nominatim"
    )
    if not isinstance(payload, list):
        raise GeoUpstreamError(f"Nominatim returned an unexpected payload type: {type(payload)}")
    if not payload:
        raise GeoNoResults(
            f"Nominatim found no match for {query!r}. Try a broader query "
            "(drop the house number, or add the city and country)."
        )
    return [
        {
            "latitude": float(r["lat"]),
            "longitude": float(r["lon"]),
            "display_name": r.get("display_name", ""),
            "category": r.get("category") or r.get("class"),
            "type": r.get("type"),
            "importance": r.get("importance"),
            "osm_type": r.get("osm_type"),
            "osm_id": r.get("osm_id"),
            "bbox": _bbox_of(r),
            "address": _address_of(r),
        }
        for r in payload[: max(1, limit)]
    ], cached


def reverse(lat: float, lon: float, *, zoom: int = 18) -> tuple[dict[str, Any], bool]:
    """Reverse-geocode a position. ``zoom`` 3 (country) to 18 (building)."""
    payload, cached = get_client().get_json(
        f"{settings.nominatim_url}/reverse",
        params={
            "lat": f"{lat:.7f}",
            "lon": f"{lon:.7f}",
            "format": "jsonv2",
            "addressdetails": 1,
            "zoom": max(0, min(zoom, 18)),
        },
        provider="Nominatim",
    )
    if not isinstance(payload, dict) or payload.get("error"):
        message = (payload or {}).get("error") if isinstance(payload, dict) else None
        raise GeoNoResults(
            f"Nominatim has no record for {lat:.5f}, {lon:.5f}"
            + (f" ({message})" if message else ". This is usually open ocean or Antarctica.")
        )
    return {
        "display_name": payload.get("display_name", ""),
        "category": payload.get("category") or payload.get("class"),
        "type": payload.get("type"),
        "osm_type": payload.get("osm_type"),
        "osm_id": payload.get("osm_id"),
        "address": _address_of(payload),
        "bbox": _bbox_of(payload),
    }, cached


def _bbox_of(raw: dict[str, Any]) -> list[float] | None:
    """Nominatim gives [south, north, west, east]; return GeoJSON order."""
    box = raw.get("boundingbox")
    if not box or len(box) != 4:
        return None
    try:
        south, north, west, east = (float(v) for v in box)
    except (TypeError, ValueError):
        return None
    return [west, south, east, north]
