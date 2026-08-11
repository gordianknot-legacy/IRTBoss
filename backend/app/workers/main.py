"""Worker entrypoint: ``python -m app.workers.main``.

Same image as the API, different command — ARCHITECTURE §6. Kept trivial on
purpose; anything clever here is logic that only runs in production.
"""

from __future__ import annotations

import logging

from redis import Redis
from rq import Queue, Worker

from app.core.config import get_settings
from app.workers.queue import QUEUE_NAME


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    worker = Worker([Queue(QUEUE_NAME, connection=connection)], connection=connection)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
