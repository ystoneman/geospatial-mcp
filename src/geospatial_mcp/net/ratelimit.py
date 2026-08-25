"""Per-host token-bucket rate limiting.

Provider policies this enforces:

* **Nominatim** -- an absolute maximum of 1 request/second, and a descriptive
  User-Agent. Violating either gets an IP blocked.
* **Valhalla (FOSSGIS)** -- 1 request/second.
* **OpenTopoData** -- 1 request/second, 1000 calls/day.
* **Overpass** -- effectively one concurrent query; slots are queued.
* **CelesTrak** -- one download per orbital-element update. Since March 2026 it
  firewalls IPs that generate 50 HTTP errors in two hours, so the orbit
  provider additionally caches to disk with a 2-hour TTL and checks the file
  mtime before ever issuing a request.

Thread-safe: tools run synchronously on the SDK's worker threads, so several
can contend for the same bucket at once.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

__all__ = ["HOST_LIMITS", "RateLimiter", "TokenBucket", "limiter"]

#: Requests per second permitted per host. Absent hosts are unthrottled.
HOST_LIMITS: dict[str, float] = {
    "nominatim.openstreetmap.org": 1.0,
    "photon.komoot.io": 1.0,
    "overpass-api.de": 0.5,
    "valhalla1.openstreetmap.de": 1.0,
    "api.opentopodata.org": 1.0,
    "router.project-osrm.org": 1.0,
    "celestrak.org": 0.1,
    "api.open-meteo.com": 5.0,
    "archive-api.open-meteo.com": 5.0,
    "air-quality-api.open-meteo.com": 5.0,
}

#: Applied to any host without an explicit entry.
DEFAULT_RATE = 10.0


@dataclass
class TokenBucket:
    """A simple token bucket refilled continuously at ``rate`` tokens/second."""

    rate: float
    capacity: float = 1.0
    _tokens: float = field(default=1.0, init=False)
    _last: float = field(default_factory=time.monotonic, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def acquire(self, *, now: float | None = None, sleep: bool = True) -> float:
        """Take one token, waiting if necessary. Returns the seconds waited."""
        with self._lock:
            current = time.monotonic() if now is None else now
            elapsed = max(0.0, current - self._last)
            self._last = current
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0
            wait = (1.0 - self._tokens) / self.rate
            self._tokens = 0.0
            self._last = current + wait
        if sleep:
            time.sleep(wait)
        return wait


class RateLimiter:
    """Holds one :class:`TokenBucket` per host."""

    def __init__(self, limits: dict[str, float] | None = None) -> None:
        self._limits = dict(HOST_LIMITS if limits is None else limits)
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def bucket_for(self, host: str) -> TokenBucket:
        with self._lock:
            bucket = self._buckets.get(host)
            if bucket is None:
                bucket = TokenBucket(rate=self._limits.get(host, DEFAULT_RATE))
                self._buckets[host] = bucket
            return bucket

    def acquire(self, host: str, *, sleep: bool = True) -> float:
        """Block until a request to ``host`` is permitted."""
        return self.bucket_for(host).acquire(sleep=sleep)


#: Process-wide limiter.
limiter = RateLimiter()
