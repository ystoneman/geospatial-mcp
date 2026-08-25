"""Time zone lookup from coordinates. Fully offline.

Uses ``tzfpy`` rather than the more familiar ``timezonefinder``: as of 2026
timezonefinder publishes Linux x86-64 wheels only, so it fails to install on
macOS, Windows and ARM64 -- which is most developer machines. ``tzfpy`` ships
broad wheel coverage and is faster.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import tzfpy

__all__ = ["local_time_info", "timezone_at"]


def timezone_at(lat: float, lon: float) -> str | None:
    """IANA time-zone name for a position, or ``None`` over open ocean."""
    return tzfpy.get_tz(lon, lat)


def local_time_info(lat: float, lon: float, when: datetime | None = None) -> dict[str, Any]:
    """Local time, UTC offset, DST state and the next DST transition."""
    name = timezone_at(lat, lon)
    if name is None:
        return {
            "timezone": None,
            "note": (
                "No time zone is defined at this position -- it is over international "
                "waters. Vessels there conventionally use UTC or a nautical time zone "
                "based on longitude."
            ),
            "nautical_utc_offset_hours": round(lon / 15.0),
        }
    zone = ZoneInfo(name)
    moment = (when or datetime.now(UTC)).astimezone(zone)
    offset = moment.utcoffset()
    dst = moment.dst()
    info: dict[str, Any] = {
        "timezone": name,
        "local_time": moment.isoformat(),
        "utc_offset_hours": (offset.total_seconds() / 3600.0) if offset else 0.0,
        "abbreviation": moment.tzname(),
        "is_dst": bool(dst and dst.total_seconds() != 0),
    }
    info["next_transition"] = _next_transition(moment, zone)
    return info


def _next_transition(start: datetime, zone: ZoneInfo) -> str | None:
    """Find the next UTC-offset change within a year, by daily then hourly scan."""
    from datetime import timedelta

    baseline = start.utcoffset()
    cursor = start
    for _ in range(370):
        cursor += timedelta(days=1)
        if cursor.astimezone(zone).utcoffset() != baseline:
            probe = cursor - timedelta(days=1)
            for _ in range(25):
                probe += timedelta(hours=1)
                if probe.astimezone(zone).utcoffset() != baseline:
                    return probe.astimezone(zone).isoformat()
            return cursor.astimezone(zone).isoformat()
    return None
