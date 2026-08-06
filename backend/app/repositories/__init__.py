"""Owner-scoped data access.

Every function in this package takes the acting :class:`~app.db.models.User` and
puts ``owner_id == user.id`` into the WHERE clause. Routes therefore cannot fetch
a row they then forget to authorise, because there is no way to ask for a row
without saying who is asking.

This is the structural fix for the IDOR in P5. The v1 report download took a
``project_id``, ignored it, and resolved the file by a semi-guessable name; the
general shape of that bug is "the identifier and the authorisation live in
different places". Here they are the same query.

A missing row and a row belonging to somebody else are indistinguishable to the
caller: both return ``None``, and the API turns both into 404. A 403 would
confirm that the UUID exists, which is a membership oracle.
"""

from .analyses import AnalysisRepository
from .datasets import DatasetRepository
from .projects import ProjectRepository
from .users import UserRepository

__all__ = [
    "AnalysisRepository",
    "DatasetRepository",
    "ProjectRepository",
    "UserRepository",
]
