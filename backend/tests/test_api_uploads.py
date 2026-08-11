"""Upload limits and schema declaration.

P5: v1 read the whole request body into RAM and then let pandas make a second
copy, with no size, row or column cap. P2: it inferred which columns were items
and fitted respondent-id columns as bogus items.
"""

from __future__ import annotations

import hashlib

from tests.conftest import CSV_BODY, auth, register


async def _project(client, token: str) -> str:
    response = await client.post(
        "/api/v1/projects", json={"name": "upload tests"}, headers=auth(token)
    )
    return response.json()["id"]


async def test_upload_records_shape_and_checksum(client, settings):
    token = await register(client)
    project_id = await _project(client, token)

    response = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        files={"file": ("responses.csv", CSV_BODY, "text/csv")},
        data={"id_column": "id"},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["n_persons"] == 20
    # Three item columns: the declared id column is excluded, not fitted.
    assert body["n_items"] == 3
    assert body["column_metadata"]["item_columns"] == ["i1", "i2", "i3"]
    assert body["column_metadata"]["id_column"] == "id"
    assert body["checksum_sha256"] == hashlib.sha256(CSV_BODY.encode()).hexdigest()

    stored = settings.upload_dir
    assert stored.exists() and any(stored.iterdir())


async def test_oversized_upload_is_rejected(client, settings):
    token = await register(client)
    project_id = await _project(client, token)

    oversized = "i1,i2\n" + "1,0\n" * settings.max_upload_bytes
    assert len(oversized) > settings.max_upload_bytes

    response = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        files={"file": ("big.csv", oversized, "text/csv")},
        headers=auth(token),
    )
    assert response.status_code == 413
    assert str(settings.max_upload_bytes) in response.json()["detail"]


async def test_too_many_columns_is_rejected(client, settings):
    token = await register(client)
    project_id = await _project(client, token)

    columns = settings.max_columns + 5
    header = ",".join(f"i{n}" for n in range(columns))
    body = header + "\n" + ",".join("1" for _ in range(columns)) + "\n"

    response = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        files={"file": ("wide.csv", body, "text/csv")},
        headers=auth(token),
    )
    assert response.status_code == 422
    assert "columns" in response.json()["detail"]


async def test_too_many_rows_is_rejected(client, settings):
    token = await register(client)
    project_id = await _project(client, token)

    rows = settings.max_rows + 10
    body = "i1\n" + "1\n" * rows
    assert len(body) <= settings.max_upload_bytes  # the row cap, not the byte cap

    response = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        files={"file": ("tall.csv", body, "text/csv")},
        headers=auth(token),
    )
    assert response.status_code == 422
    assert "rows" in response.json()["detail"]


async def test_unparseable_and_empty_uploads_are_rejected(client):
    token = await register(client)
    project_id = await _project(client, token)

    empty = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        files={"file": ("empty.csv", "", "text/csv")},
        headers=auth(token),
    )
    assert empty.status_code == 422

    # A declared column that is not in the file is a client error, not a silent
    # fallback to inference.
    mismatch = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        files={"file": ("responses.csv", CSV_BODY, "text/csv")},
        data={"id_column": "respondent"},
        headers=auth(token),
    )
    assert mismatch.status_code == 422


async def test_upload_requires_owning_the_project(client):
    owner = await register(client, "owner@example.com")
    intruder = await register(client, "intruder@example.com")
    project_id = await _project(client, owner)

    response = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        files={"file": ("responses.csv", CSV_BODY, "text/csv")},
        headers=auth(intruder),
    )
    assert response.status_code == 404
