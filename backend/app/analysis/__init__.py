"""Analysis orchestration.

One entry point, :func:`run_analysis`, which the worker calls and nothing else
does. It owns the order of operations - validate, fit, compare, diagnose - and
the decisions that only make sense across those steps: which models can apply to
this data, which one item-level diagnostics are computed against, and what
happens when a diagnostic fails.
"""

from .orchestrator import (
    DEFAULT_SEED,
    AnalysisResult,
    DiagnosticFailure,
    run_analysis,
)
from .serialise import to_jsonable
from .validate import DroppedItem, ValidatedData, validate

__all__ = [
    "DEFAULT_SEED",
    "AnalysisResult",
    "DiagnosticFailure",
    "DroppedItem",
    "ValidatedData",
    "run_analysis",
    "to_jsonable",
    "validate",
]
