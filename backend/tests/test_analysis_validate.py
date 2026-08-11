"""Tests for response-matrix validation.

The theme throughout: a column that cannot be modelled must be *rejected with a
reason*, never coerced into something fittable. Silent repair is the failure
mode being tested against, so most of these assert on what did NOT happen.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis.validate import MAX_CATEGORIES, validate
from app.irt import MISSING


def _binary_frame(n_persons: int = 50, n_items: int = 6) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    values = rng.integers(0, 2, size=(n_persons, n_items))
    return pd.DataFrame(values, columns=[f"i{j}" for j in range(n_items)])


def test_binary_data_passes_through_unchanged():
    frame = _binary_frame()
    result = validate(frame)

    assert result.data.n_persons == 50
    assert result.data.n_items == 6
    assert list(result.data.n_categories) == [2] * 6
    assert not result.dropped
    np.testing.assert_array_equal(result.data.values, frame.to_numpy())


def test_categories_are_ordered_by_value_not_by_appearance():
    """Order is the whole meaning of a polytomous scale.

    The first row here presents the codes in the order 2, 0, 1. Mapping in
    order of appearance would make category 2 the lowest, silently permuting
    the scale so that every estimated threshold describes something other than
    what it claims to.
    """
    frame = pd.DataFrame({"i0": [2, 0, 1, 1, 2, 0], "i1": [1, 1, 0, 2, 0, 2]})

    result = validate(frame)

    assert result.recoding["i0"] == {"0": 0, "1": 1, "2": 2}
    # Code 2 in the file is still category 2 after recoding.
    assert result.data.values[0, 0] == 2
    assert result.data.values[1, 0] == 0


def test_non_numeric_column_is_refused_not_alphabetised():
    """Alphabetical order is an arbitrary order, and arbitrary is wrong here."""
    frame = _binary_frame()
    frame["text"] = ["agree", "disagree"] * 25

    result = validate(frame)

    dropped = {d.item_id: d.reason for d in result.dropped}
    assert "text" in dropped
    assert "not numeric" in dropped["text"]
    assert "text" not in result.data.item_ids
    assert result.data.n_items == 6


def test_constant_item_is_dropped_with_a_reason():
    frame = _binary_frame()
    frame["everyone_right"] = 1

    result = validate(frame)

    dropped = {d.item_id: d.reason for d in result.dropped}
    assert "discriminate" in dropped["everyone_right"]
    assert "everyone_right" not in result.data.item_ids


def test_continuous_column_is_refused_rather_than_fitted():
    frame = _binary_frame()
    frame["age"] = np.arange(20, 70)

    result = validate(frame)

    dropped = {d.item_id: d.reason for d in result.dropped}
    assert str(MAX_CATEGORIES) in dropped["age"]
    assert "continuous" in dropped["age"]


def test_fractional_responses_are_refused():
    frame = _binary_frame()
    frame["partial"] = [0.5, 1.0] * 25

    result = validate(frame)

    dropped = {d.item_id: d.reason for d in result.dropped}
    assert "whole numbers" in dropped["partial"]


def test_missing_values_become_the_missing_sentinel():
    frame = _binary_frame().astype(float)
    frame.iloc[0, 0] = np.nan
    frame.iloc[3, 2] = np.nan

    result = validate(frame)

    assert result.data.values[0, 0] == MISSING
    assert result.data.values[3, 2] == MISSING
    assert (result.data.values == MISSING).sum() == 2
    assert any("full-information maximum likelihood" in n for n in result.notes)


def test_a_respondent_who_answered_nothing_is_dropped_and_counted():
    frame = _binary_frame().astype(float)
    frame.iloc[7, :] = np.nan

    result = validate(frame)

    assert result.n_persons_dropped == 1
    assert result.data.n_persons == 49
    assert any("answered no items" in n for n in result.notes)


def test_codes_with_gaps_are_renumbered_and_the_removal_is_reported():
    """Codes 1/3/5 are three categories, and the gaps are not categories."""
    frame = pd.DataFrame({"i0": [1, 3, 5, 1, 3, 5], "i1": [1, 1, 3, 3, 5, 5]})

    result = validate(frame)

    assert list(result.data.n_categories) == [3, 3]
    assert result.data.values.max() == 2
    assert result.recoding["i0"] == {"1": 0, "3": 1, "5": 2}
    assert any("gaps in their response codes" in n for n in result.notes)
    assert any("has been removed rather than estimated" in n for n in result.notes)


def test_a_one_based_scale_is_shifted_without_claiming_a_removal():
    """The 1-5 rating scale is consecutive; nothing about it was dropped.

    Both cases end in a renumbering, so it is tempting to report them with one
    note. They are different claims: this one says the codes moved, the test
    above says a category the instrument offered is gone. A note asserting a
    removal that did not happen is exactly the kind of plausible-looking
    falsehood the validation record exists to prevent.
    """
    frame = pd.DataFrame(
        {"q0": [1, 2, 3, 4, 5, 3], "q1": [5, 4, 3, 2, 1, 3]}
    )

    result = validate(frame)

    assert list(result.data.n_categories) == [5, 5]
    assert result.data.values.min() == 0
    assert result.recoding["q0"] == {"1": 0, "2": 1, "3": 2, "4": 3, "5": 4}
    assert any("running from 1 to 5" in n for n in result.notes)
    assert any("No category was removed" in n for n in result.notes)
    assert not any("gaps in their response codes" in n for n in result.notes)


def test_recoding_is_reported_for_every_kept_item():
    frame = _binary_frame()
    result = validate(frame)
    assert set(result.recoding) == set(result.data.item_ids)


def test_all_columns_unusable_raises_rather_than_returning_an_empty_matrix():
    frame = pd.DataFrame({"a": [1, 1, 1], "b": ["x", "y", "z"]})

    with pytest.raises(ValueError, match="no usable items"):
        validate(frame)


def test_empty_input_is_rejected():
    with pytest.raises(ValueError, match="no respondents"):
        validate(pd.DataFrame({"i0": []}))
    with pytest.raises(ValueError, match="no item columns"):
        validate(pd.DataFrame(index=[0, 1, 2]))
