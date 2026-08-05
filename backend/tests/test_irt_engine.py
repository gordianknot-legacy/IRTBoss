"""
Parameter recovery tests for the estimation engine.

These are the tests that decide whether the engine is trustworthy. Simulating
from known parameters and checking they come back is the only way to know an
estimator works; every other test in the suite assumes this one passes.

Tolerances are deliberately loose enough to be stable across platforms and
tight enough to fail on a real regression. They are stated as bias (systematic
error, which should be near zero) and RMSE (total error, which is dominated by
sampling variability at these sample sizes).
"""

from __future__ import annotations

import numpy as np
import pytest

from app.irt.em import MISSING, EMOptions, ResponseMatrix, fit
from app.irt.families import ModelKey, get_family
from app.irt.simulate import simulate, spread_parameters

# (model, n_persons, n_items, n_categories, max |bias|, max RMSE)
DICHOTOMOUS_CASES = [
    (ModelKey.RASCH, 1500, 20, 2, 0.10, 0.15),
    (ModelKey.ONE_PL, 1500, 20, 2, 0.10, 0.15),
    (ModelKey.TWO_PL, 2000, 20, 2, 0.10, 0.15),
    (ModelKey.THREE_PL, 3000, 30, 2, 0.12, 0.20),
]

POLYTOMOUS_CASES = [
    (ModelKey.GRM, 1500, 12, 5, 0.10, 0.15),
    (ModelKey.PCM, 1500, 12, 4, 0.10, 0.20),
    (ModelKey.GPCM, 2000, 12, 4, 0.10, 0.18),
]


@pytest.mark.parametrize(
    ("model", "n_persons", "n_items", "n_cat", "max_bias", "max_rmse"),
    DICHOTOMOUS_CASES,
)
def test_recovers_dichotomous_difficulty(
    model, n_persons, n_items, n_cat, max_bias, max_rmse
):
    true = spread_parameters(model, n_items, n_categories=n_cat)
    data, _ = simulate(true, n_persons, seed=11)

    result = fit(data, model)

    assert result.converged, result.failure_reason
    estimated = np.array([p.difficulty for p in result.item_parameters])
    error = estimated - true.difficulty

    assert abs(error.mean()) < max_bias
    assert np.sqrt((error**2).mean()) < max_rmse
    # Ordering matters more than absolute location: a difficulty scale that
    # ranks items wrongly is useless even if it is unbiased on average.
    assert np.corrcoef(estimated, true.difficulty)[0, 1] > 0.98


@pytest.mark.parametrize(
    ("model", "n_persons", "n_items", "n_cat", "max_bias", "max_rmse"),
    [c for c in DICHOTOMOUS_CASES if c[0] in (ModelKey.TWO_PL, ModelKey.THREE_PL)],
)
def test_recovers_discrimination(
    model, n_persons, n_items, n_cat, max_bias, max_rmse
):
    true = spread_parameters(model, n_items, n_categories=n_cat)
    data, _ = simulate(true, n_persons, seed=11)

    result = fit(data, model)

    assert result.converged, result.failure_reason
    estimated = np.array([p.discrimination for p in result.item_parameters])
    error = estimated - true.discrimination

    assert abs(error.mean()) < max_bias
    assert np.sqrt((error**2).mean()) < 0.25


@pytest.mark.parametrize(
    ("model", "n_persons", "n_items", "n_cat", "max_bias", "max_rmse"),
    POLYTOMOUS_CASES,
)
def test_recovers_polytomous_thresholds(
    model, n_persons, n_items, n_cat, max_bias, max_rmse
):
    true = spread_parameters(model, n_items, n_categories=n_cat)
    data, _ = simulate(true, n_persons, seed=11)

    result = fit(data, model)

    assert result.converged, result.failure_reason
    estimated = np.array([p.thresholds for p in result.item_parameters])
    error = estimated - np.asarray(true.thresholds)

    assert abs(error.mean()) < max_bias
    assert np.sqrt((error**2).mean()) < max_rmse
    assert all(p.n_categories == n_cat for p in result.item_parameters)


def test_three_pl_guessing_stays_plausible():
    """The Beta prior should keep c in the region a real item can produce.

    Without it, an unpenalised EM fit wanders to implausible lower asymptotes at
    realistic sample sizes - the failure mode mirt has by default.
    """
    true = spread_parameters(ModelKey.THREE_PL, 30)
    data, _ = simulate(true, 3000, seed=11)

    result = fit(data, ModelKey.THREE_PL)

    assert result.converged
    guessing = np.array([p.guessing for p in result.item_parameters])
    assert guessing.min() > 0.0
    assert guessing.max() < 0.45
    assert abs(guessing.mean() - true.guessing.mean()) < 0.10


def test_standard_errors_track_sampling_variability():
    """Reported SEs should approximate the actual spread of estimation error.

    This is the check that catches an information matrix that is merely
    invertible rather than correct - a plausible-looking but wrong SE is worse
    than no SE, because it will be believed.
    """
    true = spread_parameters(ModelKey.TWO_PL, 25)
    data, _ = simulate(true, 2000, seed=5)

    result = fit(data, ModelKey.TWO_PL)

    assert result.converged
    reported = np.array([p.se_difficulty for p in result.item_parameters])
    assert np.isfinite(reported).all()
    assert (reported > 0).all()

    estimated = np.array([p.difficulty for p in result.item_parameters])
    empirical = np.std(estimated - true.difficulty)

    # Within a factor of two of the empirical spread. Loose, because the
    # empirical figure is itself estimated from only 25 items.
    assert 0.5 * empirical < np.median(reported) < 2.0 * empirical


def test_every_parameter_carries_a_standard_error():
    """No estimated parameter ships without its uncertainty."""
    true = spread_parameters(ModelKey.GRM, 10, n_categories=4)
    data, _ = simulate(true, 1200, seed=3)

    result = fit(data, ModelKey.GRM)

    assert result.converged
    for params in result.item_parameters:
        assert params.se_discrimination is not None
        assert params.se_thresholds is not None
        assert len(params.se_thresholds) == len(params.thresholds)


def test_fixed_slope_reports_no_standard_error():
    """A slope pinned at 1 has no sampling variability; reporting one would lie."""
    true = spread_parameters(ModelKey.RASCH, 15)
    data, _ = simulate(true, 1000, seed=3)

    result = fit(data, ModelKey.RASCH)

    assert result.converged
    assert all(p.discrimination == pytest.approx(1.0) for p in result.item_parameters)
    assert all(p.se_discrimination is None for p in result.item_parameters)
    assert all(p.se_difficulty is not None for p in result.item_parameters)


def test_one_pl_shares_a_single_slope():
    true = spread_parameters(ModelKey.ONE_PL, 15)
    data, _ = simulate(true, 1500, seed=3)

    result = fit(data, ModelKey.ONE_PL)

    assert result.converged
    slopes = {round(p.discrimination, 8) for p in result.item_parameters}
    assert len(slopes) == 1
    # One slope plus one difficulty per item.
    assert result.n_free_parameters == 15 + 1


def test_rasch_estimates_latent_variance_not_a_slope():
    """Rasch and 1PL are different models on different metrics.

    Conflating them was a real defect in the previous implementation. Rasch
    fixes a = 1 and lets the latent SD float; that SD must be recoverable.
    """
    true = spread_parameters(ModelKey.RASCH, 20)
    data, _ = simulate(true, 2000, seed=9, latent_sd=1.4)

    result = fit(data, ModelKey.RASCH)

    assert result.converged
    assert result.latent_sd == pytest.approx(1.4, abs=0.15)
    # One difficulty per item plus the variance.
    assert result.n_free_parameters == 20 + 1


def test_missing_responses_do_not_bias_estimates():
    """Missing data is skipped per cell (FIML), never imputed."""
    true = spread_parameters(ModelKey.TWO_PL, 20)
    complete, _ = simulate(true, 2500, seed=13)
    sparse, _ = simulate(true, 2500, seed=13, missing_rate=0.15)

    assert (sparse.values == MISSING).any()

    full_fit = fit(complete, ModelKey.TWO_PL)
    sparse_fit = fit(sparse, ModelKey.TWO_PL)

    assert full_fit.converged and sparse_fit.converged
    a = np.array([p.difficulty for p in full_fit.item_parameters])
    b = np.array([p.difficulty for p in sparse_fit.item_parameters])
    assert abs((b - true.difficulty).mean()) < 0.12
    # Missingness costs precision, not accuracy.
    assert np.abs(a - b).max() < 0.35


def test_information_criteria_are_consistent_with_log_likelihood():
    """AIC and BIC must be derived from the log-likelihood beside them.

    The previous implementation's dummy fitter emitted an AIC that was not a
    function of the log-likelihood it reported, which made model comparison
    a foregone conclusion.
    """
    true = spread_parameters(ModelKey.TWO_PL, 15)
    data, _ = simulate(true, 1000, seed=17)

    result = fit(data, ModelKey.TWO_PL)

    assert result.converged
    k = result.n_free_parameters
    assert result.aic == pytest.approx(-2 * result.log_likelihood + 2 * k)
    assert result.bic == pytest.approx(
        -2 * result.log_likelihood + k * np.log(result.n_persons)
    )


def test_richer_model_achieves_higher_likelihood():
    """A nested model cannot fit better than the model that contains it."""
    true = spread_parameters(ModelKey.TWO_PL, 20)
    data, _ = simulate(true, 2000, seed=19)

    rasch = fit(data, ModelKey.RASCH)
    two_pl = fit(data, ModelKey.TWO_PL)

    assert rasch.converged and two_pl.converged
    assert two_pl.log_likelihood > rasch.log_likelihood


def test_failure_carries_no_parameters():
    """An unconverged fit must not leak partial estimates downstream."""
    true = spread_parameters(ModelKey.TWO_PL, 12)
    data, _ = simulate(true, 600, seed=23)

    result = fit(data, ModelKey.TWO_PL, EMOptions(max_cycles=1, tolerance=1e-12))

    assert not result.converged
    assert result.item_parameters == []
    assert result.log_likelihood is None
    assert result.aic is None and result.bic is None
    assert result.failure_reason and "converge" in result.failure_reason


def test_rejects_dichotomous_model_on_polytomous_data():
    true = spread_parameters(ModelKey.GRM, 10, n_categories=5)
    data, _ = simulate(true, 500, seed=29)

    with pytest.raises(ValueError, match="GRM, PCM or GPCM"):
        fit(data, ModelKey.TWO_PL)


def test_rejects_polytomous_model_on_binary_data():
    true = spread_parameters(ModelKey.TWO_PL, 10)
    data, _ = simulate(true, 500, seed=29)

    with pytest.raises(ValueError, match="every item is binary"):
        fit(data, ModelKey.GRM)


def test_response_matrix_validates_its_own_shape():
    values = np.zeros((10, 3), dtype=np.int16)
    with pytest.raises(ValueError, match="item ids"):
        ResponseMatrix(
            values=values, item_ids=["a", "b"], n_categories=np.array([2, 2, 2])
        )


@pytest.mark.parametrize("model", list(ModelKey))
def test_probabilities_are_a_valid_distribution(model):
    """Every family must produce rows that sum to one across categories."""
    family = get_family(model)
    n_cat = 4 if model.is_polytomous else 2
    theta = np.linspace(-4, 4, 25)
    observed = np.random.default_rng(0).integers(0, n_cat, size=200).astype(float)
    u = family.initial(observed, n_cat)

    probs = family.probabilities(theta, u, n_cat)

    assert probs.shape == (theta.size, n_cat)
    assert (probs > 0).all()
    np.testing.assert_allclose(probs.sum(axis=1), 1.0, atol=1e-9)


@pytest.mark.parametrize("model", [ModelKey.GRM])
def test_graded_thresholds_are_always_ordered(model):
    """The GRM's encoding must make disordered boundaries unrepresentable.

    Out-of-order boundaries would produce negative category probabilities, so
    ordering is enforced by construction rather than by a constraint the
    optimiser could violate.
    """
    family = get_family(model)
    rng = np.random.default_rng(0)
    for _ in range(200):
        u = rng.normal(0, 2.0, size=family.n_params(5))
        params = family.to_natural("x", u, 5)
        assert np.all(np.diff(params.thresholds) > 0)
