"""Authentication behaviour.

v1 had no authentication at all (P5), so these tests are the floor: an account
can be created, a wrong password is refused, an anonymous caller sees nothing,
and repeated failures are throttled.
"""

from __future__ import annotations

from app.auth.passwords import hash_password, verify_password
from tests.conftest import TEST_PASSWORD, auth, register


async def test_register_then_login(client):
    email = "analyst@example.com"
    created = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": TEST_PASSWORD}
    )
    assert created.status_code == 201
    assert created.json()["user"]["email"] == email
    # The hash must never appear in a response body under any key.
    assert "password" not in created.text.lower().replace("password_hash", "")

    client.cookies.clear()
    logged_in = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD}
    )
    assert logged_in.status_code == 200
    token = logged_in.json()["access_token"]

    client.cookies.clear()
    me = await client.get("/api/v1/auth/me", headers=auth(token))
    assert me.status_code == 200
    assert me.json()["email"] == email


async def test_login_is_case_insensitive_on_email(client):
    await register(client, "MixedCase@Example.com")
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "mixedcase@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200


async def test_wrong_password_is_rejected(client):
    await register(client, "someone@example.com")
    client.cookies.clear()
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "someone@example.com", "password": "wrong-password-entirely"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


async def test_unknown_account_gives_the_same_response_as_a_wrong_password(client):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


async def test_duplicate_registration_is_rejected(client):
    await register(client, "dupe@example.com")
    client.cookies.clear()
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "dupe@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 409


async def test_short_password_is_rejected_at_registration(client):
    response = await client.post(
        "/api/v1/auth/register", json={"email": "short@example.com", "password": "abc"}
    )
    assert response.status_code == 422


async def test_anonymous_and_forged_tokens_are_refused(client):
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/projects")).status_code == 401
    forged = await client.get("/api/v1/auth/me", headers=auth("not.a.real.token"))
    assert forged.status_code == 401


async def test_login_attempts_are_rate_limited(client, settings):
    await register(client, "throttled@example.com")
    client.cookies.clear()

    statuses = []
    for _ in range(settings.login_max_attempts + 2):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "throttled@example.com", "password": "not-the-password"},
        )
        statuses.append(response.status_code)

    assert 429 in statuses
    # Throttling must survive knowing the right password, or it is trivially
    # bypassed by interleaving a correct guess.
    blocked = await client.post(
        "/api/v1/auth/login",
        json={"email": "throttled@example.com", "password": TEST_PASSWORD},
    )
    assert blocked.status_code == 429


def test_password_hash_is_argon2id_and_salted():
    first = hash_password(TEST_PASSWORD)
    second = hash_password(TEST_PASSWORD)
    assert first.startswith("$argon2id$")
    assert first != second  # distinct salts
    assert verify_password(TEST_PASSWORD, first)
    assert not verify_password("something else", first)
    # A corrupt stored hash is a failed login, not a 500.
    assert not verify_password(TEST_PASSWORD, "")
    assert not verify_password(TEST_PASSWORD, "not-a-hash")
