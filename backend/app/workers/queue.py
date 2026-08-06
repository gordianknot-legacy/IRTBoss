"""The queue seam.

v1's worst defect (P0.1) was a dispatcher with zero call sites: code that looked
like a pipeline, was tested in isolation, and was never invoked by anything. The
countermeasure is not more care — it is a seam narrow enough to assert on. There
is exactly one function that puts work on the queue, it names exactly one task,
and an integration test drives a real HTTP request through it against a fake
Redis and asserts a job landed.

The task is enqueued *by reference to the imported function*, not by dotted
string. A renamed or deleted task then breaks at import time in the API process,
rather than at dequeue time in the worker where nobody is watching.
"""

from __future__ import annotations

import uuid

from redis import Redis
from rq import Queue

from app.core.config import Settings

QUEUE_NAME = "irtboss-analysis"

# Generous: a full comparison dossier over several model families on a large
# dataset is minutes of numerical work, and a job killed mid-EM leaves a run row
# stuck in RUNNING.
JOB_TIMEOUT_SECONDS = 60 * 60
RESULT_TTL_SECONDS = 60 * 60


_queue: Queue | None = None


def get_queue(settings: Settings) -> Queue:
    global _queue
    if _queue is None:
        _queue = Queue(
            QUEUE_NAME,
            connection=Redis.from_url(settings.redis_url),
            default_timeout=JOB_TIMEOUT_SECONDS,
        )
    return _queue


def set_queue(queue: Queue | None) -> None:
    """Install a queue explicitly. Tests use this to inject a fakeredis-backed
    queue; the worker entrypoint uses it to share one connection."""

    global _queue
    _queue = queue


def enqueue_analysis(settings: Settings, run_id: uuid.UUID) -> str:
    """Hand a persisted run to the worker. Returns the RQ job id.

    Imported inside the function so that :mod:`app.api` does not pull numpy,
    scipy and the estimation engine into the web process at import time.
    """

    from app.workers.tasks import run_analysis_task

    job = get_queue(settings).enqueue(
        run_analysis_task,
        str(run_id),
        job_timeout=JOB_TIMEOUT_SECONDS,
        result_ttl=RESULT_TTL_SECONDS,
    )
    return job.id
