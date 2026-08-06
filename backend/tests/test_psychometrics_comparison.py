"""
Tests for the model-comparison dossier.

Two properties are load-bearing and pull in opposite directions. The dossier
must *separate* models when the data genuinely separate them - held-out
prediction has to prefer the generating model over an underparameterised one -
and it must *refuse to separate* them when they fit equally, rather than
letting an argmin manufacture a winner out of noise.

A third property is a refusal in the strict sense: the 2PL-vs-3PL
likelihood-ratio test must come back as a refusal carrying its reason, never as
a p-value. The test below asserts the absence of the p-value, because printing
one would be the exact defect this module exists to prevent.

Sample sizes are kept small deliberately - cross-validation refits every model
once per fold, so these are the smallest configurations that still make the
point.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.irt.em import EMOptions, ResponseMatrix, fit
from app.irt.families import ModelKey
from app.irt.simulate import TrueParameters, simulate, spread_parameters
from app.psychometrics.comparison import AIC, BIC, CV, _fold_assignments, compare

FAST = EMOptions(compute_standard_errors=False)


def _varied_slope_test(n_items: int = 12) -> TrueParameters:
    """A 2PL test whose slopes a Rasch model cannot possibly represent."""
    slopes = np.tile([0.55, 2.3], n_items // 2)
    return TrueParameters(
        model=ModelKey.TWO_PL,
        discrimination=slopes,
        difficulty=np.linspace(-1.8, 1.8, n_items),
    )


def test_cross_validation_prefers_the_true_model_over_an_underparameterised_one():
    """2PL data with widely varied slopes: held-out prediction must pick the 2PL."""
    data, _ = simulate(_varied_slope_test(), 800, seed=71)

    dossier = compare(data, [ModelKey.RASCH, ModelKey.TWO_PL], folds=3, seed=5)

    assert dossier.leader is ModelKey.TWO_PL
    assert not dossier.indistinguishable
    assert dossier.ranked[0].model is ModelKey.TWO_PL
    assert dossier.rankings[CV][0] is ModelKey.TWO_PL

    two_pl, rasch = dossier.ranked[0], dossier.ranked[1]
    assert two_pl.cv_log_likelihood > rasch.cv_log_likelihood
    # The margin must be large relative to its own fold-to-fold noise, not just
    # positive; a positive difference on its own is a coin flip.
    assert two_pl.cv_standard_error is not None
    assert (
        two_pl.cv_log_likelihood - rasch.cv_log_likelihood
        > 2.0 * two_pl.cv_standard_error / np.sqrt(3)
    )
    assert "2PL predicts held-out responses better" in dossier.verdict


def test_cross_validation_declares_equally_fitting_models_indistinguishable():
    """Rasch and the 1PL are reparameterisations; nothing may separate them.

    Rasch fixes the slopes at 1 and estimates the latent variance, the 1PL
    estimates a common slope and fixes the variance. Same parameter count, same
    predictions. A comparison that names a winner here is reporting noise.
    """
    true = spread_parameters(ModelKey.RASCH, 12)
    data, _ = simulate(true, 800, seed=61)

    dossier = compare(data, [ModelKey.RASCH, ModelKey.ONE_PL], folds=3, seed=5)

    assert dossier.indistinguishable
    assert "indistinguishable" in dossier.verdict.lower()
    rasch = next(e for e in dossier.ranked if e.model is ModelKey.RASCH)
    one_pl = next(e for e in dossier.ranked if e.model is ModelKey.ONE_PL)
    assert rasch.cv_log_likelihood == pytest.approx(
        one_pl.cv_log_likelihood, abs=1.0
    )
    assert any("do not separate them" in note for note in dossier.notes)


def test_2pl_versus_3pl_likelihood_ratio_is_refused_not_reported():
    """c = 0 is a boundary null, so no p-value may be produced for this pair."""
    true = spread_parameters(ModelKey.THREE_PL, 10)
    data, _ = simulate(true, 600, seed=81)

    dossier = compare(data, [ModelKey.TWO_PL, ModelKey.THREE_PL], folds=2, seed=5)

    test = next(
        t
        for t in dossier.likelihood_ratio_tests
        if {t.restricted, t.full} == {ModelKey.TWO_PL, ModelKey.THREE_PL}
    )
    assert test.performed is False
    assert test.p_value is None
    assert test.statistic is None
    assert test.df is None
    assert "boundary" in test.refusal_reason
    assert "chi-square" in test.refusal_reason


def test_the_nested_1pl_versus_2pl_test_is_performed_with_the_right_df():
    """The lower rung of the ladder is a valid interior restriction."""
    data, _ = simulate(_varied_slope_test(), 800, seed=73)

    dossier = compare(data, [ModelKey.ONE_PL, ModelKey.TWO_PL], folds=2, seed=5)

    test = next(
        t
        for t in dossier.likelihood_ratio_tests
        if {t.restricted, t.full} == {ModelKey.ONE_PL, ModelKey.TWO_PL}
    )
    assert test.performed is True
    assert test.restricted is ModelKey.ONE_PL
    # 24 free parameters under the 2PL, 13 under the 1PL.
    assert test.df == 24 - 13
    assert test.statistic > 0.0
    assert 0.0 <= test.p_value <= 1.0
    # Slopes this varied are not a 1PL, so the test should reject.
    assert test.p_value < 1e-6


def test_rasch_versus_1pl_likelihood_ratio_is_refused_as_non_nested():
    true = spread_parameters(ModelKey.RASCH, 10)
    data, _ = simulate(true, 600, seed=63)

    dossier = compare(data, [ModelKey.RASCH, ModelKey.ONE_PL], folds=2, seed=5)

    test = dossier.likelihood_ratio_tests[0]
    assert test.performed is False
    assert test.p_value is None
    assert "not nested" in test.refusal_reason
    assert "metric" in test.refusal_reason


def test_grm_versus_gpcm_is_refused_and_deferred_to_held_out_prediction():
    true = spread_parameters(ModelKey.GRM, 8, n_categories=3)
    data, _ = simulate(true, 600, seed=91)

    dossier = compare(data, [ModelKey.GRM, ModelKey.GPCM], folds=2, seed=5)

    test = dossier.likelihood_ratio_tests[0]
    assert test.performed is False
    assert test.p_value is None
    assert "not nested" in test.refusal_reason
    assert "Vuong" in test.refusal_reason
    # The non-nested question is still answered, just not by an LRT.
    assert all(e.cv_log_likelihood is not None for e in dossier.ranked)


def test_pcm_versus_gpcm_is_a_valid_nested_test():
    true = spread_parameters(ModelKey.GPCM, 8, n_categories=3)
    data, _ = simulate(true, 600, seed=93)

    dossier = compare(data, [ModelKey.PCM, ModelKey.GPCM], folds=2, seed=5)

    test = dossier.likelihood_ratio_tests[0]
    assert test.performed is True
    assert test.restricted is ModelKey.PCM
    # GPCM: 8 slopes + 16 steps = 24. PCM: 16 steps + the latent variance = 17.
    assert test.df == 24 - 17
    assert test.p_value is not None


def test_disagreement_between_criteria_is_reported_not_resolved():
    """BIC's parsimony penalty routinely differs from held-out prediction.

    On a short test with a modest sample the penalty is heavy enough that BIC
    prefers Rasch while held-out prediction prefers the 2PL. The dossier must
    show both first choices rather than picking one.
    """
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 12), 800, seed=41)

    dossier = compare(data, [ModelKey.RASCH, ModelKey.TWO_PL], folds=3, seed=5)

    assert set(dossier.first_choice) == {CV, AIC, BIC}
    assert dossier.first_choice[CV] is ModelKey.TWO_PL
    assert dossier.first_choice[BIC] is ModelKey.RASCH
    assert not dossier.criteria_agree
    pair = next(
        d for d in dossier.disagreements if {d.criterion_a, d.criterion_b} == {CV, BIC}
    )
    assert pair.first_a is not pair.first_b
    assert any("different models" in note for note in dossier.notes)


def test_dossier_names_no_single_winner():
    """The structure itself must not offer a 'best model' field to read."""
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 10), 600, seed=43)

    dossier = compare(data, [ModelKey.RASCH, ModelKey.TWO_PL], folds=2, seed=5)

    assert not hasattr(dossier, "best_model")
    assert not hasattr(dossier, "recommended")
    assert not hasattr(dossier, "selected")
    assert isinstance(dossier.verdict, str) and dossier.verdict


def test_every_respondent_is_held_out_exactly_once_and_the_split_is_seeded():
    assignments = _fold_assignments(101, 4, seed=17)

    assert assignments.size == 101
    assert set(np.unique(assignments)) == {0, 1, 2, 3}
    counts = np.bincount(assignments)
    assert counts.max() - counts.min() <= 1
    np.testing.assert_array_equal(assignments, _fold_assignments(101, 4, seed=17))
    assert not np.array_equal(assignments, _fold_assignments(101, 4, seed=18))


def test_fold_results_partition_the_sample():
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 10), 600, seed=45)

    dossier = compare(data, [ModelKey.RASCH, ModelKey.TWO_PL], folds=3, seed=5)

    for evidence in dossier.ranked:
        assert len(evidence.folds) == 3
        assert sum(f.n_test for f in evidence.folds) == 600
        for f in evidence.folds:
            assert f.n_train + f.n_test == 600
        assert evidence.cv_log_likelihood == pytest.approx(
            sum(f.log_likelihood for f in evidence.folds)
        )
        assert evidence.cv_per_respondent == pytest.approx(
            evidence.cv_log_likelihood / 600
        )


def test_an_inapplicable_model_is_recorded_with_its_reason():
    """A dichotomous model on polytomous data is excluded, not crashed on."""
    true = spread_parameters(ModelKey.GRM, 8, n_categories=3)
    data, _ = simulate(true, 500, seed=95)

    dossier = compare(data, [ModelKey.GRM, ModelKey.TWO_PL], folds=2, seed=5)

    excluded = next(e for e in dossier.ranked if e.model is ModelKey.TWO_PL)
    assert not excluded.usable
    assert excluded.cv_log_likelihood is None
    assert "binary" in excluded.failure_reason
    assert dossier.leader is ModelKey.GRM
    assert "nothing to compare it against" in dossier.verdict


def test_three_pl_estimability_is_flagged_when_the_data_are_too_thin():
    true = spread_parameters(ModelKey.THREE_PL, 10)
    data, _ = simulate(true, 600, seed=83)

    dossier = compare(data, [ModelKey.TWO_PL, ModelKey.THREE_PL], folds=2, seed=5)

    assert any("joint minimum" in note for note in dossier.notes)
    assert any("Beta(5, 17)" in note for note in dossier.notes)


def test_secondary_criteria_match_the_full_sample_fit():
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 10), 600, seed=47)

    dossier = compare(data, [ModelKey.RASCH, ModelKey.TWO_PL], folds=2, seed=5)
    direct = fit(data, ModelKey.TWO_PL, FAST)

    evidence = next(e for e in dossier.ranked if e.model is ModelKey.TWO_PL)
    assert evidence.log_likelihood == pytest.approx(direct.log_likelihood)
    assert evidence.aic == pytest.approx(direct.aic)
    assert evidence.bic == pytest.approx(direct.bic)
    assert evidence.n_free_parameters == direct.n_free_parameters


def test_rejects_degenerate_requests():
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 8), 200, seed=49)

    with pytest.raises(ValueError, match="at least two models"):
        compare(data, [ModelKey.TWO_PL], folds=2)
    with pytest.raises(ValueError, match="only once"):
        compare(data, [ModelKey.TWO_PL, ModelKey.TWO_PL], folds=2)
    with pytest.raises(ValueError, match="at least two folds"):
        compare(data, [ModelKey.RASCH, ModelKey.TWO_PL], folds=1)

    tiny = ResponseMatrix(
        values=data.values[:4],
        item_ids=list(data.item_ids),
        n_categories=data.n_categories.copy(),
    )
    with pytest.raises(ValueError, match="cannot be split"):
        compare(tiny, [ModelKey.RASCH, ModelKey.TWO_PL], folds=3)
