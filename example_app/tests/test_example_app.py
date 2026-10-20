# -*- coding: utf-8 -*-
"""
    example_app.tests.test_example_app
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Exercise example application construction and resource ownership.

    :copyright: (c) 2026 by Harrison Erd.
    :license: BSD-3-Clause, see LICENSE for more details.
"""

import subprocess
import sys
import unittest
from pathlib import Path

import orjson

from example_app.tests.helpers import call_app


class AppFactoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_files_and_api_share_one_application(self):
        from example_app.app import create_app

        app = create_app(database=object())

        async def request(path):
            async def receive():
                raise AssertionError('Public endpoints should not read a body')

            messages = await call_app(
                app,
                {
                    'type': 'http',
                    'path': path,
                    'method': 'GET',
                    'headers': [],
                    'query_string': b'',
                },
                receive,
            )
            self.assertEqual(messages[0]['type'], 'http.response.start')
            self.assertEqual(messages[-1]['type'], 'http.response.body')
            self.assertFalse(messages[-1].get('more_body', False))
            return (
                messages[0]['status'],
                b''.join(message.get('body', b'') for message in messages[1:]),
                dict(messages[0]['headers']),
            )

        for path, content_type, marker in [
            ('/', b'text/html', b'Wred notebook'),
            ('/static/app.css', b'text/css', b'.workspace'),
            ('/static/app.js', b'text/javascript', b'/api/notes'),
        ]:
            with self.subTest(path=path):
                status, body, headers = await request(path)
                self.assertEqual(status, 200)
                self.assertEqual(
                    headers[b'content-type'].split(b';')[0], content_type
                )
                self.assertIn(b'max-age=0', headers[b'cache-control'])
                self.assertIn(marker, body)

        status, body, headers = await request('/ui')
        self.assertEqual((status, body, headers[b'location']), (303, b'', b'/'))
        status, body, headers = await request('/api/health')
        self.assertEqual((status, orjson.loads(body)), (200, {'status': 'ok'}))
        for path in ['/static/missing.js', '/auth.py', '/static/../auth.py']:
            with self.subTest(path=path):
                status, body, _ = await request(path)
                self.assertEqual(
                    (status, orjson.loads(body)), (404, {'error': 'Not Found'})
                )

    def test_import_factory_does_not_construct_a_database(self):
        script = """
from unittest.mock import patch

with patch('pymongo.AsyncMongoClient', side_effect=RuntimeError(
    'Importing the factory must not construct a database client'
)):
    from example_app.app import create_app
"""
        result = subprocess.run(
            [sys.executable, '-c', script],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    async def test_injected_database_follows_application_lifespan(self):
        from example_app.app import create_app

        events = []

        class Database:
            async def initialize(self):
                events.append('initialize')

            async def close(self):
                events.append('close')

        app = create_app(database=Database())
        self.assertEqual(events, [])
        messages = iter([
            {'type': 'lifespan.startup'},
            {'type': 'lifespan.shutdown'},
        ])

        async def receive():
            return next(messages)

        async def send(message):
            events.append(message['type'])

        await app({'type': 'lifespan'}, receive, send)
        self.assertEqual(events, [
            'initialize',
            'lifespan.startup.complete',
            'close',
            'lifespan.shutdown.complete',
        ])
