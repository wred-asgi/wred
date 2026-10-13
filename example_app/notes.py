"""Private note CRUD, validation, filtering, pagination, and JSON export."""
from datetime import UTC, datetime
from secrets import token_urlsafe
from urllib.parse import parse_qs

from wred import WredRequestError
from .auth import protected
from .storage import notes


async def read_note(request, partial=False):  # Validate create/replace/partial update bodies.
    # JSON arrays and scalars are valid JSON, but this endpoint needs an object.
    data = await request.json()
    # Reject empty updates and misspelled fields instead of silently ignoring them.
    if not isinstance(data, dict) or not data or data.keys() - {'title', 'body', 'pinned'}:
        # Wred turns validation exceptions into a JSON error with HTTP 400.
        raise WredRequestError('Send an object containing title, body, or pinned')
    # POST and PUT require a title; PATCH may update just one other field.
    if not partial and 'title' not in data:
        # Explain exactly which required field is missing.
        raise WredRequestError('A title is required')
    # A supplied title must be a nonempty string, with room for a short heading.
    if 'title' in data and (not isinstance(data['title'], str) or not 1 <= len(data['title'].strip()) <= 100):
        # Keep validation in the application rather than changing Wred's JSON parser.
        raise WredRequestError('Title must contain 1–100 characters')
    # Bodies are optional strings; cap their length for this small in-memory example.
    if 'body' in data and (not isinstance(data['body'], str) or len(data['body']) > 10_000):
        # A clear message lets both the browser and API users correct the request.
        raise WredRequestError('Body must be a string of at most 10,000 characters')
    # JSON true/false become Python bool values; strings like "true" are not accepted.
    if 'pinned' in data and not isinstance(data['pinned'], bool):
        # Prevent accidental truthiness from pinning notes unexpectedly.
        raise WredRequestError('Pinned must be a boolean')
    # Trim titles without altering whitespace in the note's main text.
    if 'title' in data:
        # This normalized value is what will be saved and returned to the browser.
        data['title'] = data['title'].strip()
    # PATCH changes only submitted fields; POST/PUT supply defaults for omitted fields.
    return data if partial else {'body': '', 'pinned': False, **data}


def owned_note(note_id, user):  # Authentication and resource permissions are distinct.
    # Look up the ID from the URL in this demo's note store.
    note = notes.get(note_id)
    # Missing resources should return HTTP 404, not an empty successful response.
    if note is None:
        # Return an error tuple that the calling handler can pass straight to Wred.
        return {'error': 'Note not found'}, 'application/json', 404
    # A valid login does not grant access to another person's notes.
    if note['owner'] != user['id']:
        # HTTP 403 means authenticated, but forbidden from accessing this resource.
        return {'error': 'This note belongs to another user'}, 'application/json', 403
    # Only the owner receives the actual note dictionary.
    return note


def register_routes(app):
    """Register note endpoints; each handler requires a valid bearer token."""
    # GET and POST share a path but have separate handlers; the router chooses the method.
    @app.route('/api/notes', methods=['GET'])
    # Register the protected wrapper so unauthenticated requests never reach this handler.
    @protected
    async def list_notes(request):  # Query strings control filtering and pagination.
        # ASGI exposes the query string as bytes; standard-library parsing handles escaping.
        try:
            # Limit query fields so malformed or excessively large queries fail cleanly.
            query = parse_qs(request.scope.get('query_string', b'').decode('utf-8'), max_num_fields=20)
        # Invalid encoding and too many query fields are client errors too.
        except (UnicodeDecodeError, ValueError):
            # Keep parser errors inside Wred's existing request-error handling.
            raise WredRequestError('Invalid query string')
        # Treat omitted pagination values as a request for the first five notes.
        try:
            # parse_qs returns lists because query keys may appear more than once.
            limit = int(query.get('limit', ['5'])[0])
            # Offset skips a number of filtered notes, not a number of unfiltered records.
            offset = int(query.get('offset', ['0'])[0])
        # int() raises ValueError for text such as ?limit=abc.
        except ValueError:
            # Convert conversion failures into a useful client-facing JSON error.
            raise WredRequestError('Limit and offset must be integers')
        # Bound page size and reject negative offsets.
        if not 1 <= limit <= 50 or offset < 0:
            # Defaults and bounds are application policy, not router behavior.
            raise WredRequestError('Limit must be 1–50; offset must be zero or greater')
        # Search ignores case and whitespace around the query.
        search = query.get('q', [''])[0].strip().casefold()
        # The optional pinned filter accepts only explicit boolean spellings.
        pinned = query.get('pinned', [''])[0]
        # Reject unsupported filter values instead of guessing their meaning.
        if pinned not in ('', 'true', 'false'):
            # The browser and API documentation use the same query vocabulary.
            raise WredRequestError('Pinned filter must be true or false')
        # Apply ownership before searching or counting so other users' data never leaks.
        items = [note for note in notes.values() if note['owner'] == request.user['id']]
        # Match either the heading or the note body.
        items = [note for note in items if search in (note['title'] + '\n' + note['body']).casefold()]
        # Apply a pinned/unpinned filter only when the query requested one.
        if pinned:
            # Compare real booleans rather than strings stored in the note.
            items = [note for note in items if note['pinned'] == (pinned == 'true')]
        # Show pinned notes first, then most recently edited notes within each group.
        items.sort(key=lambda note: (note['pinned'], note['updated_at'], note['id']), reverse=True)
        # Wrap the page in an object so clients can also read pagination metadata.
        return {'items': items[offset:offset + limit], 'total': len(items), 'limit': limit, 'offset': offset}


    # POST on the same URL creates a note without a GET/POST branch in the handler.
    @app.route('/api/notes', methods=['POST'])
    # All notes are owned by the authenticated user, not by a submitted owner field.
    @protected
    async def create_note(request):  # Creation returns HTTP 201 and a Location header.
        # Validate the note before touching the store.
        data = await read_note(request)
        # Use a random URL-safe ID, independent of usernames and note contents.
        note_id = token_urlsafe(9)
        # Record UTC timestamps in a format clients can parse and display.
        now = datetime.now(UTC).isoformat(timespec='microseconds')
        # The application supplies owner/ID/timestamps so clients cannot impersonate others.
        note = {'id': note_id, 'owner': request.user['id'], **data, 'created_at': now, 'updated_at': now}
        # Save the note in this single-process demo's in-memory store.
        notes[note_id] = note
        # Location identifies the newly created resource; the body contains the saved note.
        return note, 'application/json', 201, [('Location', f'/api/notes/{note_id}')]


    # A dynamic path captures the note ID as a string passed by keyword.
    @app.route('/api/notes/{note_id}', methods=['GET'])
    # Validate the token before looking up any private note.
    @protected
    async def get_note(request, note_id):  # The ownership helper also supplies 403/404 responses.
        # Return the owner's note, or the error tuple produced by the permission check.
        return owned_note(note_id, request.user)


    # Two related HTTP methods can share one handler when their logic substantially overlaps.
    @app.route('/api/notes/{note_id}', methods=['PUT', 'PATCH'])
    # Method dispatch still happens in Wred; this branch selects replacement/update semantics.
    @protected
    async def update_note(request, note_id):  # PUT replaces fields; PATCH changes only supplied fields.
        # Check permissions before reading changes or mutating the note.
        note = owned_note(note_id, request.user)
        # Error tuples must be returned without modifying the store.
        if isinstance(note, tuple):
            # Preserve the ownership helper's HTTP 403 or 404.
            return note
        # Choose partial validation only for PATCH; PUT resets omitted optional fields.
        data = await read_note(request, partial=request.method == 'PATCH')
        # Apply validated fields while preserving owner, ID, and creation time.
        note.update(data)
        # Refresh the modification timestamp used to order the notebook.
        note['updated_at'] = datetime.now(UTC).isoformat(timespec='microseconds')
        # A dictionary response sends the saved note as JSON with HTTP 200.
        return note


    # DELETE has its own handler on the same dynamic path.
    @app.route('/api/notes/{note_id}', methods=['DELETE'])
    # A valid token alone is insufficient: the handler still verifies ownership.
    @protected
    async def delete_note(request, note_id):  # Successful deletion returns HTTP 204 No Content.
        # Reuse the exact same permission rules as reading and editing.
        note = owned_note(note_id, request.user)
        # Pass missing/forbidden responses through unchanged.
        if isinstance(note, tuple):
            # Denied deletion must leave the note in the store.
            return note
        # Remove the owner's note only after the permission check succeeds.
        del notes[note_id]
        # A 204 response must have an empty body; clients should not attempt JSON parsing.
        return b'', 'application/json', 204


    # This fixed path wins over /api/notes/{note_id}, even though it is registered afterward.
    @app.route('/api/notes/export', methods=['GET'])
    # Exports must be private to the logged-in user too.
    @protected
    async def export_notes(request):  # An array response and a download header in one tuple.
        # Select only this user's records; export all of them rather than just the current page.
        items = [note for note in notes.values() if note['owner'] == request.user['id']]
        # Wred serializes the list as a JSON array; Content-Disposition gives the download a name.
        return items, 'application/json', 200, [('Content-Disposition', 'attachment; filename="notes.json"')]
