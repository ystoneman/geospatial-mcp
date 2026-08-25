"""Sun and moon position, twilight windows and shadow geometry.

Fully offline. Useful well beyond photography: solar-panel siting and yield
estimation, construction shadow studies and right-to-light assessments, crop
modelling, retail footfall by daylight hours, delivery-window planning around
dusk, film and TV scheduling, and any survey or inspection that needs a
predictable light window.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Any

from astral import LocationInfo, moon
from astral.sun import azimuth, elevation, sun

from ..errors import GeoInputError

__all__ = ["moon_info", "shadow_length_ratio", "sun_position", "sun_times"]


def _observer(lat: float, lon: float) -> LocationInfo:
    return LocationInfo(latitude=lat, longitude=lon)


def sun_times(lat: float, lon: float, on: date, tz: str = "UTC") -> dict[str, Any]:
    """Sunrise, sunset, twilight and golden/blue hour for a date.

    In polar regions the sun may not rise or set at all; those events come back
    as ``None`` with an explanation rather than raising, because "the sun does
    not set here today" is a correct and useful answer.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise GeoInputError.with_example(
            got=tz,
            problem=f"Unknown IANA time zone ({exc}).",
            example="Europe/Paris",
        ) from exc

    observer = _observer(lat, lon).observer
    result: dict[str, Any] = {"date": on.isoformat(), "timezone": tz, "notes": []}

    def when(name: str, depression: float) -> None:
        """Record a solar event, tolerating polar absence."""
        from astral.sun import dawn, dusk

        try:
            if name.startswith("dawn"):
                moment = dawn(observer, on, depression=depression, tzinfo=zone)
            else:
                moment = dusk(observer, on, depression=depression, tzinfo=zone)
            result[name] = moment.isoformat()
        except ValueError:
            result[name] = None

    try:
        events = sun(observer, date=on, tzinfo=zone)
        for key in ("dawn", "sunrise", "noon", "sunset", "dusk"):
            result[key] = events[key].isoformat()
        result["daylight_hours"] = round(
            (events["sunset"] - events["sunrise"]).total_seconds() / 3600.0, 3
        )
    except ValueError as exc:
        for key in ("dawn", "sunrise", "sunset", "dusk"):
            result[key] = None
        result["daylight_hours"] = None
        result["notes"].append(
            f"The sun neither rises nor sets normally at this latitude on this date ({exc}). "
            "This is expected inside the polar circles."
        )

    when("nautical_dawn", 12.0)
    when("nautical_dusk", 12.0)
    when("astronomical_dawn", 18.0)
    when("astronomical_dusk", 18.0)

    # Golden hour: sun between -4 and +6 degrees. Blue hour: -6 to -4.
    try:
        from astral import SunDirection
        from astral.sun import blue_hour, golden_hour

        gh_start, gh_end = golden_hour(observer, on, SunDirection.SETTING, tzinfo=zone)
        result["golden_hour_evening"] = [gh_start.isoformat(), gh_end.isoformat()]
        bh_start, bh_end = blue_hour(observer, on, SunDirection.SETTING, tzinfo=zone)
        result["blue_hour_evening"] = [bh_start.isoformat(), bh_end.isoformat()]
        gh2_start, gh2_end = golden_hour(observer, on, SunDirection.RISING, tzinfo=zone)
        result["golden_hour_morning"] = [gh2_start.isoformat(), gh2_end.isoformat()]
    except (ValueError, ImportError):
        result["golden_hour_evening"] = None
        result["blue_hour_evening"] = None
        result["golden_hour_morning"] = None
    return result


def sun_position(lat: float, lon: float, when: datetime) -> dict[str, float]:
    """Solar azimuth and elevation at an instant.

    Naive datetimes are treated as UTC rather than local, because guessing a
    zone from coordinates silently changes the answer by hours.
    """
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    observer = _observer(lat, lon).observer
    elev = elevation(observer, when)
    return {
        "azimuth_deg": round(azimuth(observer, when), 4),
        "elevation_deg": round(elev, 4),
        "is_daylight": elev > 0.0,
        "shadow_length_ratio": shadow_length_ratio(elev),
    }


def shadow_length_ratio(sun_elevation_deg: float) -> float:
    """Shadow length as a multiple of object height.

    ``cot(elevation)``. A 10 m mast at 30 degrees solar elevation casts a
    17.3 m shadow. Returns ``inf`` at or below the horizon.
    """
    if sun_elevation_deg <= 0.0:
        return math.inf
    return round(1.0 / math.tan(math.radians(sun_elevation_deg)), 4)


def moon_info(on: date) -> dict[str, Any]:
    """Moon phase for a date.

    ``astral`` reports phase on a 0-27.99 scale: 0 new, 7 first quarter,
    14 full, 21 last quarter.
    """
    phase = moon.phase(on)
    if phase < 1 or phase >= 27:
        name = "New moon"
    elif phase < 6.5:
        name = "Waxing crescent"
    elif phase < 8.5:
        name = "First quarter"
    elif phase < 13.5:
        name = "Waxing gibbous"
    elif phase < 15.5:
        name = "Full moon"
    elif phase < 20.5:
        name = "Waning gibbous"
    elif phase < 22.5:
        name = "Last quarter"
    else:
        name = "Waning crescent"
    return {
        "date": on.isoformat(),
        "phase_value": round(float(phase), 3),
        "phase_name": name,
        "illumination_pct": round(50.0 * (1.0 - math.cos(2.0 * math.pi * phase / 28.0)), 1),
    }
