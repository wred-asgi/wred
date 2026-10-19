from time import perf_counter
from uuid import uuid4

from wred import App


class RequestContext:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        request_id = uuid4().hex
        started = perf_counter()
        scope = {**scope, 'state': {**scope.get('state', {}), 'request_id': request_id}}

        async def send_with_context(message):
            if message['type'] == 'http.response.start':
                elapsed_ms = (perf_counter() - started) * 1000
                message = {
                    **message,
                    'headers': [
                        *message.get('headers', []),
                        (b'x-request-id', request_id.encode('ascii')),
                        (b'server-timing', f'app;dur={elapsed_ms:.2f}'.encode('ascii')),
                    ],
                }
            await send(message)

        await self.app(scope, receive, send_with_context)


api = App()


@api.route('/api/hello')
async def hello(request):
    return {'request_id': request.scope['state']['request_id']}


app = RequestContext(api)
