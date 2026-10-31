"""Bounded upstream I/O and shared retry-header parsing."""
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from errors import TraktError

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
API_CONCURRENCY = 2


def retry_after(headers, default=60):
    value = headers.get('Retry-After', '')
    try:
        return max(1, int(value))
    except ValueError:
        try:
            return max(1, int((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()) + 1)
        except (ValueError, TypeError, OverflowError):
            return default


async def bounded_request(http, method, url, *, max_bytes=MAX_RESPONSE_BYTES, metrics=None, service=None, expected_statuses=(), **kwargs):
    started = time.monotonic()
    status, size = None, 0
    try:
        async with http.stream(method, url, **kwargs) as response:
            content = bytearray()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > max_bytes:
                    raise TraktError('Upstream response exceeds the size limit. Request a smaller dataset.')
                content.extend(chunk)
                size += len(chunk)
            status = response.status_code
            headers = {k: v for k, v in response.headers.items() if k not in ('content-encoding', 'content-length')}
            return httpx.Response(response.status_code, content=bytes(content), headers=headers, request=response.request)
    finally:
        if metrics is not None:
            metrics.record_upstream(service, started, status, size, expected=status in expected_statuses)
