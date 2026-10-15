"""Run the notebook demo from the repository root:

    uv sync
    uv run weft example_app.app:app

Open http://127.0.0.1:8000. Users, tokens, and notes disappear on restart.
Login is restored with an HttpOnly refresh cookie; API calls use bearer tokens.
Storage and rate limits are process-local. Production needs shared storage and HTTPS.
"""

from wred import App

from . import auth, notes, pages

app = App()
pages.register_routes(app)
auth.register_routes(app)
notes.register_routes(app)
