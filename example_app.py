"""
    example_app
    ~~~~~~~~~~~

    Greeting validation and JWT authentication with Wred and msgspec.

    Install the example dependencies and run from the repository root::

        python -m pip install -e '.[server]' PyJWT msgspec
        export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
        weft app:app

    POST /greet accepts a JSON object with a name of 1–40 characters.
    GET /me requires a Bearer token signed with JWT_SECRET using HS256,
    with issuer "demo", audience "greetings", a nonempty subject, and an
    expiration time.

    :copyright: (c) 2026 by Harrison Erd.
    :license: BSD-3-Clause, see LICENSE for more details.
"""
import os
from typing import Annotated

import jwt
import msgspec
from wred import App


SECRET = os.environ['JWT_SECRET']
app = App()


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


@app.route('/greet', methods=['POST'])
async def greet(request):
    try:
        data = msgspec.json.decode(await request.body(), type=Greeting)

    except msgspec.DecodeError:
        return {'detail': 'Invalid greeting'}, 'application/json', 422

    return {'message': f'Hello, {data.name}!'}


@app.route('/me')
async def me(request):
    try:
        user = verified_user(request.headers.get('authorization'))

    except jwt.InvalidTokenError:
        return {'detail': 'Not authenticated'}, 'application/json', 401, [
            ('WWW-Authenticate', 'Bearer'),
        ]

    return {'user': user}
