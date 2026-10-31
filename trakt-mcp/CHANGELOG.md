# Changelog

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
