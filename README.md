[![Logo](https://patx.gitman.io/wred/wred-logo.png)](https://harrisonerd.com/wred)

[Wred](https://harrisonerd.com/wred) is a Python ASGI router for JSON APIs.
It uses `orjson` to read and write JSON. Pronounced "red".

Handlers are async functions. They receive a request and return a JSON-serializable
value, bytes, response tuple, or callable ASGI response. Routes support path parameters
and explicit HTTP methods. The request object provides headers, query parameters,
cached body reads, and JSON parsing. Response tuples let you set the status,
content type, and headers; callable ASGI responses can handle streaming.

Bring your own validation, authentication, and database libraries. Call them
directly from your handlers and handle their errors there, or in middleware.
Wred does not configure them for you or require particular libraries. `orjson`
is its only required dependency; you also need an ASGI server to run the app.

Sessions, CORS, CSRF protection, and rate limiting need middleware or other
application setup. Wred has no built-in form or multipart parsing, templates,
dependency injection, generated API docs, background jobs, static file serving,
or streaming helpers. It handles HTTP only, with no WebSocket support.

## Install and run

Requires Python 3.11 or later.

```bash
pip install wred
```

Save the following in `app.py`:

```python
from wred import App

app = App()

@app.route('/')
async def hello(request):
    return {'hello': 'world'}
```

To run it with Weft, install the optional `server` extra:

```bash
pip install 'wred[server]'
weft app:app
```

You can use another ASGI server instead of Weft.

Open <http://127.0.0.1:8000>. Wred is HTTP-only.
Unsupported protocols raise `RuntimeError` without sending HTTP messages,
following [ASGI guidance](https://asgi.readthedocs.io/en/latest/specs/main.html#protocol-specifications).
You can also export a middleware wrapper as `app`.

For public deployments, serve Wred behind a reverse proxy such as
[Nginx](https://nginx.org/en/docs/http/ngx_http_core_module.html#client_max_body_size)
or [Cloudflare](https://developers.cloudflare.com/waf/). Configure request-body
size limits, HTTPS, timeouts, and rate limiting at that layer. Wred buffers request
bodies in memory and does not impose a body-size limit. Restrict direct access to
the ASGI server so clients cannot bypass the proxy's protections.

See [`example_app.py`](https://gitman.io/patx/wred/src/example_app.py) for validation with msgspec, JWT
authentication with PyJWT, server-sent events with `sse-starlette`, and frontend serving with `ServeStatic`.
Setup instructions are in its module docstring; run it with `weft example_app:app`.

## Routes

Handlers are async and receive a request. Methods default to `('GET',)`;
path parameters are strings passed by keyword.

```python
@app.route('/users/{user_id}')
async def get_user(request, user_id):
    return {'id': user_id}

@app.route('/users', methods=['POST'])
async def create_user(request):
    return await request.json(), [('Content-Type', 'application/json')], 201

@app.route('/users/{user_id}', methods=['PUT', 'PATCH'])
async def update_user(request, user_id):
    return {'id': user_id, 'method': request.method}
```

Different methods can have separate handlers on the same path. Fixed routes
win over dynamic routes for that method; dynamic routes follow registration
order. Registering the same path and method again replaces its handler.
Trailing slashes are ignored when registering and matching routes: `/users`
and `/users/` use the same handler, without a redirect.
Unmatched paths or methods return JSON 404. No automatic HEAD, OPTIONS, or 405.

If you mount your Wred application at `/api`, a `/users` route in that app
would become `/api/users`. Routing respects `root_path`; `request.path` and
the original scope keep the full incoming path.

Wred does not provide a mount method. To serve another ASGI app alongside Wred,
use an external router and mount the other app at `/example` and Wred at `/`,
with the catch-all last. Handle ASGI lifespan events in the outer app;
Wred only accepts HTTP scopes.

## Requests

Since Wred 0.10, `request.query` is a cached property, matching `request.headers`.
Wred 0.9 uses `request.query()`; remove the parentheses when upgrading.

* `request.path` -> Path without the query string
* `request.method` -> HTTP method
* `request.headers` -> Header dict decoded and cached on first access, with lowercase ASCII names and Latin-1 values; repeated Cookie fields join with `; `, other repeated names keep their last value
* `request.scope` -> Original ASGI scope, including client, scheme, and middleware state
* `request.query` -> Dict of string keys and values, parsed and cached on first access.
* `await request.body()` -> Cached body raw bytes
* `await request.json()` -> Parsed JSON body; an empty body becomes `{}`

```python
@app.route('/search')
async def search(request):
    return {'q': request.query.get('q', '')}
```

Query parameters preserve blank values; repeated keys keep the last value.
Invalid UTF-8 in raw or percent-encoded query bytes raises `UnicodeDecodeError`.
JSON can be an object, array, or scalar. Wred does not validate it or convert
field types.

Authentication middleware can populate the scope for handlers to check.

## Responses

Wred handles return values in three ways:

* A callable is awaited with `(scope, receive, send)` as an ASGI response.
* A tuple sets the body, headers, and status: `(body, headers, status)`.
* Any other value gets HTTP 200. Bytes are sent unchanged with
  `application/octet-stream`; other values are serialized with `orjson.dumps`
  and get `application/json`.

Since Wred 0.13, both plain returns and tuple bodies accept any value supported
by `orjson.dumps`, including strings, numbers, booleans, and `None`. Strings
become quoted JSON strings; use bytes for raw text. Returning `None`, including
by falling off the end of a handler, sends JSON `null` with HTTP 200.

Explicit tuples send only the supplied headers; no content type is added, even
for JSON bodies. Bytes pass through unchanged; all other tuple bodies are
JSON-encoded. Headers are string pairs: names are lowercased and ASCII-encoded,
and values are Latin-1-encoded. Order and repeated headers such as `Set-Cookie`
are preserved. Use `[]` to send no headers.


* `{'hello': 'world'}` -> JSON object, 200 |
* `[{'id': 1}, {'id': 2}]` -> JSON array, 200 |
* `42` -> JSON number `42`, 200 |
* `'hello'` -> JSON string `"hello"`, 200 |
* `True` -> JSON boolean `true`, 200 |
* `None` -> JSON `null`, 200 |
* `b'hello'` -> Raw bytes, `application/octet-stream`, 200 
* `(b'hello', [('Content-Type', 'text/plain')], 200)` -> Raw text, 200
* `({'id': 3}, [('Content-Type', 'application/json'), ('Location', '/items/3')], 201)` -> JSON with a location header, 201
* `({'error': 'Invalid'}, [('Content-Type', 'application/problem+json')], 400)` -> JSON with a custom media type, 400
* `(b'', [('Location', '/')], 303)` -> Redirect with an empty body
* `(b'', [], 204)` -> No content, no headers

Tuples are always interpreted as explicit responses. To return a tuple as JSON
array data, use a list or place it inside a response tuple, such as
`((1, 2), [('Content-Type', 'application/json')], 200)`.

Wred 0.12 replaced `(body, content_type, status[, headers])` with
`(body, headers, status)`. When upgrading, move explicit content types into the
headers list; four-item response tuples are no longer accepted.

Callable responses let you use ASGI response classes from other libraries for
streaming, downloads, or SSE. They control their own headers and body messages.

## Serving the frontend

Wred does not serve static files. Use a web server such as Caddy or Nginx,
a static host, or an ASGI app such as ServeStatic. A frontend development server
such as Vite can proxy API requests to Wred during development.

Serving the frontend and API from one origin lets browser code use relative
URLs such as `fetch('/api/hello')` without CORS configuration. If you use
separate origins, configure CORS in middleware and account for cookie and
credential rules. Opening HTML directly with `file://` does not avoid those
browser restrictions.

## Errors

Exceptions propagate to your ASGI server or middleware. Wred does not turn
exceptions into responses.

* Malformed JSON raises `orjson.JSONDecodeError`.
* Invalid UTF-8 query bytes (raw or percent-encoded) and non-ASCII request
  header names raise `UnicodeDecodeError` when those properties are accessed.
* Client disconnects during body reads raise `ConnectionError`.
* Bodies that `orjson.dumps` cannot serialize raise `orjson.JSONEncodeError`
  (a `TypeError` subclass).
* Response tuples with fewer or more than three items raise `ValueError`.
* Non-ASCII response header names or values outside Latin-1 raise
  `UnicodeEncodeError`.

For ordinary and tuple responses, serialization and header encoding finish
before Wred sends the response start message.

Return response tuples for expected application errors. Catch parsing errors
in your handler when you want a JSON 400 response:

```python
import orjson

@app.route('/items', methods=['POST'])
async def create_item(request):
    try:
        data = await request.json()
    except orjson.JSONDecodeError:
        return {'error': 'Invalid JSON body'}, [('Content-Type', 'application/json')], 400
    if not isinstance(data, dict) or not data.get('title'):
        return {'error': 'A title is required'}, [('Content-Type', 'application/json')], 400
    return data, [('Content-Type', 'application/json')], 201
```

Validate inputs before returning a streaming response. Once streaming starts,
you cannot change the status or replace the body with an error response.
Unhandled exceptions reach the server; Wred does not send a second response.

## Performance

Fixed routes use dictionary lookups. Parameterized routes are matched in
registration order. Headers and query parameters are parsed on first access
and cached. Reading the body buffers it in memory; later reads reuse those bytes.

See the [Web Frameworks Benchmark](https://web-frameworks-benchmark.vercel.app/result?l=python)
for benchmark results.
