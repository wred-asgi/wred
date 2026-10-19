import os

from starlette.middleware.sessions import SessionMiddleware
from wred import App

api = App()


@api.route('/visits')
async def visits(request):
    session = request.scope['session']
    session['visits'] = session.get('visits', 0) + 1
    return {'visits': session['visits']}


app = SessionMiddleware(
    api,
    secret_key=os.environ['SESSION_SECRET'],
    same_site='lax',
    https_only=os.environ.get('COOKIE_SECURE', '1') == '1',
)
