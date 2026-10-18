# -*- coding: utf-8 -*-
"""
    example_app.notes
    ~~~~~~~~~~~~~~~~~

    Private note CRUD, validation, filtering, pagination, and JSON export.

    :copyright: (c) 2026 by Harrison Erd.
    :license: BSD-3-Clause, see LICENSE for more details.
"""

from datetime import UTC, datetime
from secrets import token_urlsafe

import orjson

from .auth import protected


async def read_note(request, partial=False):
    try:
        data = await request.json()
    except orjson.JSONDecodeError:
        raise ValueError('Invalid JSON body') from None
    if (
        not isinstance(data, dict)
        or not data
        or data.keys() - {'title', 'body', 'pinned'}
    ):
        raise ValueError('Send an object containing title, body, or pinned')
    if not partial and 'title' not in data:
        raise ValueError('A title is required')
    if 'title' in data and (
        not isinstance(data['title'], str)
        or not 1 <= len(data['title'].strip()) <= 100
    ):
        raise ValueError('Title must contain 1–100 characters')
    if 'body' in data and (
        not isinstance(data['body'], str) or len(data['body']) > 10_000
    ):
        raise ValueError('Body must be a string of at most 10,000 characters')
    if 'pinned' in data and not isinstance(data['pinned'], bool):
        raise ValueError('Pinned must be a boolean')
    if 'title' in data:
        data['title'] = data['title'].strip()
    return data if partial else {'body': '', 'pinned': False, **data}


async def owned_note(database, note_id, user):
    note = await database.get_note(note_id)
    if note is None:
        return {'error': 'Note not found'}, 'application/json', 404
    if note['owner'] != user['id']:
        return (
            {'error': 'This note belongs to another user'},
            'application/json',
            403,
        )
    return note


def register_routes(app, database):
    """Register note endpoints; each handler requires a valid bearer token."""

    @app.route('/api/notes', methods=['GET'])
    @protected(database)
    async def list_notes(request):
        # Keep this demo's query budget at 20 fields, including repeated keys.
        if request.scope.get('query_string', b'').count(b'&') >= 20:
            return {'error': 'Invalid query string'}, 'application/json', 400
        try:
            query = request.query()
        except UnicodeDecodeError:
            return {'error': 'Invalid query string'}, 'application/json', 400
        try:
            limit = int(query.get('limit') or '5')
            offset = int(query.get('offset') or '0')
        except ValueError:
            return (
                {'error': 'Limit and offset must be integers'},
                'application/json',
                400,
            )
        if not 1 <= limit <= 50 or offset < 0:
            return (
                {
                    'error': (
                        'Limit must be 1–50; offset must be zero or greater'
                    )
                },
                'application/json',
                400,
            )
        search = query.get('q', '').strip().casefold()
        pinned = query.get('pinned', '')
        if pinned not in ('', 'true', 'false'):
            return (
                {'error': 'Pinned filter must be true or false'},
                'application/json',
                400,
            )
        return await database.list_notes(
            request.user['id'], search, pinned, limit, offset
        )

    @app.route('/api/notes', methods=['POST'])
    @protected(database)
    async def create_note(request):
        try:
            data = await read_note(request)
        except ValueError as error:
            return {'error': str(error)}, 'application/json', 400
        note_id = token_urlsafe(9)
        now = datetime.now(UTC).isoformat(timespec='microseconds')
        note = {
            'id': note_id,
            'owner': request.user['id'],
            **data,
            'created_at': now,
            'updated_at': now,
        }
        await database.create_note(note)
        return (
            note,
            'application/json',
            201,
            [('Location', f'/api/notes/{note_id}')],
        )

    @app.route('/api/notes/{note_id}', methods=['GET'])
    @protected(database)
    async def get_note(request, note_id):
        return await owned_note(database, note_id, request.user)

    @app.route('/api/notes/{note_id}', methods=['PUT', 'PATCH'])
    @protected(database)
    async def update_note(request, note_id):
        note = await owned_note(database, note_id, request.user)
        if isinstance(note, tuple):
            return note
        try:
            data = await read_note(request, partial=request.method == 'PATCH')
        except ValueError as error:
            return {'error': str(error)}, 'application/json', 400
        data['updated_at'] = datetime.now(UTC).isoformat(
            timespec='microseconds'
        )
        updated = await database.update_note(note_id, request.user['id'], data)
        if updated is None:
            return {'error': 'Note not found'}, 'application/json', 404
        return updated

    @app.route('/api/notes/{note_id}', methods=['DELETE'])
    @protected(database)
    async def delete_note(request, note_id):
        note = await owned_note(database, note_id, request.user)
        if isinstance(note, tuple):
            return note
        if not await database.delete_note(note_id, request.user['id']):
            return {'error': 'Note not found'}, 'application/json', 404
        return b'', 'application/json', 204

    # This fixed path wins over /api/notes/{note_id}, even though it is
    # registered afterward.
    @app.route('/api/notes/export', methods=['GET'])
    @protected(database)
    async def export_notes(request):
        items = await database.export_notes(request.user['id'])
        return (
            items,
            'application/json',
            200,
            [('Content-Disposition', 'attachment; filename="notes.json"')],
        )
