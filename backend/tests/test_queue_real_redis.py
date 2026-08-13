"""One real RQ worker, dequeuing one real job, from real Redis.

Everywhere else the suite runs against `fakeredis`, which is the right default —
it keeps the tests service-free and it is enough to assert the seam that v1 got
wrong (P0.1: a dispatcher with no call sites). What it cannot show is that a
worker *process* picks the job up and finishes it. `fakeredis` is an in-process
object, so a test using it proves the enqueue happened and then executes the job
by calling it directly. Every step between those two — RQ's serialisation of the
job, the worker's dequeue loop, the fork, and the child writing to the database on
its own connection — has until now only ever run under Docker Compose, by hand.

So this file uses the forking :class:`rq.Worker`, the same class
`app/workers/main.py` runs in production, against a Redis this test did not
invent. It skips unless `IRTBOSS_TEST_REDIS_URL` is set, and CI sets it. The
pattern is the one already used for PostgreSQL: unrunnable on a developer machine
with no services, and observed on GitHub rather than merely constructed.

What is deliberately *not* mocked: the analysis itself. The job runs the real
orchestrator over real simulated responses, so a green result here means the whole
path — HTTP request, run row, Redis, worker, fork, estimation, persistence —
completed once, in the arrangement the deployment uses.
"""

from __future__ import annotations

import os
import uuid

import pytest
from redis import Redis
from rq import Queue, Worker
from sqlalchemy import select

from app.db.models import (
    AnalysisRun,
    DiagnosticsBlob,
    ItemParameterRow,
    ModelFit,
    RunStatus,
)
from app.irt import ModelKey
from app.irt.simulate import simulate, spread_parameters
from app.workers.queue import QUEUE_NAME, set_queue
from tests.conftest import auth, register

REDIS_URL = os.environ.get("IRTBOSS_TEST_REDIS_URL")

pytestmark = pytest.mark.skipif(
    not REDIS_URL,
    reason=(
        "needs a real Redis; set IRTBOSS_TEST_REDIS_URL. fakeredis is not a "
        "substitute here: the point of this file is that an out-of-process worker "
        "dequeues the job, which an in-process fake cannot demonstrate."
    ),
)

# Small enough to stay inside the 4 KB upload cap the settings fixture installs,
# large enough that a Rasch fit converges rather than testing the failure path by
# accident. Simulated from known parameters so it is well behaved by construction.
N_PERSONS = 200
N_ITEMS = 8


def _csv() -> str:
    true = spread_parameters(ModelKey.RASCH, N_ITEMS, seed=20260811)
    data, _theta = simulate(true, N_PERSONS, seed=20260811)
    header = ",".join(f"i{j}" for j in range(N_ITEMS))
    rows = ",".join
    return "\n".join(
        [header] + [rows(str(int(v)) for v in row) for row in data.values]
    )


@pytest.fixture
def real_queue(client):
    """Replace the fakeredis queue with a real one.

    Depends on ``client`` rather than the other way round: the client fixture
    installs the fake queue, and ``enqueue_analysis`` resolves the queue from the
    module global at call time, so overriding it afterwards is what takes effect.
    """

    connection = Redis.from_url(REDIS_URL)
    queue = Queue(QUEUE_NAME, connection=connection)
    # A leftover job from a previous run would be executed by this test's worker
    # against a database that no longer exists, and the failure would be reported
    # here rather than where it came from.
    queue.empty()
    set_queue(queue)
    yield queue
    queue.empty()
    set_queue(None)
    connection.close()


async def test_a_real_worker_dequeues_and_completes_a_real_job(
    client, engine, real_queue
):
    token = await register(client)
    project = await client.post(
        "/api/v1/projects", json={"name": "queue round trip"}, headers=auth(token)
    )
    upload = await client.post(
        f"/api/v1/projects/{project.json()['id']}/datasets",
        files={"file": ("responses.csv", _csv(), "text/csv")},
        headers=auth(token),
    )
    assert upload.status_code == 201, upload.text

    started = await client.post(
        f"/api/v1/datasets/{upload.json()['id']}/analyses",
        json={"models": ["rasch"], "seed": 11},
        headers=auth(token),
    )
    assert started.status_code == 202, started.text
    run_id = uuid.UUID(started.json()["id"])
    assert started.json()["status"] == "queued"

    # The job is in Redis and nothing has run it. This is the state a client holds
    # after a successful POST, and the state v1 could reach with no job at all.
    assert real_queue.count == 1
    job_id = real_queue.job_ids[0]

    from app.db.database import get_sessionmaker

    async with get_sessionmaker()() as session:
        queued = await session.get(AnalysisRun, run_id)
        assert queued is not None
        assert queued.status is RunStatus.QUEUED
        # The id the route recorded is the id that is actually in Redis. Nothing
        # else in the suite can check that: against a fake queue, both sides of
        # this comparison come from the same in-process object.
        assert queued.queue_job_id == job_id

    # Burst mode: work until the queue is empty, then return. The forking Worker
    # rather than SimpleWorker, because forking is what production does and it is
    # the half of this path that has never been exercised by a test.
    worker = Worker(
        [real_queue], connection=real_queue.connection, name=f"test-{uuid.uuid4().hex[:8]}"
    )
    worker.work(burst=True, with_scheduler=False)

    assert real_queue.count == 0

    # Read the row back through a fresh session: the worker wrote it from another
    # process, so anything cached in this one would hide a write that did not
    # happen.
    async with get_sessionmaker()() as session:
        run = await session.get(AnalysisRun, run_id)
        assert run is not None
        assert run.status is RunStatus.SUCCEEDED, run.failure_reason
        assert run.started_at is not None and run.finished_at is not None

        fits = (
            await session.execute(select(ModelFit).where(ModelFit.run_id == run_id))
        ).scalars().all()
        assert [f.model_key for f in fits] == ["rasch"]
        assert fits[0].converged is True
        assert fits[0].log_likelihood is not None

        # Queried rather than reached through `fits[0].item_parameters`: that is a
        # lazy relationship, and touching it on an async session outside a loaded
        # context raises MissingGreenlet rather than emitting the SELECT.
        parameters = (
            await session.execute(
                select(ItemParameterRow).where(ItemParameterRow.fit_id == fits[0].id)
            )
        ).scalars().all()
        # The estimator's output survived the trip through another process.
        assert len(parameters) == N_ITEMS
        assert all(p.se_difficulty is not None for p in parameters)
        # And its *absences* survived too, which is the more interesting half. A
        # Rasch fit does not estimate discrimination — it fixes every slope at 1 —
        # so there is no standard error for one, and a row carrying 0.0 here would
        # mean the null had been flattened into a number somewhere between the
        # child process and this query.
        assert all(p.discrimination == 1.0 for p in parameters)
        assert all(p.se_discrimination is None for p in parameters)

        blob = (
            await session.execute(
                select(DiagnosticsBlob).where(DiagnosticsBlob.run_id == run_id)
            )
        ).scalar_one()
        assert blob.payload["sample"]["n_persons"] == N_PERSONS
        assert blob.payload["sample"]["n_items"] == N_ITEMS

    # And the API serves what the worker persisted, which is the whole point of
    # the run being a durable row rather than a queue lookup.
    results = await client.get(f"/api/v1/analyses/{run_id}/results", headers=auth(token))
    assert results.status_code == 200, results.text
    assert results.json()["run"]["status"] == "succeeded"
    assert results.json()["diagnostics"]["sample"]["n_persons"] == N_PERSONS


async def test_a_job_for_a_deleted_run_is_a_no_op_not_a_crash(
    client, engine, real_queue
):
    """The one failure mode a real queue adds: a job outliving its row.

    A cascade delete removes the run while its job is still queued. The worker
    must treat that as nothing to do — a retry storm over a row that will never
    exist again is worse than silence, and this is the only place the real
    dequeue path can be checked against it.
    """
    token = await register(client)
    project = await client.post(
        "/api/v1/projects", json={"name": "deleted before run"}, headers=auth(token)
    )
    project_id = project.json()["id"]
    upload = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        files={"file": ("responses.csv", _csv(), "text/csv")},
        headers=auth(token),
    )
    started = await client.post(
        f"/api/v1/datasets/{upload.json()['id']}/analyses",
        json={"models": ["rasch"], "seed": 11},
        headers=auth(token),
    )
    run_id = uuid.UUID(started.json()["id"])

    deleted = await client.delete(f"/api/v1/projects/{project_id}", headers=auth(token))
    assert deleted.status_code in (204, 200), deleted.text

    worker = Worker(
        [real_queue], connection=real_queue.connection, name=f"test-{uuid.uuid4().hex[:8]}"
    )
    worker.work(burst=True, with_scheduler=False)

    # The job completed rather than failing: nothing to do is not an error.
    assert real_queue.count == 0
    assert real_queue.failed_job_registry.count == 0

    from app.db.database import get_sessionmaker

    async with get_sessionmaker()() as session:
        assert await session.get(AnalysisRun, run_id) is None
