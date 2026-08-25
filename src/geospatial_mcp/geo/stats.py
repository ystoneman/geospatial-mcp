"""Spatial clustering and density, computed on the sphere.

The mistake this module exists to avoid: running DBSCAN or a kernel density
estimate on raw latitude/longitude treats a degree of longitude as equal to a
degree of latitude. At 55 degrees north a degree of longitude is 57 km and a
degree of latitude is 111 km, so a "500 m" cluster radius is really an ellipse
twice as wide as it is tall. Clusters come out stretched east-west, and the
error grows toward the poles.

Every function here uses the haversine metric on radians, which scikit-learn
supports natively, so distances are true ground distances everywhere.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ..errors import GeoUnavailable

__all__ = ["EARTH_RADIUS_M", "Cluster", "cluster_points", "kernel_density"]

#: Mean Earth radius, metres. Used to convert ground distances to radians.
EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True)
class Cluster:
    """One cluster of points."""

    label: int
    size: int
    centroid_latitude: float
    centroid_longitude: float
    radius_m: float
    member_indices: list[int]


def _require_sklearn():
    try:
        import sklearn
    except ImportError:
        raise GeoUnavailable("Spatial clustering", "stats") from None
    return sklearn


def cluster_points(
    points: Sequence[tuple[float, float]],
    *,
    eps_m: float = 500.0,
    min_samples: int = 3,
    algorithm: str = "dbscan",
) -> tuple[list[Cluster], list[int]]:
    """Cluster geographic points by ground distance.

    Returns ``(clusters, noise_indices)``. DBSCAN labels points that belong to
    no cluster as noise rather than forcing them into one, which is the right
    behaviour for incident data, delivery failures or sensor readings where
    isolated points are meaningful.

    ``eps_m`` is a true ground distance in metres, converted to radians for the
    haversine metric.

    HDBSCAN varies the neighbourhood size per region, so it handles clusters of
    differing density -- dense city incidents alongside sparse rural ones --
    where plain DBSCAN needs one eps to suit both.
    """
    _require_sklearn()
    from sklearn.cluster import DBSCAN, HDBSCAN

    if not points:
        return [], []
    radians = np.radians(np.asarray(points, dtype=float))

    if algorithm == "dbscan":
        model = DBSCAN(eps=eps_m / EARTH_RADIUS_M, min_samples=min_samples, metric="haversine")
    elif algorithm == "hdbscan":
        model = HDBSCAN(min_cluster_size=max(2, min_samples), metric="haversine")
    else:
        from ..errors import GeoInputError

        raise GeoInputError.with_example(
            got=algorithm,
            problem="Unknown clustering algorithm. Valid: dbscan, hdbscan.",
            example="dbscan",
        )

    labels = model.fit_predict(radians)
    from .geodesy import distance_m

    clusters: list[Cluster] = []
    for label in sorted({int(v) for v in labels if v >= 0}):
        members = [i for i, v in enumerate(labels) if int(v) == label]
        lats = [points[i][0] for i in members]
        lons = [points[i][1] for i in members]
        centroid_lat = float(np.mean(lats))
        centroid_lon = float(np.mean(lons))
        radius = max(
            distance_m(centroid_lat, centroid_lon, points[i][0], points[i][1]) for i in members
        )
        clusters.append(
            Cluster(
                label=label,
                size=len(members),
                centroid_latitude=centroid_lat,
                centroid_longitude=centroid_lon,
                radius_m=radius,
                member_indices=members,
            )
        )
    noise = [i for i, v in enumerate(labels) if int(v) < 0]
    return clusters, noise


def kernel_density(
    points: Sequence[tuple[float, float]],
    grid: Sequence[tuple[float, float]],
    *,
    bandwidth_m: float = 1000.0,
) -> list[float]:
    """Kernel density estimate at each grid location, in points per km2.

    Uses the haversine metric so the bandwidth is a true ground distance.
    """
    _require_sklearn()
    from sklearn.neighbors import KernelDensity

    if not points or not grid:
        return [0.0] * len(grid)
    model = KernelDensity(
        bandwidth=bandwidth_m / EARTH_RADIUS_M, metric="haversine", kernel="gaussian"
    )
    model.fit(np.radians(np.asarray(points, dtype=float)))
    log_density = model.score_samples(np.radians(np.asarray(grid, dtype=float)))
    # score_samples returns log density per steradian; convert to per km2.
    per_km2 = np.exp(log_density) * len(points) / ((EARTH_RADIUS_M / 1000.0) ** 2)
    return [float(v) for v in per_km2]
