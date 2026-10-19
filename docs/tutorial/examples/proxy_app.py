from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from example_app.app import create_app

# Use only behind a trusted proxy connecting from IPv4 loopback.
app = ProxyHeadersMiddleware(create_app(), trusted_hosts=['127.0.0.1'])
