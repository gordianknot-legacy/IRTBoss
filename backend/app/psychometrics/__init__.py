"""
Psychometric diagnostics.

The estimation engine in :mod:`app.irt` answers "what are the parameters?".
This package answers the questions that decide whether those parameters mean
anything: does each item fit, does the test measure one thing, are responses
locally independent, does it work the same way for every group, and how
precisely does it measure whom.

Every statistic here reports its own uncertainty or its own limits. Nothing
returns a bare number with an implied verdict attached.
"""

from .information import (
    category_probabilities,
    item_information,
    posterior_standard_error,
    standard_error,
    test_information,
)
from .itemfit import ItemFitReport, ItemFitResult, item_fit
from .reliability import PrecisionBand, ReliabilityReport, reliability
from .scoring import PersonScores, ScoreMethod, score

__all__ = [
    "ItemFitReport",
    "ItemFitResult",
    "PersonScores",
    "PrecisionBand",
    "ReliabilityReport",
    "ScoreMethod",
    "category_probabilities",
    "item_fit",
    "item_information",
    "posterior_standard_error",
    "reliability",
    "score",
    "standard_error",
    "test_information",
]
