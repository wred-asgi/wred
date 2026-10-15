"""
Wred: An ultra micro ASGI API framework.

Wred is designed for lightweight JSON APIs, offering a minimalistic way to build
ASGI-compatible web services. It prioritizes simplicity and performance over all.


Copyright (c) 2026, Harrison Erd.
"""

__author__ = 'Harrison Erd'
__email__ = 'harrisonerd@gmail.com'
__version__ = '0.05'
__license__ = 'BSD-3-Clause'

from collections.abc import Awaitable, Callable
from asyncio import to_thread
from mimetypes import guess_type
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl
import orjson


class WredResponseError(Exception):
    """Raised when a handler returns a non-JSON response."""
    pass

class WredRequestError(Exception):
    """Raised when a request cannot be processed (e.g., invalid body)."""
    pass


class Request:
    """A request object encapsulating ASGI scope, receive, and send."""
    def __init__(self, scope: dict[str, Any], receive: Callable[[], Awaitable[dict[str, Any]]], send: Callable[[dict[str, Any]], Awaitable[None]]):
        self.scope = scope
        self.receive = receive
        self.send = send
        self.path = scope['path']
        self.method = scope['method']
        self.headers = {k.decode(): v.decode() for k, v in scope.get('headers', [])}
        self._body = None
        self._query = None

    def query(self) -> dict[str, str]:
        """Parse and cache query parameters; repeated keys keep their last value."""
        if self._query is None:
            try:
                self._query = dict(parse_qsl(self.scope.get('query_string', b'').decode('utf-8'), keep_blank_values=True))
            except UnicodeDecodeError:
                raise WredRequestError("Invalid query string")
        return self._query

    async def body(self) -> bytes:
        """Read the request body from the ASGI receive stream."""
        if self._body is None:
            self._body = b""
            while True:
                message = await self.receive()
                if message['type'] != 'http.request':
                    raise WredRequestError("Client disconnected")
                self._body += message.get('body', b'')
                if not message.get('more_body', False):
                    break
        return self._body

    async def json(self) -> dict[str, Any]:
        """Parse the request body as JSON."""
        try:
            body = await self.body()
            return orjson.loads(body) if body else {}
        except orjson.JSONDecodeError:
            raise WredRequestError("Invalid JSON body")


class App:
    """A minimal ASGI application framework."""
    def __init__(self):
        self.routes: dict[str, dict[str, Callable]] = {}
        self.pattern_routes: dict[str, dict[str, Callable]] = {}

    async def __call__(self, scope: dict[str, Any], receive: Callable[[], Awaitable[dict[str, Any]]], send: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """Handle ASGI requests."""
        if scope['type'] != 'http':
            raise RuntimeError(f"Unsupported ASGI scope type: {scope['type']}")

        request = Request(scope, receive, send)
        await self.handle_http(request)

    async def handle_http(self, request: Request) -> None:
        """Handle HTTP requests with routing and JSON response support."""
        path = request.path
        root_path = request.scope.get('root_path', '').rstrip('/')
        if root_path and (path == root_path or path.startswith(root_path + '/')):
            path = path[len(root_path):] or '/'
        method = request.method
        try:
            # Check exact matches first
            if path in self.routes and method in self.routes[path]:
                handler = self.routes[path][method]
                response = await handler(request)
                await self.dispatch_response(request, response)
                return

            # Check dynamic routes
            for pattern, method_handlers in self.pattern_routes.items():
                params = self.match_path(pattern, path)
                if params is not None and method in method_handlers:
                    handler = method_handlers[method]
                    response = await handler(request, **params)
                    await self.dispatch_response(request, response)
                    return

            # No match found
            await self.send_response(request.send, {"error": "Not Found"}, status=404)

        except (WredResponseError, WredRequestError) as e:
            status = 400 if isinstance(e, WredRequestError) else 500
            await self.send_response(request.send, {"error": str(e)}, status=status)

    async def dispatch_response(self, request: Request, response: Any) -> None:
        """Invoke an ASGI response or serialize an ordinary handler result."""
        if callable(response):
            await response(request.scope, request.receive, request.send)
        else:
            await self.send_response(request.send, response)

    async def send_response(self, send: Callable[[dict[str, Any]], Awaitable[None]], response: Any, status: int = 200) -> None:
        """Send JSON or (body, content_type, status[, headers]) with string header pairs."""
        body, content_type = response, 'application/octet-stream'
        headers = []
        if isinstance(response, tuple) and len(response) in (3, 4):
            body, content_type, status = response[:3]
            if len(response) == 4:
                headers = [(name.lower().encode('ascii'), value.encode('latin-1')) for name, value in response[3]]
        if isinstance(body, (dict, list)):
            body, content_type = orjson.dumps(body), 'application/json'
        elif not isinstance(body, bytes):
            raise WredResponseError("Response must be a dictionary, list, bytes, or response tuple")
        await send({
            'type': 'http.response.start',
            'status': status,
            'headers': [(b'content-type', content_type.encode('ascii'))] + headers,
        })
        await send({'type': 'http.response.body', 'body': body})

    def match_path(self, pattern: str, path: str) -> dict[str, str] | None:
        """Match a path against a pattern and extract parameters."""
        pattern_parts = pattern.strip('/').split('/')
        path_parts = path.strip('/').split('/')
        if len(pattern_parts) != len(path_parts):
            return None

        params = {}
        for pattern_part, path_part in zip(pattern_parts, path_parts):
            if pattern_part.startswith('{') and pattern_part.endswith('}'):
                param_name = pattern_part[1:-1]
                params[param_name] = path_part
            elif pattern_part != path_part:
                return None
        return params

    async def static(self, filename: str | Path, *, root: str | Path) -> tuple[bytes, str, int]:
        """Serve a small file inside root; read its entire body off the event loop."""
        def read() -> tuple[bytes, str, int]:
            try:
                directory = Path(root).resolve()
                path = (directory / filename).resolve()
                if not path.is_relative_to(directory) or not path.is_file():
                    return b'Not Found', 'text/plain; charset=utf-8', 404
                body = path.read_bytes()
            except (OSError, ValueError, RuntimeError):
                return b'Not Found', 'text/plain; charset=utf-8', 404
            return body, guess_type(path.name)[0] or 'application/octet-stream', 200

        return await to_thread(read)

    def route(self, path: str, methods: list[str] = ['GET']) -> Callable:
        """Decorator to register routes with specific HTTP methods."""
        def decorator(handler: Callable) -> Callable:
            routes = self.pattern_routes if '{' in path and '}' in path else self.routes
            routes.setdefault(path, {}).update({m.upper(): handler for m in methods})
            return handler
        return decorator

