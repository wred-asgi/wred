# Wred

[Wred](https://harrisonerd.com/wred) A tiny and fast Python/ASGI backend JavaScript web apps. Pronounced "red".

Your API needs to return some JSON. It probably doesn't need a goddamn cathedral.

## What you get

- Async handlers, explicit HTTP methods, and fixed or parameterized routes.
- Headers, query parameters, cached body reads, and JSON parsing.
- JSON responses, custom response tuples, and a small-file helper.
- Callable ASGI response support and routing relative to mounted paths.
- Depends on `weft-server` and `orjson`. You can use any ASGI server.

## What you don't get

Auth, sessions, databases, validation schemas, templates, form or multipart
parsing, CORS, CSRF protection, rate limiting, dependency injection, generated
docs, background jobs, WebSockets, or built-in streaming.

Use existing ASGI middleware for CORS, authentication, sessions, or compression.
[Starlette's middleware](https://starlette.dev/middleware/#using-middleware-in-other-frameworks)
can wrap Wred directly for example... Your app chooses its dependencies; Wred doesn't need to
know they exist.

## Install and run

Python 3.11+. For a new project:

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

Run it with Weft, or any other ASGI server you like:

```bash
weft app:app
```

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
Trailing slashes are ignored when registering and matching routes: `/users`
and `/users/` use the same handler, without a redirect.
Unmatched paths or methods return JSON 404. No automatic HEAD, OPTIONS, or 405.

If you mount your Wred application at `/api`, a `/users` route in that app
would become `/api/users`. Routing respects `root_path`; `request.path` and
the original scope keep the full incoming path.

Wred deliberately leaves out a mount method to keep the core focused on small
HTTP APIs. To serve another ASGI app alongside Wred, use an external router such
as [Starlette's `Router` and `Mount`](https://starlette.dev/routing/): mount the
other app at `/example` and Wred at `/`, with the catch-all last. This keeps
application composition and lifecycle decisions outside Wred's core. This works
with pretty much every ASGI application you can think of.

## Requests

* `request.path` -> Path without the query string
* `request.method` -> HTTP method
* `request.headers` -> Header dict with lowercase names and Latin-1 values; repeated Cookie fields join with `; `, other repeated names keep their last value
* `request.scope` -> Original ASGI scope, including client, scheme, and middleware state
* `request.query()` -> Cached dict of string keys and values. No `await`!
* `await request.body()` -> Cached body raw bytes
* `await request.json()` -> Parsed JSON body; an empty body becomes `{}`

```python
@app.route('/search')
async def search(request):
    return {'q': request.query().get('q', '')}
```

Query parameters preserve blank values; repeated keys keep the last value.
Invalid UTF-8 in raw or percent-encoded query bytes raises `UnicodeDecodeError`.
JSON can be an object, array, or scalar. Validate inputs and convert types yourself.

Authentication middleware can populate the scope for handlers to check.
Starlette's SessionMiddleware uses `request.scope['session']`; its cookies are
signed, not encrypted. Wred doesn't supply a session property.

## Responses

Dicts and lists become `application/json` with HTTP 200. Bytes default to
`application/octet-stream`. Custom responses use `(body, content_type, status[, headers])`.
Tuple bodies must be bytes, dicts, or lists; dicts and lists always use `application/json`.
Headers are string pairs; repeated `Set-Cookie` headers are supported.

* `{'hello': 'world'}` -> JSON object, 200
* `[{'id': 1}, {'id': 2}]` -> JSON array, 200
* `b'hello', 'text/plain', 200` -> Text response
* `{'id': 3}, 'application/json', 201, [('Location', '/items/3')]` -> Created resource with a custom header
* `b'', 'text/plain', 303, [('Location', '/')]` -> Redirect
* `b'', 'application/json', 204` -> No content

You can also return a callable ASGI response object to let it manage status, headers, and
body through `(scope, receive, send)`. Reuse external response classes for
streaming, downloads, or SSE. Use ASGI middleware for behavior across routes.
For example Starlette's StreamingResponse can be returned directly in a Wred handler.

## Static files

```python
@app.route('/')
async def index(request):
    return await app.static('index.html')

@app.route('/static/{filename}')
async def asset(request, filename):
    return await app.static(filename)
```

`static(filename, root='static')` returns `(bytes, content_type, status)`.
Omitting `root`, passing `''`, or passing `None` uses the `static` directory in the
current working directory. Set `root` to a string or `Path` to use another directory.
MIME types are guessed. Files are read in a worker thread, entirely into memory.
All file and path errors propagate to your handler, middleware, or ASGI server.
Missing files raise `FileNotFoundError`, directories raise `IsADirectoryError`,
and permission or other filesystem failures retain their original exceptions.
Resolved paths outside the configured root, including symlink escapes, raise
`ValueError` before any file is read. Invalid paths can also raise `ValueError`.
The helper does not turn these errors into HTTP responses; catch exceptions in
your application or middleware to return a 404 or another status.
Small files. Don't feed it a movie.

## Errors

Exceptions propagate to your ASGI server or middleware. Malformed JSON raises
`orjson.JSONDecodeError`, invalid UTF-8 query bytes (raw or percent-encoded) raise `UnicodeDecodeError`,
client disconnects during body reads raise `ConnectionError`, and unsupported
response types raise `TypeError`. Wred does not turn exceptions into responses.
Malformed response tuples can raise `ValueError` during unpacking.

Return response tuples for expected application errors. Catch parsing errors
in your handler when you want a JSON 400 response:

```python
import orjson

@app.route('/items', methods=['POST'])
async def create_item(request):
    try:
        data = await request.json()
    except orjson.JSONDecodeError:
        return {'error': 'Invalid JSON body'}, 'application/json', 400
    if not isinstance(data, dict) or not data.get('title'):
        return {'error': 'A title is required'}, 'application/json', 400
    return data, 'application/json', 201
```

Validate inputs before returning a streaming response. Once streaming starts,
errors cannot replace its status or body; an unhandled exception propagates to
the server without Wred attempting a second response.

## Performance

Since there isn't much to Wred, it's really fast. What it lacks in features it gains in speed.

Wred running on Weft with 8 workers achieved up to 561,103 requests/second, with a median
of 549,344 requests/second across four runs. Average p99 latency was 3.65 ms, with
zero socket errors or non-success responses. Testing used `wrk` with 4 threads, 256 concurrent
connections, and 20-second runs on a Dell XPS 13 9350 with an Intel Core Ultra 7 256V (8 cores,
up to 4.8 GHz), running Ubuntu 26.04.1 LTS (Linux 6.17.0-1023-oem, x86-64).

With respect to the lack of features mentioned above, Wred is meant to be bare bones, it's really
an experiment of how minimal and fast an ASGI framework can be without being raw ASGI. For an
actual micro framework with lifespan, streaming, multipart and more check out [MicroPie](https://harrisonerd.com/micropie).

