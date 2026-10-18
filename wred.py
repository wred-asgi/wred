"""
Wred: An ultra micro ASGI API framework.
Wred is designed for lightweight JSON APIs, offering a minimalistic way to build
ASGI-compatible web services. It prioritizes simplicity and performance over all.
Copyright (c) 2026, Harrison Erd.
"""
__author__, __email__, __license__ = 'Harrison Erd', 'harrisonerd@gmail.com', 'BSD-3-Clause'
__version__ = '0.08'
from collections.abc import Awaitable, Callable
from asyncio import to_thread
from mimetypes import guess_type
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl
import orjson

class Request:
    """A request object encapsulating ASGI scope, receive, and send."""
    def __init__(self, scope: dict[str, Any], receive: Callable[[], Awaitable[dict[str, Any]]], send: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """Store the ASGI connection and decode request headers."""
        self.scope, self.receive, self.send = scope, receive, send
        self.path, self.method = scope['path'], scope['method']
        self.headers: dict[str, str] = {}
        for k, v in scope.get('headers', []):
            k, v = k.decode('latin-1').lower(), v.decode('latin-1')
            self.headers[k] = self.headers[k] + '; ' + v if k == 'cookie' and k in self.headers else v
        self._body = self._query = None

    def query(self) -> dict[str, str]:
        """Parse and cache query parameters; repeated keys keep their last value."""
        if self._query is None:
            self._query = dict(parse_qsl(self.scope.get('query_string', b'').decode(), keep_blank_values=True))
        return self._query

    async def body(self) -> bytes:
        """Read the request body from the ASGI receive stream."""
        if self._body is None:
            chunks = []
            while True:
                message = await self.receive()
                if message['type'] != 'http.request': raise ConnectionError("Client disconnected")
                chunks.append(message.get('body', b''))
                if not message.get('more_body'): break
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
        if scope['type'] != 'http': raise RuntimeError(f"Unsupported ASGI scope type: {scope['type']}")
        await self.handle_http(Request(scope, receive, send))

    async def handle_http(self, request: Request) -> None:
        """Handle HTTP requests with routing and JSON response support."""
        path = request.path
        root = request.scope.get('root_path', '').rstrip('/')
        if root and (path == root or path.startswith(root + '/')): path = path[len(root):] or '/'
        path = path.rstrip('/') or '/'
        method = request.method
        if path in self.routes and method in self.routes[path]:
            return await self.dispatch_response(request, await self.routes[path][method](request))
        parts = path.split('/')
        for pattern, handlers in self.pattern_routes.items():
            if (params := self.match_path(pattern, parts)) is not None and method in handlers:
                return await self.dispatch_response(request, await handlers[method](request, **params))
        await self.send_response(request.send, {"error": "Not Found"}, 404)

    async def dispatch_response(self, request: Request, response: Any) -> None:
        """Invoke an ASGI response or serialize an ordinary handler result."""
        if callable(response): await response(request.scope, request.receive, request.send)
        else: await self.send_response(request.send, response)

    async def send_response(self, send: Callable[[dict[str, Any]], Awaitable[None]], response: Any, status: int = 200) -> None:
        """Send JSON or (body, content_type, status[, headers]) with string header pairs."""
        body, content_type, headers = response, 'application/octet-stream', []
        if isinstance(response, tuple):
            body, content_type, status = response[:3]
            if len(response) == 4: headers = [(n.lower().encode('ascii'), v.encode('latin-1')) for n, v in response[3]]
        if isinstance(body, (dict, list)): body, content_type = orjson.dumps(body), 'application/json'
        elif not isinstance(body, bytes): raise TypeError("Response must be dict, list, bytes, or tuple")
        await send({'type': 'http.response.start', 'status': status, 'headers': [(b'content-type', content_type.encode('latin-1'))] + headers})
        await send({'type': 'http.response.body', 'body': body})

    def match_path(self, pattern: tuple[str, ...], parts: list[str]) -> dict[str, str] | None:
        """Match normalized paths and extract parameters."""
        if len(pattern) != len(parts): return None
        params = {}
        for p, part in zip(pattern, parts):
            if p.startswith('{') and p.endswith('}'): params[p[1:-1]] = part
            elif p != part: return None
        return params

    async def static(self, filename: str | Path, *, root: str | Path | None = 'static') -> tuple[bytes, str, int]:
        """Serve a small file inside root (default: ./static), off the event loop."""
        def read() -> tuple[bytes, str, int]:
            try:
                directory = Path(root or 'static').resolve()
                path = (directory / filename).resolve()
                if not path.is_relative_to(directory) or not path.is_file(): return b'Not Found', 'text/plain; charset=utf-8', 404
                return path.read_bytes(), guess_type(path.name)[0] or 'application/octet-stream', 200
            except (OSError, ValueError, RuntimeError): return b'Not Found', 'text/plain; charset=utf-8', 404
        return await to_thread(read)

    def route(self, path: str, methods: list[str] | tuple[str, ...] = ('GET',)) -> Callable:
        """Decorator to register routes with specific HTTP methods."""
        path = path.rstrip('/') or '/'
        def decorator(handler: Callable) -> Callable:
            target = self.pattern_routes if '{' in path and '}' in path else self.routes
            key = tuple(path.split('/')) if target is self.pattern_routes else path
            target.setdefault(key, {}).update({m.upper(): handler for m in methods})
            return handler
        return decorator

