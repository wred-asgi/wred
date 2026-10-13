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

# These opaque tokens are server-side login state, even though Wred has no sessions.
token_lifetime = 3600  # Each login token is valid for one hour.
refresh_lifetime = 7 * 24 * 3600  # A browser can restore its login for up to seven days.
refresh_cookie_name = 'notebook_refresh'  # HttpOnly means JavaScript cannot read this cookie.


def same_origin_request(request):  # Protect endpoints that issue or use browser cookies.
    # HTML forms cannot supply this custom header; cross-origin fetch requires a preflight.
    if request.headers.get('x-notebook-request') != '1':
        # This example provides no cross-origin preflight permission.
        return False
    # Fetch Metadata also distinguishes sibling sites from this exact origin.
    if request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin':
        # Reject cross-site and same-site-but-cross-origin browser requests.
        return False
    # Browsers send Origin on POST; API clients may omit it but still need the custom header.
    origin = request.headers.get('origin')
    # Use ASGI's scheme and Host; do not trust arbitrary forwarded-origin headers.
    expected = f"{request.scope.get('scheme', 'http')}://{request.headers.get('host', '')}"
    # A supplied Origin must match the origin serving this application.
    return origin is None or origin == expected


def refresh_cookie(request, value, max_age):  # Return one Set-Cookie header pair.
    # SimpleCookie handles cookie formatting rather than hand-building a credential header.
    cookie = SimpleCookie()
    # The value is a random opaque token, not a username or password.
    cookie[refresh_cookie_name] = value
    # Select its attributes through the cookie morsel returned by SimpleCookie.
    morsel = cookie[refresh_cookie_name]
    # Scope browser transmission to API routes rather than static assets.
    morsel['path'] = '/api'
    # Prevent JavaScript from reading the credential.
    morsel['httponly'] = True
    # Exclude cross-site requests as an additional CSRF defense.
    morsel['samesite'] = 'Strict'
    # A positive age persists across reloads; zero removes the cookie on logout.
    morsel['max-age'] = max_age
    # HTTPS deployments get Secure; plain HTTP remains usable for the localhost demo.
    if request.scope.get('scheme') == 'https':
        # A Secure cookie is only transmitted over HTTPS.
        morsel['secure'] = True
    # Wred encodes this string pair when sending the custom response headers.
    return 'Set-Cookie', morsel.OutputString()


def read_refresh_cookie(request):  # Only this server reads the HttpOnly credential.
    # Start with an empty parser when a request has no Cookie header.
    cookie = SimpleCookie()
    # Malformed cookie syntax must not become an unhandled server exception.
    try:
        # Browser requests may include other cookies alongside this one.
        cookie.load(request.headers.get('cookie', ''))
    # Treat an invalid cookie like an absent credential.
    except CookieError:
        # Validation will return Unauthorized without exposing parser details.
        return ''
    # Select only the application's refresh cookie.
    morsel = cookie.get(refresh_cookie_name)
    # Return its opaque value, or an empty string when it is absent.
    return morsel.value if morsel else ''


def issue_access_token(username, login_id):  # Both login and refresh issue bearer credentials.
    # Access tokens are random and remain in browser memory only.
    token = token_urlsafe(32)
    # Store a digest so the server does not retain the raw bearer credential.
    digest = sha256(token.encode('utf-8')).hexdigest()
    # Tag tokens with their login ID so logout can revoke all tokens from that login.
    tokens[digest] = {'user_id': username, 'login_id': login_id, 'expires_at': monotonic() + token_lifetime}
    # Return identity too, so a tab cannot silently change accounts during a refresh.
    return {'access_token': token, 'token_type': 'bearer', 'expires_in': token_lifetime, 'user': {'id': username}}


def revoke_login(login_id):  # Revoke this login while leaving other devices' logins active.
    # Access and refresh credentials share a login ID but live in different stores.
    for store in (tokens, refresh_tokens):
        # Copy entries before deleting them from the dictionary.
        for digest, record in list(store.items()):
            # Delete only credentials belonging to the specified login.
            if record['login_id'] == login_id:
                # Previously issued bearer tokens and the refresh cookie now stop working.
                del store[digest]


async def read_credentials(request):  # Shared validation for signup and login.
    # Parse the request as JSON; malformed JSON already produces HTTP 400 in Wred.
    data = await request.json()
    # Credentials must be an object, rather than an array or another JSON value.
    if not isinstance(data, dict):
        # Wred turns this application-raised request error into a JSON 400 response.
        raise WredRequestError('Send a JSON object with username and password')
    # Read both fields; missing fields are None and fail the validation below.
    username, password = data.get('username'), data.get('password')
    # Require strings before using string methods or passing passwords to hashing.
    if not isinstance(username, str) or not isinstance(password, str):
        # Treat malformed credentials as a bad request, rather than a server error.
        raise WredRequestError('Username and password must be strings')
    # Normalize usernames so "Alice" and "alice" refer to the same account.
    username = username.strip().casefold()
    # Keep usernames nonempty; allow passphrases of 15–128 characters without truncation.
    if not 1 <= len(username) <= 64 or not 15 <= len(password) <= 128:
        # Report the accepted lengths without exposing stored user information.
        raise WredRequestError('Use a username of 1–64 and a password of 15–128 characters')
    # Pass the validated values back to whichever endpoint requested them.
    return username, password


async def hash_password(password, salt):  # Salted PBKDF2 using only Python's standard library.
    # Run the expensive 600,000-iteration hash in a thread to keep the event loop free.
    return await to_thread(pbkdf2_hmac, 'sha256', password.encode('utf-8'), salt, 600_000)


async def validate_access_token(token):  # Return a user identity, or None if invalid.
    # Hash the random token to find its record without storing the bearer credential.
    digest = sha256(token.encode('utf-8')).hexdigest()
    # An unknown token has no record, so it cannot authenticate anyone.
    record = tokens.get(digest)
    # Reject missing records before checking their expiry or user ID.
    if record is None:
        # The protected decorator will turn this into an Unauthorized response.
        return None
    # Compare against a monotonic clock so system clock changes cannot extend a login.
    if record['expires_at'] <= monotonic():
        # Remove an expired token when it is presented; it cannot be reused.
        tokens.pop(digest, None)
        # An expired token is no longer proof of an authenticated login.
        return None
    # Expose only the identity, never the password hash or stored token record.
    return {'id': record['user_id']}


def protected(handler):  # Wrap a handler with authentication before Wred calls it.
    # Keep the original handler's name and docstring on the wrapper.
    @wraps(handler)
    async def wrapper(request, *args, **kwargs):  # Preserve dynamic route parameters too.
        # Read the Authorization header; an absent header behaves like an empty value.
        header = request.headers.get('authorization', '')
        # Separate "Bearer" from the token in "Authorization: Bearer <token>".
        scheme, _, token = header.partition(' ')
        # Start unauthenticated; only an accepted bearer token can set the user.
        user = None
        # Accept case-insensitive Bearer and require a nonempty credential.
        if scheme.lower() == 'bearer' and token:
            # Check the application's token store and expiry before invoking the handler.
            user = await validate_access_token(token)
        # Missing, unknown, expired, and revoked tokens all deny access.
        if user is None:
            # Return a JSON error with HTTP 401 without running the protected handler.
            # WWW-Authenticate identifies Bearer as the required authentication scheme.
            return {'error': 'Unauthorized'}, 'application/json', 401, [('WWW-Authenticate', 'Bearer')]
        # Attach the authenticated identity for the protected handler to use.
        request.user = user
        # Retain this request's token so logout can revoke precisely this login.
        request.access_token = token
        # Forward the request and path parameters to the original async handler.
        response = await handler(request, *args, **kwargs)
        # Preserve custom statuses/headers; ordinary dicts and lists still become JSON.
        if isinstance(response, tuple):
            # The fourth tuple value is optional, so three-value responses remain valid.
            body, content_type, status = response[:3]
            # Copy existing headers before adding our privacy policy.
            headers = list(response[3]) if len(response) == 4 else []
        else:
            # Default JSON responses use HTTP 200 without extra handler boilerplate.
            body, content_type, status, headers = response, 'application/json', 200, []
        # Keep every protected response out of browser and intermediary caches.
        return body, content_type, status, headers + [('Cache-Control', 'no-store')]
    # Give the route decorator the wrapper, rather than the unprotected function.
    return wrapper


def register_routes(app):
    """Register authentication endpoints on the supplied Wred app."""
    # Register a public signup endpoint; send {"username": "alice", "password": "a long passphrase"}.
    @app.route('/api/signup', methods=['POST'])
    # Limit account creation per client IP before performing expensive password hashing.
    @rate_limit(requests=10, seconds=60)
    async def signup(request):  # Signup creates an account; login issues its access token.
        # Parse and validate the submitted credentials using the shared helper.
        username, password = await read_credentials(request)
        # Give each account a unique random salt, even when users choose identical passwords.
        salt = token_bytes(16)
        # Derive a password hash without blocking other requests on the event loop.
        password_hash = await hash_password(password, salt)
        # Check after the await so simultaneous signups cannot overwrite the same account.
        if username in users:
            # HTTP 409 means the requested username conflicts with an existing account.
            return {'error': 'Username already exists'}, 'application/json', 409
        # Store only the salt and derived hash in this demo's user dictionary.
        users[username] = {'salt': salt, 'password_hash': password_hash}
        # Return the public identity with HTTP 201 Created; do not return password material.
        return {'id': username}, 'application/json', 201


    # Register a public login endpoint; submit the same username and password as signup.
    @app.route('/api/login', methods=['POST'])
    # Count every login attempt, including invalid credentials, toward the client IP's budget.
    @rate_limit(requests=5, seconds=60)
    async def login(request):  # A successful login returns a new opaque bearer token.
        # Cookie-setting login requests need the same CSRF checks as cookie-based refreshes.
        if not same_origin_request(request):
            # A cross-origin page must not be able to log this browser into another account.
            return {'error': 'A same-origin request with X-Notebook-Request: 1 is required'}, 'application/json', 403
        # Validate the JSON credentials just as signup does.
        username, password = await read_credentials(request)
        # Use a dummy record for unknown users so failed logins still perform password hashing.
        record = users.get(username, {'salt': bytes(16), 'password_hash': bytes(32)})
        # Hash the submitted password using the stored salt and the same work factor.
        password_hash = await hash_password(password, record['salt'])
        # Compare hashes in constant time rather than comparing the original passwords.
        if username not in users or not compare_digest(password_hash, record['password_hash']):
            # Use the same message for unknown users and incorrect passwords.
            return {'error': 'Invalid credentials'}, 'application/json', 401
        # Create one identity for this login, separate from any other device's login.
        login_id = token_urlsafe(16)
        # Generate a separate credential for restoring access after a page reload.
        refresh = token_urlsafe(32)
        # Store only its digest and a fixed absolute expiry; refreshes do not extend this deadline.
        refresh_tokens[sha256(refresh.encode()).hexdigest()] = {'user_id': username, 'login_id': login_id, 'expires_at': monotonic() + refresh_lifetime}
        # Return the bearer token as JSON; Set-Cookie stores the refresh token outside JavaScript.
        return issue_access_token(username, login_id), 'application/json', 200, [('Cache-Control', 'no-store'), refresh_cookie(request, refresh, refresh_lifetime)]


    # The browser calls this on reload and when an access token expires.
    @app.route('/api/refresh', methods=['POST'])
    # Refresh is cheaper than password hashing but still gets a request budget.
    @rate_limit(requests=30, seconds=60)
    async def refresh(request):  # This endpoint alone authenticates with the refresh cookie.
        # Require a custom header and reject cross-origin requests before inspecting cookies.
        if not same_origin_request(request):
            # SameSite is defense in depth, not the sole CSRF control.
            return {'error': 'A same-origin request with X-Notebook-Request: 1 is required'}, 'application/json', 403
        # Hash the cookie value to look up the server-side record.
        digest = sha256(read_refresh_cookie(request).encode()).hexdigest()
        # Unknown, expired, or revoked cookies cannot create new access tokens.
        record = refresh_tokens.get(digest)
        # Expiry uses the original login's deadline, even after repeated reloads.
        if record is None or record['expires_at'] <= monotonic():
            # Revoke related access tokens too when a known login has expired.
            if record is not None:
                # Remove all credentials associated with this expired login.
                revoke_login(record['login_id'])
            # Clear stale browser cookies and report that a new login is required.
            return {'error': 'Unauthorized'}, 'application/json', 401, [('Cache-Control', 'no-store'), refresh_cookie(request, '', 0)]
        # Reuse the cookie while issuing a fresh memory-only access token; concurrent tabs work.
        return issue_access_token(record['user_id'], record['login_id']), 'application/json', 200, [('Cache-Control', 'no-store')]


    # Register GET /api/me; the route must register the protected wrapper, not the original handler.
    @app.route('/api/me')
    # Put @protected below @app.route because Python applies decorators from bottom to top.
    @protected
    async def me(request):  # This handler runs only after the token has been validated.
        # Return the identity supplied by the decorator, rather than trusting a client user ID.
        return request.user


    # Register POST /api/logout; send the same Authorization header used for /api/me.
    @app.route('/api/logout', methods=['POST'])
    # Require a valid login before attempting to revoke its token.
    @protected
    async def logout(request):  # Logout revokes this token; other logins remain active.
        # Hash the authenticated token to locate exactly the record created during login.
        digest = sha256(request.access_token.encode('utf-8')).hexdigest()
        # Find the login that issued this valid bearer token.
        login_id = tokens[digest]['login_id']
        # Revoke the refresh credential and every access token issued for the same login.
        revoke_login(login_id)
        # Confirm logout and delete the cookie; other devices' independent logins remain active.
        return {'logged_out': True}, 'application/json', 200, [refresh_cookie(request, '', 0)]
