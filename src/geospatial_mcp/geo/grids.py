"""Discrete global grid systems: geohash, H3, Plus Codes and web-map tiles.

Each of these encodes a position as a short string or integer that also names
an *area*, which makes them useful for binning, joining and privacy-preserving
truncation in a way raw coordinates are not.

* **Geohash** -- base-32, arbitrary precision, prefix-shareable. Ubiquitous in
  key-value stores because a shared prefix means spatial proximity.
* **H3** -- Uber's hexagonal hierarchical index. Hexagons have uniform
  adjacency (six equidistant neighbours, no diagonal problem), which is why
  ride-hailing, logistics and demand-modelling settled on it.
* **Plus Codes** (Open Location Code) -- Google's open standard, designed so
  people can say them aloud and so places without street addresses can have
  one. Widely used for humanitarian logistics and last-mile delivery.
* **Quadkey / XYZ tiles** -- the addressing scheme behind every slippy map.
"""

from __future__ import annotations

import geohashr
import h3
import mercantile
import pluscodes

from ..errors import GeoInputError

__all__ = [
    "GEOHASH_PRECISION_M",
    "geohash_decode",
    "geohash_encode",
    "h3_cell_area_km2",
    "h3_decode",
    "h3_encode",
    "pluscode_decode",
    "pluscode_encode",
    "quadkey_of",
    "tile_bounds",
    "tile_of",
]

#: Approximate cell width at the equator for each geohash length, in metres.
#: Cells are not square and narrow toward the poles; this is a planning figure.
GEOHASH_PRECISION_M: dict[int, int] = {
    1: 5_000_000,
    2: 1_250_000,
    3: 156_000,
    4: 39_100,
    5: 4_890,
    6: 1_220,
    7: 153,
    8: 38,
    9: 5,
    10: 1,
    11: 1,
    12: 1,
}


def geohash_encode(lat: float, lon: float, precision: int = 9) -> str:
    """Encode a position as a geohash of ``precision`` characters (1-12)."""
    if not 1 <= precision <= 12:
        raise GeoInputError.with_example(
            got=precision,
            problem="Geohash precision must be between 1 and 12 characters.",
            example="9  (about 5 m)",
        )
    return geohashr.encode(lat, lon, precision)


def geohash_decode(value: str) -> tuple[float, float]:
    """Decode a geohash to the ``(latitude, longitude)`` of its cell centre."""
    try:
        lat, lon = geohashr.decode(value.strip().lower())
    except Exception as exc:
        raise GeoInputError.with_example(
            got=value,
            problem=f"Not a valid geohash ({exc}).",
            example="u09tunq  (Paris, ~150 m)",
        ) from exc
    return float(lat), float(lon)


def h3_encode(lat: float, lon: float, resolution: int = 9) -> str:
    """Encode a position as an H3 cell index at ``resolution`` (0-15).

    Resolution 9 cells average about 0.1 km2 -- roughly a city block, the
    common default for demand aggregation and delivery zoning.
    """
    if not 0 <= resolution <= 15:
        raise GeoInputError.with_example(
            got=resolution,
            problem="H3 resolution must be between 0 (largest) and 15 (smallest).",
            example="9  (about 0.1 km2 per cell)",
        )
    return h3.latlng_to_cell(lat, lon, resolution)


def h3_decode(cell: str) -> tuple[float, float]:
    """Return the ``(latitude, longitude)`` centre of an H3 cell."""
    try:
        lat, lon = h3.cell_to_latlng(cell)
    except Exception as exc:
        raise GeoInputError.with_example(
            got=cell,
            problem=f"Not a valid H3 cell index ({exc}).",
            example="891fb46622fffff",
        ) from exc
    return float(lat), float(lon)


def h3_cell_area_km2(cell: str) -> float:
    """Area of a specific H3 cell in square kilometres."""
    return float(h3.cell_area(cell, unit="km^2"))


def pluscode_encode(lat: float, lon: float, code_length: int = 11) -> str:
    """Encode a position as a full Plus Code (Open Location Code).

    Length 10 gives roughly 14 x 14 m; 11 adds a refinement character for about
    3.5 x 2.8 m.
    """
    try:
        return pluscodes.encode(lat, lon, code_length)
    except Exception as exc:
        raise GeoInputError.with_example(
            got=(lat, lon, code_length),
            problem=f"Could not encode a Plus Code ({exc}).",
            example="48.8584, 2.2945 at length 10",
        ) from exc


def pluscode_decode(code: str) -> tuple[float, float]:
    """Decode a full Plus Code to the ``(latitude, longitude)`` of its centre.

    Short codes (``'GV4C+X9'`` without an area prefix) cannot be resolved
    without a reference location, so they are rejected with an explanation
    rather than guessed at.
    """
    cleaned = code.strip().upper()
    try:
        area = pluscodes.decode(cleaned)
    except Exception as exc:
        raise GeoInputError.with_example(
            got=code,
            problem=(
                f"Not a full Plus Code ({exc}). Short codes like 'GV4C+X9' need a "
                "reference town to resolve; supply the full code instead."
            ),
            example="8FW4V75V+8Q",
        ) from exc
    return float(area.center().lat), float(area.center().lon)


def tile_of(lat: float, lon: float, zoom: int) -> tuple[int, int, int]:
    """Return the ``(x, y, z)`` XYZ web-map tile containing a position."""
    if not 0 <= zoom <= 24:
        raise GeoInputError.with_example(
            got=zoom, problem="Tile zoom must be between 0 and 24.", example="12"
        )
    t = mercantile.tile(lon, lat, zoom)
    return t.x, t.y, t.z


def quadkey_of(lat: float, lon: float, zoom: int) -> str:
    """Return the Bing-style quadkey string for the tile containing a position."""
    x, y, z = tile_of(lat, lon, zoom)
    return mercantile.quadkey(mercantile.Tile(x, y, z))


def tile_bounds(x: int, y: int, z: int) -> tuple[float, float, float, float]:
    """Geographic bounds of an XYZ tile as ``(west, south, east, north)``."""
    b = mercantile.bounds(mercantile.Tile(x, y, z))
    return b.west, b.south, b.east, b.north
