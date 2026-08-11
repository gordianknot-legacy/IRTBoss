"""Tenancy: one user must not be able to reach another user's rows.

This is the regression suite for the IDOR in P5. The assertions are on **404**
specifically: a 403 would confirm that the identifier exists, turning the API
into a membership oracle over other users' UUIDs.
"""

from __future__ import annotations

import uuid

from app.repositories.projects import ProjectRepository
from app.repositories.users import UserRepository
from tests.conftest import CSV_BODY, auth, register


async def _make_project(client, token: str, name: str = "Alice's audit") -> str:
    response = await client.post(
        "/api/v1/projects", json={"name": name}, headers=auth(token)
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_second_user_gets_404_on_another_users_project(client):
    alice = await register(client, "alice@example.com")
    bob = await register(client, "bob@example.com")
    project_id = await _make_project(client, alice)

    for method, url in [
        ("get", f"/api/v1/projects/{project_id}"),
        ("patch", f"/api/v1/projects/{project_id}"),
        ("delete", f"/api/v1/projects/{project_id}"),
        ("get", f"/api/v1/projects/{project_id}/datasets"),
    ]:
        response = await getattr(client, method)(
            url, headers=auth(bob), **({"json": {"name": "hijacked"}} if method == "patch" else {})
        )
        assert response.status_code == 404, (method, url, response.status_code)

    # And the owner still sees it: the 404s above are authorisation, not a
    # broken route.
    assert (await client.get(f"/api/v1/projects/{project_id}", headers=auth(alice))).status_code == 200


async def test_project_list_is_scoped_to_the_owner(client):
    alice = await register(client, "alice2@example.com")
    bob = await register(client, "bob2@example.com")
    await _make_project(client, alice, "alice project")

    bob_list = await client.get("/api/v1/projects", headers=auth(bob))
    assert bob_list.status_code == 200
    assert bob_list.json() == []


async def test_second_user_gets_404_on_another_users_dataset_and_run(client, queue):
    alice = await register(client, "alice3@example.com")
    bob = await register(client, "bob3@example.com")
    project_id = await _make_project(client, alice)

    upload = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        files={"file": ("responses.csv", CSV_BODY, "text/csv")},
        data={"id_column": "id"},
        headers=auth(alice),
    )
    assert upload.status_code == 201, upload.text
    dataset_id = upload.json()["id"]

    run = await client.post(
        f"/api/v1/datasets/{dataset_id}/analyses",
        json={"models": ["2pl"]},
        headers=auth(alice),
    )
    assert run.status_code == 202, run.text
    run_id = run.json()["id"]

    assert (await client.get(f"/api/v1/datasets/{dataset_id}", headers=auth(bob))).status_code == 404
    assert (await client.get(f"/api/v1/analyses/{run_id}", headers=auth(bob))).status_code == 404
    assert (
        await client.get(f"/api/v1/analyses/{run_id}/results", headers=auth(bob))
    ).status_code == 404
    # Bob cannot start work on Alice's data either.
    assert (
        await client.post(
            f"/api/v1/datasets/{dataset_id}/analyses",
            json={"models": ["2pl"]},
            headers=auth(bob),
        )
    ).status_code == 404


async def test_unknown_id_and_foreign_id_are_indistinguishable(client):
    alice = await register(client, "alice4@example.com")
    bob = await register(client, "bob4@example.com")
    project_id = await _make_project(client, alice)

    foreign = await client.get(f"/api/v1/projects/{project_id}", headers=auth(bob))
    absent = await client.get(f"/api/v1/projects/{uuid.uuid4()}", headers=auth(bob))
    assert foreign.status_code == absent.status_code == 404
    assert foreign.json() == absent.json()


async def test_repository_layer_filters_by_owner_without_a_route(engine):
    """The scoping lives in the repository, so it holds for non-HTTP callers too."""

    from app.db.database import get_sessionmaker
    from app.db.models import IntendedUse, StakesLevel

    async with get_sessionmaker()() as session:
        users = UserRepository(session)
        alice = await users.create(email="repo-alice@example.com", password_hash="x")
        bob = await users.create(email="repo-bob@example.com", password_hash="y")
        project = await ProjectRepository(session, alice).create(
            name="p",
            description=None,
            stakes_level=StakesLevel.MEDIUM,
            intended_use=IntendedUse.RESEARCH,
        )
        await session.commit()

        assert await ProjectRepository(session, bob).get(project.id) is None
        assert await ProjectRepository(session, bob).delete(project.id) is False
        assert await ProjectRepository(session, alice).get(project.id) is not None
