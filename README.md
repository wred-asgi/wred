# Wred

Wred handles HTTP routing, requests, and JSON responses. Need CORS, sessions,
authentication, or compression? Wrap it with existing ASGI middleware.
No need to reinvent what ASGI already makes possible.

Your API needs to return some JSON. It probably doesn't need a goddamn cathedral.

Oh, and it's pronounced "red", like the color.

## What you get

- Async handlers and a route decorator.
- Request headers, cached body reads, and JSON parsing.
- JSON responses (dicts and lists) & static file serving.
- Response tuples: `(body, content_type, status[, headers])`.

## What you don't get

Auth, sessions, databases, validation schemas, templates, CORS, CSRF protection,
rate limiting, dependency injection, generated docs, background jobs, WebSockets,
streaming, or a reason to argue about folder structure.

Your application chooses those pieces. Use existing libraries without making
them everyone else's dependency. Wred doesn't need to know they exist.

## Use it

Python 3.11+. Install from PyPI:

Procure your goods, yeah, use `uv` not `pip`, its 2026:

```bash
$ uv init my-app
$ cd my-app
$ uv add wred
```

Already have a uv project? Just run `uv add wred`. Granian and orjson come with it.

Put this in your pipe (`app.py`):

```python
from wred import App

app = App()

@app.route('/')
async def say_hello(request):
    return {'hello': 'world'}
```

And smoke it:

```bash
uv run granian --interface asginl app:app
```

`asginl` disables lifespan handling. Wred doesn't implement it.

The server can run a middleware wrapper around Wred as its `app` too.
[Starlette's middleware](https://starlette.dev/middleware/#using-middleware-in-other-frameworks)
works with other ASGI applications: CORS, GZip, TrustedHost, HTTPS redirects,
and cookie sessions are available without changing Wred. Install only what
your app needs; Starlette isn't a Wred dependency. Choose standard ASGI wrappers
rather than integrations that require another framework's application internals.

## Routes

Handlers are async. The first argument is the request. `methods` defaults to
`['GET']`; path parameters arrive as strings, passed by keyword.

```python
@app.route('/users/{user_id}')
async def get_user(request, user_id):
    return {'id': user_id}

@app.route('/users', methods=['POST'])
async def create_user(request):
    return await request.json(), 'application/json', 201

@app.route('/users/{user_id}', methods=['PUT', 'PATCH'])
async def update_user(request, user_id):
    return {'id': user_id, 'method': request.method}
```

Different handlers can share a path with different methods. Fixed routes win
over dynamic routes for the requested method; dynamic routes are checked in
registration order. Registering the same path and method again replaces its handler.
Unmatched paths or methods return JSON 404. No automatic HEAD, OPTIONS, or 405.

## Requests

| API | What you get |
| --- | --- |
| `request.path` | URL path, without the query string. |
| `request.method` | HTTP method, such as `GET` or `POST`. |
| `request.headers` | Dictionary of decoded headers; use lowercase names. |
| `request.scope` | Raw ASGI scope: query string, client address, scheme, etc. |
| `await request.body()` | Raw bytes, cached after the first read. |
| `await request.json()` | Parsed JSON; an empty body becomes `{}`. |

JSON parsing isn't validation. Arrays and scalars parse too. Check your own inputs.

```python
from urllib.parse import parse_qs
from wred import WredRequestError

@app.route('/echo', methods=['POST'])
async def echo(request):
    data = await request.json()
    if not isinstance(data, dict):
        raise WredRequestError('Send a JSON object')
    return {'received': data}

@app.route('/search')
async def search(request):
    query = parse_qs(request.scope.get('query_string', b'').decode('utf-8'))
    return {'q': query.get('q', [''])[0]}
```

Read a bearer credential with `request.headers.get('authorization', '')`.
Check it in your application or let authentication middleware populate the ASGI
scope, then enforce access in your handlers. Middleware can also add session
data: Starlette's SessionMiddleware exposes it through `request.scope['session']`,
not a Wred-specific session property. Its cookies are signed, not encrypted.

## Responses

Return a dict or list for JSON with HTTP 200. Return bytes for
`application/octet-stream`. No `json()` helper. No ceremony.

Handlers can also return callable ASGI response objects. Wred awaits them with
`(scope, receive, send)`, letting the response handle its own headers, status,
and body. Response classes from ASGI libraries can work directly; Wred doesn't
need a dependency or adapter for them.

For a custom response, return `(body, content_type, status)` or
`(body, content_type, status, headers)`. Headers are a list of string pairs,
so repeated headers such as `Set-Cookie` work too.

```python
@app.route('/items')
async def items(request):
    return [{'id': 1}, {'id': 2}]

@app.route('/items', methods=['POST'])
async def create_item(request):
    return {'id': 3}, 'application/json', 201, [('Location', '/items/3')]

@app.route('/old')
async def redirect(request):
    return b'', 'text/plain', 303, [('Location', '/')]

@app.route('/items/{item_id}', methods=['DELETE'])
async def delete_item(request, item_id):
    return b'', 'application/json', 204
```

Dicts and lists always get `application/json`, even inside a tuple.
Other bodies must be bytes: encode text yourself, for example
`return 'hello'.encode(), 'text/plain; charset=utf-8', 200`.
Custom headers can carry cookies, cache policies, CORS rules, or `Retry-After`;
Wred sends them, you decide what they mean.
For behavior across every route, an ASGI wrapper can intercept requests and
responses to apply CORS or compression. Keep that plumbing out of your handlers.

## Static files

`await app.static(filename, root=directory)` returns `(bytes, content_type, status)`.
The root is required and accepts a string or `Path`.

```python
from pathlib import Path

static_root = Path(__file__).parent / 'static'

@app.route('/')
async def index(request):
    return await app.static('index.html', root=static_root)

@app.route('/static/{filename}')
async def asset(request, filename):
    return await app.static(filename, root=static_root)
```

The helper guesses the MIME type and rejects files outside the root, including
symlink escapes. Missing or unreadable files return a plain-text 404. Files are
read in a worker thread, entirely into memory. Small files. Don't feed it a movie.

## Errors

Malformed JSON and `WredRequestError` become HTTP 400 with `{'error': message}`.
Unsupported handler response types become JSON 500 errors. Other exceptions
aren't caught by Wred; fix your shit or handle them in your application.

## Example app

The [`example_app`](https://gitman.io/patx/wred/src/example_app) notebook demonstrates signup, login,
refresh cookies, logout, protected endpoints, note CRUD, and rate limiting.
Those features belong to the example, not the framework.
Clone the repository to try it:

```bash
git clone https://gitman.io/git/patx/wred
cd wred
uv sync
uv run granian --interface asginl --workers 1 example_app.app:app
```

Open <http://127.0.0.1:8000>. Demo data lives in memory and disappears on restart.

## Benchmarks

`GET /` returning `{"hello": "world"}`, measured on October 13, 2026.
Three runs per framework, with the run order rotated each round.

| Framework | Median requests/sec | Min | Max |
| --- | ---: | ---: | ---: |
| Wred 0.01 | **272,088** | 262,187 | 277,656 |
| BlackSheep 2.6.4 | 211,619 | 205,719 | 220,455 |
| MicroPie 0.32 | 207,720 | 197,520 | 216,010 |

Python 3.14.4, Granian 2.8.4, eight workers, HTTP/1 keep-alive, asyncio,
and access logging disabled. `wrk -t4 -c256 -d20s --latency`, after a
five-second warmup for each run. Client and server shared the same machine
over loopback. All nine measured runs had zero socket errors or non-success responses.

Wred delivered about 31% more requests/sec than MicroPie in this workload.
It's a tiny JSON response, not your database, auth, or entire application.
Benchmark your own shit.
