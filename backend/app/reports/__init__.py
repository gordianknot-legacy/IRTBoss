"""Report rendering.

Reports are rendered from persisted data only — the run row, its fits and its
stored diagnostics payload. Nothing is recomputed at render time, so
re-rendering an old run produces the same document rather than a fresh analysis
that happens to share an id.

The templates are written around one rule that the rest of the codebase also
follows: a statistic that could not be computed is rendered as an explicit
absence, never as a blank cell and never as zero.
"""

from .context import ReportContext, build_context
from .formatting import ABSENT
from .render import DEFAULT_TEMPLATE, TEMPLATE_DIR, render, render_run

__all__ = [
    "ABSENT",
    "DEFAULT_TEMPLATE",
    "TEMPLATE_DIR",
    "ReportContext",
    "build_context",
    "render",
    "render_run",
]
