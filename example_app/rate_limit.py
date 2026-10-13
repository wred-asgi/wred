"""Application-owned sliding-window rate limiting, independent of Wred."""

from collections import deque
from functools import wraps
from math import ceil
from time import monotonic

rate_buckets = {}  # (handler, client IP, window) -> accepted request timestamps.


def rate_limit(requests, seconds):
    def decorator(handler):
        @wraps(handler)
        async def wrapper(request, *args, **kwargs):
            now = monotonic()
            # Drop inactive clients so their buckets do not remain in memory forever.
            for key, timestamps in list(rate_buckets.items()):
                if timestamps[-1] <= now - key[2]:
                    del rate_buckets[key]
            # Use ASGI's client address, not an untrusted X-Forwarded-For header.
            client = (request.scope.get('client') or ('unknown', 0))[0]
            key = (handler.__name__, client, seconds)
            timestamps = rate_buckets.setdefault(key, deque())
            while timestamps and timestamps[0] <= now - seconds:
                timestamps.popleft()
            if len(timestamps) >= requests:
                retry_after = max(1, ceil(timestamps[0] + seconds - now))
                return (
                    {'error': 'Too many requests', 'retry_after': retry_after},
                    'application/json',
                    429,
                    [('Retry-After', str(retry_after)), ('Cache-Control', 'no-store')],
                )
            # Reserve the slot before any await, so concurrent requests cannot bypass it.
            timestamps.append(now)
            return await handler(request, *args, **kwargs)

        return wrapper

    return decorator
