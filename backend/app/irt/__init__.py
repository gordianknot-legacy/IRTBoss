# IRT Modeling Layer
"""
IRT model fitting and estimation.

This package provides the interface to IRT modeling engines.
Currently supports R mirt via subprocess; designed to be
replaceable with native Python implementation in the future.
"""

from .models import IRTModelFitter, FittingResult
from .mirt_wrapper import MirtWrapper

__all__ = [
    "IRTModelFitter",
    "FittingResult",
    "MirtWrapper",
]
