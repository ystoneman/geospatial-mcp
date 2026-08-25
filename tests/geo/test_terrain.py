"""Terrain analysis: slope, aspect, hillshade and DEM gaps."""

from __future__ import annotations

import numpy as np
import pytest

from geospatial_mcp.geo.terrain import hillshade, slope_aspect, terrain_statistics


class TestSlopeAspect:
    def test_45_degree_ramp(self):
        dem = np.tile(np.arange(5, dtype=float) * 10.0, (5, 1))
        slope, aspect = slope_aspect(dem, cell_size_m=10.0)
        assert slope[2, 2] == pytest.approx(45.0, abs=1e-6)
        assert aspect[2, 2] == pytest.approx(270.0, abs=1e-6)

    def test_flat_ground_has_no_slope_and_no_aspect(self):
        slope, aspect = slope_aspect(np.zeros((5, 5)), cell_size_m=10.0)
        assert np.allclose(slope, 0.0)
        assert np.all(aspect == -1.0), "flat cells must not claim a direction"

    def test_steeper_cells_give_steeper_slope(self):
        gentle = slope_aspect(np.tile(np.arange(5, dtype=float), (5, 1)), 10.0)[0][2, 2]
        steep = slope_aspect(np.tile(np.arange(5, dtype=float) * 5, (5, 1)), 10.0)[0][2, 2]
        assert steep > gentle

    def test_rejects_tiny_arrays(self):
        with pytest.raises(ValueError):
            slope_aspect(np.zeros((2, 2)), 10.0)


class TestHillshade:
    def test_output_is_in_byte_range(self):
        dem = np.tile(np.arange(10, dtype=float) * 3.0, (10, 1))
        shaded = hillshade(dem, cell_size_m=10.0)
        assert shaded.min() >= 0.0 and shaded.max() <= 255.0


class TestStatistics:
    def test_ascent_and_descent_are_separated(self):
        stats = terrain_statistics([0.0, 10.0, 5.0, 20.0])
        assert stats["total_ascent_m"] == pytest.approx(25.0)
        assert stats["total_descent_m"] == pytest.approx(5.0)
        assert stats["net_change_m"] == pytest.approx(20.0)
        assert stats["relief_m"] == pytest.approx(20.0)

    def test_gaps_are_counted_and_excluded(self):
        stats = terrain_statistics([0.0, None, 10.0, None])
        assert stats["gaps"] == 2
        assert stats["samples"] == 2

    def test_all_gaps_degrades_gracefully(self):
        assert terrain_statistics([None, None]) == {"samples": 0, "gaps": 2}
