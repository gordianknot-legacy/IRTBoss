"""
Tests for limited-information global fit.

A global fit statistic earns its place only if it satisfies two opposing
requirements at once: it must be *calibrated* under the true model - the
statistic averaging its own degrees of freedom, p-values behaving like
p-values - and it must *fire* against a misspecification that matters. A
statistic that is merely quiet proves nothing, because so is a constant.

Calibration is checked in aggregate rather than on one dataset, because a
single draw of a chi-square with 35 df is uninformative about whether the df
is right. A df error shifts every replication in the same direction, so the
mean across replications is what exposes it.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.irt.em import EMOptions, fit
from app.irt.families import ModelKey
from app.irt.simulate import TrueParameters, simulate, spread_parameters
from app.psychometrics.globalfit import global_fit

# Standard errors are never read here and cost more than the fit itself.
FAST = EMOptions(compute_standard_errors=False)


def _guessing_test(n_items: int, guessing: float) -> TrueParameters:
    """A multiple-choice-like 3PL test: steep items, difficulty above average."""
    rng = np.random.default_rng(7)
    return TrueParameters(
        model=ModelKey.THREE_PL,
        discrimination=rng.uniform(1.5, 2.5, n_items),
        difficulty=np.linspace(-1.5, 2.0, n_items),
        guessing=np.full(n_items, guessing),
    )


def test_m2_degrees_of_freedom_count_moments_less_parameters():
    """df must be s - q, with s the univariate plus bivariate margins."""
    true = spread_parameters(ModelKey.TWO_PL, 10)
    data, _ = simulate(true, 1500, seed=101)
    result = fit(data, ModelKey.TWO_PL, FAST)
    assert result.converged

    report = global_fit(data, result.item_parameters)

    assert report.statistic_name == "M2"
    assert report.n_moments == 10 + 10 * 9 // 2
    assert report.n_free_parameters == 2 * 10 == result.n_free_parameters
    assert report.df == report.n_moments - report.n_free_parameters
    assert report.failure_reason is None
    assert report.n_persons_used == 1500


def test_m2_is_calibrated_when_the_fitted_model_is_the_true_model():
    """Across replications the statistic must average its degrees of freedom.

    This is the check a wrong df cannot survive: it moves the whole
    distribution, not one draw of it.
    """
    true = spread_parameters(ModelKey.TWO_PL, 10)
    statistics = []
    p_values = []
    for seed in range(200, 212):
        data, _ = simulate(true, 1500, seed=seed)
        result = fit(data, ModelKey.TWO_PL, FAST)
        assert result.converged
        report = global_fit(data, result.item_parameters)
        statistics.append(report.statistic)
        p_values.append(report.p_value)

    df = 35
    mean = float(np.mean(statistics))
    # The mean of a chi-square(35) over 12 draws has SD sqrt(2*35/12) ~ 2.4, so
    # a band of +/- 8 is roughly three standard errors wide.
    assert abs(mean - df) < 8.0, statistics
    # p-values behave like p-values: a correct model is not routinely rejected.
    assert sum(p < 0.05 for p in p_values) <= 2, p_values


def test_rmsea2_is_near_zero_and_its_interval_brackets_it():
    true = spread_parameters(ModelKey.TWO_PL, 12)
    data, _ = simulate(true, 2000, seed=103)
    result = fit(data, ModelKey.TWO_PL, FAST)

    report = global_fit(data, result.item_parameters, confidence=0.90)

    assert report.rmsea2 < 0.01
    assert report.rmsea2_lower <= report.rmsea2 <= report.rmsea2_upper
    assert report.rmsea2_lower >= 0.0
    assert report.rmsea2_upper < 0.05
    assert report.rmsea2_confidence == 0.90


def test_srmsr_is_small_under_the_true_model():
    true = spread_parameters(ModelKey.TWO_PL, 12)
    data, _ = simulate(true, 2000, seed=105)
    result = fit(data, ModelKey.TWO_PL, FAST)

    report = global_fit(data, result.item_parameters)

    assert report.srmsr is not None
    assert report.srmsr < 0.03


def test_m2_fires_when_a_2pl_is_fitted_to_3pl_data():
    """Substantial guessing is a misspecification M2 must not miss.

    The 2PL has two parameters per item, so it can absorb the univariate
    margins almost exactly; the evidence against it lives entirely in the
    bivariate margins, which is precisely what M2 is built from.
    """
    true = _guessing_test(25, guessing=0.35)
    data, _ = simulate(true, 4000, seed=555)

    wrong = fit(data, ModelKey.TWO_PL, FAST)
    assert wrong.converged
    report = global_fit(data, wrong.item_parameters)

    assert report.p_value < 0.001, report.statistic_over_df
    assert report.statistic_over_df > 1.3
    # The interval excludes a perfectly fitting model.
    assert report.rmsea2 > 0.0
    assert report.rmsea2_lower > 0.0


def test_misspecification_shows_in_srmsr_as_well_as_the_test():
    """The effect-size index must move too, not only the significance test.

    A significant M2 at n = 4000 is expected of any misfit; SRMSR is what says
    whether the misfit is large enough to matter, so the two must agree in
    direction.
    """
    true = _guessing_test(20, guessing=0.35)
    data, _ = simulate(true, 3000, seed=557)

    correct = fit(data, ModelKey.THREE_PL, FAST)
    wrong = fit(data, ModelKey.TWO_PL, FAST)
    assert correct.converged and wrong.converged

    good = global_fit(data, correct.item_parameters)
    bad = global_fit(data, wrong.item_parameters)

    assert bad.srmsr > good.srmsr
    assert bad.statistic_over_df > good.statistic_over_df


def test_m2_star_is_used_and_calibrated_for_polytomous_items():
    """Ordinal items get the collapsed-category variant, named as such."""
    true = spread_parameters(ModelKey.GRM, 8, n_categories=4)
    statistics = []
    for seed in range(20, 28):
        data, _ = simulate(true, 2000, seed=seed)
        result = fit(data, ModelKey.GRM, FAST)
        assert result.converged
        report = global_fit(data, result.item_parameters)
        assert report.statistic_name == "M2*"
        # 8 items x 3 cuts univariate, 28 pairs x 9 cut combinations bivariate.
        assert report.n_moments == 8 * 3 + 28 * 9
        assert report.df == report.n_moments - report.n_free_parameters
        statistics.append(report.statistic)

    df = 8 * 3 + 28 * 9 - 8 * 4
    assert abs(float(np.mean(statistics)) - df) < 25.0, statistics


def test_rasch_is_evaluated_on_its_own_metric():
    """A Rasch fit's latent SD is a free parameter and must be carried in.

    Rasch fixes every slope at 1 and lets the latent variance float, so the
    moments have to be integrated against that variance and the variance has to
    count as a free parameter in the degrees of freedom.
    """
    true = spread_parameters(ModelKey.RASCH, 12)
    data, _ = simulate(true, 2000, seed=107, latent_sd=1.4)
    result = fit(data, ModelKey.RASCH, FAST)
    assert result.converged

    report = global_fit(data, result.item_parameters, latent_sd=result.latent_sd)

    # 12 difficulties plus the latent variance.
    assert report.n_free_parameters == 13 == result.n_free_parameters
    assert report.df == report.n_moments - 13
    assert report.p_value > 0.01
    assert report.srmsr < 0.03


def test_a_short_test_refuses_rather_than_reporting_a_degenerate_statistic():
    """With three binary items there are exactly as many moments as parameters."""
    true = spread_parameters(ModelKey.TWO_PL, 3)
    data, _ = simulate(true, 1000, seed=109)
    result = fit(data, ModelKey.TWO_PL, FAST)

    report = global_fit(data, result.item_parameters)

    assert report.statistic is None
    assert report.df is None
    assert report.rmsea2 is None
    assert "free parameters" in report.failure_reason


def test_small_samples_are_refused_not_approximated():
    true = spread_parameters(ModelKey.TWO_PL, 10)
    data, _ = simulate(true, 60, seed=111)
    result = fit(data, ModelKey.TWO_PL, FAST)
    if not result.converged:
        pytest.skip("fit did not converge at n=60, which is itself acceptable")

    report = global_fit(data, result.item_parameters)

    assert report.statistic is None
    assert "complete cases" in report.failure_reason


def test_missing_responses_are_dropped_and_declared():
    true = spread_parameters(ModelKey.TWO_PL, 12)
    data, _ = simulate(true, 2000, seed=113, missing_rate=0.05)
    result = fit(data, ModelKey.TWO_PL, FAST)

    report = global_fit(data, result.item_parameters)

    assert report.n_persons_used < data.n_persons
    assert any("no missing responses" in note for note in report.notes)


def test_no_fixed_cutoff_verdict_is_attached():
    """The result must carry values and caveats, never a pass/fail on a cutoff."""
    true = spread_parameters(ModelKey.TWO_PL, 12)
    data, _ = simulate(true, 1500, seed=115)
    result = fit(data, ModelKey.TWO_PL, FAST)

    report = global_fit(data, result.item_parameters)

    assert not hasattr(report, "acceptable")
    assert not hasattr(report, "flagged")
    assert not hasattr(report, "cfi")
    assert not hasattr(report, "tli")
    assert any("No fixed cutoff" in note for note in report.notes)
    assert any("unidimensional" in note for note in report.notes)


def test_rejects_mismatched_inputs():
    true = spread_parameters(ModelKey.TWO_PL, 10)
    data, _ = simulate(true, 500, seed=117)
    result = fit(data, ModelKey.TWO_PL, FAST)

    with pytest.raises(ValueError, match="for 10 columns"):
        global_fit(data, result.item_parameters[:4])
