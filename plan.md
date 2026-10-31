# Trakt MCP project and acceptance plan

Goal: a personal, read-only movie and series Trakt MCP server as a standalone Home Assistant add-on.
Codex/Zed handles analysis and recommendations. Existing add-ons remain unchanged.
Status: experimental version 0.3.0.

Setup uses the existing Home Assistant interface through configuration and logs,
or alternatively MCP tools. Home Assistant displays process status and logs.
A read-only statistics page is embedded through HA Ingress. There is no chatbot
or separate publicly exposed dashboard.

## Implemented and locally verified

- [x] Review the current official Trakt specification and Home Assistant configuration
- [x] Official Python MCP SDK 2.3.0, Streamable HTTP, and bearer authentication
- [x] Test MCP connection setup and repeated calls with the SDK client
- [x] Device flow through HA configuration/logs and MCP tools
- [x] Private persistent token file, atomic writes, and serialized refresh
- [x] Aggregated watched history, ratings, watchlist, search, and details
- [x] Series metadata, seasons/episodes, watched progress, up-next, scheduled episodes,
  personal ratings/favorites/watchlist, and filtered personal recommendations
- [x] Dated individual history, own lists and notes, hidden/dropped items, UTC calendars,
  collection, paused playback, and explicitly VIP-dependent precomputed statistics
- [x] Explicit genre preferences, streaming country, and favorite streaming sources
  from allowlisted Trakt settings without unrelated account data
- [x] Pagination using actual response headers and support for unpaginated endpoints
- [x] Popular, trending, and related candidates with filters and complete fresh exclusions
- [x] Movie credits including directors, related movies, and person filmographies
- [x] Explicit favorites and personal Trakt recommendations with fresh exclusions
- [x] Community and external movie ratings via Trakt only; direct third-party API integrations removed
- [x] Bounded persistent public SQLite cache with per-source TTLs, corruption recovery, status, and manual clearing
- [x] Account-bound RAM snapshots with activity validation, memory/age budgets, and safe invalidation
- [x] Compact preference tools and bounded credits
- [x] Optional CIDR filtering, opt-in MCP authorization tools, and runtime privilege drop
- [x] Bounded upstream responses, corrected OAuth errors and queued-request cooldowns
- [x] Synthetic 10,000-movie benchmark and defined ARM64/AMD64 CI build/smoke jobs
- [x] Bounded GET retries, rate-limit cooldown, and API concurrency limits
- [x] Status tool, logs without arguments/results, and health check
- [x] Ingress-only statistics monitor with bounded metrics, no credentials/film data, and local assets
- [x] Browser checks at desktop/mobile widths and real TCP dual-listener/shutdown smoke test
- [x] Add-on configuration, container files, startup script, and watchdog
- [x] Pinned dependencies with hashes and a pinned multiarch base-image digest
- [x] Automated tests and installation/setup documentation

## External acceptance before 1.0.0

- [ ] Build and run images for linux/arm64 and linux/amd64
- [ ] Install the add-on from the published GitHub repository on Home Assistant Green
- [ ] Authorize a real Trakt account through HA configuration and logs
- [ ] Compare real data and pagination with a larger account
- [ ] Verify token refresh, restart persistence, Supervisor watchdog, and reauthorization
- [ ] Verify bearer headers, tool forwarding, and repeated calls in Zed with Codex
- [ ] Verify actual HA Ingress routing, access controls, sidebar, and statistics on Green
- [ ] Assess recommendation quality using real ratings, favorites, and watchlist data
- [ ] Prepare release 1.0.0 only after acceptance tests pass

Docker and Home Assistant Green are unavailable in the local development
environment. No real Trakt credentials have been provided, and no changes have
been published. The definition of done for version 1 has therefore not been met.

Future work: additional read-only metadata and multiple accounts. Write tools remain excluded.
