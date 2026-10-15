# [Wred](https://harrisonerd.com/wred) is a fast, composable Python backend for JavaScript web apps. View the documentation and source [here](https://gitman.io/patx/wred).

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

# save as `app.py`
# run with `weft app:app`
```