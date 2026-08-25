"""Shared HTTP plumbing: one client, one cache, one rate limiter.

Calling an HTTP library directly from each provider module -- no shared session,
no cache, no retry, no throttle -- violates the usage policy of nearly every
provider here. Nominatim alone requires a descriptive User-Agent, a maximum of
one request per second, and caching of results. Scattered calls also burn a
shared egress IP's quota in any container or CI environment, where every user of
the image looks like one client.
"""

from .client import HttpClient, get_client

__all__ = ["HttpClient", "get_client"]
