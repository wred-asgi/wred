"""Signup, login, refresh cookies, and bearer authentication for the demo."""

from asyncio import to_thread
from functools import wraps
from hashlib import pbkdf2_hmac, sha256
from http.cookies import CookieError, SimpleCookie
from secrets import compare_digest, token_bytes, token_urlsafe
from time import time

import orjson

from .rate_limit import rate_limit

token_lifetime = 3600
refresh_lifetime = 7 * 24 * 3600
refresh_cookie_name = 'notebook_refresh'


def same_origin_request(request):
    # HTML forms cannot supply this custom header; cross-origin fetch requires a preflight.
    if request.headers.get('x-notebook-request') != '1':
        return False
    if request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin':
        return False
    # Browsers send Origin on POST; API clients may omit it but still need the custom header.
    origin = request.headers.get('origin')
    expected = f'{request.scope.get("scheme", "http")}://{request.headers.get("host", "")}'
    return origin is None or origin == expected


def refresh_cookie(request, value, max_age):
    cookie = SimpleCookie()
    cookie[refresh_cookie_name] = value
    morsel = cookie[refresh_cookie_name]
    morsel['path'] = '/api'
    morsel['httponly'] = True
    morsel['samesite'] = 'Strict'
    morsel['max-age'] = max_age
    # HTTPS deployments get Secure; plain HTTP remains usable for the localhost demo.
    if request.scope.get('scheme') == 'https':
        morsel['secure'] = True
    return 'Set-Cookie', morsel.OutputString()


def read_refresh_cookie(request):
    cookie = SimpleCookie()
    try:
        cookie.load(request.headers.get('cookie', ''))
    except CookieError:
        return ''
    morsel = cookie.get(refresh_cookie_name)
    return morsel.value if morsel else ''


def token_response(token, username):
    return {
        'access_token': token,
        'token_type': 'bearer',
        'expires_in': token_lifetime,
        'user': {'id': username},
    }


async def read_credentials(request):
    try:
        data = await request.json()
    except orjson.JSONDecodeError:
        raise ValueError('Invalid JSON body') from None
    if not isinstance(data, dict):
        raise ValueError('Send a JSON object with username and password')
    username, password = data.get('username'), data.get('password')
    if not isinstance(username, str) or not isinstance(password, str):
        raise ValueError('Username and password must be strings')
    username = username.strip().casefold()
    if not 1 <= len(username) <= 64 or not 15 <= len(password) <= 128:
        raise ValueError('Use a username of 1–64 and a password of 15–128 characters')
    return username, password


async def hash_password(password, salt):
    return await to_thread(pbkdf2_hmac, 'sha256', password.encode('utf-8'), salt, 600_000)


def protected(database):
    def decorator(handler):
        @wraps(handler)
        async def wrapper(request, *args, **kwargs):
            header = request.headers.get('authorization', '')
            scheme, _, token = header.partition(' ')
            user = None
            if scheme.lower() == 'bearer' and token:
                digest = sha256(token.encode('utf-8')).hexdigest()
                user = await database.get_access_token(digest, time())
            if user is None:
                return (
                    {'error': 'Unauthorized'},
                    'application/json',
                    401,
                    [('WWW-Authenticate', 'Bearer')],
                )
            request.user = {'id': user['user_id']}
            request.login_id = user['login_id']
            response = await handler(request, *args, **kwargs)
            if isinstance(response, tuple):
                body, content_type, status = response[:3]
                headers = list(response[3]) if len(response) == 4 else []
            else:
                body, content_type, status, headers = response, 'application/json', 200, []
            return body, content_type, status, headers + [('Cache-Control', 'no-store')]

        return wrapper

    return decorator


def register_routes(app, database):
    """Register authentication endpoints on the supplied Wred app."""

    @app.route('/api/signup', methods=['POST'])
    @rate_limit(requests=10, seconds=60)
    async def signup(request):
        try:
            username, password = await read_credentials(request)
        except ValueError as error:
            return {'error': str(error)}, 'application/json', 400
        salt = token_bytes(16)
        password_hash = await hash_password(password, salt)
        # MongoDB's unique _id also handles signups in different workers.
        if not await database.create_user(username, salt, password_hash):
            return {'error': 'Username already exists'}, 'application/json', 409
        return {'id': username}, 'application/json', 201

    @app.route('/api/login', methods=['POST'])
    @rate_limit(requests=5, seconds=60)
    async def login(request):
        if not same_origin_request(request):
            return (
                {'error': 'A same-origin request with X-Notebook-Request: 1 is required'},
                'application/json',
                403,
            )
        try:
            username, password = await read_credentials(request)
        except ValueError as error:
            return {'error': str(error)}, 'application/json', 400
        # Use a dummy record for unknown users so failed logins still perform password hashing.
        record = await database.get_user(username)
        salt = record['salt'] if record else bytes(16)
        password_hash = await hash_password(password, salt)
        if record is None or not compare_digest(password_hash, record['password_hash']):
            return {'error': 'Invalid credentials'}, 'application/json', 401
        login_id = token_urlsafe(16)
        refresh = token_urlsafe(32)
        access = token_urlsafe(32)
        now = time()
        # Persist digests and Unix timestamps so sessions survive restarts.
        await database.create_login(
            username, login_id, sha256(refresh.encode()).hexdigest(), now + refresh_lifetime,
            sha256(access.encode()).hexdigest(), now + token_lifetime,
        )
        return (
            token_response(access, username),
            'application/json',
            200,
            [('Cache-Control', 'no-store'), refresh_cookie(request, refresh, refresh_lifetime)],
        )

    @app.route('/api/refresh', methods=['POST'])
    @rate_limit(requests=30, seconds=60)
    async def refresh(request):
        if not same_origin_request(request):
            return (
                {'error': 'A same-origin request with X-Notebook-Request: 1 is required'},
                'application/json',
                403,
            )
        digest = sha256(read_refresh_cookie(request).encode()).hexdigest()
        access = token_urlsafe(32)
        now = time()
        username = await database.refresh_login(
            digest, sha256(access.encode()).hexdigest(), now + token_lifetime, now,
        )
        if username is None:
            return (
                {'error': 'Unauthorized'},
                'application/json',
                401,
                [('Cache-Control', 'no-store'), refresh_cookie(request, '', 0)],
            )
        # Reuse the cookie while issuing a fresh access token; concurrent tabs work.
        return (
            token_response(access, username),
            'application/json',
            200,
            [('Cache-Control', 'no-store')],
        )

    @app.route('/api/me')
    @protected(database)
    async def me(request):
        return request.user

    @app.route('/api/logout', methods=['POST'])
    @protected(database)
    async def logout(request):
        await database.revoke_login(request.login_id)
        return {'logged_out': True}, 'application/json', 200, [refresh_cookie(request, '', 0)]
