# Wred

A tiny Python/ASGI backend for HTML and JavaScript apps. One file. JSON from
`orjson`, server from Granian. Pronounced "red".

Your API needs to return some JSON. It probably doesn't need a goddamn cathedral.

## What you get

- Async handlers, explicit HTTP methods, and fixed or parameterized routes.
- Headers, query parameters, cached body reads, and JSON parsing.
- JSON responses, custom response tuples, and a small-file helper.
- Callable ASGI response support and routing relative to mounted paths.

## What you don't get

Auth, sessions, databases, validation schemas, templates, CORS, CSRF protection,
rate limiting, dependency injection, generated docs, background jobs, WebSockets,
or built-in streaming.

Use existing ASGI middleware for CORS, authentication, sessions, or compression.
[Starlette's middleware](https://starlette.dev/middleware/#using-middleware-in-other-frameworks)
can wrap Wred directly. Your app chooses its dependencies; Wred doesn't need to
know they exist.

## Install and run

Python 3.11+. For a new project:

```bash
uv init my-app
cd my-app
uv add wred
```

In an existing uv project, just `uv add wred`. Granian and orjson are included.

Save as `app.py`:

```python
from wred import App

app = App()

@app.route('/')
async def hello(request):
    return {'hello': 'world'}
```

And smoke it:

```bash
uv run granian --interface asginl app:app
```

Open <http://127.0.0.1:8000>. Wred is HTTP-only; `asginl` disables lifespan.
Unsupported protocols raise `RuntimeError` without sending HTTP messages,
following [ASGI guidance](https://asgi.readthedocs.io/en/latest/specs/main.html#protocol-specifications).
You can also export a middleware wrapper as `app`.

## Routes

Handlers are async and receive a request. Methods default to `['GET']`;
path parameters are strings passed by keyword.

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

Different methods can have separate handlers on the same path. Fixed routes
win over dynamic routes for that method; dynamic routes follow registration
order. Registering the same path and method again replaces its handler.
Unmatched paths or methods return JSON 404. No automatic HEAD, OPTIONS, or 405.

Mounting at `/api` makes a `/users` route handle `/api/users`. Routing respects
`root_path`; `request.path` and the original scope keep the full incoming path.

## Requests

| API | Returns |
| --- | --- |
| `request.path` | Path without the query string. |
| `request.method` | HTTP method. |
| `request.headers` | Decoded header dict; use lowercase keys. |
| `request.scope` | Original ASGI scope, including client, scheme, and middleware state. |
| `request.query()` | Cached dict of string keys and values. No `await`. |
| `await request.body()` | Cached raw bytes. |
| `await request.json()` | Parsed JSON; an empty body becomes `{}`. |

```python
@app.route('/search')
async def search(request):
    return {'q': request.query().get('q', '')}
```

Query parameters preserve blank values; repeated keys keep the last value.
JSON can be an object, array, or scalar. Validate inputs and convert types yourself.

Authentication middleware can populate the scope for handlers to check.
Starlette's SessionMiddleware uses `request.scope['session']`; its cookies are
signed, not encrypted. Wred doesn't supply a session property.

## Responses

Dicts and lists become JSON with HTTP 200. Bytes default to
`application/octet-stream`. Custom responses use
`(body, content_type, status[, headers])`:

| Handler return | Response |
| --- | --- |
| `{'hello': 'world'}` | JSON object, 200. |
| `[{'id': 1}, {'id': 2}]` | JSON array, 200. |
| `b'hello', 'text/plain', 200` | Text response. |
| `{'id': 3}, 'application/json', 201, [('Location', '/items/3')]` | Created resource with a custom header. |
| `b'', 'text/plain', 303, [('Location', '/')]` | Redirect. |
| `b'', 'application/json', 204` | No content. |

Dicts and lists always use `application/json`, including inside tuples.
Other tuple bodies must be bytes. Headers are string pairs; repeated
`Set-Cookie` headers are supported.

Return a callable ASGI response object to let it manage status, headers, and
body through `(scope, receive, send)`. Reuse external response classes for
streaming, downloads, or SSE. Use ASGI middleware for behavior across routes.

## Static files

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

`static(filename, root=...)` returns `(bytes, content_type, status)`.
The root is required and accepts a string or `Path`. MIME types are guessed;
missing, unreadable, or outside-root files return plain-text 404, including
symlink escapes. Files are read in a worker thread, entirely into memory.
Small files. Don't feed it a movie.

## Errors

Malformed JSON, invalid UTF-8 query strings, and `WredRequestError` produce
JSON 400 responses: `{'error': message}`. Raise `WredRequestError` from a handler
for application validation failures. Unsupported response types produce JSON
500 errors; other exceptions propagate.

## Example app

The [notebook demo](https://gitman.io/patx/wred/src/example_app) includes signup,
login, refresh cookies, logout, protected note CRUD, and rate limiting.
Those features belong to the app, not Wred.

```bash
git clone https://gitman.io/git/patx/wred
cd wred
uv sync
uv run granian --interface asginl --workers 1 example_app.app:app
```

Open <http://127.0.0.1:8000>. Data lives in memory and disappears on restart.

## Benchmarks

`GET /` returning `{"hello": "world"}` on October 13, 2026. Three runs per
framework, rotating their order each round.

| Framework | Median requests/sec | Min | Max |
| --- | ---: | ---: | ---: |
| Wred 0.01 | **272,088** | 262,187 | 277,656 |
| BlackSheep 2.6.4 | 211,619 | 205,719 | 220,455 |
| MicroPie 0.32 | 207,720 | 197,520 | 216,010 |

Python 3.14.4, Granian 2.8.4, eight workers, HTTP/1 keep-alive, asyncio,
no access logging. `wrk -t4 -c256 -d20s --latency`, five-second warmups.
Client and server shared a machine over loopback. All nine measured runs had
zero socket errors or non-success responses.

About 31% more requests/sec than MicroPie for this workload. It's a tiny JSON
response, not your whole application. Benchmark your own shit.
