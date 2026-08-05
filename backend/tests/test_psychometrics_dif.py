"""
Tests for differential item functioning.

The order of importance is deliberate. A DIF screen that flags clean items is
worse than useless - it sends a content committee to rewrite items that are
fine, and it discredits the flags that are real. So the first and strictest
test here is the false-positive check: two groups drawn from identical item
parameters must come back clean under all three methods. Detection is tested
after that, and always with the paired requirement that the *other* items stay
quiet.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.irt.em import EMOptions, ResponseMatrix
from app.irt.families import ItemParameters, ModelKey
from app.irt.simulate import TrueParameters, simulate
from app.psychometrics.dif import (
    LORDIF_R2_THRESHOLD,
    benjamini_hochberg,
    dif,
)

# The IRT-LR path fits a model per item per purification pass, so every test
# that switches it on uses a short test and a coarse grid.
FAST_EM = EMOptions(
    quadrature_points=31, compute_standard_errors=False, max_cycles=300
)


def _two_group_data(
    a_ref: np.ndarray,
    b_ref: np.ndarray,
    a_focal: np.ndarray,
    b_focal: np.ndarray,
    n_per_group: int,
    seed: int,
) -> tuple[ResponseMatrix, np.ndarray, list[ItemParameters]]:
    """Stack two independently simulated groups into one response matrix.

    Both groups draw ability from the same N(0, 1), so there is no impact to
    confound anything; the only difference between them is whatever difference
    the caller puts into the item parameters.
    """
    reference, _ = simulate(
        TrueParameters(ModelKey.TWO_PL, a_ref, b_ref), n_per_group, seed=seed
    )
    focal, _ = simulate(
        TrueParameters(ModelKey.TWO_PL, a_focal, b_focal),
        n_per_group,
        seed=seed + 1,
    )

    data = ResponseMatrix(
        values=np.vstack([reference.values, focal.values]),
        item_ids=reference.item_ids,
        n_categories=reference.n_categories,
    )
    groups = np.array(["ref"] * n_per_group + ["foc"] * n_per_group)

    # `dif` uses these only for the item ids, model family and category count.
    items = [
        ItemParameters(
            item_id=item_id,
            model=ModelKey.TWO_PL,
            discrimination=float(a),
            difficulty=float(b),
        )
        for item_id, a, b in zip(data.item_ids, a_ref, b_ref, strict=True)
    ]
    return data, groups, items


def _no_dif_setup(n_items: int, seed: int, n_per_group: int):
    rng = np.random.default_rng(seed)
    a = rng.uniform(0.8, 1.8, size=n_items)
    b = np.linspace(-1.6, 1.6, n_items)
    return _two_group_data(a, b, a.copy(), b.copy(), n_per_group, seed)


# --------------------------------------------------------------------------- #
# The false-positive check
# --------------------------------------------------------------------------- #


def test_identical_parameters_produce_no_dif():
    """Two groups generated from the same parameters must come back clean.

    This is the test that matters most. Everything else here can be satisfied
    by a method that flags everything.
    """
    data, groups, items = _no_dif_setup(n_items=10, seed=2026, n_per_group=1000)

    report = dif(data, items, groups, em_options=FAST_EM, purification_passes=2)
    results = report.items

    assert len(results) == 10

    classes = [r.mantel_haenszel.ets_class for r in results]
    assert all(cls is not None for cls in classes)
    # ETS C is a strong claim; none of these items should earn one, and at most
    # one stray B is tolerable across ten items at a 5% test.
    assert "C" not in classes
    assert classes.count("B") <= 1

    delta_r2 = np.array([r.logistic.total_delta_r2 for r in results])
    assert delta_r2.max() < LORDIF_R2_THRESHOLD

    # After FDR adjustment nothing should survive on any of the three methods.
    for attr in ("mh_p_adjusted", "logistic_p_adjusted", "irt_p_adjusted"):
        adjusted = [getattr(r, attr) for r in results]
        assert all(p is not None for p in adjusted), attr
        assert min(adjusted) > 0.05, (attr, adjusted)

    assert report.comparisons[0].flagged == []


def test_no_dif_leaves_the_anchor_set_intact():
    """With nothing to purify, every item should survive as an anchor."""
    data, groups, items = _no_dif_setup(n_items=8, seed=31, n_per_group=700)

    report = dif(data, items, groups, em_options=FAST_EM, purification_passes=2)
    comparison = report.comparisons[0]

    assert set(comparison.anchor_item_ids) == set(data.item_ids)


# --------------------------------------------------------------------------- #
# Uniform DIF
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def uniform_dif_report():
    """One item made 0.8 logits harder for the focal group; the rest identical."""
    n_items = 10
    rng = np.random.default_rng(7)
    a = rng.uniform(0.9, 1.6, size=n_items)
    b = np.linspace(-1.6, 1.6, n_items)

    b_focal = b.copy()
    b_focal[4] += 0.8

    data, groups, items = _two_group_data(a, b, a.copy(), b_focal, 1000, seed=7)
    report = dif(data, items, groups, em_options=FAST_EM, purification_passes=2)
    return report, data, 4


def test_uniform_dif_is_found_by_all_three_methods(uniform_dif_report):
    report, data, target = uniform_dif_report
    results = report.items
    studied = results[target]

    # Mantel-Haenszel: the item is harder for the focal group, so the odds
    # ratio favours the reference group and D-DIF is negative.
    assert studied.mantel_haenszel.odds_ratio > 1.0
    assert studied.mantel_haenszel.d_dif < -1.0
    assert studied.mantel_haenszel.ets_class == "C"

    # Logistic regression: uniform, not non-uniform.
    assert studied.logistic.total_delta_r2 >= LORDIF_R2_THRESHOLD
    assert studied.logistic.uniform_p < 0.001
    assert not studied.logistic.is_nonuniform

    # IRT likelihood ratio.
    assert studied.irt_lr is not None
    assert studied.irt_lr.df == 2       # both a and b freed for a 2PL item
    assert studied.irt_p_adjusted < 0.01

    assert {"mantel_haenszel", "logistic", "irt_lr"}.issubset(
        set(studied.flagged_by)
    )


def test_uniform_dif_does_not_contaminate_the_clean_items(uniform_dif_report):
    report, data, target = uniform_dif_report
    clean = [r for j, r in enumerate(report.items) if j != target]

    assert all(r.mantel_haenszel.ets_class != "C" for r in clean)
    assert all(
        r.logistic.total_delta_r2 < LORDIF_R2_THRESHOLD for r in clean
    ), [(r.item_id, r.logistic.total_delta_r2) for r in clean]
    # A single contaminated item out of ten pulls the matching score only
    # slightly, so at most a couple of neighbours may reach nominal
    # significance; none should survive FDR adjustment on the MH test.
    assert sum(r.mh_p_adjusted < 0.05 for r in clean) <= 1


def test_purification_drops_the_contaminated_item_from_the_anchors(
    uniform_dif_report,
):
    report, data, target = uniform_dif_report
    comparison = report.comparisons[0]

    assert data.item_ids[target] not in comparison.anchor_item_ids
    assert len(comparison.anchor_item_ids) >= 2
    assert report.items[target].irt_lr.purification_passes == 2


def test_ets_classification_needs_both_conditions():
    """Category C requires the effect size *and* the test against 1.0.

    The check is that the recorded standard error actually supports the letter
    awarded, which is what separates a conjunction rule from a bare threshold.
    """
    data, groups, items = _no_dif_setup(n_items=8, seed=55, n_per_group=400)
    n_items = 8
    rng = np.random.default_rng(55)
    a = rng.uniform(0.9, 1.6, size=n_items)
    b = np.linspace(-1.5, 1.5, n_items)
    b_focal = b.copy()
    b_focal[2] += 0.9
    data, groups, items = _two_group_data(a, b, a.copy(), b_focal, 400, seed=55)

    report = dif(data, items, groups, include_irt_lr=False)

    for entry in report.items:
        mh = entry.mantel_haenszel
        assert mh.ets_class in {"A", "B", "C"}
        assert mh.d_dif_se is not None and mh.d_dif_se > 0

        magnitude = abs(mh.d_dif)
        above_one = (magnitude - 1.0) / mh.d_dif_se > 1.645
        nonzero = mh.p_value < 0.05

        if mh.ets_class == "C":
            assert magnitude >= 1.5 and above_one
        elif mh.ets_class == "B":
            assert magnitude >= 1.0 and nonzero
            assert not (magnitude >= 1.5 and above_one)
        else:
            assert not (magnitude >= 1.5 and above_one)
            assert not (magnitude >= 1.0 and nonzero)


# --------------------------------------------------------------------------- #
# Non-uniform DIF
# --------------------------------------------------------------------------- #


def test_non_uniform_dif_is_caught_by_the_interaction_term():
    """A slope that differs across groups is what Mantel-Haenszel cannot see.

    The item's advantage crosses over somewhere in the middle of the ability
    range, so the stratum-specific odds ratios point in opposite directions and
    largely cancel in the MH average. The logistic interaction term is the
    reason that method is here at all.
    """
    n_items = 10
    a_ref = np.full(n_items, 1.1)
    b = np.linspace(-1.4, 1.4, n_items)

    a_focal = a_ref.copy()
    a_focal[6] = 0.35            # far flatter for the focal group
    a_ref = a_ref.copy()
    a_ref[6] = 2.2               # and much steeper for the reference group

    data, groups, items = _two_group_data(a_ref, b, a_focal, b.copy(), 1500, 11)

    report = dif(data, items, groups, include_irt_lr=False)
    results = report.items
    studied = results[6]

    assert studied.logistic.nonuniform_p < 0.001
    assert studied.logistic.is_nonuniform
    assert studied.logistic.total_delta_r2 >= LORDIF_R2_THRESHOLD
    assert abs(studied.logistic.interaction_coefficient) > 0.3

    clean = [r for j, r in enumerate(results) if j != 6]
    assert sum(r.logistic.nonuniform_p < 0.01 for r in clean) <= 1

    # The item is centred at b = 0.47, close enough to the middle of the
    # ability distribution that the crossing effect largely cancels: this is
    # the documented blind spot, and it should be visible here.
    assert studied.logistic.nonuniform_delta_r2 > studied.logistic.uniform_delta_r2


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #


def test_small_groups_refuse_rather_than_guess():
    """Twenty people per group buys no verdict, only an explanation."""
    data, groups, items = _no_dif_setup(n_items=8, seed=3, n_per_group=20)

    report = dif(data, items, groups)
    results = report.items

    assert all(r.mantel_haenszel is None for r in results)
    assert all(r.logistic is None for r in results)
    assert all(r.irt_lr is None for r in results)
    assert all(r.mh_p_adjusted is None for r in results)
    assert not any(r.flagged for r in results)

    comparison = report.comparisons[0]
    assert any("at least 100 in each" in note for note in comparison.notes)
    assert all(
        any("at least 100 in each" in note for note in r.notes) for r in results
    )


def test_item_with_no_within_group_variance_is_refused():
    """A group that answered an item identically supports no comparison."""
    data, groups, items = _no_dif_setup(n_items=8, seed=17, n_per_group=400)

    values = data.values.copy()
    focal = groups == "foc"
    values[focal, 3] = 1                     # every focal respondent correct
    patched = ResponseMatrix(
        values=values,
        item_ids=data.item_ids,
        n_categories=data.n_categories,
    )

    report = dif(patched, items, groups, include_irt_lr=False)
    entry = report.items[3]

    assert entry.mantel_haenszel is None
    assert entry.logistic is None
    assert any("no within-group variance" in note for note in entry.notes)
    # The other items are unaffected.
    assert all(
        report.items[j].mantel_haenszel is not None for j in range(8) if j != 3
    )


def test_single_group_is_an_error_not_an_empty_report():
    data, groups, items = _no_dif_setup(n_items=6, seed=23, n_per_group=200)
    groups = np.array(["only"] * data.n_persons)

    with pytest.raises(ValueError, match="needs two groups"):
        dif(data, items, groups)


def test_mismatched_lengths_are_rejected():
    data, groups, items = _no_dif_setup(n_items=6, seed=29, n_per_group=150)

    with pytest.raises(ValueError, match="for 6 columns"):
        dif(data, items[:3], groups)
    with pytest.raises(ValueError, match="group labels"):
        dif(data, items, groups[:-1])


# --------------------------------------------------------------------------- #
# Multiple groups, polytomous items, and the FDR adjustment
# --------------------------------------------------------------------------- #


def test_more_than_two_groups_runs_pairwise_and_says_so():
    n_items = 8
    a = np.full(n_items, 1.2)
    b = np.linspace(-1.4, 1.4, n_items)
    true = TrueParameters(ModelKey.TWO_PL, a, b)

    blocks = [simulate(true, 300, seed=41 + k)[0] for k in range(3)]
    data = ResponseMatrix(
        values=np.vstack([blk.values for blk in blocks]),
        item_ids=blocks[0].item_ids,
        n_categories=blocks[0].n_categories,
    )
    groups = np.array(["a"] * 300 + ["b"] * 300 + ["c"] * 300)
    items = [
        ItemParameters(item_id=i, model=ModelKey.TWO_PL, discrimination=1.2,
                       difficulty=0.0)
        for i in data.item_ids
    ]

    report = dif(data, items, groups, reference="a", include_irt_lr=False)

    assert len(report.comparisons) == 2
    assert {c.focal_label for c in report.comparisons} == {"b", "c"}
    assert all(c.reference_label == "a" for c in report.comparisons)
    assert any("not independent" in note for note in report.notes)

    # The convenience accessor must refuse to pick one silently.
    with pytest.raises(ValueError, match="2 group comparisons"):
        _ = report.items


def test_polytomous_items_use_the_mantel_test_and_no_ets_letter():
    n_items = 6
    a = np.full(n_items, 1.2)
    thresholds = np.linspace(-1.2, 1.2, n_items)[:, None] + np.array([-0.7, 0.7])

    reference, _ = simulate(
        TrueParameters(ModelKey.GRM, a, thresholds=thresholds), 800, seed=61
    )
    shifted = thresholds.copy()
    shifted[2] += 0.9
    focal, _ = simulate(
        TrueParameters(ModelKey.GRM, a, thresholds=shifted), 800, seed=62
    )

    data = ResponseMatrix(
        values=np.vstack([reference.values, focal.values]),
        item_ids=reference.item_ids,
        n_categories=reference.n_categories,
    )
    groups = np.array(["ref"] * 800 + ["foc"] * 800)
    items = [
        ItemParameters(
            item_id=i, model=ModelKey.GRM, discrimination=1.2,
            thresholds=[-0.7, 0.7], n_categories=3,
        )
        for i in data.item_ids
    ]

    report = dif(data, items, groups, include_irt_lr=False)
    results = report.items

    # No dichotomous machinery, and deliberately no ETS letter.
    assert all(r.mantel_haenszel is None for r in results)
    assert all(r.mantel is not None for r in results)
    assert all(not hasattr(r.mantel, "ets_class") for r in results)

    studied = results[2]
    assert studied.mantel.p_value < 0.001
    assert studied.mantel.smd < 0            # harder for the focal group
    assert studied.mantel.flagged
    assert sum(r.mantel.flagged for r in results) == 1

    # The polytomous path still feeds the logistic model and the FDR column.
    assert studied.logistic.total_delta_r2 >= LORDIF_R2_THRESHOLD
    assert studied.mh_p_adjusted is not None


def test_benjamini_hochberg_is_monotone_and_preserves_gaps():
    raw = [0.001, 0.008, 0.02, 0.04, 0.6, None, 0.9]
    adjusted = benjamini_hochberg(raw)

    assert adjusted[5] is None
    present = [a for a in adjusted if a is not None]
    assert all(a <= b for a, b in zip(present, present[1:], strict=False))
    assert all(a >= r for a, r in zip(present, [p for p in raw if p is not None],
                                      strict=True))
    # Six tests, so the smallest p is multiplied by 6/1 and the largest by 6/6.
    assert adjusted[0] == pytest.approx(0.006)
    assert adjusted[6] == pytest.approx(0.9)


def test_benjamini_hochberg_on_an_all_none_column():
    assert benjamini_hochberg([None, None]) == [None, None]
