"""Bounded, process-local operational statistics. Never retain arguments or errors."""
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
import resource
import sys
import time


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def distribution(values):
    values = sorted(values)
    if not values:
        return {'samples': 0, 'average_ms': None, 'p95_ms': None}
    return {'samples': len(values), 'average_ms': round(sum(values) / len(values), 2),
            'p95_ms': round(values[max(0, (len(values) * 95 + 99) // 100 - 1)], 2)}


class Metrics:
    def __init__(self):
        self.started = time.monotonic()
        self.started_at = timestamp()
        self.ready = False
        self.calls = self.errors = self.active = 0
        self.rejections = Counter()
        self.timings = deque(maxlen=512)
        self.tools = {}
        self.upstreams = {name: {'requests': 0, 'errors': 0, 'rate_limits': 0, 'bytes': 0,
                                 'statuses': Counter(), 'timings': deque(maxlen=512), 'last_at': None}
                          for name in ('trakt', 'oauth')}
        self.recent = deque(maxlen=30)
        self.cpu_at = self.started
        usage = resource.getrusage(resource.RUSAGE_SELF)
        self.cpu_seconds = usage.ru_utime + usage.ru_stime
        self.cpu_percent = None

    def begin_tool(self, name):
        self.calls += 1
        self.active += 1
        if name not in self.tools:
            self.tools[name] = {'calls': 0, 'errors': 0, 'timings': deque(maxlen=128)}
        self.tools[name]['calls'] += 1
        return time.monotonic()

    def finish_tool(self, name, started, outcome):
        elapsed = (time.monotonic() - started) * 1000
        self.active -= 1
        failed = outcome != 'ok'
        self.errors += failed
        entry = self.tools[name]
        entry['errors'] += failed
        entry['timings'].append(elapsed)
        self.timings.append(elapsed)
        self.recent.appendleft({'at': timestamp(), 'tool': name, 'outcome': outcome,
                                'duration_ms': round(elapsed, 2)})

    def record_upstream(self, service, started, status, size, expected=False):
        entry = self.upstreams[service]
        entry['requests'] += 1
        entry['errors'] += not expected and (status is None or not 200 <= status < 300)
        entry['rate_limits'] += status == 429
        entry['bytes'] += size
        entry['statuses'][str(status) if status else 'network_or_body_error'] += 1
        entry['timings'].append((time.monotonic() - started) * 1000)
        entry['last_at'] = timestamp()

    def snapshot(self):
        now = time.monotonic()
        usage = resource.getrusage(resource.RUSAGE_SELF)
        cpu = usage.ru_utime + usage.ru_stime
        if now - self.cpu_at >= 1:
            self.cpu_percent = round(max(0, cpu - self.cpu_seconds) / (now - self.cpu_at) * 100, 2)
            self.cpu_at, self.cpu_seconds = now, cpu
        try:
            import os
            rss = int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
            memory_kind = 'current_rss'
        except (OSError, ValueError, IndexError):
            rss = usage.ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
            memory_kind = 'peak_rss'
        return {
            'started_at': self.started_at, 'uptime_seconds': round(now - self.started, 1), 'ready': self.ready,
            'tools': {'calls': self.calls, 'errors': self.errors, 'active': self.active,
                      'success_percent': round((self.calls - self.errors - self.active) / (self.calls - self.active) * 100, 1)
                      if self.calls > self.active else None, **distribution(self.timings)},
            'per_tool': [{'name': name, 'calls': e['calls'], 'errors': e['errors'], **distribution(e['timings'])}
                         for name, e in sorted(self.tools.items())],
            'upstreams': {name: {k: v for k, v in e.items() if k not in ('statuses', 'timings')} |
                         {'statuses': dict(e['statuses']), **distribution(e['timings'])}
                          for name, e in self.upstreams.items()},
            'rejected_requests': dict(self.rejections), 'recent': list(self.recent),
            'process': {'memory_bytes': rss, 'memory_kind': memory_kind, 'cpu_percent': self.cpu_percent},
            'observed_at': timestamp(),
            'note': 'Counters reset on restart. Durations cover handler execution, including waits; '
                    'invalid parameters rejected before execution are not tool calls. '
                    'Latency samples are bounded; CPU is process usage relative to one core.'}
