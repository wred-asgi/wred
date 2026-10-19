from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.errors import ServerErrorMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from wred import App

api = App()


@api.route('/api/hello')
async def hello(request):
    return {'hello': 'world'}


async def server_error(request, exc):
    return JSONResponse({'error': 'Internal server error'}, status_code=500)


# Requests enter the last wrapper first.
app = GZipMiddleware(api, minimum_size=1000)
app = TrustedHostMiddleware(app, allowed_hosts=['localhost', '127.0.0.1', 'api.example.com'])
app = ServerErrorMiddleware(app, handler=server_error, debug=False)
app = CORSMiddleware(
    app,
    allow_origins=['http://localhost:5173'],
    allow_methods=['GET', 'POST', 'PATCH', 'DELETE'],
    allow_headers=['Authorization', 'Content-Type'],
    expose_headers=['Location'],
)
