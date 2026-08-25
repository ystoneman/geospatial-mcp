"""Spatial clustering must measure ground distance, not degrees."""

from __future__ import annotations

import pytest

pytest.importorskip("sklearn", reason="the stats extra is not installed")

from geospatial_mcp.geo.stats import cluster_points, kernel_density


class TestClustering:
    def test_two_separated_groups_are_found(self):
        points = [(48.8584 + i * 0.0001, 2.2945 + i * 0.0001) for i in range(10)] + [
            (51.5007 + i * 0.0001, -0.1246 + i * 0.0001) for i in range(10)
        ]
        clusters, noise = cluster_points(points, eps_m=500, min_samples=3)
        assert len(clusters) == 2
        assert not noise
        assert {c.size for c in clusters} == {10}

    def test_isolated_points_are_noise_not_forced_into_a_cluster(self):
        points = [(48.8584 + i * 0.0001, 2.2945) for i in range(6)] + [(0.0, 0.0)]
        clusters, noise = cluster_points(points, eps_m=200, min_samples=3)
        assert len(clusters) == 1
        assert noise == [6]

    def test_eps_is_ground_metres_not_degrees(self):
        """The bug this guards.

        Two points 600 m apart east-west at 60 degrees north are only 0.0108
        degrees apart in longitude, but 600 m on the ground. A clustering run
        that treats eps as degrees would merge them at eps=500; measuring on
        the sphere correctly keeps them apart.
        """
        far_apart = [(60.0, 0.0), (60.0, 0.0108), (60.0, 0.0216)]
        clusters, _ = cluster_points(far_apart, eps_m=500, min_samples=2)
        assert not clusters, "600 m apart must not cluster at a 500 m radius"

        clusters, _ = cluster_points(far_apart, eps_m=700, min_samples=2)
        assert len(clusters) == 1, "600 m apart must cluster at a 700 m radius"

    def test_cluster_radius_is_a_real_distance(self):
        points = [(48.8584, 2.2945), (48.8584, 2.2955), (48.8584, 2.2965)]
        clusters, _ = cluster_points(points, eps_m=200, min_samples=2)
        assert clusters
        assert 30.0 < clusters[0].radius_m < 120.0

    def test_empty_input(self):
        assert cluster_points([]) == ([], [])

    def test_unknown_algorithm_is_rejected(self):
        from geospatial_mcp.errors import GeoInputError

        with pytest.raises(GeoInputError, match="dbscan"):
            cluster_points([(0.0, 0.0), (0.1, 0.1)], algorithm="kmeans")


class TestDensity:
    def test_density_is_higher_where_points_are(self):
        points = [(48.8584 + i * 0.0005, 2.2945) for i in range(20)]
        near, far = kernel_density(points, [(48.8590, 2.2945), (49.5, 3.5)], bandwidth_m=500)
        assert near > far

    def test_empty_inputs_are_safe(self):
        assert kernel_density([], [(0.0, 0.0)]) == [0.0]
        assert kernel_density([(0.0, 0.0)], []) == []
