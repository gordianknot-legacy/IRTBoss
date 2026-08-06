"""HTTP layer: routers, schemas, and request dependencies.

Nothing in this package computes anything. It authenticates, validates, reads and
writes owner-scoped rows, and enqueues work. Any CPU-bound call appearing here
is the P5 event-loop defect returning.
"""

from .router import api_router

__all__ = ["api_router"]
