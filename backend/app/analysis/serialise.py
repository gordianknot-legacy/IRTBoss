"""Converting diagnostic dataclasses into something a JSON column can hold.

Two hazards this exists to handle, both of which produce corruption that looks
like success:

**NaN and infinity are not JSON.** Python's :mod:`json` emits bare ``NaN`` and
``Infinity`` by default, which is invalid JSON that many parsers accept and
others reject. Postgres' ``jsonb`` rejects them outright. Every one of these
statistics can legitimately produce a NaN - an unscorable respondent, an
undefined standard error, a chi-square with no degrees of freedom - so they are
converted to ``null`` here, where the conversion is deliberate, rather than
discovered at insert time.

**numpy scalars are not Python scalars.** ``np.float64`` serialises only by
accident of subclassing, and ``np.int64`` not at all. Converting explicitly
means a new numpy type in a diagnostic cannot fail a run at commit time.
"""

from __future__ import annotations

import dataclasses
import enum
import math
from typing import Any

import numpy as np


def to_jsonable(value: Any) -> Any:
    """Recursively convert ``value`` into JSON-safe primitives.

    Non-finite floats become ``None``. That is a lossy conversion and a
    deliberate one: a null reads as "this statistic has no value here", which is
    what a NaN means in every place one is produced in this codebase.
    """

    if value is None or isinstance(value, (str, bool)):
        return value

    if isinstance(value, enum.Enum):
        return to_jsonable(value.value)

    if isinstance(value, (int, np.integer)):
        return int(value)

    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None

    if isinstance(value, np.bool_):
        return bool(value)

    if isinstance(value, np.ndarray):
        return [to_jsonable(v) for v in value.tolist()]

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: to_jsonable(getattr(value, f.name))
            for f in dataclasses.fields(value)
        }

    if isinstance(value, dict):
        # Keys must be strings in JSON. Tuple keys - item pairs, group pairs -
        # are joined rather than dropped, so a pair-keyed table survives.
        return {_key(k): to_jsonable(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in value]

    return str(value)


def _key(key: Any) -> str:
    if isinstance(key, tuple):
        return "|".join(str(part) for part in key)
    if isinstance(key, enum.Enum):
        return str(key.value)
    return str(key)
