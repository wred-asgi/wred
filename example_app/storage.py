"""Shared in-memory demo data; all records disappear when the process restarts."""

# Real deployments need persistent shared storage and shared rate-limit counters.
users = {}  # Username -> salt and password hash; never store plaintext passwords.
tokens = {}  # Token digest -> user ID and expiry; never store raw bearer tokens.
refresh_tokens = {}  # Cookie digest -> user ID, login ID, and absolute expiry.
notes = {}  # Note ID -> note, including the owning username.
