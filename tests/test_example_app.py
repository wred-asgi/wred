# -*- coding: utf-8 -*-
"""
    tests.test_example_app
    ~~~~~~~~~~~~~~~~~~~~~~

    Exercise example application construction and resource ownership.

    :copyright: (c) 2026 by Harrison Erd.
    :license: BSD-3-Clause, see LICENSE for more details.
"""

import subprocess
import sys
import unittest
from pathlib import Path


class AppFactoryTests(unittest.IsolatedAsyncioTestCase):
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
            cwd=Path(__file__).resolve().parents[1],
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
