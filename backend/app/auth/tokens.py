"""Session tokens.

``itsdangerous`` rather than JWT. The product needs one claim — which user is
this — with an expiry, and JWT buys header-declared algorithms, ``alg: none``
footguns and a library that must be kept current, in exchange for
interoperability nobody here consumes. A signed, timestamped, opaque blob is the
smaller attack surface.

Expiry is enforced on *read*, from the signature timestamp, so a token cannot be
extended by editing its payload: the timestamp is inside what is signed.

The token also carries a fingerprint of the account's password hash. Changing a
password therefore invalidates every session issued before it, which is the
property that makes "log out everywhere" possible without a server-side session
table.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import Settings

_SALT = "irtboss.session.v1"


class TokenError(Exception):
    """Raised for any invalid token: bad signature, expired, or malformed.

    Deliberately one exception. Telling a client *why* its token failed is free
    information for an attacker and changes nothing for a legitimate one, whose
    only remedy is to log in again.
    """


@dataclass(frozen=True)
class SessionToken:
    user_id: uuid.UUID
    fingerprint: str
    # From the signature timestamp, which is inside what is signed, so a client
    # cannot backdate it. Compared against the account's revocation time in
    # `deps.current_user`; that is what makes "revoke my sessions" possible
    # without a server-side session table.
    issued_at: datetime


def _fingerprint(password_hash: str) -> str:
    # Truncated digest, not the hash itself: the token is handed to the client,
    # and a stored Argon2 hash should never leave the server even in encoded
    # form. 16 hex chars is ample to detect a credential change.
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        settings.secret_key.get_secret_value(), salt=_SALT
    )


def issue_token(settings: Settings, *, user_id: uuid.UUID, password_hash: str) -> str:
    return _serializer(settings).dumps(
        {"uid": str(user_id), "fp": _fingerprint(password_hash)}
    )


def read_token(settings: Settings, token: str) -> SessionToken:
    try:
        payload, issued_at = _serializer(settings).loads(
            token, max_age=settings.session_ttl_seconds, return_timestamp=True
        )
        # itsdangerous returns an aware UTC datetime; normalising here means no
        # caller has to remember which kind it got.
        if issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=UTC)
        return SessionToken(
            user_id=uuid.UUID(payload["uid"]),
            fingerprint=str(payload["fp"]),
            issued_at=issued_at.astimezone(UTC),
        )
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError) as exc:
        raise TokenError("invalid session token") from exc


def is_revoked(token: SessionToken, revoked_at: datetime | None) -> bool:
    """Was this token issued before the account revoked its sessions?

    The signature timestamp has one-second resolution, so a token issued in the
    same second as a revocation is treated as revoked. That is the safe side of
    the ambiguity: the cost is that logging in again within the same second as
    revoking returns a token that is immediately rejected, and the remedy — log
    in again — is the thing the user is already doing. The alternative leaves a
    sub-second window in which a token that should be dead still works.
    """

    if revoked_at is None:
        return False
    if revoked_at.tzinfo is None:
        # SQLite hands back naive datetimes; the column is UTC either way.
        revoked_at = revoked_at.replace(tzinfo=UTC)
    return token.issued_at < revoked_at


def fingerprint_matches(token: SessionToken, password_hash: str) -> bool:
    return hmac.compare_digest(token.fingerprint, _fingerprint(password_hash))
