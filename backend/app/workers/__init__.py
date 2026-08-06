"""Background execution: the queue seam and the analysis job.

Everything CPU-bound lives behind this package. The API's only contact with it is
:func:`app.workers.queue.enqueue_analysis`.
"""

from .queue import QUEUE_NAME, enqueue_analysis, get_queue, set_queue

__all__ = ["QUEUE_NAME", "enqueue_analysis", "get_queue", "set_queue"]
