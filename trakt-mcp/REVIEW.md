# Technical review and comparison

Reviewed on 2026-10-31. This assessment covers source code, specifications, and
local tests. It does not replace acceptance testing with a Trakt account,
Zed/Codex, and Home Assistant Green.

## Series extension review, version 0.3.1

The follow-up review found and fixed three issues: absent/partial pagination could
look like a complete first page on new personal routes; compound series exclusions
did not check global activity across reads; and the HTTP request limit alone did
not constrain whole-tool execution with large decoded results. These now have
explicit validation, before/after activity checks, and a shared two-handler limit.
Regression tests also cover empty results, cancellation and time spent queued.
The tool surface is unchanged. Real-account endpoint behavior, large series
libraries, and ARM64/Supervisor operation still require target-device acceptance.

## Framework decision

The server uses the official MCP Python SDK 2.3.0 and its high-level `MCPServer`
class. This class was named `FastMCP` in SDK 1.x; decorators, schemas, and tool
validation are already part of the abstraction in use. See the
[official migration guide](https://py.sdk.modelcontextprotocol.io/migration/#fastmcp-renamed-to-mcpserver).

The standalone [FastMCP package](https://gofastmcp.com/getting-started/welcome)
is a separate framework and remains an option for future requirements.
For a single read-only Trakt server with static bearer authentication and a
limited set of tools, there is currently no concrete reason to migrate.
Migration would require additional changes and compatibility testing.
The implementation therefore keeps the official SDK.

## Reference project comparison

| Area | wwiens/trakt_mcpserver | fab-codes/trakt-mcp-server | This add-on |
| --- | --- | --- | --- |
| Focus | Broad Trakt coverage: movies, shows, episodes, people, comments, and recommendations | Mainly shows, history, search, and watchlist | Personal movie recommendations using read-only data |
| Framework in reviewed code | FastMCP from the official MCP SDK, using the v1 import path | Standalone `fastmcp` package | Official SDK 2.x, `MCPServer` |
| Write operations | Includes ratings, history, watchlist, and check-in | Includes watchlist changes and marking episodes watched | No changes to Trakt movie data |
| Trakt authorization | Device flow and persistent token store | Access token supplied through client configuration | Device flow, refresh, and setup through HA configuration/logs |
| HTTP connection reuse | Shared client pool | Shared AsyncClient with HTTP/2 | Shared AsyncClient with bounded concurrency |
| Home Assistant operation | General MCP/container server | General MCP/container server | Dedicated add-on with options, translations, documentation, and watchdog |

Code comparison sources:

- [wwiens at cd49144](https://github.com/wwiens/trakt_mcpserver/tree/cd491444be86dbc219d77dc652f75432d7f3af57):
  README, `server/main.py`, `client/base.py`, `client/pool.py`,
  `client/movies/related.py`, and `pyproject.toml`.
- [fab-codes at 75f28ef](https://github.com/fab-codes/trakt-mcp-server/tree/75f28ef8a4d4d9f0ad3553b63ce92b46c3fd5e11):
  README, `src/api/__init__.py`, and `requirements.txt`.

The reference projects were not fully security-audited or run locally.
Descriptions such as “production-ready” in their READMEs are not an independent
quality assessment. No third-party source code was copied.

## Implemented improvements

1. Bounded persistent SQLite cache for public metadata only. It includes
   configurable TTL, manual clearing, status, and coalescing of identical
   concurrent requests without adding a Python dependency.
2. Personal lists remain uncached. Exclusions use fresh data and avoid requesting
   unnecessary full metadata. Invalid pagination and detectable list-size changes
   result in errors rather than incomplete results.
3. Related movies and credits, including directors, can be retrieved.
   Candidates can come from popular, trending, or related movies.
   Filters and exclusion lists apply to all three sources.
4. One retry for transient GET failures, bounded API concurrency, and a shared
   cooldown after HTTP 429. OAuth exchanges are not blindly retried because
   refresh tokens are single-use.
5. Rotated tokens remain in memory after a storage failure. The next authenticated
   request first retries persistence. A process termination before successful
   persistence may still require authorization again. Damaged token files can be
   replaced by repeating device authorization through HA. A damaged metadata cache
   does not prevent server startup.
6. Unexpected redirects are rejected. Bearer authentication, browser Origin
   rejection, optional Host allowlisting, and sanitized error messages remain in place.

## Known limitations and next steps

- Personal data now uses activity-validated RAM snapshots. A TTL-only personal
  cache was deliberately avoided; exclusions fail if freshness cannot be established.
- Explicit favorites, personal Trakt recommendations, person filmographies, and
  explicit account preferences were added after the initial review. The server
  now focuses exclusively on Trakt, including Trakt-provided external ratings.
  Version 0.3.0 adds individual history events, series/progress and personal
  library operations. All Trakt media operations remain read-only.
- A movie can be watched between the exclusion lookup and the tool response.
  Trakt does not provide a transaction-wide snapshot here, so absolute real-time
  consistency across multiple requests cannot be guaranteed.
- HTTP on the LAN is unencrypted. The add-on cannot prevent Internet exposure
  by itself: configure your router firewall, VPN, or HTTPS separately.
  Host allowlists are not client-IP filters.
- Container builds, operation on Green, real token refresh, and Zed/Codex
  connections still require acceptance testing.

## Follow-up review: implemented hardening

The follow-up findings were implemented on 2026-10-31:

- OAuth errors distinguish `invalid_grant` from configuration failures, preserving
  credentials when the latter occurs. Regression coverage exercises both paths.
- Invalid cache JSON is evicted and refetched. Startup can replace a corrupt
  public cache database, retaining one backup. Reads avoid cleanup writes.
- The Trakt client rechecks cooldown after acquiring a semaphore. Retry waits are not
  shortened, and device polling respects retry headers.
- Account-bound personal snapshots live only in bounded RAM, validate activity on
  every reuse, reject changes during sync, and expire after 15 minutes at most.
- Trending uses a shorter TTL. Public Trakt metadata and rating summaries can be
  cached. Status exposes cache hits, misses and bytes.
- MCP authorization tools require explicit opt-in. A CIDR filter checks socket
  peers without trusting forwarded headers. Runtime root privileges are dropped
  before the HTTP app starts. Proxy/NAT limitations still apply.
- Bounded upstream responses, full-sync transfer budgets, paged credits,
  and compact preference data reduce
  accidental resource use and unnecessary MCP round trips.
- Tests, benchmarks and HTTP smoke-test helpers run locally. ARM64/AMD64
  container builds, runtime UID and persistence checks require separate local
  verification when Docker is available. The GitHub workflow has been removed.

The earlier dependency audit checked 31 pinned Python runtime packages and found
no known vulnerabilities at scan time. It did not scan container OS packages or
the deployed network. Synthetic benchmark results and hardware limitations are
recorded in [PERFORMANCE.md](PERFORMANCE.md).

An ingress-only service monitor was subsequently added at the user's request.
It retains bounded process-local operational metrics and exposes no film data,
arguments, credentials, or arbitrary error text. The internal dashboard listener
accepts only Supervisor's real peer address; it is separate from MCP authentication
and has no published host port. Both listeners share one process and coordinate
startup and shutdown. Local browser checks covered desktop/mobile layouts, dark
mode, ingress-relative paths and CSP; direct TCP checks covered both listeners
and graceful shutdown. Actual HA Ingress acceptance remains outstanding.

The implemented controls preserve read-only access to Trakt. They do not replace
actual Green, account, networking, and client acceptance tests.

## Final local review

The final review added stricter credential/configuration validation, official
Trakt activation-URL validation, application-bound token files, authorization
consistency checks across compound queries, and a generation barrier preventing
in-flight public lookups from repopulating a manually cleared cache. Watchlist
and favorite endpoints must provide pagination metadata so exclusions cannot
silently treat a partial response as complete. Regression tests cover these cases.

Tool return annotations now publish native structured MCP results with object
output schemas, in addition to compatibility text. The real TCP smoke test checks
structured status data with a stored test token, ingress isolation, file permissions,
and coordinated shutdown.

Local checks passed: 94 tests, Ruff undefined-name/unused-import checks, Actionlint
workflow validation, JavaScript syntax, YAML/schema/translation consistency,
documentation links, dependency consistency, and a repeated audit of the 31 pinned
runtime packages without reported vulnerabilities. Container smoke checks now
also seed test-only OAuth data and check its private permissions and persistence
after restart. The current Supervisor capability configuration was reviewed for
compatibility with the runtime privilege drop.

No additional feature expansion is required before device acceptance. Real
ARM64/AMD64 builds, Supervisor/AppArmor/Ingress behavior on Green, live OAuth
refresh and Zed/Codex integration remain external acceptance
items. None of those deployment checks is claimed as locally completed.
