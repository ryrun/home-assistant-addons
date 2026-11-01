# Trakt MCP Server

Experimental Home Assistant add-on (0.3.5) for personal movie and series data from Trakt.tv.
AI assistants receive read-only access through authenticated MCP Streamable HTTP
at `http://homeassistant.local:8765/mcp`.

Setup uses the existing Home Assistant configuration and log tabs. A compact
read-only service monitor opens inside HA through Ingress, showing requests,
latency, cache efficiency, errors, and process resources. No separate dashboard
port is published. The server has no chatbot or built-in LLM.

## Features

- Watched movies with play counts and last viewing dates
- Series search, status, seasons, episodes, cast/crew, related series, and ratings
- Personal series progress, next unwatched episodes, up-next, and scheduled episodes
- Series watchlist, favorites, watched aggregates, and personal show/season/episode ratings
- Individual history events with UTC date filters and optional item selection
- Personal lists and notes, hidden/dropped items, collection, and paused playback
- Personal/global UTC release calendars and VIP-dependent account statistics
- Personal series recommendations with fresh started/watchlist/hidden exclusions
- Personal ratings, explicit favorites, movie watchlist, search, and movie details
- Personal Trakt recommendations and directors' or actors' movie credits
- Explicit favorite/disliked genres, streaming country, and streaming favorites
  from Trakt settings, without unrelated account details
- Community and external movie ratings supplied by Trakt, including IMDb and Rotten Tomatoes
- Candidates from popular, trending, or related movies with genre, year, and rating filters
- Cast and crew, including directors, to support explanations
- Bounded persistent public cache and activity-validated private RAM snapshots
- Compact preference data with completeness indicators
- Complete watched-movie exclusion and optional watchlist exclusion using Trakt IDs
- Device authorization, persistent OAuth tokens, and automatic token refresh
- Bearer authentication, optional CIDR/Host restrictions, bounded upstream I/O, and runtime privilege drop
- HA authorization by default; MCP authorization tools require explicit opt-in
- Ingress-protected service statistics with local assets and bounded RAM-only history
- Health check, Supervisor watchdog, and local test coverage
- Declared support for aarch64 (Home Assistant Green) and amd64

Installation, authorization, and client configuration: [DOCS.md](DOCS.md).
Development status and outstanding hardware acceptance: [project plan](../plan.md).
Technical decisions and comparison: [REVIEW.md](REVIEW.md).
Resource measurements and Green acceptance: [PERFORMANCE.md](PERFORMANCE.md).

All API data is fetched from Trakt. External movie scores are returned only when
Trakt supplies them; no additional rating or streaming service is contacted.
Streaming favorites express preferences; movie availability is not provided.

All Trakt media/library operations are read-only. Collection entries do not prove
current access, playback positions require a player that reports to Trakt, and
unavailable VIP statistics are returned as unknown rather than zero.
New personal library reads bypass persistent public caches. No background sync
or additional API credentials are needed. Reconnect your MCP client after an
upgrade; `trakt_get_status` reports `server_version` for deployment diagnostics.

## Development

Use Python 3.13. Runtime and test dependencies, including transitive packages,
are pinned with versions and SHA-256 hashes.

```sh
cd trakt-mcp
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.txt
.venv/bin/pytest -q tests
```

For intentional dependency updates, install `pip-tools==7.6.2` in a separate
environment and run these commands from the repository root:

```sh
pip-compile --generate-hashes --strip-extras -o trakt-mcp/requirements.txt trakt-mcp/requirements.in
pip-compile --generate-hashes --strip-extras -o trakt-mcp/requirements-dev.txt trakt-mcp/requirements-dev.in
```

The official Python base image is also pinned by its multiarch digest.
The container can run without Supervisor when `/data/options.json` and persistent
`/data` storage are provided. Options correspond to `config.yaml`.
Local runs also support `TRAKT_OPTIONS_FILE` and `TRAKT_DATA_DIR` overrides.
