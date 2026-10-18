# -*- coding: utf-8 -*-
"""
    example_app.app
    ~~~~~~~~~~~~~~~

    Build the notebook demo explicitly with ``create_app``. Importing this
    module does not create an application or a database client. See
    ``example_app.asgi`` for the server entry point and startup instructions.

    :copyright: (c) 2026 by Harrison Erd.
    :license: BSD-3-Clause, see LICENSE for more details.
"""

import os
from pathlib import Path

from servestatic import ServeStaticASGI

from wred import App

from . import auth, notes, pages
from .rate_limit import RateLimiter
from .storage import Database

STATIC_ROOT = Path(__file__).resolve().parent / 'static'


class NotebookApp:
    """Own the example's database lifecycle while keeping Wred HTTP-only."""

    def __init__(self, database):
        self.database = database
        self.http = App()
        rate_limit = RateLimiter()
        pages.register_routes(self.http, rate_limit)
        auth.register_routes(self.http, self.database, rate_limit)
        notes.register_routes(self.http, self.database)
        self.http = ServeStaticASGI(
            self.http,
            root=str(STATIC_ROOT),
            index_file=True,
            autorefresh=True,
            max_age=0,
        )
        self.http.add_files(str(STATIC_ROOT), prefix='static/')

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'lifespan':
            return await self.http(scope, receive, send)
        while True:
            message = await receive()
            if message['type'] == 'lifespan.startup':
                try:
                    await self.database.initialize()
                except Exception as error:
                    await self.database.close()
                    await send({
                        'type': 'lifespan.startup.failed',
                        'message': str(error),
                    })
                    return
                await send({'type': 'lifespan.startup.complete'})
            elif message['type'] == 'lifespan.shutdown':
                await self.database.close()
                await send({'type': 'lifespan.shutdown.complete'})
                return


def create_app(mongodb_uri=None, database_name=None, *, database=None):
    """Build an app with independent rate limits and an owned database.

    Without ``database``, create a MongoDB client using the explicit URI and
    name, falling back to ``MONGODB_URI`` and ``MONGODB_DATABASE``. Defaults
    are ``mongodb://127.0.0.1:27017`` and ``wred_notebook``.

    An injected ``database`` takes precedence over URI and name settings.
    The app calls its async ``initialize`` and ``close`` methods during
    lifespan startup and shutdown, including closing it on startup failure.
    """
    if database is None:
        database = Database(
            mongodb_uri
            if mongodb_uri is not None
            else os.environ.get('MONGODB_URI', 'mongodb://127.0.0.1:27017'),
            database_name
            if database_name is not None
            else os.environ.get('MONGODB_DATABASE', 'wred_notebook'),
        )
    return NotebookApp(database)
