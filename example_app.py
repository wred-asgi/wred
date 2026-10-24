"""
    example_app
    ~~~~~~~~~~~

    Validation, JWT authentication, SSE, and frontend serving with Wred.

    Install the example dependencies and run from the repository root::

        python -m pip install -e '.[server]' PyJWT msgspec sse-starlette servestatic
        export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
        mkdir -p frontend
        echo '<h1>Wred example</h1>' > frontend/index.html
        weft example_app:app

    ServeStatic serves frontend/index.html at http://127.0.0.1:8000/.
    Replace the placeholder HTML with your frontend build. Existing files take
    priority over Wred routes; keep greet, me, and events out of that directory.

    POST /greet accepts a JSON object with a name of 1–40 characters.
    GET /me requires a Bearer token signed with JWT_SECRET using HS256,
    with issuer "demo", audience "greetings", a nonempty subject, and an
    expiration time.

    GET /events streams five messages using sse-starlette. Watch them arrive::

        curl -N http://127.0.0.1:8000/events

    EventSourceResponse is returned directly from a Wred handler, while
    ServeStatic wraps the app. If you use a reverse proxy, configure it to pass
    SSE events through without buffering.

    :copyright: (c) 2026 by Harrison Erd.
    :license: BSD-3-Clause, see LICENSE for more details.
"""
import asyncio
import os
from pathlib import Path
from typing import Annotated

import jwt
import msgspec
from servestatic import ServeStaticASGI
from sse_starlette import EventSourceResponse
from wred import App


SECRET = os.environ['JWT_SECRET']
api = App()


class Greeting(msgspec.Struct, forbid_unknown_fields=True):
    name: Annotated[str, msgspec.Meta(min_length=1, max_length=40)]


def verified_user(authorization):
    scheme, _, token = (authorization or '').partition(' ')

    if scheme.lower() != 'bearer' or not token:
        raise jwt.InvalidTokenError('Bearer token required')

    claims = jwt.decode(
        token, SECRET, algorithms=['HS256'],
        issuer='demo', audience='greetings',
        options={'require': ['sub', 'exp', 'iss', 'aud']},
    )

    if not claims['sub']:
        raise jwt.InvalidTokenError('User required')

    return claims['sub']


@api.route('/greet', methods=['POST'])
async def greet(request):
    try:
        data = msgspec.json.decode(await request.body(), type=Greeting)

    except msgspec.DecodeError:
        return {'detail': 'Invalid greeting'}, [('Content-Type', 'application/json')], 422

    return {'message': f'Hello, {data.name}!'}


@api.route('/me')
async def me(request):
    try:
        user = verified_user(request.headers.get('authorization'))

    except jwt.InvalidTokenError:
        return {'detail': 'Not authenticated'}, [
            ('Content-Type', 'application/json'),
            ('WWW-Authenticate', 'Bearer'),
        ], 401

    return {'user': user}


@api.route('/events')
async def events(request):
    async def messages():
        for number in range(5):
            yield {'data': f'Event {number}'}
            await asyncio.sleep(1)

    return EventSourceResponse(messages())


app = ServeStaticASGI(
    api,
    root=Path(__file__).resolve().parent / 'frontend',
    index_file=True,
)
