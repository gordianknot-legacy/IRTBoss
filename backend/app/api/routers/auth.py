"""Registration, login, logout, and "who am I".

The login handler is written so that the response is the same shape and the same
work regardless of whether the account exists: an unknown email still costs an
Argon2 verification against a dummy hash. Skipping it would make "no such user"
measurably faster than "wrong password", which is an account-enumeration oracle
that no amount of identical wording fixes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.api.schemas import LoginRequest, RegisterRequest, SessionOut, UserOut
from app.auth.csrf import new_csrf_token, set_csrf_cookie
from app.auth.passwords import hash_password, verify_password
from app.auth.ratelimit import get_login_rate_limiter
from app.auth.tokens import issue_token
from app.repositories.users import UserRepository, normalise_email

router = APIRouter(prefix="/auth", tags=["auth"])

# Verified against when the account does not exist, purely to keep the timing of
# the two branches comparable. Never matches any password.
_DUMMY_HASH = hash_password("timing-equalisation-placeholder-value")

# Registration shares the login limiter's configured budget but not its counters:
# a failed registration should not spend a real user's login attempts, and a
# successful login should not clear an enumeration sweep's record.
_REGISTER_SCOPE = "register|"


def _client_ip(request: Request) -> str:
    # No X-Forwarded-For parsing: behind a proxy that does not strip it, a
    # client-supplied header would let an attacker rotate their own rate-limit
    # key. Configure the proxy to set the peer address instead.
    return request.client.host if request.client else "unknown"


def _start_session(response: Response, settings, token: str) -> None:
    """Set both halves of a browser session: the credential and the CSRF token."""

    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,           # not readable by script: limits XSS to same-origin requests
        # Not `is_production`: `environment` is a free string, and under that rule
        # a deployment named `staging` served this cookie over plaintext. See
        # Settings.session_cookie_is_secure.
        secure=settings.session_cookie_is_secure,
        samesite="lax",
        path="/",
    )
    set_csrf_cookie(response, settings, new_csrf_token())


@router.post("/register", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
    session: SessionDep,
) -> SessionOut:
    limiter = get_login_rate_limiter(settings)
    scope = _REGISTER_SCOPE + normalise_email(payload.email)
    ip = _client_ip(request)

    if limiter.is_blocked(scope, ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Try again later.",
        )

    users = UserRepository(session)
    if await users.get_by_email(payload.email) is not None:
        # Registration cannot avoid disclosing that an address is taken — the
        # uniqueness constraint is user-visible by definition, and closing the
        # oracle properly needs an email channel this product does not have (it
        # would answer "check your inbox" either way). What is closed here is the
        # *bulk* case: throttling means the endpoint cannot be used to test a list
        # of addresses. A patient attacker can still probe one address, and
        # PROGRESS.md says so.
        limiter.record_failure(scope, ip)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        )

    user = await users.create(
        email=payload.email, password_hash=hash_password(payload.password)
    )
    await session.commit()

    token = issue_token(settings, user_id=user.id, password_hash=user.password_hash)
    _start_session(response, settings, token)
    return SessionOut(
        access_token=token,
        expires_in=settings.session_ttl_seconds,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=SessionOut)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
    session: SessionDep,
) -> SessionOut:
    limiter = get_login_rate_limiter(settings)
    email = normalise_email(payload.email)
    ip = _client_ip(request)

    if limiter.is_blocked(email, ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
        )

    user = await UserRepository(session).get_by_email(email)
    stored_hash = user.password_hash if user is not None else _DUMMY_HASH
    ok = verify_password(payload.password, stored_hash)

    if not ok or user is None or not user.is_active:
        limiter.record_failure(email, ip)
        # One message for every failure mode: wrong password, unknown account,
        # deactivated account.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    limiter.reset(email, ip)
    token = issue_token(settings, user_id=user.id, password_hash=user.password_hash)
    _start_session(response, settings, token)
    return SessionOut(
        access_token=token,
        expires_in=settings.session_ttl_seconds,
        user=UserOut.model_validate(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, settings: SettingsDep) -> Response:
    """Clears this browser's cookies.

    Deliberately local. A token already issued stays valid for the rest of its
    TTL, so a bearer token held by a script is unaffected — which is why
    ``/auth/revoke-sessions`` exists. Making plain logout global instead would
    mean signing out of a phone ended a desktop session, which is surprising in
    the ordinary case and is not what a user pressing "log out" is asking for.

    Exempt from the CSRF check: see :mod:`app.auth.csrf`.
    """

    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/revoke-sessions", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_sessions(
    response: Response,
    settings: SettingsDep,
    session: SessionDep,
    user: CurrentUser,
) -> Response:
    """Invalidate every session for this account, including this one.

    The revocation that used to require changing your password. It stamps the
    account and rejects any token signed before that instant, so tokens held by
    other browsers and by scripts stop working — the case that matters after a
    laptop is lost or a token is pasted somewhere it should not have been.

    All-or-nothing by construction: one timestamp per account rather than one row
    per session means there is nothing to revoke selectively. A token issued
    within the same second as the revocation is also rejected, so log in again
    afterwards rather than reusing a token from that second.
    """

    user.sessions_revoked_at = datetime.now(UTC)
    await session.commit()

    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser, response: Response, settings: SettingsDep) -> UserOut:
    """Who am I — and, incidentally, where the CSRF cookie is refreshed.

    The frontend calls this on load. Reissuing the token here means a browser
    holding a valid session cookie whose CSRF cookie has expired, or which
    predates this defence existing, recovers on the next page load instead of
    having every mutating request rejected until it logs out.
    """

    set_csrf_cookie(response, settings, new_csrf_token())
    return UserOut.model_validate(user)
