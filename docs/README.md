# [Wred](https://harrisonerd.com/wred) is a tiny and fast Python backend for JavaScript web apps. View the documentation and source [here](https://gitman.io/patx/wred).

## Installation

```bash
$ pip install wred
```

## Quick Start

```python
from wred import App

app = App()

@app.route("/")
async def index(request):
    return {"hello": "world"}
```

## Serving the frontend

Use whatever you want to serve your frontend. Wred works with ASGI middleware
such as ServeStatic, Starlette's
[`FileResponse`](https://starlette.dev/responses/#fileresponse) and
[`StaticFiles`](https://starlette.dev/staticfiles/), web servers such as Caddy,
frontend dev servers such as Vite, and other hosting or build tools. These are
options, not requirements.
See the [frontend serving examples](https://gitman.io/patx/wred#serving-the-frontend)
in the full README. The notebook example uses PyMongo and ServeStatic as its
own dependencies.
