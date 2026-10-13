"""Application-owned sliding-window rate limiting, independent of Wred."""
from collections import deque
from functools import wraps
from math import ceil
from time import monotonic

rate_buckets = {}  # (handler, client IP, window) -> accepted request timestamps.


def rate_limit(requests, seconds):  # A sliding-window decorator, owned by this application.
    # Construct a decorator that can be placed beneath @app.route.
    def decorator(handler):
        # Preserve the original function's identity and documentation.
        @wraps(handler)
        async def wrapper(request, *args, **kwargs):
            # A monotonic clock makes windows independent of wall-clock adjustments.
            now = monotonic()
            # Drop inactive clients so their buckets do not remain in memory forever.
            for key, timestamps in list(rate_buckets.items()):
                # Each key records its own window length, which may differ by endpoint.
                if timestamps[-1] <= now - key[2]:
                    # The whole bucket has aged out of its window.
                    del rate_buckets[key]
            # Use ASGI's client address, not an untrusted X-Forwarded-For header.
            client = (request.scope.get('client') or ('unknown', 0))[0]
            # Keep different endpoints' request budgets independent.
            key = (handler.__name__, client, seconds)
            # A deque efficiently removes the oldest accepted requests.
            timestamps = rate_buckets.setdefault(key, deque())
            # Expire each timestamp that no longer belongs to this sliding window.
            while timestamps and timestamps[0] <= now - seconds:
                # Newer timestamps stay in order at the right end.
                timestamps.popleft()
            # Reject excess requests before password hashing or other handler work begins.
            if len(timestamps) >= requests:
                # Tell clients exactly how many whole seconds to wait before retrying.
                retry_after = max(1, ceil(timestamps[0] + seconds - now))
                # Our fourth response tuple value carries Retry-After and a cache policy.
                return {'error': 'Too many requests', 'retry_after': retry_after}, 'application/json', 429, [('Retry-After', str(retry_after)), ('Cache-Control', 'no-store')]
            # Reserve the slot before any await, so concurrent requests cannot bypass it.
            timestamps.append(now)
            # Allow the original handler to process the request and route parameters.
            return await handler(request, *args, **kwargs)
        # Give Wred the limited wrapper instead of the original function.
        return wrapper
    # Return the configured decorator for use on each endpoint.
    return decorator
