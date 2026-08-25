"""The OpenCelliD bounding box must be geodesically correct.

Computing this box by dividing metres by a fixed 111_320.0 degrees-per-metre
constant is accurate enough at the clamped radius -- about 3.4 m out at the
equator and 1.6 m at 78 degrees, on a 500 m half-side. It is still wrong to do,
because every other distance in the package is computed on the ellipsoid, and a
lone exception is how the inaccurate form spreads back into places where the
error does matter.
"""

from __future__ import annotations

import math

import pytest

from geospatial_mcp.geo.geodesy import distance_m
from geospatial_mcp.net.providers.cells import RADIO_GENERATION, _bbox_around, _normalise


class TestBoundingBox:
    @pytest.mark.parametrize("lat", [0.0, 23.5, 45.0, 60.0, 78.0, -33.87])
    @pytest.mark.parametrize("half_m", [100.0, 500.0, 1000.0])
    def test_edges_are_the_requested_ground_distance(self, lat, half_m):
        """Each edge must sit exactly half_m from the centre, at every latitude."""
        lon = 12.0
        south, west, north, east = _bbox_around(lat, lon, half_m)

        assert distance_m(lat, lon, north, lon) == pytest.approx(half_m, abs=0.05)
        assert distance_m(lat, lon, south, lon) == pytest.approx(half_m, abs=0.05)
        assert distance_m(lat, lon, lat, east) == pytest.approx(half_m, abs=0.05)
        assert distance_m(lat, lon, lat, west) == pytest.approx(half_m, abs=0.05)

    def test_box_is_ordered_south_west_north_east(self):
        south, west, north, east = _bbox_around(48.8584, 2.2945, 500.0)
        assert south < north
        assert west < east

    def test_it_beats_the_flat_earth_approximation_it_replaced(self):
        """Pin the improvement rather than asserting it in a comment."""
        lat, lon, half = 78.0, 15.0, 500.0
        *_, east = _bbox_around(lat, lon, half)
        geodesic_error = abs(distance_m(lat, lon, lat, east) - half)

        flat_delta_lon = half / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
        flat_error = abs(distance_m(lat, lon, lat, lon + flat_delta_lon) - half)

        assert geodesic_error < 0.1
        assert flat_error > geodesic_error

    def test_stays_inside_the_opencellid_area_cap(self):
        """OpenCelliD rejects a query covering more than 4 km2."""
        half = math.sqrt(4_000_000.0) / 2.0
        for lat in (0.0, 45.0, 78.0):
            south, west, north, east = _bbox_around(lat, 0.0, half)
            height_m = distance_m(south, 0.0, north, 0.0)
            width_m = distance_m(lat, west, lat, east)
            assert (height_m * width_m) <= 4_000_000.0 * 1.001


class TestNormalise:
    def test_maps_radio_technology_to_the_generation_people_say(self):
        for radio, generation in RADIO_GENERATION.items():
            entry = _normalise({"radio": radio, "lat": 48.86, "lon": 2.29}, 48.86, 2.29)
            assert entry["generation"] == generation

    def test_unknown_radio_type_is_reported_as_none_not_guessed(self):
        entry = _normalise({"radio": "6G", "lat": 48.86, "lon": 2.29}, 48.86, 2.29)
        assert entry["radio"] == "6G"
        assert entry["generation"] is None

    def test_distance_is_measured_from_the_search_centre(self):
        entry = _normalise({"radio": "LTE", "lat": 48.8684, "lon": 2.2945}, 48.8584, 2.2945)
        assert entry["distance_m"] == pytest.approx(1112.0, abs=5.0)

    def test_a_record_without_a_position_omits_the_distance(self):
        entry = _normalise({"radio": "LTE", "mcc": 208}, 48.8584, 2.2945)
        assert "distance_m" not in entry
        assert entry["mcc"] == 208
