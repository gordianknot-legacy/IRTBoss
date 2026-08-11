"""CSRF defence for cookie-authenticated requests.

The session cookie is ``SameSite=Lax``, which already stops a cross-site *form
post* from carrying it. Relying on that alone was the previous position, and it
is thinner than it looks: Lax is a same-site check, so it does not constrain a
subdomain, a browser that does not implement it, or a future decision to relax it
for a redirect flow. It also leaves nothing at all in the way once someone adds
an endpoint that mutates on GET.

So: a double-submit token. A random value is set in a second cookie that script
*can* read, and an unsafe request must echo it in a header. A cross-site attacker
can make the browser send cookies but cannot read them and cannot set a custom
header on a cross-origin request, so it cannot produce the echo.

Three deliberate limits on where the check applies:

**Only when the request authenticates by cookie.** A bearer token is not attached
by the browser automatically, so a request carrying one is not a forged request;
requiring a header the caller would have to invent adds nothing. Scripts, tests
and the generated client are unaffected.

**Not on logout.** A forged logout is a nuisance, and the alternative failure —
a session holding a valid session cookie but no CSRF cookie, unable to log out —
is worse. Logout is the one endpoint whose job is to make the session safe.

**Not on requests with no session cookie.** Login and registration arrive without
one, and there is no session to hijack yet. Login CSRF (forcing a victim into an
attacker's account) is not defended here, and is recorded as such in PROGRESS.md.
"""

from __future__ import annotations

import hmac
import secrets

from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.core.config import Settings

CSRF_HEADER_NAME = "X-CSRF-Token"

# Methods that must not mutate state, so nothing to forge. TRACE is here because
# it is in the RFC's safe set; the application does not route it.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Exempt paths, matched exactly. A prefix match would silently exempt any future
# route added underneath it, so this is the full path — spelled out rather than
# built from `app.api.router.API_PREFIX`, which would be a circular import
# (the routers import this module). `test_api_csrf.py` asserts the literal still
# names the real logout route, which is the drift this would otherwise invite.
EXEMPT_PATHS = frozenset({"/api/v1/auth/logout"})

TOKEN_BYTES = 32


def new_csrf_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def set_csrf_cookie(response: Response, settings: Settings, token: str) -> None:
    """Set the readable half of the double-submit pair.

    ``httponly=False`` is the point of this cookie and not an oversight: the
    frontend has to read it to echo it. It carries no authority on its own — a
    session cookie is still required — so exposing it to script costs nothing
    that an XSS able to read it would not already have.
    """

    response.set_cookie(
        settings.csrf_cookie_name,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=False,
        secure=settings.session_cookie_is_secure,
        samesite="lax",
        path="/",
    )


class CSRFMiddleware(BaseHTTPMiddleware):
    """Rejects unsafe cookie-authenticated requests that do not echo the token."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if self._requires_token(request):
            cookie = request.cookies.get(self._settings.csrf_cookie_name)
            header = request.headers.get(CSRF_HEADER_NAME)
            if not cookie or not header or not hmac.compare_digest(cookie, header):
                # 403 rather than 401: the caller is authenticated, and retrying
                # with the same credentials will not help. The message says what
                # to do because the legitimate cause is a client that has not
                # been taught to echo the header.
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            f"Missing or invalid {CSRF_HEADER_NAME} header. "
                            "Cookie-authenticated requests that change state must "
                            f"echo the {self._settings.csrf_cookie_name} cookie in "
                            "that header."
                        )
                    },
                )
        return await call_next(request)

    def _requires_token(self, request: Request) -> bool:
        if request.method.upper() in SAFE_METHODS:
            return False
        if request.url.path in EXEMPT_PATHS:
            return False
        if not request.cookies.get(self._settings.session_cookie_name):
            return False
        # A caller that also sends a bearer token is a script, not a browser
        # following a link. This is not an exemption an attacker can take: an
        # `Authorization` header is not CORS-safelisted, so a cross-origin request
        # carrying one needs a preflight that succeeds against the origin
        # allowlist in `app.main`. Note that `deps._extract_token` still prefers
        # the cookie when both are present — the exemption is about who is
        # calling, not about which credential ends up being used.
        authorization = request.headers.get("Authorization", "")
        return not authorization.lower().startswith("bearer ")
