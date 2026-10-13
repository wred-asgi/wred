"""Wred Notebook: a complete, commented application built on Wred.

From the repository root:
    uv sync
    uv run granian --interface asginl --workers 1 examples.app:app

Or, inside a virtual environment:
    python3 -m pip install .
    granian --interface asginl --workers 1 examples.app:app

Open http://127.0.0.1:8000, create an account, and write a note.
The browser keeps its bearer token in memory and restores login with an HttpOnly cookie.
Users, login tokens, and notes reset when this single-process demo restarts.
Production applications need shared storage and HTTPS; rate limits here are process-local.

Example layout:
    app.py         Creates the app and registers each group of routes.
    pages.py       Browser UI, static assets, redirect, health, and rate-limit demo.
    auth.py        Passwords, bearer tokens, refresh cookies, and auth endpoints.
    notes.py       Private note CRUD, validation, filtering, and export.
    rate_limit.py  Reusable application-level throttling decorator.
    storage.py     Shared in-memory users, credentials, and notes.
    static/        Browser HTML, CSS, and JavaScript.

API walkthrough:
    POST /api/signup                  {"username": "alice", "password": "a long passphrase"}
    POST /api/login                   Same credentials; returns access_token.
    POST /api/refresh                 Restore access using the browser's refresh cookie.
    GET  /api/me                      Send Authorization: Bearer <access_token>.
    GET  /api/notes?q=idea&limit=5&offset=0
    POST /api/notes                   {"title": "An idea", "body": "Details", "pinned": false}
    GET  /api/notes/{note_id}          Read an owned note.
    PATCH /api/notes/{note_id}         Change selected fields.
    PUT  /api/notes/{note_id}          Replace title/body/pinned fields.
    DELETE /api/notes/{note_id}        Returns HTTP 204 with an empty body.
    GET  /api/notes/export             Download this user's notes as a JSON array.
    POST /api/logout                  Revoke the token used for this request.
    GET  /api/rate-limit-demo          Three requests per client IP every ten seconds.

All note endpoints require the bearer header. Login and refresh also require
X-Notebook-Request: 1, an application-level CSRF defense. The UI and API share
an origin, so CORS is unnecessary. Wred stays unchanged.
"""

from wred import App

# Each module owns its handlers and registers them on the same application.
from . import auth, notes, pages

# This is the ASGI application Granian imports using examples.app:app.
app = App()
# Public routes serve the browser UI and demonstrate basic responses.
pages.register_routes(app)
# Authentication routes handle signup, login, refresh, profile, and logout.
auth.register_routes(app)
# Note routes demonstrate authenticated resource access and CRUD.
notes.register_routes(app)
