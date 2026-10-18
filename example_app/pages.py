# -*- coding: utf-8 -*-
"""
    example_app.pages
    ~~~~~~~~~~~~~~~~~

    Public page/assets, redirect, health check, and a rate-limit demonstration.

    :copyright: (c) 2026 by Harrison Erd.
    :license: BSD-3-Clause, see LICENSE for more details.
"""

from pathlib import Path

STATIC_ROOT = Path(__file__).parent / 'static'


def register_routes(app, rate_limit):
    """Register the browser UI and public demonstration endpoints."""

    @app.route('/')
    async def home(request):
        body, content_type, status = await app.static(
            'index.html', root=STATIC_ROOT
        )
        return body, content_type, status, [('Cache-Control', 'no-cache')]

    @app.route('/static/{filename}')
    async def assets(request, filename):
        body, content_type, status = await app.static(
            filename, root=STATIC_ROOT
        )
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
