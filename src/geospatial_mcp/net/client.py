"""The single HTTP client every provider goes through.

Responsibilities, in order of importance:

1. **A descriptive User-Agent on every request.** Nominatim's policy states
   that stock library User-Agents "will not do". Setting it here, once, is the
   only way to guarantee every call site sends the same identifying string --
   scattered HTTP calls drift toward whatever default their library ships.
2. **Rate limiting** per host, before the request leaves.
3. **Caching** to disk, checked before the request and populated after.
4. **Retries** with exponential backoff and full jitter, on 429 and 5xx only,
   honouring ``Retry-After``.
5. **Turning failures into the right exception type**, so a rate limit reads
   differently from a malformed query and the model can act accordingly.
"""

from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import httpx2 as httpx

from ..config import Settings
from ..config import settings as global_settings
from ..errors import GeoRateLimited, GeoUpstreamError
from .cache import ResponseCache
from .ratelimit import RateLimiter
from .ratelimit import limiter as global_limiter

__all__ = ["HttpClient", "get_client", "reset_client"]

logger = logging.getLogger("geospatial_mcp.net")

#: A forged closing tag in an upstream body would otherwise break out of the
#: quoted block; see :func:`_quoted_upstream`.
_CLOSING_DELIMITER = re.compile(r"</\s*upstream-response\s*>", re.IGNORECASE)


def _quoted_upstream(raw: bytes | str, settings: Settings, limit: int = 200) -> str:
    """Render an upstream response body for inclusion in an error message.

    Two things happen to it first, because this string ends up in the model's
    context and it came off a community-run mirror we do not control.

    Any configured API key is redacted. Several providers echo the request --
    query string included -- back in their error body, so a key set by the
    operator can arrive here and be handed to the model, and from there to
    wherever the transcript goes.

    The fragment is then labelled and delimited. A mirror that returns an HTML
    error page, or text chosen by whoever operates it, is data rather than
    instruction, and the model should be able to see where it starts and stops.

    Note the closing delimiter is neutralised inside the body. ``repr`` escapes
    quotes and backslashes but not angle brackets, so without this a mirror
    could emit its own ``</upstream-response>`` and make everything after it
    read as though it had left the quoted block.
    """
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    for secret in (
        settings.openrouteservice_key,
        settings.opencellid_key,
        settings.open_meteo_key,
        settings.firms_map_key,
    ):
        if secret:
            text = text.replace(secret, "***redacted***")
    text = text[:limit]
    text = _CLOSING_DELIMITER.sub("<\\/upstream-response>", text)
    return f"<upstream-response untrusted>{text!r}</upstream-response>"


#: Status codes worth retrying. Everything else is deterministic: retrying a
#: malformed Overpass query just burns quota and returns the same error.
_RETRYABLE = {408, 425, 429, 500, 502, 503, 504}


class HttpClient:
    """A rate-limited, cached, retrying HTTP client."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        cache: ResponseCache | None = None,
        rate_limiter: RateLimiter | None = None,
        transport: Any = None,
    ) -> None:
        self.settings = settings or global_settings
        self.cache = (
            cache
            if cache is not None
            else ResponseCache(
                self.settings.cache_dir / "http.sqlite3", enabled=self.settings.cache_enabled
            )
        )
        self.limiter = rate_limiter or global_limiter
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.settings.http_timeout_s, connect=5.0),
            follow_redirects=True,
            headers={
                "User-Agent": self.settings.user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            transport=transport,
        )

    # -- public API ---------------------------------------------------------

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        provider: str = "upstream",
        ttl_s: float | None = None,
        use_cache: bool = True,
        timeout_s: float | None = None,
    ) -> tuple[Any, bool]:
        """GET a URL and parse JSON. Returns ``(payload, was_cached)``."""
        raw, cached = self.get_bytes(
            url,
            params=params,
            headers=headers,
            provider=provider,
            ttl_s=ttl_s,
            use_cache=use_cache,
            timeout_s=timeout_s,
        )
        try:
            import json

            return json.loads(raw), cached
        except ValueError as exc:
            raise GeoUpstreamError(
                f"{provider} returned a non-JSON response ({exc}). "
                f"First 200 bytes: {_quoted_upstream(raw, self.settings)}"
            ) from exc

    def post_json(
        self,
        url: str,
        *,
        data: Any = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
        provider: str = "upstream",
        ttl_s: float | None = None,
        use_cache: bool = True,
        timeout_s: float | None = None,
    ) -> tuple[Any, bool]:
        """POST and parse JSON. Used by Overpass (QL body) and Valhalla."""
        import json as _json

        host = urlparse(url).hostname or ""
        key = self.cache.make_key("POST", url, None, body=data if data is not None else json_body)
        if use_cache:
            hit = self.cache.get(key)
            if hit is not None:
                return _json.loads(hit), True

        response = self._request(
            "POST",
            url,
            params=None,
            headers=headers,
            provider=provider,
            content=data,
            json_body=json_body,
            timeout_s=timeout_s,
        )
        body = response.content
        if use_cache:
            self.cache.set(
                key,
                host,
                body,
                ttl_s=ttl_s,
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
            )
        try:
            return _json.loads(body), False
        except ValueError as exc:
            raise GeoUpstreamError(
                f"{provider} returned a non-JSON response ({exc}). "
                f"First 200 bytes: {_quoted_upstream(body, self.settings)}"
            ) from exc

    def get_bytes(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        provider: str = "upstream",
        ttl_s: float | None = None,
        use_cache: bool = True,
        timeout_s: float | None = None,
    ) -> tuple[bytes, bool]:
        """GET raw bytes. Returns ``(body, was_cached)``."""
        host = urlparse(url).hostname or ""
        key = self.cache.make_key("GET", url, dict(params or {}))
        if use_cache:
            hit = self.cache.get(key)
            if hit is not None:
                logger.debug("cache hit %s", url)
                return hit, True

        response = self._request(
            "GET", url, params=params, headers=headers, provider=provider, timeout_s=timeout_s
        )
        body = response.content
        if use_cache:
            self.cache.set(
                key,
                host,
                body,
                ttl_s=ttl_s,
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
            )
        return body, False

    def close(self) -> None:
        self._client.close()
        self.cache.close()

    # -- internals ----------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None,
        headers: Mapping[str, str] | None,
        provider: str,
        content: Any = None,
        json_body: Any = None,
        timeout_s: float | None = None,
    ) -> httpx.Response:
        host = urlparse(url).hostname or ""
        effective_timeout = self.settings.http_timeout_s if timeout_s is None else timeout_s
        last_error: Exception | None = None

        for attempt in range(self.settings.max_retries + 1):
            self.limiter.acquire(host)
            try:
                response = self._client.request(
                    method,
                    url,
                    params=params,
                    headers=dict(headers or {}),
                    content=content,
                    json=json_body,
                    timeout=httpx.Timeout(effective_timeout, connect=5.0),
                )
            except httpx.TimeoutException:
                last_error = GeoUpstreamError(
                    f"{provider} timed out after {effective_timeout:.0f}s. "
                    "Narrow the query (smaller radius, fewer categories) or retry."
                )
            except httpx.HTTPError as exc:
                last_error = GeoUpstreamError(f"Could not reach {provider}: {exc}")
            else:
                if response.status_code < 400:
                    return response
                if response.status_code == 429:
                    retry_after = _retry_after_seconds(response)
                    if attempt >= self.settings.max_retries:
                        raise GeoRateLimited(provider, retry_after)
                    last_error = GeoRateLimited(provider, retry_after)
                    self._sleep(attempt, retry_after)
                    continue
                if response.status_code in _RETRYABLE:
                    last_error = GeoUpstreamError(
                        f"{provider} returned HTTP {response.status_code}."
                    )
                else:
                    # Deterministic failure -- retrying cannot help.
                    raise GeoUpstreamError(
                        f"{provider} returned HTTP {response.status_code}: "
                        f"{_quoted_upstream(response.text, self.settings, limit=300)}"
                    )
            if attempt < self.settings.max_retries:
                self._sleep(attempt, None)

        assert last_error is not None
        raise last_error

    @staticmethod
    def _sleep(attempt: int, retry_after: float | None) -> None:
        """Exponential backoff with full jitter, capped, honouring Retry-After."""
        if retry_after is not None:
            time.sleep(min(retry_after, 30.0))
            return
        time.sleep(random.uniform(0.0, min(2.0**attempt, 8.0)))


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


_client: HttpClient | None = None


def get_client() -> HttpClient:
    """Return the process-wide HTTP client, creating it on first use."""
    global _client
    if _client is None:
        _client = HttpClient()
    return _client


def reset_client(client: HttpClient | None = None) -> None:
    """Replace the process-wide client (test hook)."""
    global _client
    if _client is not None and client is not _client:
        _client.close()
    _client = client
