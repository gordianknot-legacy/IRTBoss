# IRT Modeling Layer
"""
IRT model fitting and estimation.

This package provides the interface to IRT modeling engines.
Currently supports R mirt via subprocess; designed to be
replaceable with native Python implementation in the future.
"""

from .mirt_wrapper import MirtWrapper
from .models import FittingResult, IRTModelFitter

__all__ = [
    "FittingResult",
    "IRTModelFitter",
    "MirtWrapper",
]
