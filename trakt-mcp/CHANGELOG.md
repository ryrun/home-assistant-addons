# Changelog

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
