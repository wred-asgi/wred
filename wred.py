"""
Wred: An ultra micro ASGI API framework.
Copyright (c) 2026, Harrison Erd.
"""
__author__, __email__, __license__ = 'Harrison Erd', 'harrisonerd@gmail.com', 'BSD-3-Clause'
__version__ = '0.13'
from collections.abc import Awaitable, Callable
from functools import cached_property
from typing import Any
from urllib.parse import parse_qsl
import orjson

class Request:
    """A request object encapsulating ASGI scope, receive, and send."""
    def __init__(self, scope: dict[str, Any], receive: Callable[[], Awaitable[dict[str, Any]]], send: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """Store the ASGI connection and initialize request caches."""
        self.scope, self.receive, self.send = scope, receive, send
        self.path, self.method = scope['path'], scope['method']
        self._body = None

    @cached_property
    def headers(self) -> dict[str, str]:
        """Decode and cache headers, joining duplicates with commas (semicolons for Cookie)."""
        headers: dict[str, str] = {}
        for k, v in self.scope.get('headers', []):
            k, v = k.decode('ascii').lower(), v.decode('latin-1')
            headers[k] = headers[k] + ('; ' if k == 'cookie' else ', ') + v if k in headers else v
        return headers

    @cached_property
    def query(self) -> dict[str, str]:
        """Parse and cache query parameters on first access; repeated keys keep their last value."""
        return dict(parse_qsl(self.scope.get('query_string', b'').decode(), keep_blank_values=True, errors='strict'))

    async def body(self) -> bytes:
        """Read the request body from the ASGI receive stream."""
        if self._body is None:
            chunks = []
            while True:
                message = await self.receive()
                if message['type'] != 'http.request':
                    raise ConnectionError("Client disconnected")
                chunks.append(message.get('body', b''))
                if not message.get('more_body'):
                    break
            self._body = b''.join(chunks)
        return self._body

    async def json(self) -> Any:
        """Parse the request body as JSON."""
        body = await self.body()
        return orjson.loads(body) if body else {}

class App:
    """A minimal ASGI application framework."""
    def __init__(self) -> None:
        """Create fixed and pre-split dynamic route tables."""
        self.routes: dict[str, dict[str, Callable]] = {}
        self.pattern_routes: dict[tuple[str, ...], dict[str, Callable]] = {}

    async def __call__(self, scope: dict[str, Any], receive: Callable[[], Awaitable[dict[str, Any]]], send: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """Handle ASGI requests."""
        if scope['type'] != 'http':
            raise RuntimeError(f"Unsupported ASGI scope type: {scope['type']}")
        request = Request(scope, receive, send)
        path = request.path
        root = scope.get('root_path', '').rstrip('/')
        if root and (path == root or path.startswith(root + '/')):
            path = path[len(root):] or '/'
        path = path.rstrip('/') or '/'
        method = request.method
        if (handlers := self.routes.get(path)) is not None and (handler := handlers.get(method)) is not None:
            response = await handler(request)
        else:
            parts = path.split('/')
            for pattern, handlers in self.pattern_routes.items():
                if (params := self.match_path(pattern, parts)) is not None and method in handlers:
                    response = await handlers[method](request, **params)
                    break
            else:
                return await self.send_response(send, {"error": "Not Found"}, 404)
        if callable(response):
            await response(scope, receive, send)
        else:
            await self.send_response(send, response)

    async def send_response(self, send: Callable[[dict[str, Any]], Awaitable[None]], response: Any, status: int = 200) -> None:
        """Send JSON or (body, headers, status) with string header pairs."""
        if isinstance(response, tuple):
            response, headers, status = response
            headers = [(n.lower().encode('ascii'), v.encode('latin-1')) for n, v in headers]
        else:
            content_type = b'application/octet-stream' if isinstance(response, bytes) else b'application/json'
            headers = [(b'content-type', content_type)]
        if not isinstance(response, bytes):
            response = orjson.dumps(response)
        await send({'type': 'http.response.start', 'status': status, 'headers': headers})
        await send({'type': 'http.response.body', 'body': response})

    def match_path(self, pattern: tuple[str, ...], parts: list[str]) -> dict[str, str] | None:
        """Match normalized paths and extract parameters."""
        if len(pattern) != len(parts): return None
        params = {}
        for p, part in zip(pattern, parts):
            if p.startswith('{') and p.endswith('}'):
                params[p[1:-1]] = part
            elif p != part:
                return None
        return params

    def route(self, path: str, methods: list[str] | tuple[str, ...] = ('GET',)) -> Callable:
        """Decorator to register routes with specific HTTP methods."""
        path = path.rstrip('/') or '/'
        def decorator(handler: Callable) -> Callable:
            target = self.pattern_routes if '{' in path and '}' in path else self.routes
            key = tuple(path.split('/')) if target is self.pattern_routes else path
            target.setdefault(key, {}).update({m.upper(): handler for m in methods})
            return handler
        return decorator
