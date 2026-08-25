"""Photon (Komoot): fuzzy, typo-tolerant geocoding built on OSM.

Exists here for one specific reason: Nominatim's usage policy forbids
autocomplete and as-you-type search, and it does poorly on misspellings.
Photon is built on the same OSM data, is designed for exactly that use, and is
keyless. Data is ODbL 1.0.
"""

from __future__ import annotations

from typing import Any

from ...config import settings
from ...errors import GeoNoResults, GeoUpstreamError
from ..client import get_client

__all__ = ["search"]


def search(
    query: str,
    *,
    limit: int = 5,
    near: tuple[float, float] | None = None,
    language: str | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Fuzzy-search place names. ``near`` biases results toward a position."""
    params: dict[str, Any] = {"q": query, "limit": max(1, min(limit, 50))}
    if near:
        params["lat"], params["lon"] = f"{near[0]:.6f}", f"{near[1]:.6f}"
    if language:
        params["lang"] = language

    payload, cached = get_client().get_json(
        f"{settings.photon_url}/api", params=params, provider="Photon"
    )
    if not isinstance(payload, dict) or "features" not in payload:
        raise GeoUpstreamError("Photon returned a payload without a 'features' key.")
    features = payload["features"]
    if not features:
        raise GeoNoResults(f"Photon found no match for {query!r}.")

    results = []
    for feature in features:
        coords = (feature.get("geometry") or {}).get("coordinates") or [None, None]
        props = feature.get("properties") or {}
        if coords[0] is None:
            continue
        results.append(
            {
                "latitude": float(coords[1]),
                "longitude": float(coords[0]),
                "name": props.get("name"),
                "type": props.get("type") or props.get("osm_value"),
                "osm_key": props.get("osm_key"),
                "osm_id": props.get("osm_id"),
                "address": {
                    k: props[k]
                    for k in (
                        "street",
                        "housenumber",
                        "city",
                        "district",
                        "state",
                        "postcode",
                        "country",
                        "countrycode",
                    )
                    if props.get(k)
                },
            }
        )
    return results, cached
