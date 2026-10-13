"""Public page/assets, redirect, health check, and a rate-limit demonstration."""
from pathlib import Path

from .rate_limit import rate_limit

# Resolve assets relative to this file, not the terminal's working directory.
static_root = Path(__file__).parent / 'static'


def register_routes(app):
    """Register the browser UI and public demonstration endpoints."""
    # GET / serves the browser application through the app's built-in file helper.
    @app.route('/')
    async def home(request):  # Every handler receives Wred's Request object.
        # Await the file read; the helper returns (body, content_type, status).
        body, content_type, status = await app.static('index.html', root=static_root)
        # A fourth tuple value adds response headers without introducing another class.
        return body, content_type, status, [('Cache-Control', 'no-cache')]


    # This route serves the app's stylesheet and JavaScript by filename.
    @app.route('/static/{filename}')
    async def assets(request, filename):  # Dynamic parameters arrive as strings.
        # Confinement and missing-file handling are provided by app.static().
        body, content_type, status = await app.static(filename, root=static_root)
        # Avoid stale assets while experimenting with the example's source.
        return body, content_type, status, [('Cache-Control', 'no-cache')]


    # Old links to /ui demonstrate a real redirect using the Location header.
    @app.route('/ui')
    async def old_ui(request):  # Redirects need an empty bytes body and a custom status.
        # HTTP 303 tells the client to follow Location with a GET request.
        return b'', 'text/plain', 303, [('Location', '/')]


    # A basic public health endpoint is useful for uptime checks.
    @app.route('/api/health')
    async def health(request):  # No authentication is required for a simple health check.
        # Plain dictionaries still become application/json responses with HTTP 200.
        return {'status': 'ok'}


    # This public endpoint makes throttling easy to try without locking users out of login.
    @app.route('/api/rate-limit-demo')
    # The fourth and fifth rapid requests get HTTP 429 with Retry-After.
    @rate_limit(requests=3, seconds=10)
    async def rate_limit_demo(request):  # The frontend has a button that sends five requests.
        # A successful request is an ordinary JSON dictionary response.
        return {'message': 'Request accepted'}
