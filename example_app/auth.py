"""Signup, login, refresh cookies, and bearer authentication for the demo."""

from asyncio import to_thread
from functools import wraps
from hashlib import pbkdf2_hmac, sha256
from http.cookies import CookieError, SimpleCookie
from secrets import compare_digest, token_bytes, token_urlsafe
from time import monotonic

from wred import WredRequestError
from .rate_limit import rate_limit
from .storage import users, tokens, refresh_tokens

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


def issue_access_token(username, login_id):
    token = token_urlsafe(32)
    # Store a digest so the server does not retain the raw bearer credential.
    digest = sha256(token.encode('utf-8')).hexdigest()
    # Tag tokens with their login ID so logout can revoke all tokens from that login.
    tokens[digest] = {
        'user_id': username,
        'login_id': login_id,
        'expires_at': monotonic() + token_lifetime,
    }
    return {
        'access_token': token,
        'token_type': 'bearer',
        'expires_in': token_lifetime,
        'user': {'id': username},
    }


def revoke_login(login_id):
    for store in (tokens, refresh_tokens):
        for digest, record in list(store.items()):
            if record['login_id'] == login_id:
                del store[digest]


async def read_credentials(request):
    data = await request.json()
    if not isinstance(data, dict):
        raise WredRequestError('Send a JSON object with username and password')
    username, password = data.get('username'), data.get('password')
    if not isinstance(username, str) or not isinstance(password, str):
        raise WredRequestError('Username and password must be strings')
    username = username.strip().casefold()
    if not 1 <= len(username) <= 64 or not 15 <= len(password) <= 128:
        raise WredRequestError('Use a username of 1–64 and a password of 15–128 characters')
    return username, password


async def hash_password(password, salt):
    return await to_thread(pbkdf2_hmac, 'sha256', password.encode('utf-8'), salt, 600_000)


async def validate_access_token(token):
    digest = sha256(token.encode('utf-8')).hexdigest()
    record = tokens.get(digest)
    if record is None:
        return None
    if record['expires_at'] <= monotonic():
        tokens.pop(digest, None)
        return None
    return {'id': record['user_id']}


def protected(handler):
    @wraps(handler)
    async def wrapper(request, *args, **kwargs):
        header = request.headers.get('authorization', '')
        scheme, _, token = header.partition(' ')
        user = None
        if scheme.lower() == 'bearer' and token:
            user = await validate_access_token(token)
        if user is None:
            return (
                {'error': 'Unauthorized'},
                'application/json',
                401,
                [('WWW-Authenticate', 'Bearer')],
            )
        request.user = user
        request.access_token = token
        response = await handler(request, *args, **kwargs)
        if isinstance(response, tuple):
            body, content_type, status = response[:3]
            headers = list(response[3]) if len(response) == 4 else []
        else:
            body, content_type, status, headers = response, 'application/json', 200, []
        return body, content_type, status, headers + [('Cache-Control', 'no-store')]

    return wrapper


def register_routes(app):
    """Register authentication endpoints on the supplied Wred app."""

    @app.route('/api/signup', methods=['POST'])
    @rate_limit(requests=10, seconds=60)
    async def signup(request):
        username, password = await read_credentials(request)
        salt = token_bytes(16)
        password_hash = await hash_password(password, salt)
        # Check after the await so simultaneous signups cannot overwrite the same account.
        if username in users:
            return {'error': 'Username already exists'}, 'application/json', 409
        users[username] = {'salt': salt, 'password_hash': password_hash}
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
        username, password = await read_credentials(request)
        # Use a dummy record for unknown users so failed logins still perform password hashing.
        record = users.get(username, {'salt': bytes(16), 'password_hash': bytes(32)})
        password_hash = await hash_password(password, record['salt'])
        if username not in users or not compare_digest(password_hash, record['password_hash']):
            return {'error': 'Invalid credentials'}, 'application/json', 401
        login_id = token_urlsafe(16)
        refresh = token_urlsafe(32)
        # Store only its digest and a fixed absolute expiry; refreshes do not extend this deadline.
        refresh_tokens[sha256(refresh.encode()).hexdigest()] = {
            'user_id': username,
            'login_id': login_id,
            'expires_at': monotonic() + refresh_lifetime,
        }
        return (
            issue_access_token(username, login_id),
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
        record = refresh_tokens.get(digest)
        if record is None or record['expires_at'] <= monotonic():
            if record is not None:
                revoke_login(record['login_id'])
            return (
                {'error': 'Unauthorized'},
                'application/json',
                401,
                [('Cache-Control', 'no-store'), refresh_cookie(request, '', 0)],
            )
        # Reuse the cookie while issuing a fresh memory-only access token; concurrent tabs work.
        return (
            issue_access_token(record['user_id'], record['login_id']),
            'application/json',
            200,
            [('Cache-Control', 'no-store')],
        )

    @app.route('/api/me')
    @protected
    async def me(request):
        return request.user

    @app.route('/api/logout', methods=['POST'])
    @protected
    async def logout(request):
        digest = sha256(request.access_token.encode('utf-8')).hexdigest()
        login_id = tokens[digest]['login_id']
        revoke_login(login_id)
        return {'logged_out': True}, 'application/json', 200, [refresh_cookie(request, '', 0)]
