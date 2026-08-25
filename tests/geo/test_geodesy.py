"""Geodesy golden vectors.

Values are cross-checked against pygeodesy's independent pure-Python
implementation of Karney's exact geodesic, and against published reference
figures for the length of a degree.
"""

from __future__ import annotations

import itertools
import math

import pytest

from geospatial_mcp.geo import geodesy


class TestReferenceDistances:
    """Published WGS84 figures, to the centimetre."""

    @pytest.mark.parametrize(
        ("lat1", "lon1", "lat2", "lon2", "expected_m", "label"),
        [
            (0.0, 0.0, 0.0, 1.0, 111_319.49, "one degree of longitude at the equator"),
            (0.0, 0.0, 1.0, 0.0, 110_574.39, "one degree of latitude at the equator"),
            (89.0, 0.0, 90.0, 0.0, 111_693.86, "one degree of latitude at the pole"),
        ],
    )
    def test_degree_lengths(self, lat1, lon1, lat2, lon2, expected_m, label):
        assert geodesy.distance_m(lat1, lon1, lat2, lon2) == pytest.approx(expected_m, abs=0.02), (
            label
        )

    def test_flat_earth_approximation_is_materially_wrong(self):
        """Pin the error the old 111.32 km/deg approximation introduced.

        At 60 degrees north the approximation is out by about 140 m per degree
        of longitude -- 0.25%. Smooth, plausible, and wrong.
        """
        actual = geodesy.distance_m(60.0, 0.0, 60.0, 1.0)
        flat_earth = 111_320.0 * math.cos(math.radians(60.0))
        assert actual == pytest.approx(55_799.47, abs=0.05)
        assert abs(actual - flat_earth) > 130.0

    def test_near_antipodal_converges(self):
        """Vincenty's method fails to converge here; Karney's does not."""
        distance = geodesy.distance_m(0.0, 0.0, 0.5, 179.5)
        assert math.isfinite(distance)
        assert distance == pytest.approx(19_936_288.579, abs=0.01)


class TestBearings:
    def test_bearing_is_normalised_to_compass_range(self):
        for lat, lon in [(51.5, -0.12), (-33.87, 151.21), (0.0, 0.0)]:
            bearing = geodesy.bearing_deg(48.8584, 2.2945, lat, lon)
            assert 0.0 <= bearing < 360.0

    def test_due_north_and_south(self):
        assert geodesy.bearing_deg(0.0, 0.0, 10.0, 0.0) == pytest.approx(0.0, abs=1e-9)
        assert geodesy.bearing_deg(10.0, 0.0, 0.0, 0.0) == pytest.approx(180.0, abs=1e-9)

    @pytest.mark.parametrize(
        ("bearing", "expected"),
        [(0, "N"), (45, "NE"), (90, "E"), (180, "S"), (270, "W"), (359, "N"), (330.47, "NNW")],
    )
    def test_compass_points(self, bearing, expected):
        assert geodesy.compass_point(bearing) == expected


class TestRoundTrips:
    def test_destination_inverts_inverse(self):
        """Solving forward then backward must return the start point."""
        start = (48.8584, 2.2945)
        end = (51.5007, -0.1246)
        forward, _, distance = geodesy.inverse(*start, *end)
        recovered = geodesy.destination(*start, forward, distance)
        assert recovered[0] == pytest.approx(end[0], abs=1e-9)
        assert recovered[1] == pytest.approx(end[1], abs=1e-9)

    def test_midpoint_is_equidistant(self):
        start, end = (48.8584, 2.2945), (51.5007, -0.1246)
        mid = geodesy.midpoint(*start, *end)
        assert geodesy.distance_m(*start, *mid) == pytest.approx(
            geodesy.distance_m(*mid, *end), rel=1e-9
        )


class TestDensify:
    def test_endpoints_are_exact_and_spacing_even(self):
        points = geodesy.densify(48.8584, 2.2945, 51.5007, -0.1246, 11)
        assert len(points) == 11
        assert (points[0][0], points[0][1]) == (48.8584, 2.2945)
        assert (points[-1][0], points[-1][1]) == pytest.approx((51.5007, -0.1246))
        gaps = [b[2] - a[2] for a, b in itertools.pairwise(points)]
        assert max(gaps) == pytest.approx(min(gaps), rel=1e-9)

    def test_samples_lie_on_the_geodesic_not_a_degree_line(self):
        """Sampling must follow the ellipsoid, not a straight line in degrees.

        On a long east-west path the true geodesic bows poleward, so linear
        interpolation of latitude and longitude is measurably off the real path.
        """
        lat1, lon1, lat2, lon2 = 55.0, -10.0, 55.0, 40.0
        points = geodesy.densify(lat1, lon1, lat2, lon2, 11)
        middle = points[5]
        linear_lat = (lat1 + lat2) / 2.0
        assert middle[0] > linear_lat + 0.5  # the geodesic bows north

    def test_rejects_too_few_points(self):
        with pytest.raises(ValueError):
            geodesy.densify(0.0, 0.0, 1.0, 1.0, 1)


class TestArea:
    def test_area_shrinks_with_latitude(self):
        """A one-degree box is much smaller near the pole than at the equator."""
        equator, _ = geodesy.polygon_area_m2([(0, 0), (0, 1), (1, 1), (1, 0)])
        high, _ = geodesy.polygon_area_m2([(60, 0), (60, 1), (61, 1), (61, 0)])
        assert equator / 1e6 == pytest.approx(12_308.8, abs=1.0)
        assert high / 1e6 == pytest.approx(6_122.8, abs=1.0)

    def test_degenerate_ring_is_zero(self):
        assert geodesy.polygon_area_m2([(0, 0), (0, 1)]) == (0.0, 0.0)
