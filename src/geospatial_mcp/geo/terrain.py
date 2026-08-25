"""Terrain analysis: elevation statistics, slope, aspect and hillshade.

Slope and aspect follow Horn's 3x3 method rather than a simple second-order
difference, because that is what ArcGIS and GDAL both compute and what anyone
cross-checking a result will be comparing against.

Elevation gaps are carried through as ``None``. Substituting sea level for
missing data turns "we do not know" into a confident wrong answer, and the
downstream statistics have no way to tell the difference.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = [
    "hillshade",
    "slope_aspect",
    "terrain_statistics",
]


def terrain_statistics(elevations: list[float | None]) -> dict[str, float | int]:
    """Summary statistics for an elevation profile, ignoring gaps."""
    values = [e for e in elevations if e is not None]
    if not values:
        return {"samples": 0, "gaps": len(elevations)}
    array = np.asarray(values, dtype=float)
    gain = float(np.sum(np.clip(np.diff(array), 0, None)))
    loss = float(-np.sum(np.clip(np.diff(array), None, 0)))
    return {
        "samples": len(values),
        "gaps": len(elevations) - len(values),
        "min_m": float(array.min()),
        "max_m": float(array.max()),
        "mean_m": float(array.mean()),
        "relief_m": float(array.max() - array.min()),
        "net_change_m": float(array[-1] - array[0]),
        "total_ascent_m": gain,
        "total_descent_m": loss,
    }


def slope_aspect(dem: np.ndarray, cell_size_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Slope (degrees) and aspect (degrees from north) by Horn's method.

    Horn's 3x3 kernel is the method ArcGIS and GDAL both use, and is more
    robust on noisy DEMs than a simple second-order difference. Edge cells are
    computed against replicated borders.
    """
    if dem.ndim != 2 or min(dem.shape) < 3:
        raise ValueError("DEM must be a 2-D array at least 3x3")
    padded = np.pad(dem.astype(float), 1, mode="edge")
    a, b, c = padded[:-2, :-2], padded[:-2, 1:-1], padded[:-2, 2:]
    d, _, f = padded[1:-1, :-2], padded[1:-1, 1:-1], padded[1:-1, 2:]
    g, h, i = padded[2:, :-2], padded[2:, 1:-1], padded[2:, 2:]

    dz_dx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8.0 * cell_size_m)
    dz_dy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8.0 * cell_size_m)

    slope = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))
    aspect = np.degrees(np.arctan2(dz_dy, -dz_dx))
    aspect = np.where(
        aspect < 0, 90.0 - aspect, np.where(aspect > 90.0, 450.0 - aspect, 90.0 - aspect)
    )
    aspect = np.where(slope < 1e-9, -1.0, aspect % 360.0)  # flat cells have no aspect
    return slope, aspect


def hillshade(
    dem: np.ndarray,
    cell_size_m: float,
    *,
    azimuth_deg: float = 315.0,
    altitude_deg: float = 45.0,
    z_factor: float = 1.0,
) -> np.ndarray:
    """Shaded-relief array in 0-255 for a DEM.

    The 315-degree default (light from the north-west) is conventional because
    human perception reads terrain lit from that direction as convex rather
    than inverted.
    """
    slope, aspect = slope_aspect(dem * z_factor, cell_size_m)
    zenith = math.radians(90.0 - altitude_deg)
    azimuth = math.radians(360.0 - azimuth_deg + 90.0)
    slope_rad = np.radians(slope)
    aspect_rad = np.radians(np.where(aspect < 0, 0.0, aspect))
    shaded = math.cos(zenith) * np.cos(slope_rad) + math.sin(zenith) * np.sin(slope_rad) * np.cos(
        azimuth - aspect_rad
    )
    return np.clip(shaded * 255.0, 0, 255)
