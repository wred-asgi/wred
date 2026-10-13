"""Private note CRUD, validation, filtering, pagination, and JSON export."""

from datetime import UTC, datetime
from secrets import token_urlsafe

from wred import WredRequestError
from .auth import protected
from .storage import notes


async def read_note(request, partial=False):
    data = await request.json()
    if not isinstance(data, dict) or not data or data.keys() - {'title', 'body', 'pinned'}:
        raise WredRequestError('Send an object containing title, body, or pinned')
    if not partial and 'title' not in data:
        raise WredRequestError('A title is required')
    if 'title' in data and (
        not isinstance(data['title'], str) or not 1 <= len(data['title'].strip()) <= 100
    ):
        raise WredRequestError('Title must contain 1–100 characters')
    if 'body' in data and (not isinstance(data['body'], str) or len(data['body']) > 10_000):
        raise WredRequestError('Body must be a string of at most 10,000 characters')
    if 'pinned' in data and not isinstance(data['pinned'], bool):
        raise WredRequestError('Pinned must be a boolean')
    if 'title' in data:
        data['title'] = data['title'].strip()
    return data if partial else {'body': '', 'pinned': False, **data}


def owned_note(note_id, user):
    note = notes.get(note_id)
    if note is None:
        return {'error': 'Note not found'}, 'application/json', 404
    if note['owner'] != user['id']:
        return {'error': 'This note belongs to another user'}, 'application/json', 403
    return note


def register_routes(app):
    """Register note endpoints; each handler requires a valid bearer token."""

    @app.route('/api/notes', methods=['GET'])
    @protected
    async def list_notes(request):
        # Keep this demo's query budget at 20 fields, including repeated keys.
        if request.scope.get('query_string', b'').count(b'&') >= 20:
            raise WredRequestError('Invalid query string')
        query = request.query()
        try:
            limit = int(query.get('limit') or '5')
            offset = int(query.get('offset') or '0')
        except ValueError:
            raise WredRequestError('Limit and offset must be integers')
        if not 1 <= limit <= 50 or offset < 0:
            raise WredRequestError('Limit must be 1–50; offset must be zero or greater')
        search = query.get('q', '').strip().casefold()
        pinned = query.get('pinned', '')
        if pinned not in ('', 'true', 'false'):
            raise WredRequestError('Pinned filter must be true or false')
        # Apply ownership before searching or counting so other users' data never leaks.
        items = [note for note in notes.values() if note['owner'] == request.user['id']]
        items = [
            note for note in items if search in (note['title'] + '\n' + note['body']).casefold()
        ]
        if pinned:
            items = [note for note in items if note['pinned'] == (pinned == 'true')]
        # Show pinned notes first, then most recently edited notes within each group.
        items.sort(key=lambda note: (note['pinned'], note['updated_at'], note['id']), reverse=True)
        return {
            'items': items[offset : offset + limit],
            'total': len(items),
            'limit': limit,
            'offset': offset,
        }

    @app.route('/api/notes', methods=['POST'])
    @protected
    async def create_note(request):
        data = await read_note(request)
        note_id = token_urlsafe(9)
        now = datetime.now(UTC).isoformat(timespec='microseconds')
        note = {
            'id': note_id,
            'owner': request.user['id'],
            **data,
            'created_at': now,
            'updated_at': now,
        }
        notes[note_id] = note
        return note, 'application/json', 201, [('Location', f'/api/notes/{note_id}')]

    @app.route('/api/notes/{note_id}', methods=['GET'])
    @protected
    async def get_note(request, note_id):
        return owned_note(note_id, request.user)

    @app.route('/api/notes/{note_id}', methods=['PUT', 'PATCH'])
    @protected
    async def update_note(request, note_id):
        note = owned_note(note_id, request.user)
        if isinstance(note, tuple):
            return note
        data = await read_note(request, partial=request.method == 'PATCH')
        note.update(data)
        note['updated_at'] = datetime.now(UTC).isoformat(timespec='microseconds')
        return note

    @app.route('/api/notes/{note_id}', methods=['DELETE'])
    @protected
    async def delete_note(request, note_id):
        note = owned_note(note_id, request.user)
        if isinstance(note, tuple):
            return note
        del notes[note_id]
        return b'', 'application/json', 204

    # This fixed path wins over /api/notes/{note_id}, even though it is registered afterward.
    @app.route('/api/notes/export', methods=['GET'])
    @protected
    async def export_notes(request):
        items = [note for note in notes.values() if note['owner'] == request.user['id']]
        return (
            items,
            'application/json',
            200,
            [('Content-Disposition', 'attachment; filename="notes.json"')],
        )
