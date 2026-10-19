[![Logo](https://patx.gitman.io/wred/wred-logo.png)](https://harrisonerd.com/wred)

[Wred](https://harrisonerd.com/wred) is a tiny and fast Python backend for JavaScript web apps. View the documentation and source [here](https://gitman.io/patx/wred).

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
