"""Public page/assets, redirect, health check, and a rate-limit demonstration."""

from pathlib import Path

from .rate_limit import rate_limit

static_root = Path(__file__).parent / 'static'


def register_routes(app):
    """Register the browser UI and public demonstration endpoints."""

    @app.route('/')
    async def home(request):
        body, content_type, status = await app.static('index.html', root=static_root)
        return body, content_type, status, [('Cache-Control', 'no-cache')]

    @app.route('/static/{filename}')
    async def assets(request, filename):
        body, content_type, status = await app.static(filename, root=static_root)
        return body, content_type, status, [('Cache-Control', 'no-cache')]

    @app.route('/ui')
    async def old_ui(request):
        return b'', 'text/plain', 303, [('Location', '/')]

    @app.route('/api/health')
    async def health(request):
        return {'status': 'ok'}

    @app.route('/api/rate-limit-demo')
    @rate_limit(requests=3, seconds=10)
    async def rate_limit_demo(request):
        return {'message': 'Request accepted'}
