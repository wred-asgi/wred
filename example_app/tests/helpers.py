async def call_app(app, scope, receive):
    """Drive an ASGI request and capture its actual outgoing messages."""
    messages = []

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages
