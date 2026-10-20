[![Logo](https://patx.gitman.io/wred/wred-logo.png)](https://harrisonerd.com/wred)

[Wred](https://harrisonerd.com/wred) is a tiny and fast Python backend for JavaScript web apps. View the documentation and source [here](https://gitman.io/patx/wred).

Wred 0.11 preserves the explicit content type in response tuples with dict or
list bodies while JSON-encoding the body. See the
[0.11 release notes](https://harrisonerd.com/wred/tutorial/releases.html#version-011)
and [API reference](https://harrisonerd.com/wred/tutorial/api-reference.html#responses).

## Installation

```bash
$ pip install 'wred[server]'
```

## Quick Start

```python
from wred import App

app = App()

@app.route('/')
async def index(request):
    return {'hello': 'world'}

# run with `weft app:app`
```
