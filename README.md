# Wred

A small ASGI framework for JSON APIs. One file. JSON from `orjson`, server from `granian`.

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

Those are your problem. You can solve them without making them everyone else's.

## Use it

Python 3.11+. Clone the repo, then install it:

Procure your goods, yeah, use `uv` not `pip`, its 2026:

```bash
$ git clone https://gitman.io/git/patx/wred
$ cd wred
$ uv sync
```

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
Checking that credential is your job.

## Responses

Return a dict or list for JSON with HTTP 200. Return bytes for
`application/octet-stream`. No `json()` helper. No ceremony.

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

```bash
uv run granian --interface asginl --workers 1 example_app.app:app
```

Open <http://127.0.0.1:8000>. Demo data lives in memory and disappears on restart.
