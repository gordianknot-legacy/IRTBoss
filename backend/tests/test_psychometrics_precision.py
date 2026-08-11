"""
Tests for information, person scoring and reliability.

The information and reliability tests are checked against closed-form results
rather than against the implementation's own output, because both quantities
were wrong in the previous implementation in ways that looked plausible. A test
that only asserts "it returns a number between 0 and 1" would have passed on
the broken code.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.irt.em import MISSING, fit
from app.irt.families import ItemParameters, ModelKey, get_family
from app.irt.simulate import simulate, spread_parameters
from app.psychometrics import ScoreMethod, item_information, reliability, score
from app.psychometrics import test_information as total_information
from app.psychometrics.information import category_probabilities


def _two_pl(a: float, b: float) -> ItemParameters:
    return ItemParameters(
        item_id="x", model=ModelKey.TWO_PL, discrimination=a, difficulty=b
    )


def _three_pl(a: float, b: float, c: float) -> ItemParameters:
    return ItemParameters(
        item_id="x", model=ModelKey.THREE_PL, discrimination=a, difficulty=b,
        guessing=c,
    )


# --------------------------------------------------------------------------- #
# Information
# --------------------------------------------------------------------------- #


def test_two_pl_information_matches_closed_form():
    """I(theta) = a^2 P Q for the 2PL."""
    a, b = 1.4, -0.3
    theta = np.linspace(-3, 3, 41)

    p = 1.0 / (1.0 + np.exp(-a * (theta - b)))
    expected = a**2 * p * (1 - p)

    np.testing.assert_allclose(
        item_information(_two_pl(a, b), theta), expected, rtol=1e-5, atol=1e-8
    )


def test_three_pl_information_matches_closed_form():
    """The 3PL information function is not a^2 P Q.

    The correct form is a^2 * (Q/P) * ((P - c)/(1 - c))^2. The previous
    implementation used the 2PL formula for the 3PL, which overstates precision
    for every guessable item - most severely at the low end of the scale, which
    is exactly where guessing bites.
    """
    a, b, c = 1.3, 0.2, 0.25
    theta = np.linspace(-3, 3, 41)

    p = c + (1 - c) / (1.0 + np.exp(-a * (theta - b)))
    q = 1 - p
    expected = a**2 * (q / p) * ((p - c) / (1 - c)) ** 2

    actual = item_information(_three_pl(a, b, c), theta)
    np.testing.assert_allclose(actual, expected, rtol=1e-4, atol=1e-7)

    naive = a**2 * p * q
    assert (actual < naive).all(), "guessing must reduce information everywhere"


def test_three_pl_information_peaks_above_difficulty():
    """Guessing shifts the point of maximum information above b."""
    item = _three_pl(1.5, 0.0, 0.25)
    grid = np.linspace(-3, 3, 1201)
    peak = grid[int(np.argmax(item_information(item, grid)))]
    assert peak > 0.05


@pytest.mark.parametrize("model", list(ModelKey))
def test_information_is_positive_and_finite(model):
    n_cat = 4 if model.is_polytomous else 2
    family = get_family(model)
    rng = np.random.default_rng(0)
    observed = rng.integers(0, n_cat, size=200).astype(float)
    params = family.to_natural("x", family.initial(observed, n_cat), n_cat)

    info = item_information(params, np.linspace(-4, 4, 33))
    assert np.isfinite(info).all()
    assert (info > 0).all()


def test_test_information_is_additive():
    items = [_two_pl(1.0, -1.0), _two_pl(1.5, 0.0), _two_pl(0.8, 1.0)]
    theta = np.linspace(-3, 3, 21)
    total = total_information(items, theta)
    parts = sum(item_information(i, theta) for i in items)
    np.testing.assert_allclose(total, parts, rtol=1e-10)


def test_round_trip_through_natural_parameters_preserves_probabilities():
    """from_natural must invert to_natural for every family.

    Diagnostics evaluate models from stored parameters, so a lossy round trip
    would silently change every statistic computed after a fit is reloaded.
    """
    rng = np.random.default_rng(7)
    theta = np.linspace(-3, 3, 17)

    for model in ModelKey:
        family = get_family(model)
        n_cat = 4 if model.is_polytomous else 2
        u = rng.normal(0, 0.7, size=family.n_params(n_cat))
        params = family.to_natural("x", u, n_cat)

        np.testing.assert_allclose(
            category_probabilities(params, theta),
            family.probabilities(theta, u, n_cat),
            rtol=1e-9,
            atol=1e-12,
        )


# --------------------------------------------------------------------------- #
# Person scoring
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "method", [ScoreMethod.EAP, ScoreMethod.MAP, ScoreMethod.WLE]
)
def test_scores_recover_true_ability(method):
    true = spread_parameters(ModelKey.TWO_PL, 30)
    data, theta = simulate(true, 1500, seed=41)
    result = fit(data, ModelKey.TWO_PL)
    assert result.converged

    scores = score(data, result.item_parameters, method)

    assert scores.scorable.all()
    assert np.corrcoef(scores.theta, theta)[0, 1] > 0.90
    assert abs(np.mean(scores.theta - theta)) < 0.15


def test_eap_shrinks_and_wle_does_not():
    """EAP pulls extreme scores towards the mean; WLE is built not to.

    This is the reason both are offered. The regression of estimate on truth has
    slope below 1 for EAP by construction, and close to 1 for WLE.
    """
    true = spread_parameters(ModelKey.TWO_PL, 30)
    data, theta = simulate(true, 2000, seed=43)
    result = fit(data, ModelKey.TWO_PL)
    assert result.converged

    eap = score(data, result.item_parameters, ScoreMethod.EAP)
    wle = score(data, result.item_parameters, ScoreMethod.WLE)

    eap_slope = np.polyfit(theta, eap.theta, 1)[0]
    wle_slope = np.polyfit(theta, wle.theta, 1)[0]

    assert eap_slope < 0.95
    assert wle_slope > eap_slope
    # And the spread of WLE estimates is wider, being unshrunk.
    assert np.std(wle.theta) > np.std(eap.theta)


def test_wle_is_less_biased_at_the_extremes():
    true = spread_parameters(ModelKey.TWO_PL, 30)
    data, theta = simulate(true, 2000, seed=47)
    result = fit(data, ModelKey.TWO_PL)
    assert result.converged

    eap = score(data, result.item_parameters, ScoreMethod.EAP)
    wle = score(data, result.item_parameters, ScoreMethod.WLE)

    top = theta > np.quantile(theta, 0.90)
    assert abs(np.mean(wle.theta[top] - theta[top])) < abs(
        np.mean(eap.theta[top] - theta[top])
    )


def test_unanswered_respondent_is_not_scored():
    """No responses means no score, not the population mean wearing a name."""
    true = spread_parameters(ModelKey.TWO_PL, 10)
    data, _ = simulate(true, 200, seed=51)
    data.values[0, :] = MISSING

    scores = score(data, fit(data, ModelKey.TWO_PL).item_parameters)

    assert np.isnan(scores.theta[0])
    assert np.isnan(scores.standard_error[0])
    assert scores.n_responses[0] == 0
    assert scores.scorable[1:].all()


def test_standard_errors_are_smallest_where_information_peaks():
    true = spread_parameters(ModelKey.TWO_PL, 25)
    data, _ = simulate(true, 1000, seed=53)
    result = fit(data, ModelKey.TWO_PL)

    scores = score(data, result.item_parameters, ScoreMethod.EAP)
    keep = scores.scorable
    central = np.abs(scores.theta[keep]) < 0.5
    extreme = np.abs(scores.theta[keep]) > 2.0

    assert central.any() and extreme.any()
    assert scores.standard_error[keep][central].mean() < (
        scores.standard_error[keep][extreme].mean()
    )


def test_polytomous_scoring_works():
    true = spread_parameters(ModelKey.GRM, 12, n_categories=5)
    data, theta = simulate(true, 1000, seed=57)
    result = fit(data, ModelKey.GRM)
    assert result.converged

    scores = score(data, result.item_parameters, ScoreMethod.EAP)
    assert np.corrcoef(scores.theta, theta)[0, 1] > 0.90


# --------------------------------------------------------------------------- #
# Reliability
# --------------------------------------------------------------------------- #


def test_marginal_reliability_is_not_the_jensen_biased_formula():
    """Regression test for the defect this module exists to fix.

    The previous implementation reciprocated the *average information*; the
    correct figure averages the *error variance*. Jensen's inequality says
    ``1 / E[I] <= E[1 / I]``, so the old route always returned the larger
    number whenever information varies across the trait range - which it always
    does.

    The comparison is against ``marginal_information``, which defines ``SE`` the
    same way the old code did. ``marginal_bayesian`` uses a different error
    variance - it counts the prior's information too - so it can legitimately
    come out higher and says nothing about this bias either way.

    Both sides use the same population weights. Comparing a density-weighted
    integral against an unweighted grid mean would confound the actual bias
    with how far the grid extends into the tails.
    """
    items = [
        _two_pl(a, b)
        for a, b in zip(
            np.linspace(0.7, 1.8, 20), np.linspace(-2.0, 2.0, 20), strict=True
        )
    ]
    report = reliability(items)

    grid = report.theta_grid
    info = report.test_information
    density = np.exp(-0.5 * grid**2) * np.gradient(grid)
    weights = density / density.sum()

    old_formula = 1.0 - 1.0 / float(np.dot(weights, info))

    assert report.marginal_information < old_formula
    # The overstatement is material, not a rounding difference.
    assert old_formula - report.marginal_information > 0.02


def test_reliability_rises_with_test_length():
    short = [_two_pl(1.2, b) for b in np.linspace(-1.5, 1.5, 10)]
    long = [_two_pl(1.2, b) for b in np.linspace(-1.5, 1.5, 40)]

    assert reliability(long).marginal_bayesian > reliability(
        short
    ).marginal_bayesian


def test_bayesian_reliability_is_bounded():
    """The Bayesian figure cannot exceed 1 or fall below 0, whatever the test."""
    useless = [_two_pl(0.05, 0.0) for _ in range(3)]
    strong = [_two_pl(2.5, b) for b in np.linspace(-2, 2, 60)]

    for items in (useless, strong):
        rho = reliability(items).marginal_bayesian
        assert 0.0 <= rho <= 1.0

    assert reliability(useless).marginal_bayesian < 0.15
    assert reliability(strong).marginal_bayesian > 0.90


def test_a_test_that_measures_nothing_says_so():
    report = reliability([_two_pl(0.05, 0.0) for _ in range(3)])

    assert report.bands[0].lower is None
    assert any("does not support individual-level" in n for n in report.notes)
    assert any("below the level" in n for n in report.notes)


def test_precision_band_tracks_where_items_are():
    """A test built at the low end should be precise at the low end only."""
    items = [_two_pl(1.8, b) for b in np.linspace(-2.5, -0.5, 30)]
    report = reliability(items)

    band = report.bands[0]
    assert band.lower is not None and band.upper is not None
    assert band.upper < 0.75
    assert report.peak_information_at < 0.0


def test_conditional_sem_curves_are_ordered():
    """A prior can only ever add information, so Bayesian SEs are smaller."""
    items = [_two_pl(1.2, b) for b in np.linspace(-2, 2, 20)]
    report = reliability(items)

    assert (report.conditional_sem_bayesian < report.conditional_sem_ml).all()
    assert (report.conditional_sem_bayesian <= 1.0).all()


def test_omega_is_reported_for_two_pl_and_withheld_elsewhere():
    two_pl = [_two_pl(1.3, b) for b in np.linspace(-2, 2, 25)]
    report = reliability(two_pl)
    assert report.omega is not None
    assert 0.0 < report.omega < 1.0
    # Omega and marginal reliability measure the same construct by different
    # routes, so they should broadly agree on a well-behaved test.
    assert abs(report.omega - report.marginal_bayesian) < 0.15

    guessable = [_three_pl(1.3, b, 0.2) for b in np.linspace(-2, 2, 25)]
    withheld = reliability(guessable)
    assert withheld.omega is None
    assert any("3PL" in n for n in withheld.notes)


def test_no_alpha_anywhere():
    """Cronbach's alpha is excluded by design; make that a test, not a comment."""
    import importlib

    module = importlib.import_module("app.psychometrics.reliability")
    source = module.__doc__ or ""
    assert "alpha" in source.lower(), "the exclusion must stay documented"
    report = reliability([_two_pl(1.2, b) for b in np.linspace(-2, 2, 10)])
    assert not hasattr(report, "alpha")
    assert not hasattr(report, "cronbach_alpha")


def test_empirical_reliability_uses_the_sample_not_the_model():
    true = spread_parameters(ModelKey.TWO_PL, 30)
    data, _ = simulate(true, 1500, seed=61)
    result = fit(data, ModelKey.TWO_PL)
    scores = score(data, result.item_parameters, ScoreMethod.EAP)

    report = reliability(result.item_parameters, scores=scores)

    assert report.empirical is not None
    assert 0.0 < report.empirical < 1.0
    # Sample drawn from the assumed normal population, so the two agree.
    assert abs(report.empirical - report.marginal_bayesian) < 0.10
