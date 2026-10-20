# -*- coding: utf-8 -*-
"""
    example_app.tests.test_notebook
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Exercise the example's API contracts through the actual Wred ASGI app.

    :copyright: (c) 2026 by Harrison Erd.
    :license: BSD-3-Clause, see LICENSE for more details.
"""

import asyncio
import os
import subprocess
import sys
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import orjson

from example_app import auth, rate_limit
from example_app.app import create_app
from example_app.tests.helpers import call_app

mongodb_uri = os.environ.get('WRED_TEST_MONGODB_URI')


@unittest.skipUnless(
    mongodb_uri,
    'Set WRED_TEST_MONGODB_URI to run the MongoDB integration tests',
)
class NotebookTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.database_name = 'wred_test_' + uuid4().hex
        self.apps = []
        self.app = self.new_app()
        self.addAsyncCleanup(self.clean_database)

    def new_app(self):
        app = create_app(mongodb_uri, self.database_name)
        self.apps.append(app)
        return app

    async def clean_database(self):
        try:
            await self.app.database.client.drop_database(self.database_name)
        finally:
            for app in self.apps:
                await app.database.close()

    async def request(self, path, method='GET', data=None, token=None,
                      authorization=None, cookie=None, client='127.0.0.1',
                      csrf_header=True, extra_headers=(), scheme='http',
                      app=None):
        url = urlsplit(path)

        async def receive():
            if method == 'GET':
                raise AssertionError(
                    'GET handlers should not consume the request body'
                )
            return {'type': 'http.request', 'body': orjson.dumps(data)}

        headers = [
            (b'content-type', b'application/json'),
            (b'host', b'notebook.test'),
        ]
        if csrf_header:
            headers.append((b'x-notebook-request', b'1'))
        if cookie is not None:
            headers.append((b'cookie', cookie.encode()))
        headers.extend(extra_headers)
        if token is not None:
            headers.append((b'authorization', f'Bearer {token}'.encode()))
        if authorization is not None:
            headers.append((b'authorization', authorization))
        messages = await call_app(
            self.app if app is None else app,
            {
                'type': 'http',
                'path': unquote(url.path),
                'method': method,
                'query_string': url.query.encode(),
                'headers': headers,
                'scheme': scheme,
                'client': (client, 12345),
            },
            receive,
        )
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]['type'], 'http.response.start')
        self.assertEqual(messages[1]['type'], 'http.response.body')
        response_headers = dict(messages[0]['headers'])
        body = messages[1]['body']
        if body and response_headers[b'content-type'] == b'application/json':
            body = orjson.loads(body)
        return messages[0]['status'], body, response_headers

    async def account(self, username='alice'):
        credentials = {
            'username': username,
            'password': 'a long example passphrase',
        }
        status, user, _ = await self.request(
            '/api/signup', 'POST', credentials
        )
        self.assertEqual(
            (status, user), (201, {'id': username.strip().casefold()})
        )
        status, login, headers = await self.request(
            '/api/login', 'POST', credentials
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers[b'cache-control'], b'no-store')
        self.assertEqual(login['token_type'], 'bearer')
        self.assertEqual(login['expires_in'], 3600)
        return login['access_token']

    async def create(self, token, **data):
        status, note, headers = await self.request(
            '/api/notes', 'POST', data, token
        )
        self.assertEqual(status, 201)
        self.assertEqual(
            headers[b'location'], f"/api/notes/{note['id']}".encode()
        )
        self.assertEqual(headers[b'cache-control'], b'no-store')
        return note

    async def test_lifespan_starts_and_stops_the_database(self):
        worker = self.new_app()
        messages = iter(
            [{'type': 'lifespan.startup'}, {'type': 'lifespan.shutdown'}]
        )

        async def receive():
            return next(messages)

        responses = await call_app(worker, {'type': 'lifespan'}, receive)
        self.assertEqual(
            responses,
            [
                {'type': 'lifespan.startup.complete'},
                {'type': 'lifespan.shutdown.complete'},
            ],
        )

    async def test_signup_login_and_independent_login_revocation(self):
        token = await self.account(' Alice ')
        status, profile, headers = await self.request('/api/me', token=token)
        self.assertEqual((status, profile), (200, {'id': 'alice'}))
        self.assertEqual(headers[b'cache-control'], b'no-store')
        credentials = {
            'username': 'alice',
            'password': 'a long example passphrase',
        }
        self.assertEqual(
            (await self.request('/api/signup', 'POST', credentials))[0], 409
        )
        for data in [
            dict(credentials, username='unknown'),
            dict(credentials, password='an incorrect long passphrase'),
        ]:
            self.assertEqual(
                (await self.request('/api/login', 'POST', data))[:2],
                (401, {'error': 'Invalid credentials'}),
            )
        _, login, _ = await self.request('/api/login', 'POST', credentials)
        second_token = login['access_token']
        self.assertNotEqual(token, second_token)
        self.assertEqual(
            (await self.request('/api/logout', 'POST', token=token))[:2],
            (200, {'logged_out': True}),
        )
        self.assertEqual((await self.request('/api/me', token=token))[0], 401)
        self.assertEqual(
            (await self.request('/api/me', token=second_token))[:2],
            (200, {'id': 'alice'}),
        )
        expired_time = auth.time() + 3601
        with patch.object(auth, 'time', return_value=expired_time):
            self.assertEqual(
                (await self.request('/api/me', token=second_token))[0], 401
            )

    async def test_accounts_notes_and_sessions_survive_a_new_process(self):
        token = await self.account()
        note = await self.create(token, title='Remember me', pinned=True)
        credentials = {
            'username': 'alice',
            'password': 'a long example passphrase',
        }
        _, login, headers = await self.request(
            '/api/login', 'POST', credentials
        )
        morsel = SimpleCookie(headers[b'set-cookie'].decode())[
            auth.REFRESH_COOKIE_NAME
        ]
        cookie = f'{auth.REFRESH_COOKIE_NAME}={morsel.value}'
        script = """
import asyncio
import sys
import orjson
from example_app.asgi import app
from example_app.tests.helpers import call_app


async def main():
    data = orjson.loads(sys.stdin.buffer.read())
    results = []
    for path, method, headers in [
        (
            '/api/notes',
            'GET',
            [(b'authorization', ('Bearer ' + data['token']).encode())],
        ),
        (
            '/api/refresh',
            'POST',
            [
                (b'cookie', data['cookie'].encode()),
                (b'x-notebook-request', b'1'),
            ],
        ),
        ('/api/login', 'POST', [(b'x-notebook-request', b'1')]),
    ]:

        async def receive():
            return {
                'type': 'http.request',
                'body': orjson.dumps(data['credentials']),
            }

        messages = await call_app(
            app,
            {
                'type': 'http',
                'path': path,
                'method': method,
                'headers': headers,
            },
            receive,
        )
        results.append(
            [messages[0]['status'], orjson.loads(messages[1]['body'])]
        )
    await app.database.close()
    sys.stdout.buffer.write(orjson.dumps(results))


asyncio.run(main())
"""
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, '-c', script],
            input=orjson.dumps({
                'token': login['access_token'],
                'cookie': cookie,
                'credentials': credentials,
            }),
            env={
                **os.environ,
                'MONGODB_URI': mongodb_uri,
                'MONGODB_DATABASE': self.database_name,
            },
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        listed, refreshed, logged_in = orjson.loads(result.stdout)
        self.assertEqual((listed[0], listed[1]['items']), (200, [note]))
        self.assertEqual(
            (refreshed[0], refreshed[1]['user']), (200, {'id': 'alice'})
        )
        self.assertEqual(
            (logged_in[0], logged_in[1]['user']), (200, {'id': 'alice'})
        )
        # Tokens issued in the new process must be usable and revocable in the
        # original.
        renewed = refreshed[1]['access_token']
        self.assertEqual(
            (await self.request('/api/me', token=renewed))[0], 200
        )
        await self.request('/api/logout', 'POST', token=renewed)
        restarted = self.new_app()
        self.assertEqual(
            (
                await self.request(
                    '/api/me', token=login['access_token'], app=restarted
                )
            )[0],
            401,
        )
        self.assertEqual(
            (
                await self.request(
                    '/api/refresh', 'POST', cookie=cookie, app=restarted
                )
            )[0],
            401,
        )
        self.assertEqual(
            (await self.request('/api/me', token=token, app=restarted))[0], 200
        )

    async def test_workers_handle_duplicate_signups_and_concurrent_patches(
                                                                           self
          ):
        worker = self.new_app()
        credentials = {
            'username': 'alice',
            'password': 'a long example passphrase',
        }
        responses = await asyncio.gather(
            self.request('/api/signup', 'POST', credentials),
            self.request('/api/signup', 'POST', credentials, app=worker),
        )
        self.assertEqual(
            sorted(response[0] for response in responses), [201, 409]
        )
        _, login, _ = await self.request(
            '/api/login', 'POST', credentials, app=worker
        )
        token = login['access_token']
        note = await self.create(token, title='Original', body='Original body')
        path = f"/api/notes/{note['id']}"
        responses = await asyncio.gather(
            self.request(path, 'PATCH', {'title': 'New title'}, token),
            self.request(
                path, 'PATCH', {'body': 'New body'}, token, app=worker
            ),
        )
        self.assertEqual([response[0] for response in responses], [200, 200])
        _, edited, _ = await self.request(path, token=token, app=worker)
        self.assertEqual(
            (edited['title'], edited['body']), ('New title', 'New body')
        )
        for search in ('New+title', 'New+body'):
            _, page, _ = await self.request(
                '/api/notes?q=' + search, token=token, app=worker
            )
            self.assertEqual(page['items'], [edited])

    async def test_invalid_credentials_and_bearer_headers(self):
        for data in [
            [],
            {},
            {'username': 1, 'password': 'a long passphrase'},
            {'username': 'alice', 'password': False},
            {'username': ' ', 'password': 'a long passphrase'},
            {'username': 'alice', 'password': 'short'},
            {'username': 'x' * 65, 'password': 'a long passphrase'},
            {'username': 'alice', 'password': 'x' * 129},
        ]:
            with self.subTest(data=data):
                self.assertEqual(
                    (await self.request('/api/signup', 'POST', data))[0], 400
                )
        for header in [b'', b'Basic example', b'Bearer ', b'Bearer unknown']:
            with self.subTest(header=header):
                status, error, headers = await self.request(
                    '/api/notes', authorization=header
                )
                self.assertEqual(
                    (status, error), (401, {'error': 'Unauthorized'})
                )
                self.assertEqual(headers[b'www-authenticate'], b'Bearer')

    async def test_create_read_patch_replace_delete_and_export(self):
        token = await self.account()
        note = await self.create(
            token, title='  First idea  ', body='Some details', pinned=True
        )
        self.assertEqual(
            (note['title'], note['body'], note['pinned'], note['owner']),
            ('First idea', 'Some details', True, 'alice'),
        )
        path = f"/api/notes/{note['id']}"
        self.assertEqual(
            (await self.request(path, token=token))[:2], (200, note)
        )
        status, edited, _ = await self.request(
            path, 'PATCH', {'body': 'Edited details'}, token
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            (edited['title'], edited['body'], edited['pinned']),
            ('First idea', 'Edited details', True),
        )
        self.assertEqual(edited['created_at'], note['created_at'])
        status, replaced, _ = await self.request(
            path, 'PUT', {'title': 'Replacement'}, token
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            (replaced['title'], replaced['body'], replaced['pinned']),
            ('Replacement', '', False),
        )
        status, exported, headers = await self.request(
            '/api/notes/export', token=token
        )
        self.assertEqual((status, exported), (200, [replaced]))
        self.assertEqual(
            headers[b'content-disposition'],
            b'attachment; filename="notes.json"',
        )
        self.assertEqual(headers[b'cache-control'], b'no-store')
        status, body, _ = await self.request(path, 'DELETE', token=token)
        self.assertEqual((status, body), (204, b''))
        self.assertEqual((await self.request(path, token=token))[0], 404)
        self.assertEqual(
            (await self.request('/api/notes/export', token=token))[:2],
            (200, []),
        )

    async def test_accounts_cannot_access_each_others_notes(self):
        alice = await self.account('alice')
        bob = await self.account('bob')
        note = await self.create(
            alice, title='Private', body='Only Alice can read this'
        )
        bob_note = await self.create(bob, title='Bob only')
        path = f"/api/notes/{note['id']}"
        for method, data in [
            ('GET', None),
            ('PATCH', {'title': 'Stolen'}),
            ('PUT', {'title': 'Stolen'}),
            ('DELETE', None),
        ]:
            with self.subTest(method=method):
                self.assertEqual(
                    (await self.request(path, method, data, bob))[0], 403
                )
        self.assertEqual(
            (await self.request(path, token=alice))[:2], (200, note)
        )
        _, page, _ = await self.request('/api/notes', token=bob)
        self.assertEqual((page['items'], page['total']), ([bob_note], 1))
        self.assertEqual(
            (await self.request('/api/notes/export', token=bob))[:2],
            (200, [bob_note]),
        )
        for method in ['GET', 'PATCH', 'DELETE']:
            self.assertEqual(
                (
                    await self.request(
                        '/api/notes/missing', method, {'title': 'Missing'}, bob
                    )
                )[0],
                404,
            )

    async def test_filtering_pagination_and_invalid_queries(self):
        token = await self.account()
        first = await self.create(
            token,
            title='Coffee idea',
            body='Learn C++; Straße; 100%_done; $title; [.*]',
            pinned=True,
        )
        second = await self.create(
            token, title='Second idea', body='Coffee later'
        )
        await self.create(token, title='A separate thought')
        _, page, _ = await self.request(
            '/api/notes?q=COFFEE&limit=1&offset=0', token=token
        )
        self.assertEqual(
            (page['items'], page['total'], page['limit'], page['offset']),
            ([first], 2, 1, 0),
        )
        _, page, _ = await self.request(
            '/api/notes?q=coffee&limit=1&offset=1', token=token
        )
        self.assertEqual(page['items'], [second])
        _, page, _ = await self.request(
            '/api/notes?q=C%2B%2B&pinned=true', token=token
        )
        self.assertEqual(page['items'], [first])
        for search in ['STRASSE', '100%25_done', '$title', '%5B.*%5D']:
            _, page, _ = await self.request(
                '/api/notes?q=' + search, token=token
            )
            self.assertEqual(page['items'], [first])
        _, page, _ = await self.request(
            '/api/notes?offset=9223372036854775808', token=token
        )
        self.assertEqual((page['items'], page['total']), ([], 3))
        _, page, _ = await self.request('/api/notes?pinned=false', token=token)
        self.assertEqual(page['total'], 2)
        for query in [
            'limit=abc',
            'offset=abc',
            'limit=0',
            'limit=51',
            'offset=-1',
            'offset=18446744073709551616',
            'offset=' + '9' * 100,
            'pinned=maybe',
            '&'.join(f'x={i}' for i in range(21)),
        ]:
            with self.subTest(query=query):
                self.assertEqual(
                    (await self.request('/api/notes?' + query, token=token))[
                        0
                    ],
                    400,
                )

    async def test_notes_reject_invalid_or_unowned_field_updates(self):
        token = await self.account()
        for data in [
            [],
            {},
            {'body': 'No title'},
            {'title': 7},
            {'title': ' '},
            {'title': 'x' * 101},
            {'title': 'Valid', 'body': 3},
            {'title': 'Valid', 'body': 'x' * 10_001},
            {'title': 'Valid', 'pinned': 'true'},
            {'title': 'Valid', 'owner': 'bob'},
        ]:
            with self.subTest(data=data):
                self.assertEqual(
                    (await self.request('/api/notes', 'POST', data, token))[0],
                    400,
                )
        note = await self.create(token, title='Keep me')
        path = f"/api/notes/{note['id']}"
        for data in [{}, {'owner': 'bob'}, {'title': ''}, {'pinned': 1}]:
            self.assertEqual(
                (await self.request(path, 'PATCH', data, token))[0], 400
            )
        self.assertEqual(
            (await self.request(path, token=token))[:2], (200, note)
        )
        self.assertEqual(
            (
                await self.request(
                    path, 'PUT', {'body': 'Missing title'}, token
                )
            )[0],
            400,
        )
        status, pinned, _ = await self.request(
            path, 'PATCH', {'pinned': True}, token
        )
        self.assertEqual(
            (status, pinned['pinned'], pinned['title']), (200, True, 'Keep me')
        )

    async def test_cookie_restores_login_and_logout_revokes_login(self):
        credentials = {
            'username': 'alice',
            'password': 'a long example passphrase',
        }
        self.assertEqual(
            (await self.request('/api/signup', 'POST', credentials))[0], 201
        )
        status, login, headers = await self.request(
            '/api/login', 'POST', credentials, scheme='https'
        )
        self.assertEqual(status, 200)
        cookies = SimpleCookie(headers[b'set-cookie'].decode())
        morsel = cookies[auth.REFRESH_COOKIE_NAME]
        self.assertTrue(morsel['httponly'])
        self.assertTrue(morsel['secure'])
        self.assertEqual(morsel['samesite'], 'Strict')
        self.assertEqual(morsel['path'], '/api')
        self.assertEqual(int(morsel['max-age']), 7 * 24 * 3600)
        self.assertEqual(morsel['domain'], '')
        cookie = f'{auth.REFRESH_COOKIE_NAME}={morsel.value}'
        status, restored, headers = await self.request(
            '/api/refresh', 'POST', cookie=cookie
        )
        self.assertEqual(status, 200)
        self.assertNotEqual(restored['access_token'], login['access_token'])
        self.assertEqual(restored['user'], {'id': 'alice'})
        self.assertEqual(headers[b'cache-control'], b'no-store')
        self.assertEqual(
            (await self.request('/api/me', token=restored['access_token']))[
                :2
            ],
            (200, {'id': 'alice'}),
        )
        # Cookies alone must never authorize notes endpoints, keeping bearer
        # auth separate.
        self.assertEqual(
            (await self.request('/api/notes', cookie=cookie))[0], 401
        )
        refreshed, logged_out = await asyncio.gather(
            self.request('/api/refresh', 'POST', cookie=cookie),
            self.request(
                '/api/logout', 'POST', token=restored['access_token']
            ),
        )
        self.assertEqual(logged_out[0], 200)
        self.assertIn(refreshed[0], (200, 401))
        if refreshed[0] == 200:
            self.assertEqual(
                (
                    await self.request(
                        '/api/me', token=refreshed[1]['access_token']
                    )
                )[0],
                401,
            )
        _, _, headers = logged_out
        cleared = SimpleCookie(headers[b'set-cookie'].decode())[
            auth.REFRESH_COOKIE_NAME
        ]
        self.assertEqual(cleared['max-age'], '0')
        self.assertEqual(cleared['path'], '/api')
        for access in [login['access_token'], restored['access_token']]:
            self.assertEqual(
                (await self.request('/api/me', token=access))[0], 401
            )
        self.assertEqual(
            (await self.request('/api/refresh', 'POST', cookie=cookie))[0], 401
        )

    async def test_cross_origin_refresh_preserves_valid_login(self):
        credentials = {
            'username': 'alice',
            'password': 'a long example passphrase',
        }
        await self.request('/api/signup', 'POST', credentials)
        _, _, headers = await self.request('/api/login', 'POST', credentials)
        cookie = SimpleCookie(headers[b'set-cookie'].decode())[
            auth.REFRESH_COOKIE_NAME
        ]
        cookie = f'{auth.REFRESH_COOKIE_NAME}={cookie.value}'
        for options in [
            {'csrf_header': False},
            {'extra_headers': [(b'origin', b'https://attacker.test')]},
            {'extra_headers': [(b'origin', b'null')]},
            {'extra_headers': [(b'sec-fetch-site', b'cross-site')]},
            {'extra_headers': [(b'sec-fetch-site', b'same-site')]},
        ]:
            with self.subTest(options=options):
                self.assertEqual(
                    (
                        await self.request(
                            '/api/refresh', 'POST', cookie=cookie, **options
                        )
                    )[0],
                    403,
                )
        self.assertEqual(
            (
                await self.request(
                    '/api/refresh',
                    'POST',
                    cookie=cookie,
                    extra_headers=[(b'origin', b'http://notebook.test')],
                )
            )[0],
            200,
        )
        self.assertEqual(
            (
                await self.request(
                    '/api/login', 'POST', credentials, csrf_header=False
                )
            )[0],
            403,
        )

    async def test_invalid_refresh_cookies_clear_browser_state(self):
        credentials = {
            'username': 'alice',
            'password': 'a long example passphrase',
        }
        await self.request('/api/signup', 'POST', credentials)
        _, login, headers = await self.request(
            '/api/login', 'POST', credentials
        )
        morsel = SimpleCookie(headers[b'set-cookie'].decode())[
            auth.REFRESH_COOKIE_NAME
        ]
        self.assertFalse(
            morsel['secure'], 'Local HTTP demo cookies should work without TLS'
        )
        cookie = f'{auth.REFRESH_COOKIE_NAME}={morsel.value}'
        # Access expiry is recoverable while the independent refresh credential
        # is valid.
        now = auth.time()
        with patch.object(auth, 'time', return_value=now + 3601):
            self.assertEqual(
                (await self.request('/api/me', token=login['access_token']))[
                    0
                ],
                401,
            )
            self.assertEqual(
                (await self.request('/api/refresh', 'POST', cookie=cookie))[0],
                200,
            )
        with patch.object(auth, 'time', return_value=now + 7 * 24 * 3600 + 1):
            status, _, headers = await self.request(
                '/api/refresh', 'POST', cookie=cookie
            )
            self.assertEqual(status, 401)
            self.assertEqual(
                SimpleCookie(headers[b'set-cookie'].decode())[
                    auth.REFRESH_COOKIE_NAME
                ]['max-age'],
                '0',
            )
        for invalid in [None, 'notebook_refresh=unknown', 'malformed; cookie']:
            self.assertEqual(
                (await self.request('/api/refresh', 'POST', cookie=invalid))[
                    0
                ],
                401,
            )

    async def test_rate_limits_slide_and_isolate_clients_and_endpoints(self):
        with patch.object(rate_limit, 'monotonic', return_value=100):
            self.assertEqual(
                (await self.request('/api/rate-limit-demo'))[0], 200
            )
        with patch.object(rate_limit, 'monotonic', return_value=105):
            self.assertEqual(
                (await self.request('/api/rate-limit-demo'))[0], 200
            )
        with patch.object(rate_limit, 'monotonic', return_value=106):
            self.assertEqual(
                (await self.request('/api/rate-limit-demo'))[0], 200
            )
        with patch.object(rate_limit, 'monotonic', return_value=109):
            status, error, headers = await self.request('/api/rate-limit-demo')
            self.assertEqual(status, 429)
            self.assertEqual(error['retry_after'], 1)
            self.assertEqual(headers[b'retry-after'], b'1')
            self.assertEqual(headers[b'cache-control'], b'no-store')
            worker = self.new_app()
            self.assertEqual(
                (await self.request('/api/rate-limit-demo', app=worker))[0],
                200,
            )
            self.assertEqual(
                (await self.request('/api/rate-limit-demo'))[0], 429
            )
            self.assertEqual(
                (
                    await self.request(
                        '/api/rate-limit-demo', client='127.0.0.2'
                    )
                )[0],
                200,
            )
            self.assertEqual((await self.request('/api/health'))[0], 200)
            self.assertEqual(
                (
                    await self.request(
                        '/api/rate-limit-demo',
                        extra_headers=[(b'x-forwarded-for', b'127.0.0.3')],
                    )
                )[0],
                429,
            )
        with patch.object(rate_limit, 'monotonic', return_value=110):
            self.assertEqual(
                (await self.request('/api/rate-limit-demo'))[0], 200
            )
        with patch.object(rate_limit, 'monotonic', return_value=200):
            self.assertEqual(
                (await self.request('/api/rate-limit-demo'))[0], 200
            )

    async def test_concurrent_login_attempts_cannot_bypass_rate_limit(self):
        credentials = {
            'username': 'unknown',
            'password': 'a long example passphrase',
        }
        with patch.object(rate_limit, 'monotonic', return_value=100):
            responses = await asyncio.gather(
                *[
                    self.request('/api/login', 'POST', credentials)
                    for _ in range(6)
                ]
            )
            self.assertEqual(
                sorted(status for status, _, _ in responses), [401] * 5 + [429]
            )
            limited = next(
                response for response in responses if response[0] == 429
            )
            self.assertEqual(limited[2][b'retry-after'], b'60')
        with patch.object(rate_limit, 'monotonic', return_value=110):
            self.assertEqual(
                (await self.request('/api/login', 'POST', credentials))[2][
                    b'retry-after'
                ],
                b'50',
            )
        with patch.object(rate_limit, 'monotonic', return_value=160):
            self.assertEqual(
                (await self.request('/api/login', 'POST', credentials))[0], 401
            )


if __name__ == '__main__':
    unittest.main()
