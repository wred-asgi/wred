# -*- coding: utf-8 -*-
"""
    example_app.pages
    ~~~~~~~~~~~~~~~~~

    Redirect, health check, and a rate-limit demonstration.

    :copyright: (c) 2026 by Harrison Erd.
    :license: BSD-3-Clause, see LICENSE for more details.
"""


def register_routes(app, rate_limit):
    """Register public demonstration endpoints; ServeStatic handles files."""

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
