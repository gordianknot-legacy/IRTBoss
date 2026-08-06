"""Registration, login, logout, and "who am I".

The login handler is written so that the response is the same shape and the same
work regardless of whether the account exists: an unknown email still costs an
Argon2 verification against a dummy hash. Skipping it would make "no such user"
measurably faster than "wrong password", which is an account-enumeration oracle
that no amount of identical wording fixes.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.api.schemas import LoginRequest, RegisterRequest, SessionOut, UserOut
from app.auth.passwords import hash_password, verify_password
from app.auth.ratelimit import get_login_rate_limiter
from app.auth.tokens import issue_token
from app.repositories.users import UserRepository, normalise_email

router = APIRouter(prefix="/auth", tags=["auth"])

# Verified against when the account does not exist, purely to keep the timing of
# the two branches comparable. Never matches any password.
_DUMMY_HASH = hash_password("timing-equalisation-placeholder-value")


def _client_ip(request: Request) -> str:
    # No X-Forwarded-For parsing: behind a proxy that does not strip it, a
    # client-supplied header would let an attacker rotate their own rate-limit
    # key. Configure the proxy to set the peer address instead.
    return request.client.host if request.client else "unknown"


def _set_session_cookie(response: Response, settings, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,           # not readable by script: limits XSS to same-origin requests
        secure=settings.is_production,
        samesite="lax",
        path="/",
    )


@router.post("/register", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    response: Response,
    settings: SettingsDep,
    session: SessionDep,
) -> SessionOut:
    users = UserRepository(session)
    if await users.get_by_email(payload.email) is not None:
        # Registration cannot avoid disclosing that an address is taken — the
        # uniqueness constraint is user-visible by definition. Login is where
        # enumeration is worth defending, and it is defended above.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        )

    user = await users.create(
        email=payload.email, password_hash=hash_password(payload.password)
    )
    await session.commit()

    token = issue_token(settings, user_id=user.id, password_hash=user.password_hash)
    _set_session_cookie(response, settings, token)
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
    _set_session_cookie(response, settings, token)
    return SessionOut(
        access_token=token,
        expires_in=settings.session_ttl_seconds,
        user=UserOut.model_validate(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, settings: SettingsDep) -> Response:
    """Clears the cookie.

    Bearer tokens held by non-browser clients remain valid until they expire —
    there is no server-side session table to revoke against. Changing a password
    invalidates them all (see :mod:`app.auth.tokens`), which is the escape hatch
    that matters after a leak.
    """

    response.delete_cookie(settings.session_cookie_name, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
