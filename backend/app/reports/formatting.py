"""Number and label formatting for reports.

Small module, one job, and it is the job the whole product turns on: **absence
must not look like a value.**

A statistic that could not be computed is not zero, not blank, and not a dash
the eye slides over. Every formatter here renders a missing value as an explicit
marker, and the template pairs that marker with the reason wherever one is
known. The v1 report rendered ``None`` as an empty table cell, which reads as a
clean result rather than as a hole.
"""

from __future__ import annotations

import math
from typing import Any

# Rendered wherever a number does not exist. Deliberately not an empty string
# and not "0".
ABSENT = "not computed"


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def num(value: Any, digits: int = 3) -> str:
    """Fixed-point, or the absence marker."""

    number = _finite(value)
    return ABSENT if number is None else f"{number:.{digits}f}"


def integer(value: Any) -> str:
    number = _finite(value)
    return ABSENT if number is None else f"{round(number):,}"


def percent(value: Any, digits: int = 1) -> str:
    number = _finite(value)
    return ABSENT if number is None else f"{number * 100:.{digits}f}%"


def pvalue(value: Any) -> str:
    """Small p-values as a bound, never as a rounded zero.

    ``0.000`` invites the reading "the probability is zero", which is not what a
    p-value below the display precision means.
    """

    number = _finite(value)
    if number is None:
        return ABSENT
    if number < 0.001:
        return "< 0.001"
    return f"{number:.3f}"


def interval(low: Any, high: Any, digits: int = 3) -> str:
    """A confidence interval, or the marker if either bound is missing.

    A half-open interval is not reported: an interval with one endpoint is not
    an interval, and rendering ``[0.041, not computed]`` would invite the reader
    to treat the lower bound as if it were the whole result.
    """

    lower, upper = _finite(low), _finite(high)
    if lower is None or upper is None:
        return ABSENT
    return f"[{lower:.{digits}f}, {upper:.{digits}f}]"


def estimate_with_se(value: Any, standard_error: Any, digits: int = 3) -> str:
    """An estimate and its standard error, kept together.

    A point estimate whose standard error could not be computed is still shown -
    it is a real estimate - but the missing precision is stated rather than
    omitted, because an unqualified number reads as a precise one.
    """

    point = _finite(value)
    if point is None:
        return ABSENT
    error = _finite(standard_error)
    if error is None:
        return f"{point:.{digits}f} (SE {ABSENT})"
    return f"{point:.{digits}f} ± {error:.{digits}f}"


def yes_no(value: Any) -> str:
    if value is None:
        return ABSENT
    return "Yes" if value else "No"


def duration(seconds: Any) -> str:
    number = _finite(seconds)
    if number is None:
        return ABSENT
    if number < 60:
        return f"{number:.1f} s"
    minutes, remainder = divmod(number, 60)
    return f"{int(minutes)} min {remainder:.0f} s"
