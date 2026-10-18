# -*- coding: utf-8 -*-
"""
    tests.test_wred
    ~~~~~~~~~~~~~~~

    Exercise Wred request handling and ASGI response behavior.

    :copyright: (c) 2026 by Harrison Erd.
    :license: BSD-3-Clause, see LICENSE for more details.
"""

import unittest

import orjson

from wred import App


async def call_app(app, scope, receive):
    """Drive an ASGI request and capture its actual outgoing messages."""
    messages = []

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages


class WredTests(unittest.IsolatedAsyncioTestCase):
    async def test_callable_responses_on_fixed_and_dynamic_routes(self):
        class Response:
            def __init__(self, name):
                self.name = name

            async def __call__(self, scope, receive, send):
                message = await receive()
                await send({
                    'type': 'http.response.start',
                    'status': 202,
                    'headers': [
                        (b'content-type', b'text/plain'),
                        (b'x-response', b'asgi'),
                    ],
                })
                await send({
                    'type': 'http.response.body',
                    'body': f'{scope["path"]}:{self.name}:'.encode(),
                    'more_body': True,
                })
                await send(
                    {'type': 'http.response.body', 'body': message['body']}
                )

        app = App()

        @app.route('/fixed', methods=['POST'])
        async def fixed(request):
            return Response('fixed')

        @app.route('/dynamic/{name}', methods=['POST'])
        async def dynamic(request, name):
            return Response(name)

        for path, root_path, prefix in [
            ('/fixed', '', b'/fixed:fixed:'),
            ('/dynamic/alice', '', b'/dynamic/alice:alice:'),
            ('/api/fixed', '/api', b'/api/fixed:fixed:'),
            ('/api/dynamic/alice', '/api', b'/api/dynamic/alice:alice:'),
        ]:
            with self.subTest(path=path):

                async def receive():
                    return {'type': 'http.request', 'body': b'payload'}

                messages = await call_app(
                    app,
                    {
                        'type': 'http',
                        'path': path,
                        'root_path': root_path,
                        'method': 'POST',
                    },
                    receive,
                )
                self.assertEqual(
                    messages,
                    [
                        {
                            'type': 'http.response.start',
                            'status': 202,
                            'headers': [
                                (b'content-type', b'text/plain'),
                                (b'x-response', b'asgi'),
                            ],
                        },
                        {
                            'type': 'http.response.body',
                            'body': prefix,
                            'more_body': True,
                        },
                        {'type': 'http.response.body', 'body': b'payload'},
                    ],
                )

    async def test_mounted_routing_preserves_scope(self):
        app = App()

        @app.route('/items/{name}')
        async def item(request, name):
            return {
                'route': name,
                'path': request.path,
                'scope_path': request.scope['path'],
            }

        @app.route('/items/special')
        @app.route('/')
        @app.route('/apiary/items')
        async def fixed(request):
            return {
                'route': 'fixed',
                'path': request.path,
                'scope_path': request.scope['path'],
            }

        cases = [
            ('/items/alice', None, 'alice'),
            ('/items/alice', '', 'alice'),
            ('/api/items/alice', '/api', 'alice'),
            ('/api/items/alice', '/api/', 'alice'),
            ('/api/items/special', '/api', 'fixed'),
            ('/api/items/special/', '/api', 'fixed'),
            ('/proxy/api/items/alice', '/proxy/api', 'alice'),
            ('/api', '/api', 'fixed'),
            ('/api/', '/api', 'fixed'),
            ('/items/alice', '/api', 'alice'),
            ('/apiary/items', '/api', 'fixed'),
        ]
        for path, root_path, route in cases:
            with self.subTest(path=path, root_path=root_path):

                async def receive():
                    raise AssertionError('GET handlers should not read a body')

                scope = {'type': 'http', 'path': path, 'method': 'GET'}
                if root_path is not None:
                    scope['root_path'] = root_path
                original = scope.copy()
                messages = await call_app(app, scope, receive)
                self.assertEqual(messages[0]['status'], 200)
                self.assertEqual(
                    orjson.loads(messages[1]['body']),
                    {
                        'route': route,
                        'path': path,
                        'scope_path': path,
                    },
                )
                self.assertEqual(scope, original)

    async def test_dictionary_and_list_responses_are_json(self):
        app = App()

        @app.route('/')
        async def home(request):
            return value

        async def receive():
            raise AssertionError('GET handler should not read a body')

        cases = [
            ({'hello': 'world'}, b'{"hello":"world"}'),
            ([{'id': 1}, {'id': 2}], b'[{"id":1},{"id":2}]'),
            ([], b'[]'),
        ]
        for value, body in cases:
            with self.subTest(value=value):
                messages = await call_app(
                    app,
                    {'type': 'http', 'path': '/', 'method': 'GET'},
                    receive,
                )
                self.assertEqual(
                    messages,
                    [
                        {
                            'type': 'http.response.start',
                            'status': 200,
                            'headers': [
                                (b'content-type', b'application/json')
                            ],
                        },
                        {'type': 'http.response.body', 'body': body},
                    ],
                )

    async def test_custom_status_and_explicit_json_errors(self):
        app = App()

        @app.route('/{name}/created')
        async def created(request, name):
            return {'name': name}, 'application/json', 201

        @app.route('/input', methods=['POST'])
        async def input_data(request):
            try:
                return await request.json()
            except orjson.JSONDecodeError:
                return {'error': 'Invalid JSON body'}, 'application/json', 400

        cases = [
            ('GET', '/alice/created', b'', 201, b'{"name":"alice"}'),
            ('GET', '/missing', b'', 404, b'{"error":"Not Found"}'),
            ('POST', '/input', b'{', 400, b'{"error":"Invalid JSON body"}'),
            ('POST', '/input', b'', 200, b'{}'),
            ('GET', '/alice/missing', b'', 404, b'{"error":"Not Found"}'),
            ('DELETE', '/alice/created', b'', 404, b'{"error":"Not Found"}'),
        ]
        for method, path, request_body, status, body in cases:
            with self.subTest(path=path):

                async def receive():
                    return {'type': 'http.request', 'body': request_body}

                messages = await call_app(
                    app,
                    {'type': 'http', 'path': path, 'method': method},
                    receive,
                )
                self.assertEqual(
                    messages,
                    [
                        {
                            'type': 'http.response.start',
                            'status': status,
                            'headers': [
                                (b'content-type', b'application/json')
                            ],
                        },
                        {'type': 'http.response.body', 'body': body},
                    ],
                )

    async def test_parsing_and_response_errors_propagate_without_sending(self):
        app = App()

        @app.route('/input', methods=['POST'])
        async def input_data(request):
            return await request.json()

        @app.route('/search')
        async def search(request):
            return request.query()

        @app.route('/invalid')
        async def invalid(request):
            return response

        cases = [
            ('POST', '/input', b'{', b'', None, orjson.JSONDecodeError),
            ('GET', '/search', b'', b'\xff', None, UnicodeDecodeError),
            ('GET', '/search', b'', b'q=%FF', None, UnicodeDecodeError),
            ('GET', '/search', b'', b'%FF=value', None, UnicodeDecodeError),
            ('GET', '/invalid', b'', b'', 'unsupported response', TypeError),
            ('GET', '/invalid', b'', b'', (b'bad', 'text/plain'), ValueError),
        ]
        for method, path, body, query_string, response, error in cases:
            with self.subTest(
                path=path, query_string=query_string, response=response
            ):
                messages = []

                async def receive():
                    return {'type': 'http.request', 'body': body}

                async def send(message):
                    messages.append(message)

                with self.assertRaises(error):
                    await app(
                        {
                            'type': 'http',
                            'path': path,
                            'method': method,
                            'query_string': query_string,
                        },
                        receive,
                        send,
                    )
                self.assertEqual(messages, [])

    async def test_callable_response_errors_preserve_started_stream(self):
        app = App()

        @app.route('/stream', methods=['POST'])
        async def stream(request):
            async def response(scope, receive, send):
                await send({
                    'type': 'http.response.start',
                    'status': 200,
                    'headers': [(b'content-type', b'text/plain')],
                })
                await send({
                    'type': 'http.response.body',
                    'body': b'hello\n',
                    'more_body': True,
                })
                await request.json()

            return response

        async def receive():
            return {'type': 'http.request', 'body': b'{'}

        messages = []

        async def send(message):
            messages.append(message)

        with self.assertRaises(orjson.JSONDecodeError):
            await app(
                {'type': 'http', 'path': '/stream', 'method': 'POST'},
                receive,
                send,
            )
        self.assertEqual(
            messages,
            [
                {
                    'type': 'http.response.start',
                    'status': 200,
                    'headers': [(b'content-type', b'text/plain')],
                },
                {
                    'type': 'http.response.body',
                    'body': b'hello\n',
                    'more_body': True,
                },
            ],
        )

    async def test_route_priority_and_method_registration(self):
        app = App()

        @app.route('/people/{name}')
        async def person(request, name):
            return {'name': name}

        @app.route('/people/{name}', methods=['POST'])
        async def update_person(request, name):
            return {'updated': name}

        @app.route('/people/alice/', methods=['PUT'])
        @app.route('/people/alice')
        async def alice(request):
            return {'fixed': True}

        cases = [
            ('GET', '/people/alice', b'{"fixed":true}'),
            ('GET', '/people/alice/', b'{"fixed":true}'),
            ('GET', '/people/bob', b'{"name":"bob"}'),
            ('GET', '/people/bob/', b'{"name":"bob"}'),
            ('POST', '/people/alice', b'{"updated":"alice"}'),
            ('POST', '/people/alice/', b'{"updated":"alice"}'),
            ('PUT', '/people/alice', b'{"fixed":true}'),
            ('PUT', '/people/alice/', b'{"fixed":true}'),
        ]
        for method, path, body in cases:
            with self.subTest(method=method, path=path):

                async def receive():
                    raise AssertionError('These handlers do not read the body')

                messages = await call_app(
                    app,
                    {'type': 'http', 'path': path, 'method': method},
                    receive,
                )
                self.assertEqual(messages[0]['status'], 200)
                self.assertEqual(messages[1]['body'], body)

    async def test_query_decodes_to_strings_without_reading_body(self):
        app = App()

        @app.route('/search')
        async def search(request):
            return {
                'params': request.query(),
                'q': request.query().get('q', ''),
            }

        cases = [
            (None, 200, {'params': {}, 'q': ''}),
            (b'', 200, {'params': {}, 'q': ''}),
            (
                b'q=coffee+ideas&limit=20',
                200,
                {
                    'params': {'q': 'coffee ideas', 'limit': '20'},
                    'q': 'coffee ideas',
                },
            ),
            (
                b'q=C%2B%2B&label=caf%C3%A9&x%26y=a%3Db',
                200,
                {
                    'params': {'q': 'C++', 'label': 'café', 'x&y': 'a=b'},
                    'q': 'C++',
                },
            ),
            (
                b'q=&bare&tag=first&tag=last',
                200,
                {'params': {'q': '', 'bare': '', 'tag': 'last'}, 'q': ''},
            ),
        ]
        for query_string, status, body in cases:
            with self.subTest(query_string=query_string):

                async def receive():
                    raise AssertionError(
                        'Query parsing should not read the request body'
                    )

                scope = {'type': 'http', 'path': '/search', 'method': 'GET'}
                if query_string is not None:
                    scope['query_string'] = query_string
                messages = await call_app(app, scope, receive)
                self.assertEqual(messages[0]['status'], status)
                self.assertEqual(orjson.loads(messages[1]['body']), body)

    async def test_headers_are_lazy_cached_and_replaceable(self):
        app = App()
        reads = []

        class Headers(list):
            def __iter__(self):
                reads.append(True)
                return super().__iter__()

        @app.route('/unused')
        async def unused(request):
            return {'ok': True}

        @app.route('/headers')
        async def headers(request):
            values = request.headers
            values['x-local'] = 'added'
            self.assertIs(request.headers, values)
            self.assertEqual(len(reads), 1)
            request.headers = {'replacement': 'works'}
            return request.headers

        async def receive():
            raise AssertionError('Header access should not read the body')

        for raw in ([], [(b'X-Example', b'value')]):
            with self.subTest(headers=raw):
                reads.clear()
                scope = {
                    'type': 'http',
                    'path': '/unused',
                    'method': 'GET',
                    'headers': Headers(raw),
                }
                messages = await call_app(app, scope, receive)
                self.assertEqual(messages[0]['status'], 200)
                self.assertEqual(reads, [])
                scope['path'] = '/headers'
                messages = await call_app(app, scope, receive)
                self.assertEqual(
                    orjson.loads(messages[1]['body']),
                    {'replacement': 'works'},
                )

    async def test_streamed_body_is_cached_and_headers_are_available(self):
        app = App()
        reads = 0
        chunks = iter([
            {
                'type': 'http.request',
                'body': b'{"name":',
                'more_body': True,
            },
            {'type': 'http.request', 'more_body': True},
            {
                'type': 'http.request',
                'body': b'"Alice"}',
                'more_body': False,
            },
        ])

        @app.route('/stream', methods=['POST'])
        async def stream(request):
            first = await request.body()
            parsed = await request.json()
            cached = await request.body()
            return {
                'raw': first.decode(),
                'cached': cached.decode(),
                'parsed': parsed,
                'header': request.headers['x-example'],
                'cookie': request.headers['cookie'],
            }

        async def receive():
            nonlocal reads
            reads += 1
            return next(chunks)

        messages = await call_app(
            app,
            {
                'type': 'http',
                'http_version': '2',
                'path': '/stream',
                'method': 'POST',
                'headers': [
                    (b'X-Example', b'caf\xe9'),
                    (b'Cookie', b'notebook_refresh=valid-token'),
                    (b'cookie', b'theme=dark'),
                    (b'COOKIE', b'lang=en'),
                ],
            },
            receive,
        )
        self.assertEqual(reads, 3)
        self.assertEqual(messages[0]['status'], 200)
        self.assertEqual(
            orjson.loads(messages[1]['body']),
            {
                'raw': '{"name":"Alice"}',
                'cached': '{"name":"Alice"}',
                'parsed': {'name': 'Alice'},
                'header': 'café',
                'cookie': 'notebook_refresh=valid-token; theme=dark; lang=en',
            },
        )

    async def test_disconnect_stops_body_reading(self):
        app = App()
        reads = 0

        @app.route('/input', methods=['POST'])
        async def input_data(request):
            return await request.json()

        async def receive():
            nonlocal reads
            reads += 1
            if reads > 1:
                raise AssertionError('Body reading continued after disconnect')
            return {'type': 'http.disconnect'}

        messages = []

        async def send(message):
            messages.append(message)

        with self.assertRaisesRegex(ConnectionError, 'Client disconnected'):
            await app(
                {'type': 'http', 'path': '/input', 'method': 'POST'},
                receive,
                send,
            )
        self.assertEqual(messages, [])
        self.assertEqual(reads, 1)

    async def test_unsupported_protocols_raise_without_io(self):
        app = App()

        async def receive():
            raise AssertionError('An unsupported scope should not be read')

        for protocol in ['lifespan', 'websocket', 'unsupported']:
            with self.subTest(protocol=protocol):
                messages = []

                async def send(message):
                    messages.append(message)

                with self.assertRaisesRegex(
                    RuntimeError, 'Unsupported ASGI scope type'
                ):
                    await app({'type': protocol}, receive, send)
                self.assertEqual(messages, [])

    async def test_raw_and_custom_response_bodies(self):
        app = App()

        @app.route('/')
        async def raw(request):
            return response

        cases = [
            (b'\x00\xff', 200, b'application/octet-stream', b'\x00\xff', []),
            (
                (b'<p>Hello</p>', 'text/html; charset=utf-8', 202),
                202,
                b'text/html; charset=utf-8',
                b'<p>Hello</p>',
                [],
            ),
            (
                ([], 'application/json', 201),
                201,
                b'application/json',
                b'[]',
                [],
            ),
            (
                (
                    {'error': 'Unauthorized'},
                    'application/json',
                    401,
                    [
                        ('WWW-Authenticate', 'Bearer'),
                        ('Cache-Control', 'no-store'),
                    ],
                ),
                401,
                b'application/json',
                b'{"error":"Unauthorized"}',
                [
                    (b'www-authenticate', b'Bearer'),
                    (b'cache-control', b'no-store'),
                ],
            ),
            (
                (
                    b'',
                    'text/plain',
                    303,
                    [
                        ('Location', '/ui'),
                        ('X-Label', 'caf\u00e9'),
                        ('Set-Cookie', 'a=1; Secure'),
                        ('Set-Cookie', 'b=2; Secure'),
                    ],
                ),
                303,
                b'text/plain',
                b'',
                [
                    (b'location', b'/ui'),
                    (b'x-label', b'caf\xe9'),
                    (b'set-cookie', b'a=1; Secure'),
                    (b'set-cookie', b'b=2; Secure'),
                ],
            ),
            (
                ([], 'application/json', 200, []),
                200,
                b'application/json',
                b'[]',
                [],
            ),
        ]
        for response, status, content_type, body, headers in cases:
            with self.subTest(response=response):

                async def receive():
                    raise AssertionError(
                        'These responses do not use a request body'
                    )

                messages = await call_app(
                    app,
                    {'type': 'http', 'path': '/', 'method': 'GET'},
                    receive,
                )
                self.assertEqual(
                    messages,
                    [
                        {
                            'type': 'http.response.start',
                            'status': status,
                            'headers': [(b'content-type', content_type)]
                            + headers,
                        },
                        {'type': 'http.response.body', 'body': body},
                    ],
                )


if __name__ == '__main__':
    unittest.main()
