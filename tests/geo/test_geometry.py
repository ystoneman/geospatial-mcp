"""Geometry operations must be correct on the ellipsoid, not in degree space."""

from __future__ import annotations

import math

import pytest
from shapely.geometry import LineString, Point, Polygon

from geospatial_mcp.errors import GeoInputError
from geospatial_mcp.geo.geodesy import distance_m
from geospatial_mcp.geo.geometry import (
    geodesic_buffer,
    geometry_from_geojson,
    hull,
    measure_geometry,
    overlay,
    simplify_geometry,
)


class TestGeodesicBuffer:
    @pytest.mark.parametrize("latitude", [0.0, 30.0, 48.86, 60.0, 78.0, -45.0])
    def test_buffer_radius_is_true_ground_distance_at_any_latitude(self, latitude):
        """The headline fix.

        Buffering in degrees produces an ellipse stretched by 1/cos(latitude):
        2x wrong at 60 degrees, 5x at 78. Projecting to an azimuthal
        equidistant plane makes the radius correct everywhere.
        """
        buffered = geodesic_buffer(Point(0.0, latitude), 10_000.0)
        radii = [distance_m(latitude, 0.0, y, x) for x, y in list(buffered.exterior.coords)[::4]]
        assert min(radii) == pytest.approx(10_000.0, abs=1.0)
        assert max(radii) == pytest.approx(10_000.0, abs=1.0)

    def test_disc_area_matches_pi_r_squared(self):
        area_km2 = measure_geometry(geodesic_buffer(Point(2.2945, 48.8584), 1000.0))["area_km2"]
        # A 32-segment polygon slightly under-covers the true circle.
        assert area_km2 == pytest.approx(math.pi, rel=0.002)

    def test_zero_distance_is_a_no_op(self):
        point = Point(2.2945, 48.8584)
        assert geodesic_buffer(point, 0.0) is point


class TestMeasurement:
    def test_area_is_geodesic_not_planar(self):
        """A one-degree box near the pole is genuinely smaller on the ground."""
        equator = measure_geometry(Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]))["area_km2"]
        polar = measure_geometry(Polygon([(0, 60), (1, 60), (1, 61), (0, 61)]))["area_km2"]
        assert equator == pytest.approx(12_308.8, abs=1.0)
        assert polar == pytest.approx(6_122.8, abs=1.0)
        assert polar < equator / 1.9

    def test_holes_are_subtracted(self):
        outer = [(0, 0), (1, 0), (1, 1), (0, 1)]
        hole = [(0.4, 0.4), (0.6, 0.4), (0.6, 0.6), (0.4, 0.6)]
        solid = measure_geometry(Polygon(outer))["area_m2"]
        with_hole = measure_geometry(Polygon(outer, [hole]))["area_m2"]
        assert with_hole < solid
        assert with_hole == pytest.approx(solid * 0.96, rel=0.02)

    def test_linestring_length(self):
        line = LineString([(0, 0), (0, 1)])
        assert measure_geometry(line)["length_m"] == pytest.approx(110_574.39, abs=1.0)


class TestSimplify:
    def test_tolerance_is_in_metres(self):
        line = LineString([(0, 0), (0.001, 0.0005), (0.002, 0), (0.003, 0.0005), (0.004, 0)])
        coarse = simplify_geometry(line, 500.0)
        assert len(coarse.coords) < len(line.coords)

    def test_zero_tolerance_is_a_no_op(self):
        line = LineString([(0, 0), (1, 1)])
        assert simplify_geometry(line, 0.0) is line


class TestHulls:
    def test_concave_hull_excludes_the_gap_between_clusters(self):
        """A convex hull bridges genuine emptiness; a concave hull does not.

        Two separated clusters of points -- two depots, two burn scars, two
        service pockets. The convex hull claims the empty ground between them.

        Note GEOS's ratio only bites where point density actually varies. For a
        shape defined purely by boundary points (a hollow ring drawn with no
        interior samples) the concave hull equals the convex hull at every
        ratio, which is why this test uses clustered samples.
        """
        import random

        from shapely.geometry import MultiPoint

        random.seed(7)
        left = [(random.gauss(0.0, 0.05), random.gauss(0.0, 0.05)) for _ in range(60)]
        right = [(random.gauss(2.0, 0.05), random.gauss(0.0, 0.05)) for _ in range(60)]
        points = MultiPoint(left + right)

        convex = measure_geometry(hull(points, kind="convex"))["area_m2"]
        tight = measure_geometry(hull(points, kind="concave", ratio=0.0))["area_m2"]
        assert tight < convex * 0.5, f"concave {tight:,.0f} vs convex {convex:,.0f}"

    def test_ratio_one_equals_the_convex_hull(self):
        import random

        from shapely.geometry import MultiPoint

        random.seed(11)
        points = MultiPoint([(random.uniform(0, 1), random.uniform(0, 1)) for _ in range(40)])
        assert measure_geometry(hull(points, kind="concave", ratio=1.0))[
            "area_m2"
        ] == pytest.approx(measure_geometry(hull(points, kind="convex"))["area_m2"], rel=1e-6)

    def test_bad_ratio_is_rejected(self):
        with pytest.raises(GeoInputError):
            hull(Point(0, 0).buffer(1), kind="concave", ratio=5.0)

    def test_unknown_kind_is_rejected(self):
        with pytest.raises(GeoInputError, match="convex"):
            hull(Point(0, 0), kind="banana")


class TestOverlay:
    def test_intersection_of_disjoint_shapes_is_empty(self):
        a = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        b = Polygon([(5, 5), (6, 5), (6, 6), (5, 6)])
        assert overlay(a, b, "intersection").is_empty

    def test_union_area_is_at_least_each_input(self):
        a = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        b = Polygon([(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)])
        union = measure_geometry(overlay(a, b, "union"))["area_m2"]
        assert union >= measure_geometry(a)["area_m2"]
        assert union >= measure_geometry(b)["area_m2"]

    def test_invalid_input_is_repaired_rather_than_rejected(self):
        """Self-intersecting polygons are common in real customer data."""
        bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
        assert not bowtie.is_valid
        square = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        assert not overlay(bowtie, square, "intersection").is_empty

    def test_unknown_operation_names_the_valid_ones(self):
        square = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        with pytest.raises(GeoInputError, match="intersection"):
            overlay(square, square, "merge")


class TestParsing:
    def test_accepts_geojson_feature_and_collection(self):
        point = '{"type":"Point","coordinates":[2.29,48.86]}'
        feature = f'{{"type":"Feature","geometry":{point},"properties":{{}}}}'
        collection = f'{{"type":"FeatureCollection","features":[{feature}]}}'
        for text in (point, feature, collection):
            assert not geometry_from_geojson(text).is_empty

    def test_accepts_wkt(self):
        assert geometry_from_geojson("POINT (2.29 48.86)").geom_type == "Point"

    def test_rejects_nonsense_with_an_example(self):
        with pytest.raises(GeoInputError) as exc:
            geometry_from_geojson("banana")
        assert "POINT" in str(exc.value)
