# Changelog

## 0.3.5

- Include parsed numeric page, total and response-size diagnostics in pagination
  mismatch errors. Keep completeness checks unchanged; no payloads or credentials
  are included. This supports diagnosing real up-next response discrepancies.

- Remove the Trakt GitHub Actions workflow; retain local tests, benchmarks and
  HTTP smoke-test helpers, and document local verification commands.

## 0.3.4

- Read watched shows through the bounded live sync reader, following actual
  upstream pagination before producing MCP pages. Support complete arrays too.
- Retain per-page validation, stable total checks, and the 200-page/16 MiB sync
  limits; never treat a partial first page as the complete watched library.
- Cover multi-page upstream responses alongside unpaginated watched libraries.

## 0.3.3

- Validate complete-array endpoint responses before applying local MCP pagination.
  Watched-show libraries larger than a requested page and full-array pagination
  headers no longer cause false page-number or page-size errors.
- Continue rejecting unexpected partial upstream pages and inconsistent headers.
- Cover 125-show libraries across first, middle, final and out-of-range pages,
  with and without upstream pagination headers.

## 0.3.2

- Include `library.py` and `version.py` in the Docker build context; the previous
  allowlist excluded these required modules and prevented add-on updates.
- Remove the obsolete streaming module entry from the build allowlist.
- Check Docker COPY sources against the build-context allowlist in regression tests.

## 0.3.1

- Require pagination metadata for paged history, up-next, list items, movie/episode
  collections and playback; incomplete headers no longer imply a complete result.
- Validate declared page sizes, totals and final-page lengths while retaining
  legitimate empty and non-paginated endpoint responses.
- Validate Trakt activity before/after series recommendation exclusions; reject
  results if activity changes or freshness cannot be established.
- Limit execution to two concurrent MCP tool handlers per process. Waiting calls
  remain covered by the 120-second timeout, and cancellation releases capacity.
- Extend regression coverage for pagination failures, changed activity, shared
  execution limits and queued-call timeout/cancellation behavior.

## 0.3.0

- Add read-only series search/details, seasons and episodes, cast/crew, related
  series, and community/external ratings for shows, seasons, and episodes.
- Add personal series progress with bounded episode pages and explicit special,
  hidden-season, and rewatch semantics; separate up-next and scheduled episodes.
- Add series watchlist/favorites/watched aggregates and personal ratings across
  movies, shows, seasons, and episodes.
- Add detailed history with UTC range/item filters, own lists and list notes,
  hidden/dropped items, collection, and player-reported paused playback.
- Add personal/global UTC release calendars with 1–31 day windows and account
  statistics with explicit unavailable results for missing VIP precomputed data.
- Add personal series recommendations with fresh, complete exclusion lists and
  original ranks, omitting other users' recommendation notes.
- Keep new personal reads out of public caches, exclude list share links and
  unrelated profile fields, and preserve existing response/concurrency budgets.
- Handle valid public 204 responses without treating them as malformed JSON.
- Report `server_version` in status and share the runtime version constant.
- 41 default tools; two optional authorization tools remain disabled by default.
  No new credentials/options or changes to Trakt media data are required.

## 0.2.1

- Add the Trakt API app management address to the Client ID configuration help.
- Provide clickable shortcuts at the top of the Documentation tab and service
  monitor; Home Assistant's configuration helper itself renders plain text.

## 0.2.0

- Remove the direct TMDb/JustWatch integration, its configuration fields, provider
  discovery, streaming offer/shortlist tools, and related monitor statistics.
- Focus all data access on Trakt. Explicit Trakt genre and streaming preferences
  remain available; they do not imply verified subscriptions or movie availability.
- Add `trakt_get_movie_ratings_summary` for community and external scores supplied
  by Trakt, preserving source scales, votes, links, and missing values.
- Remove legacy provider catalogs from the public cache at startup. Existing
  Trakt authorization is retained, and obsolete streaming options are ignored.
- Reconnect MCP clients after upgrading to refresh the changed tool list.

## 0.1.3

- Add read-only `trakt_get_user_preferences` for explicit favorite/disliked genres,
  streaming country, and favorite streaming source identifiers from Trakt settings.
- Fetch settings live with OAuth, return only allowlisted preference fields, and
  keep complete account settings out of caches, tool outputs, and logs.
- Distinguish missing settings from empty selections and streaming favorites from
  verified subscriptions, TMDb provider IDs, and actual movie availability.
- No TMDb credentials, new options, or additional authorization are required.

## 0.1.2

- Report actionable startup validation errors without logging option values.
- Identify failing startup stages and unexpected exception types, error numbers,
  and source locations while withholding raw exception text and tracebacks.
- Validate configuration before changing persistent storage ownership or runtime
  privileges, and align the MCP-reported version with the add-on version.

## 0.1.1

- Use `http://localhost` for token refresh and document the matching Trakt app
  redirect URI, compatible with Trakt's development app restrictions.
- Verify refresh request parameters with and without a client secret while
  preserving single-use token rotation under concurrent requests.

## 0.1.0

Initial experimental release.

- Read-only Trakt movie history, ratings, favorites, watchlist, details, credits,
  filmographies, personal recommendations, and filtered recommendation candidates.
- Optional TMDb/JustWatch availability by country and selected providers,
  including batch shortlists and source attribution.
- Authenticated Streamable HTTP MCP with structured tool outputs and optional client network/Host restrictions.
- Home Assistant device authorization, private application-bound OAuth storage,
  automatic refresh, and opt-in MCP authorization tools.
- Bounded public SQLite cache and activity-validated account-bound RAM snapshots.
- Ingress-only service statistics without movie data or credentials.
- Runtime privilege drop, bounded requests/results, rate-limit handling,
  regression tests, and ARM64/AMD64 CI builds and smoke checks.

The release remains experimental until live account, Home Assistant Green,
Ingress, and client acceptance tests pass.
