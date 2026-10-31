"""Reproducible synthetic benchmark; this is not a Home Assistant Green measurement."""
import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import platform
import resource
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from server import create_app  # noqa: F401 - Include the real SDK import cost in process RSS.
from trakt_client import TraktClient


class AuthStub:
    async def access_token(self, rejected_token=None):
        return 'benchmark-only-token'


async def benchmark(size, iterations):
    body = json.dumps([{'plays': 1, 'last_watched_at': '2026-10-31T00:00:00Z',
                        'movie': {'title': f'Example movie {i}', 'year': 2024,
                                  'genres': ['mystery'], 'ids': {'trakt': i}}}
                       for i in range(size)]).encode()
    results = {}
    for enabled in (False, True):
        calls = Counter()
        async def upstream(request):
            calls[request.url.path] += 1
            if request.url.path == '/sync/last_activities':
                return httpx.Response(200, json={'all': '2026-10-31T00:00:00Z'})
            return httpx.Response(200, content=body)
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as http:
            client = TraktClient(http, AuthStub(), 'benchmark', personal_cache=enabled)
            timings = []
            for i in range(iterations):
                start = time.perf_counter()
                result = await client.watched(page=i % max(1, (size + 99)//100) + 1)
                assert len(result['items']) <= 100
                timings.append((time.perf_counter() - start) * 1000)
            results['validated_snapshot' if enabled else 'uncached'] = {
                'first_page_ms': round(timings[0], 2), 'median_page_ms': round(statistics.median(timings[1:] or timings), 2),
                'full_list_downloads': calls['/sync/watched/movies'], 'activity_checks': calls['/sync/last_activities'],
                'simulated_list_bytes_transferred': calls['/sync/watched/movies'] * len(body)}
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {'platform': platform.system(), 'architecture': platform.machine(), 'python': platform.python_version(),
            'movies': size, 'page_requests': iterations, 'peak_process_rss_mib': round(peak / (1024**2 if sys.platform == 'darwin' else 1024), 1),
            'results': results, 'limitations': 'Synthetic in-process HTTP; no real network or Green hardware. RSS is process high-water mark including SDK and fixtures.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--movies', type=int, default=10000)
    parser.add_argument('--iterations', type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.movies <= 20000 or not 1 <= args.iterations <= 200:
        parser.error('Use 1–20000 movies and 1–200 iterations.')
    print(json.dumps(asyncio.run(benchmark(args.movies, args.iterations)), indent=2))
