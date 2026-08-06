"""Email/password authentication.

v1 had none: every project, dataset and report was world-readable by UUID (P5).
This package supplies the three pieces that were missing — a password hash worth
storing, a session token that expires, and a dependency that turns a request into
a :class:`~app.db.models.User` — and nothing else.

Passwords are never logged, never returned in a schema, and never compared with
``==``: :mod:`app.auth.passwords` delegates to argon2-cffi, whose verifier is
constant-time.
"""

from .passwords import PasswordHasher, hash_password, needs_rehash, verify_password
from .ratelimit import LoginRateLimiter, get_login_rate_limiter
from .tokens import SessionToken, TokenError, issue_token, read_token

__all__ = [
    "LoginRateLimiter",
    "PasswordHasher",
    "SessionToken",
    "TokenError",
    "get_login_rate_limiter",
    "hash_password",
    "issue_token",
    "needs_rehash",
    "read_token",
    "verify_password",
]
