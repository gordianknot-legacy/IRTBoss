"""CSRF defence for cookie-authenticated requests.

The property under test is narrow and worth stating: a request that carries the
session cookie and changes state must echo the CSRF cookie in a header. What is
*not* under test is the browser behaviour that makes the defence work — that a
cross-origin caller cannot read a cookie or set a custom header. That is the
browser's contract, and no test here can stand in for it.

Note what these tests imply about the rest of the suite: it authenticates with
bearer headers (see `conftest.register`), which is the exempt path, so nothing
else here would have noticed the check being added — or being broken.
"""

from __future__ import annotations

from app.api.router import API_PREFIX
from app.auth.csrf import CSRF_HEADER_NAME, EXEMPT_PATHS
from app.main import create_app
from tests.conftest import TEST_PASSWORD, auth


async def _login_with_cookies(client, email: str = "csrf@example.com") -> str:
    """Register, keeping the cookie jar, and return the readable CSRF token."""

    response = await client.post(
        f"{API_PREFIX}/auth/register", json={"email": email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 201, response.text
    token = client.cookies.get("irtboss_csrf")
    assert token, "registration should set a readable CSRF cookie"
    return token


def _project() -> dict:
    return {"name": "CSRF probe"}


async def test_registration_sets_both_cookies(client):
    await _login_with_cookies(client)
    assert client.cookies.get("irtboss_session")
    assert client.cookies.get("irtboss_csrf")


async def test_cookie_authenticated_post_without_the_header_is_refused(client):
    await _login_with_cookies(client)

    response = await client.post(f"{API_PREFIX}/projects", json=_project())

    assert response.status_code == 403
    assert CSRF_HEADER_NAME in response.json()["detail"]


async def test_cookie_authenticated_post_with_the_header_succeeds(client):
    csrf = await _login_with_cookies(client)

    response = await client.post(
        f"{API_PREFIX}/projects", json=_project(), headers={CSRF_HEADER_NAME: csrf}
    )

    assert response.status_code == 201, response.text


async def test_a_wrong_token_is_refused(client):
    """Presence is not enough: the header has to match the cookie.

    A forged request can set a header value it invents; what it cannot do is
    discover the one in the victim's cookie jar.
    """
    csrf = await _login_with_cookies(client)

    response = await client.post(
        f"{API_PREFIX}/projects",
        json=_project(),
        headers={CSRF_HEADER_NAME: csrf[:-1] + ("a" if csrf[-1] != "a" else "b")},
    )

    assert response.status_code == 403


async def test_a_get_needs_no_token(client):
    await _login_with_cookies(client)
    response = await client.get(f"{API_PREFIX}/projects")
    assert response.status_code == 200


async def test_bearer_callers_are_unaffected(client):
    """The script path stays a bare bearer token and no ceremony.

    Not an exploitable exemption: `Authorization` is not CORS-safelisted, so a
    cross-origin request carrying one needs a preflight that succeeds against the
    origin allowlist.
    """
    response = await client.post(
        f"{API_PREFIX}/auth/register",
        json={"email": "script@example.com", "password": TEST_PASSWORD},
    )
    token = response.json()["access_token"]
    client.cookies.clear()

    created = await client.post(
        f"{API_PREFIX}/projects", json=_project(), headers=auth(token)
    )

    assert created.status_code == 201, created.text


async def test_login_needs_no_token(client):
    """There is no session to hijack before one exists."""
    await _login_with_cookies(client, "returning@example.com")
    client.cookies.clear()

    response = await client.post(
        f"{API_PREFIX}/auth/login",
        json={"email": "returning@example.com", "password": TEST_PASSWORD},
    )

    assert response.status_code == 200


async def test_logout_is_exempt_and_clears_both_cookies(client):
    """Being unable to log out is worse than a forged logout.

    A browser holding a session cookie with no usable CSRF cookie must still have
    a way to end its session, so this endpoint cannot be gated on the token it
    might be missing.
    """
    await _login_with_cookies(client)

    response = await client.post(f"{API_PREFIX}/auth/logout")

    assert response.status_code == 204
    assert not client.cookies.get("irtboss_session")
    assert not client.cookies.get("irtboss_csrf")


async def test_me_reissues_the_csrf_cookie(client):
    """The recovery path for a browser whose CSRF cookie went missing."""
    await _login_with_cookies(client)
    client.cookies.delete("irtboss_csrf")
    assert not client.cookies.get("irtboss_csrf")

    response = await client.get(f"{API_PREFIX}/auth/me")

    assert response.status_code == 200
    reissued = client.cookies.get("irtboss_csrf")
    assert reissued
    assert (
        await client.post(
            f"{API_PREFIX}/projects",
            json=_project(),
            headers={CSRF_HEADER_NAME: reissued},
        )
    ).status_code == 201


def test_the_exempt_path_names_a_route_that_exists(settings):
    """`app.auth.csrf` spells the logout path as a literal to avoid a circular
    import. This is the check that the literal has not drifted from the route."""
    app = create_app(settings)
    # From the OpenAPI document rather than `app.routes`, which holds router
    # wrappers rather than a flat list of paths.
    paths = set(app.openapi()["paths"])

    assert paths >= EXEMPT_PATHS
    assert set(EXEMPT_PATHS) == {f"{API_PREFIX}/auth/logout"}
    # And the endpoint it names still mutates state, which is the only reason the
    # exemption is interesting.
    assert "post" in app.openapi()["paths"][f"{API_PREFIX}/auth/logout"]


def test_the_csrf_cookie_is_readable_and_the_session_cookie_is_not(settings):
    """One of these two has to be readable by script and the other must not be."""
    from fastapi import Response

    from app.auth.csrf import new_csrf_token, set_csrf_cookie

    response = Response()
    set_csrf_cookie(response, settings, new_csrf_token())
    header = response.headers["set-cookie"]

    assert settings.csrf_cookie_name in header
    assert "httponly" not in header.lower()
    assert "samesite=lax" in header.lower()
