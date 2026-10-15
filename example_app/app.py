"""Run the notebook demo with MongoDB listening on localhost:27017:

    uv sync --extra example
    uv run --extra example weft example_app.app:app

Open http://127.0.0.1:8000. MongoDB preserves accounts, sessions, and notes.
Set MONGODB_URI and MONGODB_DATABASE to choose another server/database.
Rate limits are process-local. Use HTTPS outside localhost.
"""

import os

from wred import App

from . import auth, notes, pages
from .storage import Database


class NotebookApp:
    """Own the example's database lifecycle while keeping Wred HTTP-only."""

    def __init__(self, mongodb_uri, database_name):
        self.database = Database(mongodb_uri, database_name)
        self.http = App()
        pages.register_routes(self.http)
        auth.register_routes(self.http, self.database)
        notes.register_routes(self.http, self.database)

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
                    await send({'type': 'lifespan.startup.failed', 'message': str(error)})
                    return
                await send({'type': 'lifespan.startup.complete'})
            elif message['type'] == 'lifespan.shutdown':
                await self.database.close()
                await send({'type': 'lifespan.shutdown.complete'})
                return


def create_app(mongodb_uri=None, database_name=None):
    """Build an app with one native async MongoDB client per worker."""
    return NotebookApp(
        mongodb_uri if mongodb_uri is not None else os.environ.get('MONGODB_URI', 'mongodb://127.0.0.1:27017'),
        database_name if database_name is not None else os.environ.get('MONGODB_DATABASE', 'wred_notebook'),
    )


app = create_app()
