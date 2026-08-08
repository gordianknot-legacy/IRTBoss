"""The report endpoint.

Rendering is tested in ``tests/test_reports.py``; what is tested here is that
the route obeys the same two rules as the rest of the API — a report is scoped
to its owner, and a run that did not succeed has no report — and that the
document it returns is complete rather than a page of missing sections.
"""

from __future__ import annotations

import io
import uuid

import pandas as pd

from app.analysis import run_analysis
from app.db.models import RunStatus
from app.irt import ModelKey
from app.irt.simulate import simulate, spread_parameters
from app.reports import ABSENT
from app.repositories.analyses import SystemRunAccess, fit_to_row
from app.storage import get_object_store
from tests.conftest import auth, register


def _csv_body(n_items: int = 10, n_persons: int = 150) -> str:
    """A dataset large enough for the diagnostics to actually produce numbers.

    ``conftest.CSV_BODY`` is 20 respondents on 3 items, one of them constant.
    That is the right fixture for testing upload and tenancy, but a report
    rendered from it is almost entirely absences — every section heading would
    still appear, so a test asserting on headings alone would pass while proving
    nothing about the content.

    Sized to stay under the 4 KB upload cap the test settings impose, which is
    why this is 150 respondents rather than a more comfortable 400.
    """

    true = spread_parameters(ModelKey.TWO_PL, n_items)
    data, _ = simulate(true, n_persons, seed=83)
    frame = pd.DataFrame(
        data.values, columns=[f"i{j}" for j in range(data.n_items)]
    )
    frame.insert(0, "id", [f"p{n}" for n in range(n_persons)])
    return frame.to_csv(index=False)


CSV_BODY = _csv_body()


async def _queued_run(client, token: str) -> tuple[str, str]:
    project = await client.post(
        "/api/v1/projects",
        json={"name": "Report pilot", "stakes_level": "high",
              "intended_use": "certification"},
        headers=auth(token),
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    upload = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        files={"file": ("responses.csv", CSV_BODY, "text/csv")},
        data={"id_column": "id"},
        headers=auth(token),
    )
    assert upload.status_code == 201, upload.text
    dataset_id = upload.json()["id"]

    run = await client.post(
        f"/api/v1/datasets/{dataset_id}/analyses",
        json={"models": ["2pl"]},
        headers=auth(token),
    )
    assert run.status_code == 202, run.text
    return dataset_id, run.json()["id"]


async def _complete(run_id: str) -> None:
    """Run the real analysis and store it, as the worker would."""

    import pandas as pd

    from app.db.database import get_sessionmaker

    async with get_sessionmaker()() as session:
        access = SystemRunAccess(session)
        run = await access.get(uuid.UUID(run_id))
        # Resolved through the store, exactly as the worker does it — the
        # reference is not a path any more.
        frame = pd.read_csv(io.BytesIO(get_object_store().get(run.dataset.storage_ref)))
        items = run.dataset.column_metadata.get("item_columns") or list(frame.columns)
        result = run_analysis(frame[items], ["2pl"], seed=run.seed)
        await access.store_success(
            run,
            fits=[fit_to_row(f) for f in result.fits],
            diagnostics=result.diagnostics,
            notes=result.notes,
        )
        await session.commit()


async def test_a_completed_run_renders_a_full_report(client):
    token = await register(client, "reporter@example.com")
    _, run_id = await _queued_run(client, token)
    await _complete(run_id)

    response = await client.get(
        f"/api/v1/analyses/{run_id}/report", headers=auth(token)
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert html.lstrip().startswith("<!doctype html>")
    for section in (
        "Report pilot",
        "The data",
        "Model comparison",
        "Item fit",
        "Assumptions",
        "Reproducing this analysis",
    ):
        assert section in html, section
    # Declared stakes reach the document.
    assert "declared high-stakes" in html

    # Section headings are static, so they would appear even for a dataset that
    # produced nothing. These check the report has actual content: every item is
    # in the parameter table, and the headline statistics are numbers rather
    # than the absence marker.
    for j in range(10):
        assert f"i{j}" in html
    for label in ("RMSEA2", "Marginal reliability (Bayesian)", "McDonald's omega"):
        assert ABSENT not in html.split(label, 1)[1][:220], label


async def test_an_incomplete_run_has_no_report(client):
    token = await register(client, "incomplete@example.com")
    _, run_id = await _queued_run(client, token)

    response = await client.get(
        f"/api/v1/analyses/{run_id}/report", headers=auth(token)
    )

    assert response.status_code == 409
    assert RunStatus.QUEUED.value in response.json()["detail"]


async def test_another_users_report_is_a_404(client):
    alice = await register(client, "report-alice@example.com")
    bob = await register(client, "report-bob@example.com")
    _, run_id = await _queued_run(client, alice)
    await _complete(run_id)

    foreign = await client.get(
        f"/api/v1/analyses/{run_id}/report", headers=auth(bob)
    )
    absent = await client.get(
        f"/api/v1/analyses/{uuid.uuid4()}/report", headers=auth(bob)
    )

    assert foreign.status_code == absent.status_code == 404
    # Indistinguishable, so the route is not an oracle for run ids.
    assert foreign.json() == absent.json()


async def test_a_report_requires_authentication(client):
    token = await register(client, "anon-report@example.com")
    _, run_id = await _queued_run(client, token)

    response = await client.get(f"/api/v1/analyses/{run_id}/report")

    assert response.status_code == 401
