"""Turning an uploaded table into a response matrix the estimator can accept.

Ingest deliberately stops short of this: it records what values it saw per
column but does not act on them, because deciding that ``{0, 1, 2}`` means
three ordered categories is a measurement judgement, not a parsing one. That
judgement is made here, once, and every decision it makes is recorded as a note
that reaches the report.

The rule the whole module is built around: **never silently repair data.** An
item that cannot be modelled is dropped with a reason, not quietly coerced into
something fittable. A column of free text is an error, not a column of zeros.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.irt import MISSING, ResponseMatrix

# An item with more categories than this is far more likely to be a
# misidentified continuous variable - a raw score, an age, a timestamp - than a
# genuine rating scale. Refusing is safer than fitting a 40-category GRM that
# will not converge and will waste an hour doing it.
MAX_CATEGORIES = 12


@dataclass(frozen=True)
class DroppedItem:
    item_id: str
    reason: str


@dataclass(frozen=True)
class ValidatedData:
    """A response matrix plus the full record of how it was arrived at."""

    data: ResponseMatrix
    recoding: dict[str, dict[str, int]]
    dropped: list[DroppedItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    n_persons_dropped: int = 0

    @property
    def is_polytomous(self) -> bool:
        return self.data.is_polytomous


def _column_codes(series: pd.Series) -> tuple[np.ndarray, dict[str, int]] | str:
    """Map one column onto 0-based category codes, or explain why it cannot be.

    Returns the codes and the mapping, or a string reason for dropping.

    Ordering is by *value*, numerically when the column is numeric. This matters
    more than it looks: every polytomous model here treats categories as
    ordered, so mapping them in the order they happen to appear in the file
    would silently permute the scale and produce thresholds that describe
    nothing.
    """

    values = series.dropna()
    if values.empty:
        return "every response is missing"

    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().all():
        distinct = sorted(numeric.unique().tolist())
        # Integer-valued floats are the normal case for a CSV read by pandas;
        # a genuinely fractional score is not a category.
        fractional = [v for v in distinct if float(v) != int(v)]
        if fractional:
            return (
                "responses are not whole numbers "
                f"(for example {fractional[0]}), so they are not categories"
            )
        labels = [str(int(v)) for v in distinct]
        original = {str(int(v)): v for v in distinct}
    else:
        # A non-numeric column has no defensible order. Alphabetical order is an
        # arbitrary one, and for an ordered model an arbitrary order is wrong,
        # not merely inconvenient.
        return (
            "responses are not numeric, so their order cannot be determined; "
            "recode the categories to integers before uploading"
        )

    if len(distinct) < 2:
        return f"every observed response is {labels[0]}, so the item cannot discriminate"
    if len(distinct) > MAX_CATEGORIES:
        return (
            f"{len(distinct)} distinct responses exceeds the {MAX_CATEGORIES}-category "
            "limit; this column looks like a continuous measure rather than an item"
        )

    mapping = {label: index for index, label in enumerate(labels)}
    lookup = {original[label]: index for label, index in mapping.items()}

    codes = np.full(len(series), MISSING, dtype=np.int16)
    raw = pd.to_numeric(series, errors="coerce")
    for value, index in lookup.items():
        codes[(raw == value).to_numpy()] = index
    return codes, mapping


def validate(frame: pd.DataFrame) -> ValidatedData:
    """Validate and recode a table of item responses.

    Raises :class:`ValueError` only when nothing usable survives. Anything that
    can be salvaged is salvaged, and everything that was discarded to get there
    is listed in the result.
    """

    if frame.shape[1] == 0:
        raise ValueError("no item columns were supplied")
    if frame.shape[0] == 0:
        raise ValueError("no respondents were supplied")

    notes: list[str] = []
    dropped: list[DroppedItem] = []
    kept_ids: list[str] = []
    kept_codes: list[np.ndarray] = []
    recoding: dict[str, dict[str, int]] = {}

    for column in frame.columns:
        item_id = str(column)
        outcome = _column_codes(frame[column])
        if isinstance(outcome, str):
            dropped.append(DroppedItem(item_id=item_id, reason=outcome))
            continue
        codes, mapping = outcome
        kept_ids.append(item_id)
        kept_codes.append(codes)
        recoding[item_id] = mapping

    if not kept_ids:
        raise ValueError(
            "no usable items remain after validation: "
            + "; ".join(f"{d.item_id}: {d.reason}" for d in dropped)
        )
    if dropped:
        notes.append(
            f"{len(dropped)} of {frame.shape[1]} columns were excluded and are "
            "listed with their reasons; they take no part in any statistic below."
        )

    values = np.column_stack(kept_codes).astype(np.int16)
    n_categories = np.array(
        [len(recoding[item_id]) for item_id in kept_ids], dtype=int
    )

    # A respondent who answered nothing contributes no likelihood and would be
    # carried through every downstream calculation as a row of NaN. Dropping
    # them is reported, because "n = 1,200" on a report has to mean 1,200 people
    # who actually responded.
    answered = (values != MISSING).any(axis=1)
    n_persons_dropped = int((~answered).sum())
    if n_persons_dropped:
        values = values[answered]
        notes.append(
            f"{n_persons_dropped} respondents answered no items at all and were "
            "excluded; reported sample sizes count only respondents with at "
            "least one response."
        )
    if values.shape[0] == 0:
        raise ValueError("no respondent answered any item")

    non_consecutive = {
        item_id: sorted(mapping)
        for item_id, mapping in recoding.items()
        if [int(k) for k in mapping] != list(range(len(mapping)))
    }
    if non_consecutive:
        example = next(iter(non_consecutive))
        notes.append(
            f"{len(non_consecutive)} items had non-consecutive response codes "
            f"(for example {example}: {non_consecutive[example]}) and were "
            "renumbered to consecutive categories. An unused middle category is "
            "not distinguishable from one that does not exist, so a category "
            "nobody chose has been removed rather than estimated."
        )

    missing_rate = float((values == MISSING).mean())
    if missing_rate > 0:
        notes.append(
            f"{missing_rate:.1%} of responses are missing. They are handled by "
            "full-information maximum likelihood: each respondent contributes "
            "the items they answered, and nothing is imputed."
        )

    return ValidatedData(
        data=ResponseMatrix(
            values=values, item_ids=kept_ids, n_categories=n_categories
        ),
        recoding=recoding,
        dropped=dropped,
        notes=notes,
        n_persons_dropped=n_persons_dropped,
    )
