"""The pipeline is actually connected.

P0.1 — the worst defect in v1 — was a dispatcher with zero call sites: the job
machinery existed, was plausible, and was never invoked. These tests exist so
that class of bug cannot recur silently. They assert, in order:

1. A request to start an analysis puts a job on a real (fake-backed) queue.
2. The job names a function that can actually be imported and called.
3. The route does **not** call it inline — estimation must not run on the event
   loop (P5).
4. The job, when run, persists what the orchestrator returned, and records a
   failure as a failure rather than as an empty success.

The orchestrator ``app.analysis.run_analysis`` is written elsewhere; it is
injected here as a module in ``sys.modules`` so these tests describe the
contract the worker depends on without owning it.
"""

from __future__ import annotations

import importlib
import sys
import types
import uuid
from dataclasses import dataclass, field

import pytest
from sqlalchemy import select

from app.db.models import (
    AnalysisRun,
    DiagnosticsBlob,
    ItemParameterRow,
    ModelFit,
    RunStatus,
)
from app.irt import FitResult, ItemParameters, ModelKey
from tests.conftest import CSV_BODY, auth, register

TASK_PATH = "app.workers.tasks.run_analysis_task"


async def _dataset(client, token: str) -> str:
    project = await client.post(
        "/api/v1/projects", json={"name": "pipeline"}, headers=auth(token)
    )
    project_id = project.json()["id"]
    upload = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        files={"file": ("responses.csv", CSV_BODY, "text/csv")},
        data={"id_column": "id"},
        headers=auth(token),
    )
    assert upload.status_code == 201, upload.text
    return upload.json()["id"]


async def test_starting_an_analysis_enqueues_a_job(client, queue):
    token = await register(client)
    dataset_id = await _dataset(client, token)

    assert queue.count == 0
    response = await client.post(
        f"/api/v1/datasets/{dataset_id}/analyses",
        json={"models": ["2pl", "rasch"], "seed": 7},
        headers=auth(token),
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["requested_models"] == ["2pl", "rasch"]
    assert body["seed"] == 7
    assert body["engine_version"]

    assert queue.count == 1
    job = queue.jobs[0]
    assert job.func_name == TASK_PATH
    assert job.args == (body["id"],)

    # The dotted name resolves to a real callable — the exact check that would
    # have caught P0.1.
    module_name, _, attribute = TASK_PATH.rpartition(".")
    assert callable(getattr(importlib.import_module(module_name), attribute))


async def test_the_route_does_not_run_the_analysis_inline(client, queue, monkeypatch):
    token = await register(client)
    dataset_id = await _dataset(client, token)

    called: list[str] = []

    def _spy(run_id: str) -> None:
        called.append(run_id)

    # Patched where `enqueue_analysis` imports it from, so an inline call would
    # be recorded rather than executed.
    monkeypatch.setattr("app.workers.tasks.run_analysis_task", _spy)
    sys.modules.pop("app.analysis", None)

    response = await client.post(
        f"/api/v1/datasets/{dataset_id}/analyses",
        json={"models": ["2pl"]},
        headers=auth(token),
    )

    assert response.status_code == 202
    assert called == []
    # Nothing on the request path imported the estimation orchestrator.
    assert "app.analysis" not in sys.modules

    status = await client.get(
        f"/api/v1/analyses/{response.json()['id']}", headers=auth(token)
    )
    assert status.json()["status"] == "queued"


async def test_results_are_unavailable_until_the_run_succeeds(client, queue):
    token = await register(client)
    dataset_id = await _dataset(client, token)
    run = await client.post(
        f"/api/v1/datasets/{dataset_id}/analyses",
        json={"models": ["2pl"]},
        headers=auth(token),
    )
    results = await client.get(
        f"/api/v1/analyses/{run.json()['id']}/results", headers=auth(token)
    )
    # Not an empty 200: a results document for an unfinished run would present
    # absent numbers as findings.
    assert results.status_code == 409


async def test_unsupported_model_key_is_rejected_before_enqueue(client, queue):
    token = await register(client)
    dataset_id = await _dataset(client, token)
    response = await client.post(
        f"/api/v1/datasets/{dataset_id}/analyses",
        json={"models": ["4pl"]},
        headers=auth(token),
    )
    assert response.status_code == 422
    assert queue.count == 0


async def test_unsupported_score_method_is_rejected_before_enqueue(client, queue):
    """Refused at the door rather than defaulted to EAP.

    A run recorded as `wl` and scored as EAP would report a method nobody chose,
    which is worse than a 422: the report would name an estimator that had not
    been used.
    """
    token = await register(client)
    dataset_id = await _dataset(client, token)
    response = await client.post(
        f"/api/v1/datasets/{dataset_id}/analyses",
        json={"models": ["2pl"], "score_method": "wl"},
        headers=auth(token),
    )
    assert response.status_code == 422
    assert "score_method" in response.json()["detail"]
    assert queue.count == 0


async def test_the_score_method_is_recorded_on_the_run(client, queue):
    token = await register(client)
    dataset_id = await _dataset(client, token)

    default = await client.post(
        f"/api/v1/datasets/{dataset_id}/analyses",
        json={"models": ["2pl"]},
        headers=auth(token),
    )
    assert default.json()["score_method"] == "eap"

    chosen = await client.post(
        f"/api/v1/datasets/{dataset_id}/analyses",
        json={"models": ["2pl"], "score_method": "WLE"},
        headers=auth(token),
    )
    assert chosen.status_code == 202
    # Normalised on the way in, so the stored value is comparable across runs.
    assert chosen.json()["score_method"] == "wle"

    polled = await client.get(
        f"/api/v1/analyses/{chosen.json()['id']}", headers=auth(token)
    )
    assert polled.json()["score_method"] == "wle"


# --- the job itself ------------------------------------------------------

@dataclass
class _FakeAnalysisResult:
    fits: list = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


def _install_orchestrator(monkeypatch, fn) -> None:
    module = types.ModuleType("app.analysis")
    module.run_analysis = fn
    monkeypatch.setitem(sys.modules, "app.analysis", module)


def _fit() -> FitResult:
    return FitResult(
        model=ModelKey.TWO_PL,
        converged=True,
        n_cycles=42,
        elapsed_seconds=1.5,
        log_likelihood=-1234.5,
        n_free_parameters=6,
        n_persons=20,
        latent_sd=1.0,
        item_parameters=[
            ItemParameters(
                item_id=f"i{n}",
                model=ModelKey.TWO_PL,
                discrimination=1.0 + n / 10,
                difficulty=-0.5 + n,
                se_discrimination=0.08,
                se_difficulty=0.11,
            )
            for n in range(3)
        ],
    )


async def _queued_run(client, queue) -> tuple[str, str]:
    token = await register(client)
    dataset_id = await _dataset(client, token)
    response = await client.post(
        f"/api/v1/datasets/{dataset_id}/analyses",
        json={"models": ["2pl"]},
        headers=auth(token),
    )
    assert response.status_code == 202
    return token, response.json()["id"]


async def test_the_job_persists_what_the_orchestrator_returned(
    client, queue, engine, monkeypatch
):
    token, run_id = await _queued_run(client, queue)

    seen: dict = {}

    def _run_analysis(data, models, groups=None, seed=None, score_method="eap"):
        seen["shape"] = data.shape
        seen["columns"] = list(data.columns)
        seen["models"] = list(models)
        seen["seed"] = seed
        seen["score_method"] = score_method
        return _FakeAnalysisResult(
            fits=[_fit()],
            diagnostics={"reliability": {"marginal": 0.81}},
            notes=["one note"],
        )

    _install_orchestrator(monkeypatch, _run_analysis)

    from app.workers.tasks import _execute

    await _execute(uuid.UUID(run_id))

    # The declared id column never reaches the estimator (P2).
    assert seen["columns"] == ["i1", "i2", "i3"]
    assert seen["shape"] == (20, 3)
    assert seen["models"] == ["2pl"]
    assert seen["seed"] is not None
    # The run's stored scoring method reaches the orchestrator. Defaulting it here
    # instead would score every run by EAP while the run row said otherwise, which
    # is the failure mode that looks like working software.
    assert seen["score_method"] == "eap"

    from app.db.database import get_sessionmaker

    async with get_sessionmaker()() as session:
        run = await session.get(AnalysisRun, uuid.UUID(run_id))
        await session.refresh(run)
        assert run.status is RunStatus.SUCCEEDED
        assert run.started_at is not None and run.finished_at is not None
        assert run.notes == ["one note"]

        fits = (await session.execute(select(ModelFit).where(ModelFit.run_id == run.id))).scalars().all()
        assert len(fits) == 1
        assert fits[0].model_key == "2pl"
        assert fits[0].converged is True
        assert fits[0].aic == pytest.approx(2 * 6 + 2 * 1234.5)

        rows = (
            await session.execute(
                select(ItemParameterRow).where(ItemParameterRow.fit_id == fits[0].id)
            )
        ).scalars().all()
        assert [r.item_id for r in sorted(rows, key=lambda r: r.position)] == ["i0", "i1", "i2"]
        assert all(r.se_discrimination is not None for r in rows)

        blob = (
            await session.execute(
                select(DiagnosticsBlob).where(DiagnosticsBlob.run_id == run.id)
            )
        ).scalar_one()
        assert blob.payload == {"reliability": {"marginal": 0.81}}


async def test_a_failing_orchestrator_marks_the_run_failed(client, queue, engine, monkeypatch):
    token, run_id = await _queued_run(client, queue)

    def _boom(data, models, groups=None, seed=None, score_method="eap"):
        raise RuntimeError("estimation diverged")

    _install_orchestrator(monkeypatch, _boom)

    from app.workers.tasks import _execute

    await _execute(uuid.UUID(run_id))

    from app.db.database import get_sessionmaker

    async with get_sessionmaker()() as session:
        run = await session.get(AnalysisRun, uuid.UUID(run_id))
        await session.refresh(run)
        assert run.status is RunStatus.FAILED
        assert "estimation diverged" in run.failure_reason
        fits = (await session.execute(select(ModelFit).where(ModelFit.run_id == run.id))).scalars().all()
        assert fits == []

    # And the failure reason is not handed to the client verbatim.
    results = await client.get(f"/api/v1/analyses/{run_id}/results", headers=auth(token))
    assert results.status_code == 409


async def test_an_unconverged_fit_stores_nulls_not_zeros(client, queue, engine, monkeypatch):
    token, run_id = await _queued_run(client, queue)

    def _unconverged(data, models, groups=None, seed=None, score_method="eap"):
        return _FakeAnalysisResult(
            fits=[
                FitResult(
                    model=ModelKey.THREE_PL,
                    converged=False,
                    n_cycles=500,
                    elapsed_seconds=9.0,
                    failure_reason="did not converge in 500 cycles",
                )
            ],
            diagnostics={},
        )

    _install_orchestrator(monkeypatch, _unconverged)

    from app.workers.tasks import _execute

    await _execute(uuid.UUID(run_id))

    from app.db.database import get_sessionmaker

    async with get_sessionmaker()() as session:
        fit = (
            await session.execute(select(ModelFit).where(ModelFit.run_id == uuid.UUID(run_id)))
        ).scalar_one()
        assert fit.converged is False
        # None, not 0.0: a zero here is a fabricated measurement.
        assert fit.log_likelihood is None
        assert fit.aic is None and fit.bic is None
        rows = (
            await session.execute(
                select(ItemParameterRow).where(ItemParameterRow.fit_id == fit.id)
            )
        ).scalars().all()
        assert rows == []
        assert fit.failure_reason == "did not converge in 500 cycles"
