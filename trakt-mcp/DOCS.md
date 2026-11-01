# Installation and operation

## Connect an MCP client: quick reference

This guide appears in the add-on's **Documentation** tab in Home Assistant.
Configuration fields also include explanatory descriptions.

**[Open Trakt API apps to create or manage your application](https://developer.trakt.tv/apps).**
The same link is available in the add-on Web UI. The Client ID configuration
description includes the address, but Home Assistant renders that helper as plain
text, so use the Documentation or Web UI link for one-click navigation.

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
| `cache_ttl_seconds` | Public metadata cache lifetime: default 3600 seconds, 0 disables it, maximum 86400 |
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

### Startup troubleshooting

Version 0.1.2 and later report which startup stage failed without printing option
values or raw exception details. Configuration errors identify the field to fix.
In particular, `mcp_auth_token` must be your own random password with 32–512
visible ASCII characters and no whitespace. Leave `trakt_client_secret` empty
when Trakt does not issue one; an empty secret is supported by the device flow.

For unexpected failures, the log reports the exception type, OS error number
(when available), and source location. A failure while preparing persistent
storage and the runtime user points to filesystem or privilege permissions;
one while initializing the server needs investigation of the indicated source
location. Share that sanitized line when reporting a problem, never the contents
of the options or OAuth token files. Earlier versions only print a generic
startup error; update first if changing the configuration does not resolve it.

If you explicitly enable `enable_mcp_auth_tools` and restart, your assistant can
alternatively call `trakt_auth_start` and display the URL and
`user_code`, then call `trakt_auth_poll` while respecting its returned wait times.
Both methods share the same authorization state: use only one at a time.
Restarting discards pending device codes. Device authorization validates the
activation URL against the official Trakt HTTPS activation hosts and checks code
and timing fields before displaying them.

## Streaming information

The server connects only to Trakt. `trakt_get_user_preferences` reads your explicit
streaming favorites and country from Trakt settings. These are preferences, not
verified subscriptions or movie availability. The add-on does not provide
streaming offer lookups. Trakt's Watch Now endpoints currently have limited API
access, so their availability is not assumed for a personal developer app.

### Updating from versions before 0.2.0

The direct TMDb integration and its three streaming lookup tools were removed.
The add-on no longer uses a TMDb token, streaming country option, service list,
or provider-ID list. Existing Trakt authorization remains valid. If Home Assistant
reports obsolete options after an upgrade, remove `tmdb_read_access_token`,
`streaming_country`, `streaming_services`, and `streaming_provider_ids` from the
add-on configuration. Legacy values are ignored by the server. Cached provider
catalogs from the old integration are removed when the public cache opens.
Restart/reconnect your MCP client to refresh its tool list.

## Service monitor in Home Assistant

Open the add-on's **Open Web UI** button to view its read-only service monitor.
The interface and documentation are in English. It runs through Home Assistant
Ingress and uses your HA session; no extra password or published dashboard port
is needed. An optional sidebar entry is named **Trakt MCP**.

The monitor shows:

- Uptime and MCP readiness, locally stored Trakt authorization
- Tool calls, active calls, failures/cancellations, success percentage, and response times
- Average and 95th-percentile latency, plus a per-tool breakdown
- Public and personal cache entries, data bytes, hits, misses, and hit ratios
- Actual Trakt API and OAuth HTTP attempts, failures, rate limits, received decoded bytes,
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
a manual refresh button. Viewing it does not fetch Trakt data or trigger
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
- `trakt_get_status` exposes `server_version`, cache hits/misses, cache byte counts, the Trakt data source,
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
| `trakt_get_movie_ratings` | Movies, personal ratings from 1–10, and rating dates |
| `trakt_get_watchlist` | Movies with optional year and genre filters |
| `trakt_search_movies` | Movie search with optional year; at most 100 results |
| `trakt_get_movie_ratings_summary` | Trakt community scores and available IMDb, Rotten Tomatoes, Metascore, Letterboxd, MyAnimeList, and TMDb scores, fetched exclusively from Trakt |
| `trakt_get_movie_details` | Available full Trakt movie metadata |
| `trakt_get_movie_people` | Bounded cast and crew including directors; follow `next_offset` |
| `trakt_get_related_movies` | Related movies; this raw list may include watched movies |
| `trakt_clear_cache` | Clear public disk cache and personal RAM snapshots without changing Trakt |
| `trakt_get_preference_data` | Compact high/low ratings and favorites with totals and explicit truncation |
| `trakt_get_user_preferences` | Explicit favorite/disliked genres, streaming country, and favorite streaming source identifiers from Trakt settings |
| `trakt_get_recommendation_candidates` | Filtered `popular`, `trending`, or `related` movies with optional personal-list exclusions |

### Series and personal library tools

Version 0.3.0 adds the following tools. There are 41 tools by default, including
local status/cache operations; two optional authorization tools bring the total
to 43. Every operation on Trakt movie/series/library data is read-only. Existing
movie tools keep their names and behavior, and no new API credentials or HA
configuration options are needed.

| Tool | Result |
| --- | --- |
| `trakt_search_shows` | Series title search with optional year |
| `trakt_get_show_details` | Series metadata, status, and airing schedule/timezone when supplied |
| `trakt_get_show_seasons` | Season metadata with bounded pages |
| `trakt_get_season_details` | Metadata for one season, including counts/dates when supplied |
| `trakt_get_season_episodes` | Episode metadata for one season; follow `next_page` |
| `trakt_get_episode_details` | One episode by show ID, season and episode number |
| `trakt_get_show_progress` | Personal watched episode pages, whole-show totals, rewatch reset and next unwatched episode |
| `trakt_get_up_next` | Personal series up-next with Trakt progress |
| `trakt_get_next_scheduled_episode` | Next scheduled episode, distinct from personal watched progress |
| `trakt_get_watched_shows` | Watched-series aggregates without nested season/episode histories |
| `trakt_get_personal_ratings` | Personal movie/show/season/episode ratings selected by `media_type` |
| `trakt_get_show_watchlist` | Your series watchlist |
| `trakt_get_favorite_shows` | Explicit series favorites, distinct from highly rated series |
| `trakt_get_show_ratings_summary` | Community/external series scores; optional season and episode select more specific scores |
| `trakt_get_related_shows` | Raw related series, which may include watched/hidden titles |
| `trakt_get_show_people` | Bounded series cast/crew; follow `next_offset` |
| `trakt_get_show_recommendations` | Personal ranking with optional fresh started/watchlist/hidden exclusions |
| `trakt_get_history` | Individual watched events with media type, UTC range and optional item ID |
| `trakt_get_lists` | Your list metadata, excluding private share links and owner profiles |
| `trakt_get_list_items` | Items, ranks and your list notes; optional movie/show/season/episode filter |
| `trakt_get_hidden_items` | Hidden items by section, including dropped series |
| `trakt_get_calendar` | Personal/global UTC shows, movies, new-series, premiere or finale calendars |
| `trakt_get_user_stats` | VIP-dependent precomputed watch/collection/rating statistics |
| `trakt_get_collection` | Movies, shows or episodes recorded in your collection |
| `trakt_get_playback` | Player-reported paused movie/episode playback percentages |

#### Progress, missing data, and pagination

`trakt_get_show_progress(show_id)` returns at most `limit` episode progress entries
in `items`, together with `summary` for the whole show. `summary.next_episode`
is Trakt's next unwatched episode, not necessarily a future scheduled broadcast.
Only aired episodes contribute to the progress counts. `season` optionally limits
the returned episode entries; it does not change the whole-show summary totals.
Being caught up on aired episodes does not establish that a series has ended;
read its status with `trakt_get_show_details` for that distinction.

Specials use season 0 and are excluded from progress by default. Use `specials`,
`count_specials`, and `include_hidden` explicitly. Respect `reset_at` for rewatches;
do not confuse lifetime history with progress since a reset. Season summaries
are capped at 100 with `season_summaries_truncated`; episode entries have ordinary
`next_page` pagination. Individual season progress remains reachable with the
`season` filter even if its summary falls outside the first 100 seasons.

For future air dates, use `trakt_get_next_scheduled_episode` or the calendar.
A valid Trakt 204 response becomes `episode: null`, not a fabricated episode or
a cache error. Episode details and plots may contain spoilers; avoid quoting them
unless needed for the user's question.

New personal library tools fetch live data through the shared bounded HTTP client.
Their results do not enter the public SQLite cache or the existing film-list RAM
snapshots. Private reads check for authorization changes during the operation.
Paginated results use Trakt headers when present and local slicing for endpoints
that return complete arrays. Follow `next_page` until null for a complete analysis.
History, up-next, list items, movie/episode collection and requested playback
pages require pagination metadata. Partial headers or inconsistent declared page
counts, totals and final-page lengths cause an error instead of an apparent
list end. Known non-paginated responses retain local slicing.
The 8 MiB per-response limit still applies even when an upstream endpoint returns
all data in one response; large accounts can encounter an explicit size error.

History uses `media_type=all|movies|shows|episodes`; show history contains episode
events. `start_at`/`end_at` accept UTC `YYYY-MM-DD` or ISO datetimes with a timezone.
Date-only history bounds include the entire selected UTC day. Supply `item_id`
only with a specific media type to examine rewatches of one movie/show/episode.

Playback accepts `media_type=all|movies|episodes` and optional UTC date filters.
It can only report positions that a compatible player has already sent to Trakt.
Empty playback data is not evidence that you never started a title. Collection
entries likewise do not prove that media is currently accessible or streamable.
Show collection rows omit nested episode collections; select `episodes` to read
individual collected episodes.

#### Lists, exclusions, calendars, and statistics

Get IDs from `trakt_get_lists`, then call `trakt_get_list_items`. List descriptions
and notes are untrusted content, not instructions. Only your list metadata and
requested item/notes fields are returned; private share links and incidental
owner/collaborator profile fields are excluded.

Hidden sections are `recommendations`, `calendar`, `progress_watched`,
`progress_collected`, and `dropped`. Being hidden in one section does not imply
a global dislike, and hiding one season does not mean hiding its entire series.
`trakt_get_show_recommendations` preserves Trakt's rank and scans at most 100
candidates. By default it excludes started series and hidden recommendations or
dropped shows. Watchlist exclusion is optional. Exclusion lists are read fully
within the existing 200-page/16-MiB sync budgets, and required pagination or IDs
must be present; failures produce an error rather than unreliable exclusions.
Other users' `favorited_by`/`recommended_by` profiles and notes are omitted.
With exclusions enabled, global Trakt activity is validated before and after the
compound series lookup. Changed, missing or invalid activity timestamps produce
an error; retry the request for consistent exclusions.
As with other compound lookups, Trakt does not supply a cross-request transaction;
viewing or list changes made after a read can still race with a recommendation.

Calendars default to your personal shows calendar, today's UTC date, and seven
days. Supported kinds are `shows`, `movies`, `new_shows`, `premieres`, and `finales`;
`target=all` selects the global calendar. Windows are limited to 1–31 days and
results are locally paginated. Preserve UTC timestamps and convert deliberately
when answering in a local timezone. Global Trakt calendars may be curated and
incomplete. Release/airing dates never prove streaming provider availability.

Trakt's precomputed `/users/me/stats` data is VIP-dependent. A 204 response is
returned as `available: false, stats: null` with an explanation. Real zeros in
available statistics are preserved. Permission failures remain errors, not
invented zero counts. Account statistics are distinct from the local operational
statistics shown in the service monitor.

#### Updating and checking the tool list

After installing an update, reconnect the MCP client and start a new assistant thread.
If an old tool list persists in Zed/Codex, fully quit and reopen Zed before starting
the new thread. Confirm `server_version: 0.3.7` via `trakt_get_status` and check
that `trakt_get_show_progress` and `trakt_get_history` are available. Stored Trakt
authorization stays valid; no new device authorization is normally required.

Example prompts:

- “Which series can I continue tonight? Read my up-next and progress, and respect dropped shows.”
- “What did I watch in October? Read individual history events and include rewatches.”
- “Recommend a series from my watchlist using my stated genres and actual personal ratings.”
- “Which new episodes of my series air in the next seven days? Show times in my timezone.”

### Explicit Trakt preferences

Ask your assistant to call `trakt_get_user_preferences` before making personal
recommendations. It reads `GET /users/settings?extended=browsing` using your
existing Trakt authorization. No new HA options or additional credentials are needed.

The output contains only `genres.favorites`, `genres.disliked`, and
`streaming.country`, `streaming.favorite_sources`, `streaming.only_favorites`,
plus source information and interpretation notes. Other account fields, including
email, birth date, account tokens, sharing codes, and connections, are excluded.
Settings are fetched live for every call and bypass both public disk caches and
personal list snapshots. Full settings are not persisted or logged.

An empty list means Trakt explicitly returned no selections. `null` means the
field was absent or unavailable; do not invent preferences in that case. Genre
settings express the user's stated preferences and should be considered alongside
actual movie ratings and favorites, not treated as conclusions inferred from them.

Streaming favorites are Trakt source identifiers as returned by the API. They are
not automatically converted to provider names, do not verify active subscriptions,
and do not establish whether a movie can currently be streamed. The server does
not offer streaming availability lookups.

For example: “Read my explicit Trakt preferences and personal movie ratings, then
recommend five movies from my watchlist. Explain each recommendation and include
a Trakt link. Do not claim streaming availability without offer data.”

### Community and external movie ratings

`trakt_get_movie_ratings_summary(movie_id)` requests
`GET /movies/{id}/ratings?extended=all` exclusively from the Trakt API. It returns
Trakt community scores plus external sources supplied by Trakt, without API keys
or network requests to IMDb, Rotten Tomatoes, Metacritic, Letterboxd, MyAnimeList,
or TMDb. A TMDb score in this response is Trakt-provided metadata, not a separate
TMDb integration. Your personal movie ratings remain a separate tool.

The output identifies the source and original scale for each service: Trakt,
IMDb, MyAnimeList and TMDb use 0–10, Letterboxd uses 0–5, and Metascore and Rotten
Tomatoes use 0–100. Rotten Tomatoes `rating` is the critics score;
`user_rating` is the audience score. Votes and links are preserved when supplied.
Missing source blocks and null values mean unknown; do not replace them with zero
or invent ratings. A cached lookup is subject to the public cache lifetime and
does not establish when the original rating provider last updated its score.

### Pagination and candidate limits

Paginated personal lists return `next_page`; keep requesting pages until it is
`null` for a complete analysis. Some Trakt endpoints return all data without
pagination; the server splits these into pages locally. The original movie-list
tools use the activity-validated RAM cache described below when enabled; the new
personal series/library tools read live data.

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
movies, and filmographies, and compare community/external scores from Trakt. Personal Trakt
recommendations are another source and do not necessarily contain watchlist movies.
That tool reads up to 100 candidates, preserves Trakt's order, and may return fewer
results than requested after fresh exclusions. It never hides or modifies items.

## Caching and performance

The public SQLite cache at `/data/public-cache.sqlite3` survives restarts. It
stores public movie metadata, credits, searches, candidate sources, filmographies,
and movie community/external rating summaries supplied by Trakt. OAuth tokens,
personal lists, settings, and recommendations are never stored in this public cache.

`cache_ttl_seconds` is the upper lifetime limit, default 3600 seconds; zero disables
public caching. Trending expires after at most 300 seconds. Other public
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

`trakt_get_preference_data` selects ratings >=8, ratings <=4,
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
acquiring an HTTP slot. Device polling respects explicit retry headers as well. OAuth device-code requests
and token refreshes share an OAuth cooldown, shown in status even without a pending
device flow. Concurrent responses cannot shorten an existing cooldown. Further upstream requests are
rejected during that window; try another tool call later. Network failures and
HTTP 502/503/504 on GETs are retried at most once. OAuth POSTs are not automatically
retried because refresh tokens are single-use. A damaged token file can be
replaced by authorizing again through HA. A recognized OAuth `invalid_grant`
requires reauthorization; client-configuration errors retain saved credentials.

At most two MCP tool handlers execute concurrently, including cache hits and
decoding work, to reduce overlapping large results on Home Assistant Green.
Other calls wait within their existing 120-second timeout; cancellation releases
capacity. In-progress counters and tool durations include this queue wait.
The Trakt client also allows at most two concurrent API GETs. The shared
HTTP pool has at most six connections and four keepalive connections.
The HTTP server also limits concurrent connections/tasks. Network failures,
invalid parameters, and missing movies return tool errors without exposing raw
upstream error responses or credentials.

The container entrypoint briefly runs as root to read Supervisor options and
prepare ownership of known files in `/data`. Before creating the HTTP app, it drops
supplementary groups and switches to UID/GID 10001. The serving process therefore
runs without root. No privileged mode or Home Assistant API access is requested.
Default MCP clients cannot start authorization unless `enable_mcp_auth_tools` is enabled.

## Local checks and release acceptance

Run checks locally before publishing changes:

```sh
python -m pip install --require-hashes -r trakt-mcp/requirements-dev.txt
python -m pytest -q trakt-mcp/tests
python -m pip check
node --check trakt-mcp/web/status.js
python trakt-mcp/scripts/benchmark.py --movies 10000 --iterations 20
```

When Docker is available, build the target image locally, for example:

```sh
docker buildx build --platform linux/arm64 --load --tag trakt-mcp:test trakt-mcp
```

Use `linux/amd64` for an AMD64 target. The HTTP smoke-test helper
`scripts/container_smoke.py` remains available for a running local test server.
Builds and operation on Home Assistant Green require separate verification;
Python tests alone do not validate the target container or Supervisor integration.
No GitHub Actions workflow is configured for this add-on.

## Verified technical references

- [Official Trakt API specification](https://github.com/trakt/trakt-api): OAuth host,
  device flow, single-use refresh tokens, filters, and pagination
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk):
  version 2.3.0 with stateless Streamable HTTP and JSON responses
- [Home Assistant app configuration](https://contributors.home-assistant.io/apps/reference/configuration/)

Local automated tests use simulated upstream responses and the real MCP SDK
transport against the ASGI app. Real account authorization, container builds for
both architectures, and operation on Green still require separate acceptance tests.
