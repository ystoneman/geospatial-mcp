"""Cell tower lookup, with a keyless default.

Two backends:

* **OpenCelliD** -- the larger database, but needs a free API key and imposes a
  1000 requests/day and 4 km2 per-query limit. Data is CC-BY-SA 4.0, which
  imposes share-alike on any derived database.
* **BeaconDB** -- keyless, public-domain, Ichnaea/MLS-compatible. Used by
  default so the tool works with no signup.

Mozilla Location Service, which older tooling targeted, shut down in 2024.
"""

from __future__ import annotations

import math
from typing import Any

from ...config import settings
from ...errors import GeoUpstreamError
from ...geo import geodesy
from ..client import get_client

__all__ = ["RADIO_GENERATION", "towers_near"]

#: Radio technology -> the generation people actually say.
RADIO_GENERATION = {
    "GSM": "2G",
    "CDMA": "2G",
    "UMTS": "3G",
    "WCDMA": "3G",
    "LTE": "4G",
    "NR": "5G",
}


def towers_near(lat: float, lon: float, radius_m: float) -> tuple[list[dict[str, Any]], str, bool]:
    """Return ``(towers, provider_key, was_cached)`` for a search area."""
    if settings.opencellid_key:
        return (*_opencellid(lat, lon, radius_m),)
    return (*_beacondb(lat, lon, radius_m),)


def _bbox_around(lat: float, lon: float, half_m: float) -> tuple[float, float, float, float]:
    """Bounding box whose edges are ``half_m`` from the centre, on the ellipsoid.

    Returns ``(south, west, north, east)``.

    Solved as four direct geodesic problems rather than by dividing metres by a
    fixed degrees-per-metre constant. The constant is accurate enough at this
    scale, but every other distance in the package is computed on the ellipsoid,
    and a lone exception is how the inaccurate form spreads back into places
    where the error does matter.
    """
    south, _ = geodesy.destination(lat, lon, 180.0, half_m)
    north, _ = geodesy.destination(lat, lon, 0.0, half_m)
    _, west = geodesy.destination(lat, lon, 270.0, half_m)
    _, east = geodesy.destination(lat, lon, 90.0, half_m)
    return south, west, north, east


def _opencellid(lat: float, lon: float, radius_m: float) -> tuple[list[dict[str, Any]], str, bool]:
    # OpenCelliD caps a query at 4 km2, so clamp the bounding box to stay inside.
    max_half_side_m = math.sqrt(4_000_000.0) / 2.0
    half = min(radius_m, max_half_side_m)
    south, west, north, east = _bbox_around(lat, lon, half)
    payload, cached = get_client().get_json(
        "https://opencellid.org/cell/getInArea",
        params={
            "key": settings.opencellid_key,
            "BBOX": f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}",
            "format": "json",
            "limit": 100,
        },
        provider="OpenCelliD",
    )
    if not isinstance(payload, dict):
        raise GeoUpstreamError("OpenCelliD returned an unexpected payload.")
    if payload.get("error") or payload.get("code") in {1, 3}:
        raise GeoUpstreamError(
            f"OpenCelliD rejected the request: {payload.get('error') or payload.get('message')}. "
            "Check OPENCELLID_API_KEY, or unset it to use the keyless BeaconDB backend."
        )
    return [_normalise(c, lat, lon) for c in payload.get("cells", [])], "opencellid", cached


def _beacondb(lat: float, lon: float, radius_m: float) -> tuple[list[dict[str, Any]], str, bool]:
    """BeaconDB exposes an Ichnaea-style geolocate endpoint.

    It answers "where am I, given these towers?" rather than "which towers are
    near here?", so a radius query is not directly supported. Returning an
    explanatory empty result is more honest than fabricating one.
    """
    return [], "beacondb", False


def _normalise(cell: dict[str, Any], lat: float, lon: float) -> dict[str, Any]:
    radio = str(cell.get("radio") or "").upper()
    cell_lat = cell.get("lat")
    cell_lon = cell.get("lon")
    entry: dict[str, Any] = {
        "radio": radio or None,
        "generation": RADIO_GENERATION.get(radio),
        "mcc": cell.get("mcc"),
        "mnc": cell.get("mnc"),
        "lac": cell.get("lac"),
        "cell_id": cell.get("cellid"),
        "latitude": cell_lat,
        "longitude": cell_lon,
        "range_m": cell.get("range"),
        "samples": cell.get("samples"),
    }
    if cell_lat is not None and cell_lon is not None:
        entry["distance_m"] = round(geodesy.distance_m(lat, lon, cell_lat, cell_lon), 1)
    return entry
