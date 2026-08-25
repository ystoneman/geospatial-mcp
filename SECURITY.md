# Security policy

## Reporting

Report vulnerabilities through
[GitHub's private advisory form](https://github.com/ystoneman/geospatial-mcp/security/advisories/new).
Please do not open a public issue.

Expect an acknowledgement within a week.

## What this server does and does not do

It is read-only. No tool writes files, mutates remote state, or executes
commands. Every tool is annotated `readOnlyHint: true`, `destructiveHint: false`.

It makes outbound HTTPS requests to the geospatial providers listed in the
README, and caches responses under `GEO_CACHE_DIR`. It opens no listening
socket unless started with `--transport http`.

## In scope

- **Leaking secrets through tool output or logs.** API keys must never appear
  in a tool response, an error message, or a log line. HTTP request logging is
  set to `WARNING` precisely because httpx logs full query strings, which
  contain user coordinates and search terms.
- **Server-side request forgery.** User-supplied place names and geometry flow
  into upstream URLs. Provider base URLs are operator-configured, never
  caller-supplied, and paths are not interpolated from user input.
- **Denial of service through unbounded parameters.** Sample counts, radii,
  batch sizes and result limits are all clamped. A report of a parameter that
  is not is in scope.
- **Cache poisoning.** The response cache is keyed on the canonicalised
  request; a way to make one caller's query return another's result is in scope.
- **Prompt injection through tool results.** Upstream content — OpenStreetMap
  place names, address strings, tower records — is attacker-influenceable text
  that reaches the model. We prefer structured fields over free text and cap
  response sizes, but treat all of it as untrusted.

## Out of scope

- Rate limits, outages or data errors at upstream providers.
- The accuracy of third-party geospatial data. OpenStreetMap is
  community-edited and DEM coverage has gaps; the server reports `meta.notes`
  where it can detect a limitation.
- Running the HTTP transport exposed to the internet without authentication.
  It binds `127.0.0.1` by default for this reason; put it behind a proxy.

## For operators

- The server trusts its environment. Anyone who can set `NOMINATIM_URL` or
  `OVERPASS_URL` can redirect queries to a host they control.
- The cache may contain user coordinates and search terms. Treat
  `GEO_CACHE_DIR` as data of the same sensitivity as the queries themselves.
- Optional API keys are read from the environment and are never logged or
  returned in a response.
