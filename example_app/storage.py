# -*- coding: utf-8 -*-
"""
    example_app.storage
    ~~~~~~~~~~~~~~~~~~~

    Application-owned MongoDB storage using PyMongo's native async client.

    :copyright: (c) 2026 by Harrison Erd.
    :license: BSD-3-Clause, see LICENSE for more details.
"""

from asyncio import Lock
from datetime import UTC, datetime

from pymongo import AsyncMongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError


NOTE_FIELDS = {'_id': 0, '_title_search': 0, '_body_search': 0}


def timestamp(seconds):
    return datetime.fromtimestamp(seconds, UTC)


class Database:
    def __init__(self, uri, name):
        # One client/pool per app worker and event loop; connection is lazy.
        self.client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5000)
        self.db = self.client[name]
        self._initialized = False
        self._init_lock = Lock()

    async def initialize(self):
        if self._initialized:
            return
        async with self._init_lock:
            if not self._initialized:
                await self.client.admin.command('ping')
                await self.db.sessions.create_index(
                    'refresh_digest', unique=True
                )
                await self.db.sessions.create_index(
                    'access_tokens.digest', unique=True
                )
                await self.db.sessions.create_index(
                    'expires_at', expireAfterSeconds=0
                )
                await self.db.notes.create_index(
                    [
                        ('owner', 1),
                        ('pinned', -1),
                        ('updated_at', -1),
                        ('id', -1),
                    ],
                )
                self._initialized = True

    async def close(self):
        await self.client.close()

    async def create_user(self, username, salt, password_hash):
        await self.initialize()
        try:
            await self.db.users.insert_one(
                {
                    '_id': username,
                    'salt': salt,
                    'password_hash': password_hash,
                },
            )
        except DuplicateKeyError:
            return False
        return True

    async def get_user(self, username):
        await self.initialize()
        return await self.db.users.find_one({'_id': username})

    async def create_login(self, username, login_id, refresh_digest,
                           refresh_expires, access_digest, access_expires):
        await self.initialize()
        # Keep a login and its access credentials in one document. Refresh and
        # logout are atomic without requiring replica-set transactions.
        await self.db.sessions.insert_one({
            '_id': login_id,
            'user_id': username,
            'refresh_digest': refresh_digest,
            'expires_at': timestamp(refresh_expires),
            'access_tokens': [
                {
                    'digest': access_digest,
                    'expires_at': timestamp(access_expires),
                }
            ],
        })

    async def refresh_login(self, refresh_digest, access_digest,
                            access_expires, now):
        await self.initialize()
        current_time = timestamp(now)
        session = await self.db.sessions.find_one_and_update(
            {
                'refresh_digest': refresh_digest,
                'expires_at': {'$gt': current_time},
            },
            [
                {
                    '$set': {
                        'access_tokens': {
                            '$concatArrays': [
                                # Prune old access tokens while retaining
                                # tokens used by other tabs.
                                {
                                    '$filter': {
                                        'input': '$access_tokens',
                                        'as': 'token',
                                        'cond': {
                                            '$gt': [
                                                '$$token.expires_at',
                                                current_time,
                                            ]
                                        },
                                    }
                                },
                                {
                                    '$literal': [
                                        {
                                            'digest': access_digest,
                                            'expires_at': timestamp(
                                                access_expires
                                            ),
                                        }
                                    ]
                                },
                            ]
                        }
                    }
                }
            ],
            projection={'user_id': 1},
            return_document=ReturnDocument.AFTER,
        )
        return session['user_id'] if session else None

    async def get_access_token(self, digest, now):
        await self.initialize()
        current_time = timestamp(now)
        # TTL cleanup is asynchronous, so authorization must check both
        # deadlines.
        session = await self.db.sessions.find_one(
            {
                'expires_at': {'$gt': current_time},
                'access_tokens': {
                    '$elemMatch': {
                        'digest': digest,
                        'expires_at': {'$gt': current_time},
                    }
                },
            },
            {'user_id': 1},
        )
        if session:
            return {'user_id': session['user_id'], 'login_id': session['_id']}

    async def revoke_login(self, login_id):
        await self.initialize()
        await self.db.sessions.delete_one({'_id': login_id})

    async def list_notes(self, owner, search, pinned, limit, offset):
        await self.initialize()
        query = {'owner': owner}
        if search:
            # Store Python-casefolded fields to preserve Unicode substring
            # search.
            # $literal keeps search text such as "$title" from becoming an
            # expression.
            query['$expr'] = {
                '$gte': [
                    {
                        '$indexOfCP': [
                            {
                                '$concat': [
                                    '$_title_search',
                                    '\n',
                                    '$_body_search',
                                ]
                            },
                            {'$literal': search},
                        ]
                    },
                    0,
                ]
            }
        if pinned:
            query['pinned'] = pinned == 'true'
        # MongoDB skip accepts signed 64-bit integers. Larger offsets are
        # empty.
        items = (
            [{'$match': {'_id': {'$exists': False}}}]
            if offset >= 2**63
            else [
                {'$skip': offset},
                {'$limit': limit},
                {'$project': NOTE_FIELDS},
            ]
        )
        cursor = await self.db.notes.aggregate([
            {'$match': query},
            {'$sort': {'pinned': -1, 'updated_at': -1, 'id': -1}},
            {'$facet': {'items': items, 'count': [{'$count': 'total'}]}},
        ])
        result = (await cursor.to_list(length=1))[0]
        return {
            'items': result['items'],
            'total': result['count'][0]['total'] if result['count'] else 0,
            'limit': limit,
            'offset': offset,
        }

    async def create_note(self, note):
        await self.initialize()
        await self.db.notes.insert_one({
            **note,
            '_id': note['id'],
            '_title_search': note['title'].casefold(),
            '_body_search': note['body'].casefold(),
        })

    async def get_note(self, note_id):
        await self.initialize()
        return await self.db.notes.find_one({'_id': note_id}, NOTE_FIELDS)

    async def update_note(self, note_id, owner, data):
        await self.initialize()
        fields = {
            key: data[key]
            for key in ('title', 'body', 'pinned', 'updated_at')
            if key in data
        }
        for key in ('title', 'body'):
            if key in fields:
                fields[f'_{key}_search'] = fields[key].casefold()
        return await self.db.notes.find_one_and_update(
            {'_id': note_id, 'owner': owner},
            {'$set': fields},
            projection=NOTE_FIELDS,
            return_document=ReturnDocument.AFTER,
        )

    async def delete_note(self, note_id, owner):
        await self.initialize()
        result = await self.db.notes.delete_one(
            {'_id': note_id, 'owner': owner}
        )
        return result.deleted_count == 1

    async def export_notes(self, owner):
        await self.initialize()
        return (
            await self.db.notes.find({'owner': owner}, NOTE_FIELDS)
            .sort(
                [('created_at', 1), ('id', 1)],
            )
            .to_list(length=None)
        )
