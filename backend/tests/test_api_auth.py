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


async def test_registration_is_rate_limited_so_it_cannot_sweep_a_list(client, settings):
    """The duplicate-address 409 is an enumeration oracle, and stays one.

    It cannot be closed without an email channel — a product that answers "check
    your inbox" either way needs an inbox to send to. What is closed is the bulk
    case: the endpoint cannot be used to test a list of addresses. A patient
    attacker probing a single address is still told the truth, and PROGRESS.md
    records that.
    """
    await register(client, "taken@example.com")
    client.cookies.clear()

    statuses = []
    for _ in range(settings.login_max_attempts + 2):
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "taken@example.com", "password": TEST_PASSWORD},
        )
        statuses.append(response.status_code)

    assert 409 in statuses, "the first probes should still answer honestly"
    assert 429 in statuses, "a sweep should run out of budget"


async def test_registration_throttling_does_not_consume_login_attempts(client, settings):
    """A stranger hammering registration must not lock the owner out of login."""
    await register(client, "owner@example.com")
    client.cookies.clear()

    for _ in range(settings.login_max_attempts + 2):
        await client.post(
            "/api/v1/auth/register",
            json={"email": "owner@example.com", "password": TEST_PASSWORD},
        )

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": TEST_PASSWORD},
    )
    assert login.status_code == 200


async def test_revoking_sessions_kills_a_token_held_elsewhere(client):
    """The revocation that used to require changing your password.

    Two tokens for one account stand in for two devices. Revoking through one
    must invalidate the other, which is the whole point: after a laptop goes
    missing, "change your password" should not be the only lever.
    """
    first = await register(client, "twodevices@example.com")
    client.cookies.clear()
    second = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "twodevices@example.com", "password": TEST_PASSWORD},
        )
    ).json()["access_token"]
    client.cookies.clear()

    assert (await client.get("/api/v1/auth/me", headers=auth(first))).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=auth(second))).status_code == 200

    revoked = await client.post(
        "/api/v1/auth/revoke-sessions", headers=auth(second)
    )
    assert revoked.status_code == 204

    assert (await client.get("/api/v1/auth/me", headers=auth(first))).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=auth(second))).status_code == 401


async def test_revoking_sessions_requires_authentication(client):
    assert (await client.post("/api/v1/auth/revoke-sessions")).status_code == 401


async def test_a_token_issued_after_a_revocation_still_works(client, engine):
    """Revocation is a line in time, not a permanent lock on the account."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from app.db.database import get_sessionmaker
    from app.db.models import User

    await register(client, "backagain@example.com")
    client.cookies.clear()

    # Stamped in the past rather than by calling the endpoint: the signature
    # timestamp has one-second resolution, so a token minted in the same second
    # as a revocation is rejected by design (see `app.auth.tokens.is_revoked`).
    # Sleeping through that would make this test slow to prove nothing extra.
    async with get_sessionmaker()() as session:
        await session.execute(
            update(User)
            .where(User.email == "backagain@example.com")
            .values(sessions_revoked_at=datetime.now(UTC) - timedelta(seconds=30))
        )
        await session.commit()

    fresh = await client.post(
        "/api/v1/auth/login",
        json={"email": "backagain@example.com", "password": TEST_PASSWORD},
    )
    assert fresh.status_code == 200
    client.cookies.clear()
    token = fresh.json()["access_token"]
    assert (await client.get("/api/v1/auth/me", headers=auth(token))).status_code == 200


def test_a_token_from_the_revocation_second_is_treated_as_revoked():
    """The documented resolution of the one-second ambiguity, asserted.

    itsdangerous stamps whole seconds. A token whose stamp equals the second in
    which sessions were revoked could be from either side of the line, and the
    safe reading is "revoked" — the cost is a re-login, and the alternative
    leaves a sub-second window where a token that should be dead still works.
    """
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from app.auth.tokens import SessionToken, is_revoked

    revoked_at = datetime(2026, 8, 11, 12, 0, 0, 500_000, tzinfo=UTC)
    same_second = SessionToken(
        user_id=uuid4(),
        fingerprint="0" * 16,
        issued_at=revoked_at.replace(microsecond=0),
    )

    assert is_revoked(same_second, revoked_at)
    assert not is_revoked(same_second, None)
    later = SessionToken(
        user_id=uuid4(),
        fingerprint="0" * 16,
        issued_at=revoked_at + timedelta(seconds=1),
    )
    assert not is_revoked(later, revoked_at)
