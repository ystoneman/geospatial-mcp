"""Geometry operations that are correct on the ellipsoid, not in degree space.

The trap this module exists to avoid: Shapely is a *planar* library. Handing it
longitude/latitude degrees and calling ``.buffer(0.05)`` produces a shape that
is circular in degree space, which on the ground is an ellipse stretched
east-west by 1/cos(latitude) -- 2x wrong at 60 degrees, 6x at 80. Areas
computed the same way are in square degrees, a unit that means nothing.

RF coverage is where this trap is easiest to fall into: buffering transmitter
positions by an averaged degree radius, then converting the resulting area with
a single cosine factor taken at the centre of the study area, looks reasonable
and is wrong by a factor that grows with latitude and with the size of the area.

The fix used throughout: project to a locally-accurate metric CRS (Azimuthal
Equidistant centred on the geometry, or the appropriate UTM zone), do the work
in metres, project back.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from pyproj import CRS, Transformer
from shapely import (
    concave_hull,
    make_valid,
    set_precision,
    simplify,
    unary_union,
)
from shapely.geometry import (
    LineString,
    MultiPolygon,
    Polygon,
    mapping,
    shape,
)
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

from ..errors import GeoInputError
from .geodesy import polygon_area_m2

__all__ = [
    "OVERLAY_OPS",
    "aeqd_crs_for",
    "geodesic_buffer",
    "geometry_from_geojson",
    "geometry_to_geojson",
    "hull",
    "measure_geometry",
    "overlay",
    "project_to_metres",
    "project_to_wgs84",
    "repair",
    "simplify_geometry",
]

_WGS84 = CRS.from_epsg(4326)

#: Set operations exposed by ``geom_overlay``.
OVERLAY_OPS = ("intersection", "union", "difference", "symmetric_difference")


def aeqd_crs_for(lat: float, lon: float) -> CRS:
    """An Azimuthal Equidistant CRS centred on a point.

    AEQD preserves distance from its centre exactly, which makes it the right
    projection for buffering: a circle of radius r in this plane is a true
    geodesic circle of radius r on the ground.
    """
    return CRS.from_proj4(
        f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 "
        "+ellps=WGS84 +datum=WGS84 +units=m +no_defs"
    )


def project_to_metres(geom: BaseGeometry, crs: CRS) -> BaseGeometry:
    """Project a WGS84 geometry into a metric CRS."""
    transformer = Transformer.from_crs(_WGS84, crs, always_xy=True)
    return shapely_transform(transformer.transform, geom)


def project_to_wgs84(geom: BaseGeometry, crs: CRS) -> BaseGeometry:
    """Project a metric geometry back to WGS84 degrees."""
    transformer = Transformer.from_crs(crs, _WGS84, always_xy=True)
    return shapely_transform(transformer.transform, geom)


def geodesic_buffer(geom: BaseGeometry, distance_m: float, *, quad_segs: int = 32) -> BaseGeometry:
    """Buffer a geometry by a true ground distance in metres.

    Projects to an AEQD plane centred on the geometry, buffers there, and
    projects back -- so the result is a genuine geodesic offset rather than a
    degree-space approximation.
    """
    if distance_m == 0:
        return geom
    centroid = geom.centroid
    crs = aeqd_crs_for(centroid.y, centroid.x)
    buffered = project_to_metres(geom, crs).buffer(distance_m, quad_segs=quad_segs)
    return project_to_wgs84(buffered, crs)


def geometry_from_geojson(value: str | dict[str, Any]) -> BaseGeometry:
    """Build a Shapely geometry from GeoJSON text, a dict, or a WKT string."""
    import json

    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{"):
            try:
                value = json.loads(text)
            except ValueError as exc:
                raise GeoInputError.with_example(
                    got=text[:80],
                    problem=f"Invalid GeoJSON ({exc}).",
                    example='{"type":"Point","coordinates":[2.2945,48.8584]}',
                ) from exc
        else:
            from shapely import from_wkt

            try:
                return from_wkt(text)
            except Exception as exc:
                raise GeoInputError.with_example(
                    got=text[:80],
                    problem=f"Not valid WKT or GeoJSON ({exc}).",
                    example="POINT (2.2945 48.8584)",
                ) from exc

    assert isinstance(value, dict)
    # Accept a bare geometry, a Feature, or a FeatureCollection.
    if value.get("type") == "Feature":
        value = value.get("geometry") or {}
    elif value.get("type") == "FeatureCollection":
        geoms = [shape(f["geometry"]) for f in value.get("features", []) if f.get("geometry")]
        if not geoms:
            raise GeoInputError("The FeatureCollection contains no geometries.")
        return unary_union(geoms)
    try:
        return shape(value)
    except Exception as exc:
        raise GeoInputError.with_example(
            got=str(value)[:80],
            problem=f"Could not read that GeoJSON geometry ({exc}).",
            example='{"type":"Polygon","coordinates":[[[2.29,48.85],[2.30,48.85],[2.30,48.86],[2.29,48.85]]]}',
        ) from exc


def geometry_to_geojson(geom: BaseGeometry) -> dict[str, Any]:
    """Convert a Shapely geometry to a GeoJSON geometry dict."""
    return mapping(geom)


def _rings_of(geom: BaseGeometry) -> Iterable[Sequence[tuple[float, float]]]:
    """Yield exterior rings as (lat, lon) sequences for geodesic area."""
    if isinstance(geom, Polygon):
        yield [(y, x) for x, y in geom.exterior.coords]
    elif isinstance(geom, MultiPolygon):
        for part in geom.geoms:
            yield [(y, x) for x, y in part.exterior.coords]


def measure_geometry(geom: BaseGeometry) -> dict[str, Any]:
    """Geodesic area, length and centroid of any geometry.

    Area and perimeter come from :func:`~.geodesy.polygon_area_m2`, which works
    on the ellipsoid; holes are subtracted using the same method.
    """
    result: dict[str, Any] = {
        "geometry_type": geom.geom_type,
        "is_valid": geom.is_valid,
        "is_empty": geom.is_empty,
    }
    if not geom.is_empty:
        centroid = geom.centroid
        result["centroid"] = {"latitude": centroid.y, "longitude": centroid.x}
        west, south, east, north = geom.bounds
        result["bbox"] = {"west": west, "south": south, "east": east, "north": north}

    area_m2 = 0.0
    perimeter_m = 0.0
    for ring in _rings_of(geom):
        area, perimeter = polygon_area_m2(ring)
        area_m2 += area
        perimeter_m += perimeter
    # Subtract interior rings (holes).
    polys = (
        [geom]
        if isinstance(geom, Polygon)
        else (list(geom.geoms) if isinstance(geom, MultiPolygon) else [])
    )
    for poly in polys:
        for interior in poly.interiors:
            hole_area, _ = polygon_area_m2([(y, x) for x, y in interior.coords])
            area_m2 -= hole_area

    if area_m2:
        result["area_m2"] = area_m2
        result["area_km2"] = area_m2 / 1e6
        result["area_hectares"] = area_m2 / 10_000.0
        result["perimeter_m"] = perimeter_m
    if isinstance(geom, LineString):
        from .geodesy import path_length_m

        result["length_m"] = path_length_m([(y, x) for x, y in geom.coords])
    return result


def hull(geom: BaseGeometry, *, kind: str = "convex", ratio: float = 0.3) -> BaseGeometry:
    """Convex or concave hull of a geometry.

    A concave hull traces the actual outline of a scattered point set -- a
    service territory, a wildfire perimeter, a delivery footprint -- where a
    convex hull would bridge across genuine gaps.

    ``ratio`` runs from 0 (tightest) to 1 (identical to the convex hull), and is
    steeply non-linear: measured on a noisy ring, ratio 0.0 yields 8% of the
    convex area while ratio 0.1 already yields 99%. Start at 0.0 and increase
    if the outline comes back too ragged.

    One limitation worth knowing: GEOS derives the hull from a Delaunay
    triangulation, so the ratio only takes effect where point *density* varies.
    A shape described purely by boundary points, with no interior samples,
    returns the convex hull at every ratio.
    """
    if kind == "convex":
        return geom.convex_hull
    if kind == "concave":
        if not 0.0 <= ratio <= 1.0:
            raise GeoInputError.with_example(
                got=ratio,
                problem="Concave-hull ratio must be between 0 and 1.",
                example="0.3  (fairly tight around the points)",
            )
        return concave_hull(geom, ratio=ratio)
    raise GeoInputError.with_example(
        got=kind,
        problem="Hull kind must be 'convex' or 'concave'.",
        example="convex",
    )


def simplify_geometry(geom: BaseGeometry, tolerance_m: float) -> BaseGeometry:
    """Douglas-Peucker simplification with the tolerance given in metres.

    Taking the tolerance in metres rather than degrees is the whole point: a
    degree tolerance means a different ground distance at every latitude.
    """
    if tolerance_m <= 0:
        return geom
    centroid = geom.centroid
    crs = aeqd_crs_for(centroid.y, centroid.x)
    reduced = simplify(project_to_metres(geom, crs), tolerance_m, preserve_topology=True)
    return project_to_wgs84(reduced, crs)


def repair(geom: BaseGeometry, *, grid_size: float | None = None) -> BaseGeometry:
    """Make an invalid geometry valid (self-intersections, unclosed rings)."""
    fixed = make_valid(geom)
    if grid_size:
        fixed = set_precision(fixed, grid_size)
    return fixed


def overlay(a: BaseGeometry, b: BaseGeometry, operation: str) -> BaseGeometry:
    """Apply a set operation between two geometries."""
    if operation not in OVERLAY_OPS:
        raise GeoInputError.with_example(
            got=operation,
            problem=f"Unknown overlay operation. Valid: {', '.join(OVERLAY_OPS)}.",
            example="intersection",
        )
    left = a if a.is_valid else make_valid(a)
    right = b if b.is_valid else make_valid(b)
    return getattr(left, operation)(right)
