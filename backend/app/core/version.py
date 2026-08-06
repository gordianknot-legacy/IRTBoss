"""Build identity of the estimation stack.

Every :class:`~app.db.models.AnalysisRun` records the engine version that
produced it. v1 promised reproducibility metadata in three places and stored
none of it (P4); a run row that cannot name the code that made it is not
reproducible, so this string is written at enqueue time and never inferred
later.

Bump this whenever a change to ``app.irt`` or ``app.psychometrics`` could move a
number. Stored runs then remain honestly attributable to the code that produced
them.
"""

ENGINE_VERSION = "irtboss-engine/2.0.0"
