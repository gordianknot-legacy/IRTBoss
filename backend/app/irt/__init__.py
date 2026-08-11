"""
Item response theory estimation.

A native marginal-maximum-likelihood estimator. Nothing here shells out to R:
the previous implementation did, and silently substituted fabricated parameters
whenever R was unavailable, which is the defect this package was written to
remove.
"""

from .em import (
    MISSING,
    EMOptions,
    FitResult,
    Quadrature,
    ResponseMatrix,
    fit,
)
from .families import (
    DICHOTOMOUS_MODELS,
    POLYTOMOUS_MODELS,
    ItemParameters,
    ModelKey,
    SlopeMode,
    get_family,
)

__all__ = [
    "DICHOTOMOUS_MODELS",
    "MISSING",
    "POLYTOMOUS_MODELS",
    "EMOptions",
    "FitResult",
    "ItemParameters",
    "ModelKey",
    "Quadrature",
    "ResponseMatrix",
    "SlopeMode",
    "fit",
    "get_family",
]
