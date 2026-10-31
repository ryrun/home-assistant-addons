# Installation and operation

## Connect an MCP client: quick reference

This guide appears in the add-on's **Documentation** tab in Home Assistant.
Configuration fields also include explanatory descriptions.

- **Server URL:** `http://homeassistant.local:8765/mcp`. Alternatively, use your
  Home Assistant's local IP address and adjust the port if you changed its mapping.
- **Transport:** Streamable HTTP.
- **Client authentication:** HTTP header `Authorization: Bearer YOUR_MCP_TOKEN`.
  Use the **MCP access password** you configured for the add-on.
- **Check the connection:** Ask your assistant to call `trakt_get_status`.
- **Connect Trakt:** Enable **Start Trakt authorization** and use the activation
  code shown in the **Log** tab, as described below.

The URL is an example. This version does not automatically discover your local
Home Assistant address or a changed host port. Copyable Zed and Codex examples
appear below. The access password is never printed in the documentation or logs.

## Install in Home Assistant

1. Under **Settings → Apps/Add-ons → Store → Repositories**, add
   `https://github.com/ryrun/home-assistant-addons`.
2. Install **Trakt MCP Server**. Its image is built locally from the add-on folder;
   no separately published container image is required.
3. Configure the options below, save, and start the add-on.
4. Enable **Start on boot** and **Watchdog**. Change the default host port 8765
   in the add-on's network settings if necessary.

Installation requires this version to be available on the repository branch in
use. The local development version has not been published automatically.

## Trakt application and options

Register your own API application under [Trakt Apps](https://developer.trakt.tv/apps).
Set its redirect URI to exactly `http://localhost` (without a trailing slash).
Trakt development apps only allow localhost redirects. The add-on uses the device
flow, so no callback server needs to run at that address. The same URI is sent
when refreshing tokens.

| Option | Description |
| --- | --- |
| `trakt_client_id` | Your Trakt application's client ID; required |
| `trakt_client_secret` | Your server-side Trakt application's client secret; optional under the current Trakt specification |
| `mcp_auth_token` | Your own random MCP password, 32–512 visible ASCII characters without whitespace or control characters |
| `authorize_trakt` | Start a new device authorization through the add-on logs at startup; default `false` |
| `log_level` | Recommended: `info`; alternatives: `debug`, `warning`, `error` |
| `personal_cache_enabled` | Enable account-bound RAM snapshots validated against Trakt activity; default `true` |
| `enable_mcp_auth_tools` | Expose MCP authorization tools; default `false`, use HA setup instead |
| `allowed_networks` | Allowed client CIDRs; defaults to private IPv4, loopback, IPv6 ULA and IPv6 link-local ranges; empty disables the IP filter |
| `streaming_provider_ids` | Preferred stable provider IDs from `trakt_get_streaming_providers`; empty by default |
| `cache_ttl_seconds` | Public metadata cache lifetime: default 3600 seconds, 0 disables it, maximum 86400 |
| `tmdb_read_access_token` | Optional TMDb API Read Access Token for availability and provider lists; not a Trakt token |
| `streaming_country` | Streaming country as an ISO code; default `DE`, other examples: `AT`, `CH` |
| `streaming_services` | Exact provider names from `trakt_get_streaming_providers`; empty by default |
| `allowed_hosts` | Optional Host-header allowlist including ports, e.g. `homeassistant.local:8765`, `192.168.1.10:8765` |

Generate an MCP token locally with
`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`.
It is independent of your Trakt OAuth tokens. Boolean options must be actual
JSON booleans, not quoted strings, when running outside Supervisor.

## Authorize through Home Assistant

1. Enable `authorize_trakt`, save, and start or restart the add-on.
2. Open the **Log** tab to find a short-lived user activation code.
3. Open [Trakt activation](https://auth.trakt.tv/activate), enter the code, and
   authorize your application for the intended account.
4. The add-on checks for approval automatically at Trakt's required intervals.
   Wait for the authorization success message in the log.
5. Disable `authorize_trakt` again and save. Otherwise, the next restart starts
   another device authorization. Existing tokens remain until a new authorization
   succeeds.

If the device code expires or is denied, restart the add-on with authorization
enabled. After successful authorization, token refresh is automatic.
Repeat setup if the refresh token is revoked.

If you explicitly enable `enable_mcp_auth_tools` and restart, your assistant can
alternatively call `trakt_auth_start` and display the URL and
`user_code`, then call `trakt_auth_poll` while respecting its returned wait times.
Both methods share the same authorization state: use only one at a time.
Restarting discards pending device codes. Device authorization validates the
activation URL against the official Trakt HTTPS activation hosts and checks code
and timing fields before displaying them.

## Set up streaming availability

Trakt tools work without additional credentials. For streaming offers, register
[TMDb API access](https://www.themoviedb.org/settings/api) and enter its
**API Read Access Token** in `tmdb_read_access_token`. Use the bearer token,
not the shorter v3 API key. No personal TMDb account data or TMDb user authorization
is needed. Store the token only in the HA configuration.

1. Set `tmdb_read_access_token` and `streaming_country` in HA, save, and restart
   the add-on.
2. Ask your assistant to call `trakt_get_streaming_providers` to list providers.
3. Prefer adding the returned numeric IDs to `streaming_provider_ids`. Exact
   names in `streaming_services` also work. Save and restart. Leave both lists
   empty to show offers without subscription matching.
4. Ask the assistant to call `trakt_get_movie_streaming` with a Trakt movie ID.
   Optional `country`, `services`, and `provider_ids` arguments independently override
   their corresponding HA defaults for that call. Use empty lists to clear selections.

For example, set the country to `DE` and use the Netflix ID returned by the
provider tool, or add `Netflix` to your services list. Unknown names or IDs cause
a configuration error rather than a misleading negative availability result.
Add-on channels such as “Paramount+ Amazon Channel” are separate offers and are
not automatically included in a general Prime subscription. Ad-supported plans
may also have separate provider names. Your selection is manual; the add-on never
signs in to your streaming accounts.

Responses separate `subscription`, `free`, `ads`, `rent`, and `buy` offers, and
include subscription matches, country, source, and an optional TMDb listing URL.
Only `subscription` offers count toward `available_with_configured_subscription`;
ad-supported free offers, rentals, and purchases do not count as subscription matches.
If regional offer data is missing, the status is `no_data` and subscription
availability is `null` (unknown). The subscription match is also `null` when neither provider IDs nor names are configured.

`checked_at` is our lookup time, not the provider's last update time.
Offers are fetched on each call and bypass the public metadata cache.
A missing TMDb ID produces a clear error rather than an unreliable title-based match.

**Data source: JustWatch via TMDb.** The assistant must name this source when
reporting availability. This product uses the TMDB API but is not endorsed or
certified by TMDB. Provider listings do not guarantee current playback or
entitlement for your particular account. Use the returned TMDb URL to check;
the API does not provide complete direct playback links.

See the [provider documentation](https://developer.themoviedb.org/reference/movie-watch-providers)
and [TMDb authentication guide](https://developer.themoviedb.org/docs/authentication-application).
Trakt also documents Watch Now data, but API access is restricted.
This implementation therefore uses TMDb as its explicit streaming source.

## Service monitor in Home Assistant

Open the add-on's **Open Web UI** button to view its read-only service monitor.
The interface and documentation are in English. It runs through Home Assistant
Ingress and uses your HA session; no extra password or published dashboard port
is needed. An optional sidebar entry is named **Trakt MCP**.

The monitor shows:

- Uptime and MCP readiness, locally stored Trakt authorization, and whether TMDb is configured
- Tool calls, active calls, failures/cancellations, success percentage, and response times
- Average and 95th-percentile latency, plus a per-tool breakdown
- Public and personal cache entries, data bytes, hits, misses, and hit ratios
- Actual Trakt, TMDb, and OAuth HTTP attempts, failures, rate limits, received decoded bytes,
  and cooldowns
- Add-on process memory, process CPU relative to one core, and rejected MCP request counts
- The last 30 tool names, outcomes, timestamps, and durations

Counters and recent calls are kept only in RAM and reset on restart. No tool
arguments, movie titles, ratings, tokens, raw upstream errors, or user identities
are retained in these statistics. Latency windows are bounded: 512 overall/HTTP
samples and 128 per tool. Tool durations include waits, authorization and cache
validation; HTTP durations cover each actual attempt. Invalid parameters rejected
before a handler runs are not counted as tool calls. Expected pending OAuth
responses are not treated as failed attempts.

The page refreshes local statistics every ten seconds while visible and includes
a manual refresh button. Viewing it does not fetch Trakt/TMDb data or trigger
background synchronization. A failed refresh marks the visible numbers as
potentially stale. On Linux, memory is current RSS; where unavailable, it is
explicitly labeled peak RSS. These values describe this process, not total HA usage.

Ingress uses internal container port **8099**, which is not mapped in `ports`.
The listener accepts only the real Supervisor socket peer `172.30.32.2` (including
its IPv4-mapped IPv6 form), ignoring forwarded-client headers. Other peers receive
403 even with a valid MCP bearer token. The dashboard does not proxy MCP requests
and exposes no configuration or authorization actions. The existing MCP listener
on port 8765 continues to require its own bearer token and configured network rules.
The two listeners share one Python process and one set of caches and HTTP clients.

All assets are local; there are no external fonts, scripts, analytics, or CDNs.
Relative asset/API URLs support HA's changing ingress path. Responses use a strict
Content Security Policy, same-origin framing, no-store caching, and no-referrer headers.
See [Home Assistant's ingress guide](https://contributors.home-assistant.io/apps/guides/ingress/).
Actual integration with Supervisor still needs acceptance on the target Green.

## Status and logs

- The Home Assistant add-on page shows whether the process is running.
- `/health` returns minimal process status without credentials. The Supervisor
  watchdog and container health check can access it without a bearer token.
  A Trakt outage does not trigger a restart loop.
- Logs report MCP readiness, stored authorization, and, at `info` level,
  successful MCP calls with tool names and durations. Errors have readable messages.
  Arguments, results, and OAuth tokens are not logged.
- `trakt_get_status` exposes cache hits/misses, cache byte counts, streaming configuration,
  and local status to authenticated MCP clients.
  Stored tokens do not prove current Trakt connectivity or token validity.
- The **Open Web UI** button opens the ingress service monitor described above.
  Configuration and full textual logs remain in the standard add-on tabs.

The user activation code is intentionally visible in logs during setup.
Wait until it expires before sharing logs. Private `device_code`, access tokens,
and refresh tokens are never returned to MCP clients or printed in logs.

## Zed

Following the [Zed MCP documentation](https://zed.dev/docs/ai/mcp), configure
a remote MCP server with an explicit Authorization header:

```json
{
  "context_servers": {
    "trakt": {
      "url": "http://homeassistant.local:8765/mcp",
      "headers": { "Authorization": "Bearer YOUR_MCP_TOKEN" }
    }
  }
}
```

The header is required. This server uses static bearer authentication and does
not provide an MCP OAuth authorization server. Trakt OAuth is only used for
server-side access to Trakt. Forwarding tools to external agents depends on the
Zed/ACP agent version. A green MCP indicator alone does not confirm that a
particular external agent receives the tools.

## Codex with its own MCP configuration

As described in the [official OpenAI documentation](https://developers.openai.com/codex/mcp),
Codex can alternatively configure the server directly:

```toml
[mcp_servers.trakt]
url = "http://homeassistant.local:8765/mcp"
bearer_token_env_var = "TRAKT_MCP_TOKEN"
tool_timeout_sec = 130
```

`TRAKT_MCP_TOKEN` must be available in the process that starts Codex, including
when Zed launches the agent. Keep credentials out of the repository.
Choose one configuration method to avoid registering tools twice.
Verify the integration with your installed Zed/Codex version.

## Tools and limitations

Tools publish an object output schema and return native MCP `structuredContent`
as well as the SDK's text representation for compatibility. Both current and
legacy negotiation modes are covered by local tests.

| Tool | Result |
| --- | --- |
| `trakt_get_status` | Local process and authorization status without secrets |
| `trakt_auth_start`, `trakt_auth_poll` | Optional authorization tools, disabled by default |
| `trakt_get_watched_movies` | Movies, IDs, play counts, and last viewing dates |
| `trakt_get_favorite_movies` | Explicitly marked Trakt favorites with pagination, independent of high ratings |
| `trakt_get_person_movies` | Bounded person credits with characters/jobs and `next_offset` |
| `trakt_get_personal_recommendations` | Personal Trakt ranking with optional fresh watched/watchlist exclusions |
| `trakt_get_streaming_providers` | Country-specific provider names for subscription setup |
| `trakt_get_movie_streaming` | Fresh offer lookup by country and selected services; JustWatch via TMDb |
| `trakt_get_movie_ratings` | Movies, personal ratings from 1–10, and rating dates |
| `trakt_get_watchlist` | Movies with optional year and genre filters |
| `trakt_search_movies` | Movie search with optional year; at most 100 results |
| `trakt_get_movie_details` | Available full Trakt movie metadata |
| `trakt_get_movie_people` | Bounded cast and crew including directors; follow `next_offset` |
| `trakt_get_related_movies` | Related movies; this raw list may include watched movies |
| `trakt_clear_cache` | Clear public disk cache and personal RAM snapshots without changing Trakt |
| `trakt_get_streaming_shortlist` | Up to ten movie availability lookups with per-movie errors and duplicate coalescing |
| `trakt_get_preference_data` | Compact high/low ratings and favorites with totals and explicit truncation |
| `trakt_get_recommendation_candidates` | Filtered `popular`, `trending`, or `related` movies with optional personal-list exclusions |

Paginated personal lists return `next_page`; keep requesting pages until it is
`null` for a complete analysis. Some Trakt endpoints return all data without
pagination; the server splits these into pages locally. Personal lists use the
activity-validated RAM cache described below when enabled.

Candidate sources are `source="popular"` (default), `"trending"`, or `"related"`.
For `related`, provide `seed_movie_id` for a movie the user actually likes.
Trakt does not support genre/year filters on that endpoint, so related movies
are filtered locally. Other sources apply both upstream and local filters.
None of these sources represents the user's personal ranking.

The search scans up to ten pages of a requested 100 movies each. Trakt may cap
the actual page size. `pages_scanned` and `scan_limit_reached` expose this limit.
Lesser-known movies may be underrepresented. Genres use OR semantics;
`min_rating` uses 0–10 and is converted to 0–100 for Trakt's filter.

Exclusion lists are loaded completely, up to 200 API pages. Errors, missing pagination headers on watchlist/favorites endpoints, or missing
Trakt IDs produce an error rather than unreliable exclusions. Each tool call has
an additional 120-second total timeout. Compound personal recommendations and preference lookups reject authorization
changes during the operation, including between separate source lists.
Individual upstream responses are limited
to 8 MiB of decoded data (64 KiB for OAuth). A complete personal-list sync has an
additional 16 MiB transfer budget. Oversized results fail explicitly rather than
being silently truncated. Credits tools default to 50 entries, support `limit`
up to 100 and `offset`, and expose `next_offset`. Missing metadata is never invented.
The watched list contains aggregates, not individual historical viewing events.
Separate tools retrieve directors and related movies. The assistant makes and
explains the final personal selection using data it actually retrieved.

For watchlist recommendations, the assistant should retrieve the watchlist,
ratings, and explicit favorites, evaluate candidates using metadata, related
movies, and filmographies, and then check their streaming offers. Personal Trakt
recommendations are another source and do not necessarily contain watchlist movies.
That tool reads up to 100 candidates, preserves Trakt's order, and may return fewer
results than requested after fresh exclusions. It never hides or modifies items.

## Caching and performance

The public SQLite cache at `/data/public-cache.sqlite3` survives restarts. It
stores public movie metadata, credits, searches, candidate sources, filmographies,
and the TMDb provider catalog. OAuth tokens, personal lists and recommendations,
and movie availability responses are never stored in this public cache.

`cache_ttl_seconds` is the upper lifetime limit, default 3600 seconds; zero disables
public caching. Trending expires after at most 300 seconds. The provider catalog
uses at most 86400 seconds, further capped by the configured lifetime. Other public
metadata uses the configured lifetime. Identical concurrent public Trakt queries
are coalesced. There is no background polling; expired data is refreshed on demand.

The cache holds at most 256 entries totaling 16 MiB of response bodies. Single
responses over 512 KiB are not stored. SQLite uses additional bookkeeping space
and can reuse freed pages. Normal reads do not perform housekeeping writes;
expired rows are removed on writes. Invalid cached JSON is removed and fetched
again. A corrupt database found during startup is replaced, retaining one
`public-cache.corrupt` backup. An unavailable cache falls back to direct requests.

With `personal_cache_enabled: true`, watched movies, ratings, favorites, and
watchlist data are kept only in a bounded 16 MiB RAM cache. Before every reuse,
the server fetches `/sync/last_activities` and validates its timestamp. Initial
loads check activity both before and after syncing. A changed account/token,
changed activity, or a snapshot age over 15 minutes invalidates reuse. Relevant
changes are treated conservatively using the global activity timestamp.

A missing activity timestamp, failed freshness check, or change during sync
produces an error instead of silently reusing stale exclusions. OAuth refresh may
also invalidate a snapshot even when the account is unchanged. If a dataset is too
large to retain, it is returned fresh without caching. Activity validation does
not provide a transaction-wide snapshot or eliminate races with concurrent viewing.
Set `personal_cache_enabled: false` to fetch personal lists directly on every call.

`trakt_get_status` reports cache bytes, entries, hits and misses.
`trakt_clear_cache` clears both caches. It changes only local state. Public
lookups already in progress may finish for their caller, but cannot repopulate
the cache after it has been cleared.

For a short movie selection, use `trakt_get_streaming_shortlist` with at most ten
IDs. It reduces MCP round trips, not necessarily upstream requests, and preserves
per-movie errors. `trakt_get_preference_data` selects ratings >=8, ratings <=4,
and explicit favorites; it reports source totals and whether groups were truncated.
Interpretation remains the assistant's responsibility.

See [PERFORMANCE.md](PERFORMANCE.md) for reproducible measurements, resource limits,
and Home Assistant Green acceptance checks.

## Security, persistence, and errors

OAuth tokens are stored atomically at `/data/oauth.json` with file permissions
`0600`. Newly saved token files include an application-ID fingerprint. Changing
`trakt_client_id` requires authorizing that application again; the old file is
retained so an accidental configuration change can be reversed. Legacy files
without this metadata remain readable and gain a binding on the next save.
Tokens survive container restarts and add-on updates. `/data` is the private,
persistent add-on directory and requires no additional host-folder mapping.
Home Assistant backups can contain options and tokens; protect them accordingly.

The MCP process listens on all IPv4 interfaces inside the container, and port
8765 is published on the Home Assistant host. The default `allowed_networks` permits private IPv4, loopback, IPv6 ULA and IPv6
link-local client addresses. Configure explicit CIDRs for your network, or use an
empty list to disable IP filtering. Bearer authentication protects tool calls. The IP filter checks the actual socket
peer, rejects missing/unrecognized peers, and handles IPv4-mapped IPv6 addresses.
It ignores forwarded-client headers. A proxy or NAT can mask the original client
behind an allowed address, so this filter is not proof of LAN-only exposure. **The Home Assistant login does not protect the
separate MCP port.** Anyone who has the token and can reach the port can use the
tools. `/health` is available without a token and only reports process status.
`allowed_hosts` separately checks the destination Host header, not the client IP.

Do not forward port 8765 on your router or expose it through a public reverse
proxy. The router firewall must block unsolicited inbound Internet traffic,
including IPv6. Actual external reachability depends on your network and has not
been checked here.

HTTP sends the bearer token without encryption. Use it only on a trusted LAN;
use a VPN or an HTTPS reverse proxy for remote access. Browser Origin requests
are rejected. Optionally constrain `allowed_hosts`; behind a proxy, the forwarded
Host header must match that allowlist.

For MCP HTTP `401`, check your MCP token. For Trakt authorization errors, repeat
device authorization. Rate-limit handling respects `Retry-After` in seconds,
defaulting to 60 seconds when absent or invalid. Explicit waits are not shortened;
HTTP-date values are also supported. Queued requests recheck the cooldown after
acquiring an HTTP slot. Device polling respects explicit retry headers as well. Further upstream requests are
rejected during that window; try another tool call later. Network failures and
HTTP 502/503/504 on GETs are retried at most once. OAuth POSTs are not automatically
retried because refresh tokens are single-use. A damaged token file can be
replaced by authorizing again through HA. A recognized OAuth `invalid_grant`
requires reauthorization; client-configuration errors retain saved credentials.

Each service, Trakt or TMDb, allows at most two concurrent API GETs. The shared
HTTP pool has at most six connections and four keepalive connections.
The HTTP server also limits concurrent connections/tasks. Network failures,
invalid parameters, and missing movies return tool errors without exposing raw
upstream error responses or credentials.

The container entrypoint briefly runs as root to read Supervisor options and
prepare ownership of known files in `/data`. Before creating the HTTP app, it drops
supplementary groups and switches to UID/GID 10001. The serving process therefore
runs without root. No privileged mode or Home Assistant API access is requested.
Default MCP clients cannot start authorization unless `enable_mcp_auth_tools` is enabled.

## Automated checks and release acceptance

The repository workflow `.github/workflows/trakt-mcp.yml` runs Python tests and a
synthetic benchmark, builds ARM64 and AMD64 images, and smoke-tests health, bearer
authentication, tool discovery, repeated calls, runtime UID, restart, private token/cache permissions and persistence, and
ingress listener isolation. Container smoke tests use a 256 MiB / one-CPU limit. Workflow
actions are pinned to commits. These checks run after the changes reach GitHub;
they have not been executed locally where Docker is unavailable.

## Verified technical references

- [Official Trakt API specification](https://github.com/trakt/trakt-api): OAuth host,
  device flow, single-use refresh tokens, filters, and pagination
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk):
  version 2.3.0 with stateless Streamable HTTP and JSON responses
- [Home Assistant app configuration](https://contributors.home-assistant.io/apps/reference/configuration/)

Local automated tests use simulated upstream responses and the real MCP SDK
transport against the ASGI app. Real account authorization, container builds for
both architectures, and operation on Green still require separate acceptance tests.
