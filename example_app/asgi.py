# -*- coding: utf-8 -*-
"""
    example_app.asgi
    ~~~~~~~~~~~~~~~~

    Run the notebook demo with MongoDB listening on localhost:27017::

        python -m pip install -e '.[server]' pymongo servestatic
        weft example_app.asgi:app

    Open http://127.0.0.1:8000. MongoDB preserves accounts, sessions,
    and notes. ServeStatic serves the frontend in the same ASGI process,
    with file refresh and caching settings configured for local development.
    Set MONGODB_URI and MONGODB_DATABASE to choose another server/database.
    Rate limits are isolated per app and process-local. Use HTTPS outside
    localhost.

    :copyright: (c) 2026 by Harrison Erd.
    :license: BSD-3-Clause, see LICENSE for more details.
"""

from .app import create_app


app = create_app()
