# Performance and Home Assistant Green

Home Assistant Green has a quad-core Cortex-A55 processor at 1.8 GHz, 4 GB RAM,
and 32 GB eMMC ([official specifications](https://www.home-assistant.io/green/)).
This add-on performs HTTP I/O, JSON processing and bounded caching. It runs no LLM,
embedding model, background catalog sync, or recommendation training job.

The design is suitable for a single-account home deployment, provided Home
Assistant and other add-ons leave sufficient free resources. This is an engineering
assessment, not a completed Green hardware benchmark or a guarantee for every installation.

## Resource controls

- Two executing MCP tool handlers per process; queued calls share the 120-second
  deadline and release capacity on cancellation. This includes cached responses.
- Two concurrent GETs per upstream service; six HTTP pool connections in total
- At most 8 MiB of decoded data per upstream response; OAuth responses use 64 KiB
- At most 16 MiB transferred per complete personal-list sync
- Public cache: 256 entries / 16 MiB of bodies, excluding SQLite overhead;
  entries larger than 512 KiB are not retained
- Personal cache: at most 16 MiB of serialized list data in RAM, with activity
  validation on every use and a maximum snapshot age of 15 minutes
- Bounded tool output: 100 list results, default 50 credits, compact preference groups
- Series progress is paged by episode, with at most 100 season summaries and an
  explicit truncation flag; calendars cover at most 31 days per request
- New personal library reads are fresh and do not populate the public disk cache
- A 120-second tool timeout, 64 KiB inbound MCP body limit, and Uvicorn concurrency limit
- No background polling; idle operation makes no regular Trakt requests
- The service monitor polls only local statistics every ten seconds while visible;
  its bounded counters/latency samples stay in RAM, with no statistics database
- Read-only cache hits avoid housekeeping writes, reducing unnecessary eMMC activity

These are data/concurrency limits, not a hard process memory cap. JSON objects,
SDK imports, TLS connections, and concurrent requests also consume memory.
For local container smoke tests, a 256 MiB / one-CPU limit is a useful test
condition; passing it does not establish a worst-case memory bound.

## Reproducible synthetic benchmark

```sh
python trakt-mcp/scripts/benchmark.py --movies 10000 --iterations 20
```

A local macOS ARM64 run with Python 3.13.3 on 2026-10-31, including MCP SDK imports:

| Metric | Uncached | Activity-validated RAM snapshot |
| --- | ---: | ---: |
| Movies in simulated watched list | 10,000 | 10,000 |
| Page requests | 20 | 20 |
| Full-list downloads | 20 | 1 |
| Small activity lookups | 0 | 21 |
| Simulated list bytes transferred | 31,955,600 | 1,597,780 |
| First page, local processing | 8.06 ms | 14.05 ms |
| Median subsequent page, local processing | 7.37 ms | 7.06 ms |

The entire benchmark process peaked at **85.1 MiB RSS**. This is a high-water mark
including SDK imports and synthetic fixtures, not a measured idle server figure.
The benchmark exercises client/cache code with in-process mock HTTP; it does not
measure real Trakt latency, HTTPS, Docker, Supervisor, or Green CPU performance.
Numbers vary between runs and must not be presented as Green response times.

The snapshot reduced full-list transfer by 95%. Initial validation adds two small
requests, and later pages still perform one activity lookup each. This reduces
large downloads rather than eliminating network calls. A memory-object cache
layer was not added: local page processing was already around 7 ms, and retaining
extra decoded object graphs would increase RAM use for little demonstrated benefit.

## Acceptance on the actual Green

1. Install the ARM64 add-on, enable start on boot and watchdog, and authorize Trakt.
2. Confirm MCP status, personal ratings, favorites, watchlist, explicit preferences,
   and movie community/external ratings supplied by Trakt.
   Also verify series progress (specials, hidden seasons, rewatches), up-next,
   personal lists/history, UTC calendars, collection and paused playback.
   Missing VIP precomputed statistics should report unavailable, not zero.
   Open the Ingress service monitor and verify readiness, call counts and cache hits.
3. Observe the add-on CPU and memory indicators while idle and during requests.
   Check available system RAM alongside other add-ons.
4. Request several watched pages and repeat a candidate search. Inspect cache hit
   counters and byte counts using `trakt_get_status`.
5. Change a rating/watchlist entry on Trakt, then confirm that the next request
   invalidates the personal snapshot. Test token refresh and restart persistence.
6. Verify that normal Home Assistant automations remain responsive. Test errors
   under a Trakt outage without rapid retries or watchdog restart loops.

Real account, Green hardware, and Zed/Codex acceptance remain outstanding in the
local environment. ARM64/AMD64 builds and resource-limited container smoke tests
need separate local verification when Docker is available.
