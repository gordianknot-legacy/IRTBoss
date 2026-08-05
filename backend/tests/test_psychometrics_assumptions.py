"""
Tests for the unidimensionality and local-independence checks.

Both assumptions are tested in both directions, because a diagnostic that always
fires is as useless as one that never does. Dimensionality is checked against
data generated with one factor and against data generated with two correlated
factors; local dependence is checked against clean data and against data with a
pair whose dependence was deliberately manufactured.

The polychoric correlation is checked against a known quantity rather than
against another implementation: bivariate normal data with a chosen correlation
is discretised, and the estimator has to recover the correlation of the
underlying continuous variables, not of the categories.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.irt.em import MISSING, ResponseMatrix, fit
from app.irt.families import ModelKey
from app.irt.simulate import simulate, spread_parameters
from app.psychometrics.assumptions import (
    _bvn_cdf,
    bifactor_approximation,
    local_independence,
    polychoric_correlation,
    polychoric_matrix,
    unidimensionality,
    velicer_map,
)

# Replication counts are kept low enough that the whole module runs in well
# under two minutes. Every one of them is above the point where the assertions
# below become unstable, which was checked by raising them.
BOOTSTRAP = 100
PARALLEL_ITERATIONS = 40


# --------------------------------------------------------------------------- #
# Data generators
# --------------------------------------------------------------------------- #


def _two_factor_binary(
    n_persons: int = 1200,
    n_items: int = 16,
    factor_correlation: float = 0.3,
    seed: int = 7,
) -> ResponseMatrix:
    """Binary responses from two correlated traits, first half on each.

    The factors correlate at 0.3, which is low enough to be genuinely
    two-dimensional and high enough that a naive unidimensional fit would still
    look plausible - the case a dimensionality check has to earn its place on.
    """
    rng = np.random.default_rng(seed)
    covariance = [[1.0, factor_correlation], [factor_correlation, 1.0]]
    theta = rng.multivariate_normal([0.0, 0.0], covariance, size=n_persons)

    a = rng.uniform(1.2, 2.0, size=n_items)
    b = np.linspace(-1.5, 1.5, n_items)
    half = n_items // 2

    values = np.empty((n_persons, n_items), dtype=np.int16)
    for j in range(n_items):
        trait = theta[:, 0] if j < half else theta[:, 1]
        p = 1.0 / (1.0 + np.exp(-a[j] * (trait - b[j])))
        values[:, j] = (rng.random(n_persons) < p).astype(np.int16)

    return ResponseMatrix(
        values=values,
        item_ids=[f"item_{j + 1:02d}" for j in range(n_items)],
        n_categories=np.full(n_items, 2, dtype=int),
    )


def _with_dependent_pair(
    data: ResponseMatrix, a: int, b: int, probability: float, seed: int
) -> ResponseMatrix:
    """Copy item ``a``'s response into item ``b`` for most respondents."""
    rng = np.random.default_rng(seed)
    values = data.values.copy()
    copied = rng.random(values.shape[0]) < probability
    values[copied, b] = values[copied, a]
    return ResponseMatrix(
        values=values,
        item_ids=list(data.item_ids),
        n_categories=data.n_categories,
    )


# --------------------------------------------------------------------------- #
# Bivariate normal and polychoric correlation
# --------------------------------------------------------------------------- #


def test_bivariate_normal_cdf_matches_scipy():
    """The Gauss-Legendre CDF must agree with an independent implementation."""
    from scipy.stats import multivariate_normal

    for rho in (-0.9, -0.4, 0.0, 0.25, 0.7, 0.95):
        for h, k in ((0.0, 0.0), (0.3, -0.5), (1.8, 2.2), (-2.5, 0.1)):
            ours = float(
                _bvn_cdf(np.array([[h]]), np.array([[k]]), rho)[0, 0]
            )
            theirs = float(
                multivariate_normal.cdf(
                    [h, k], mean=[0, 0], cov=[[1.0, rho], [rho, 1.0]]
                )
            )
            assert ours == pytest.approx(theirs, abs=1e-9)


@pytest.mark.parametrize("true_rho", [-0.6, -0.2, 0.0, 0.35, 0.7])
def test_polychoric_recovers_the_latent_correlation(true_rho):
    """Discretising a bivariate normal must not change the estimated correlation.

    This is the property that distinguishes the polychoric from the Pearson
    correlation. The cut points are deliberately asymmetric so that a Pearson
    correlation of the categories would be visibly attenuated.
    """
    rng = np.random.default_rng(2024)
    z = rng.multivariate_normal(
        [0.0, 0.0], [[1.0, true_rho], [true_rho, 1.0]], size=20000
    )
    x = (z[:, 0] > 0.4).astype(np.int16)                       # binary, skewed
    y = np.digitize(z[:, 1], [-0.7, 0.2, 1.1]).astype(np.int16)  # 4 categories

    estimate = polychoric_correlation(x, y, 2, 4)
    assert estimate == pytest.approx(true_rho, abs=0.03)

    if abs(true_rho) > 0.3:
        pearson = float(np.corrcoef(x, y)[0, 1])
        assert abs(pearson) < abs(true_rho) - 0.05


def test_polychoric_matrix_is_symmetric_with_unit_diagonal():
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 8), 800, seed=31)
    result = polychoric_matrix(data)

    assert result.matrix.shape == (8, 8)
    np.testing.assert_allclose(np.diag(result.matrix), 1.0)
    np.testing.assert_allclose(result.matrix, result.matrix.T, atol=1e-12)
    assert result.min_pair_n == data.n_persons
    assert (np.abs(result.matrix) <= 1.0).all()


def test_polychoric_uses_pairwise_complete_observations():
    """Missing responses reduce a pair's sample size without dropping the pair."""
    data, _ = simulate(
        spread_parameters(ModelKey.TWO_PL, 8), 800, seed=37, missing_rate=0.15
    )
    result = polychoric_matrix(data)

    assert (data.values == MISSING).any()
    assert result.min_pair_n < data.n_persons
    assert np.isfinite(result.matrix).all()


def test_constant_item_is_reported_not_silently_correlated():
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 6), 400, seed=41)
    values = data.values.copy()
    values[:, 2] = 1                        # nobody varies on this item
    flat = ResponseMatrix(
        values=values, item_ids=data.item_ids, n_categories=data.n_categories
    )

    result = polychoric_matrix(flat)

    assert (result.matrix[2, [0, 1, 3, 4, 5]] == 0.0).all()
    assert any("no usable joint information" in n for n in result.notes)


# --------------------------------------------------------------------------- #
# Dimensionality
# --------------------------------------------------------------------------- #


def test_unidimensional_data_retains_one_factor():
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 16), 1200, seed=11)

    report = unidimensionality(data, n_iterations=PARALLEL_ITERATIONS, seed=5)

    assert report.n_factors_parallel == 1
    assert report.n_factors_map == 1
    assert report.explained_common_variance > 0.90
    assert report.omega_hierarchical > 0.80
    assert report.essentially_unidimensional is True

    # The first eigenvalue must clear its reference by a wide margin and the
    # second must fail: a marginal call here would make the test flaky for
    # reasons unrelated to the code.
    rows = report.parallel.eigenvalues
    assert rows[0].observed > 2.0 * rows[0].random_p95
    assert rows[1].observed < rows[1].random_p95


def test_two_factor_data_retains_two_factors():
    data = _two_factor_binary()

    report = unidimensionality(data, n_iterations=PARALLEL_ITERATIONS, seed=5)

    assert report.n_factors_parallel == 2
    assert report.n_factors_map == 2
    assert report.explained_common_variance < 0.80
    assert report.essentially_unidimensional is False

    # The clustering must recover the blocks the data was built from, up to the
    # arbitrary labelling of the two group factors.
    assignment = report.bifactor.group_assignment
    first, second = assignment[:8], assignment[8:]
    assert len(set(first.tolist())) == 1
    assert len(set(second.tolist())) == 1
    assert first[0] != second[0]

    # Eight items in each of two groups out of 16: 56 within-group pairs of 120.
    assert report.percent_uncontaminated == pytest.approx(1.0 - 56 / 120)


def test_parallel_analysis_table_is_complete_and_ordered():
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 10), 900, seed=13)

    report = unidimensionality(data, n_iterations=PARALLEL_ITERATIONS, seed=5)
    rows = report.parallel.eigenvalues

    assert len(rows) == 10
    assert [r.component for r in rows] == list(range(1, 11))
    observed = [r.observed for r in rows]
    assert observed == sorted(observed, reverse=True)
    # Retention is the leading run, so no gap of retained/not/retained.
    retained = [r.retained for r in rows]
    assert retained == sorted(retained, reverse=True)
    assert sum(retained) == report.n_factors_parallel


def test_map_minimum_is_a_genuine_minimum():
    data = _two_factor_binary()
    matrix = polychoric_matrix(data).matrix

    result = velicer_map(matrix)

    assert result.n_components_squared == 2
    assert result.average_squared[2] == pytest.approx(min(result.average_squared))
    # The curve must fall to the minimum and rise afterwards; a monotone series
    # would mean the partialling is not doing what it claims.
    assert result.average_squared[0] > result.average_squared[2]
    assert result.average_squared[3] > result.average_squared[2]
    assert len(result.average_fourth) == len(result.average_squared)


def test_ecv_is_one_when_no_group_factors_are_modelled():
    """The first-factor-only case must be labelled, not passed off as bifactor."""
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 12), 800, seed=17)
    matrix = polychoric_matrix(data).matrix

    result = bifactor_approximation(matrix, n_group_factors=0)

    assert result.ecv == pytest.approx(1.0)
    assert result.puc == pytest.approx(1.0)
    assert result.omega_hierarchical == pytest.approx(result.omega_total)
    assert any("No group factors were requested" in n for n in result.notes)
    assert any("approximation to a bifactor pattern" in n for n in result.notes)


def test_bifactor_approximation_declares_its_limits():
    data = _two_factor_binary()
    matrix = polychoric_matrix(data).matrix

    result = bifactor_approximation(matrix, n_group_factors=2)

    assert 0.0 < result.ecv < 1.0
    assert 0.0 < result.omega_hierarchical < result.omega_total <= 1.0
    assert result.general_loadings.shape == (16,)
    assert (result.general_loadings > 0).all()
    assert any("not from a fitted bifactor" in n for n in result.notes)


def test_unidimensionality_notes_never_claim_construct_validity_is_settled():
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 12), 700, seed=19)

    report = unidimensionality(data, n_iterations=PARALLEL_ITERATIONS, seed=5)

    assert any("not construct validity" in n for n in report.notes)
    assert report.parallel.notes
    assert report.map_test.notes
    assert report.bifactor.notes


def test_too_few_items_is_refused():
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 2), 300, seed=23)
    with pytest.raises(ValueError, match="at least 3 items"):
        unidimensionality(data, n_iterations=5)


# --------------------------------------------------------------------------- #
# Local independence
# --------------------------------------------------------------------------- #


def test_clean_data_raises_no_local_dependence_flags():
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 15), 1000, seed=21)
    result = fit(data, ModelKey.TWO_PL)
    assert result.converged

    report = local_independence(
        data, result.item_parameters, n_bootstrap=BOOTSTRAP, seed=4
    )

    assert report.flagged == []
    assert len(report.pairs) == 15 * 14 // 2
    assert report.critical_value is not None and report.critical_value > 0


def test_manufactured_dependence_is_flagged():
    """An item copying its neighbour must be caught, and be the worst pair."""
    base, _ = simulate(spread_parameters(ModelKey.TWO_PL, 15), 1000, seed=21)
    data = _with_dependent_pair(base, a=3, b=4, probability=0.85, seed=99)

    result = fit(data, ModelKey.TWO_PL)
    assert result.converged

    report = local_independence(
        data, result.item_parameters, n_bootstrap=BOOTSTRAP, seed=4
    )

    flagged = {(p.index_a, p.index_b) for p in report.flagged}
    assert (3, 4) in flagged

    worst = max(report.pairs, key=lambda p: abs(p.q3_star))
    assert (worst.index_a, worst.index_b) == (3, 4)
    assert worst.q3_star > 0.5
    # Chen-Thissen must agree, and must sign the excess association positively.
    assert worst.ld_signed_z is not None and worst.ld_signed_z > 10

    # The contamination of theta by one dominant pair is a documented effect,
    # and the report has to say so rather than let the reader chase the
    # collateral flags.
    assert any("distort the theta estimates" in n for n in report.notes)


def test_the_q3_cutoff_is_empirical_and_length_dependent():
    """Short and long tests must not share a critical value.

    This is the property the fixed 0.2 rule gets wrong. The bootstrap null has to
    reproduce it: with fewer items the maximum of a smaller set of Q3* values is
    smaller, but each is noisier, and the two effects do not cancel.
    """
    critical = {}
    for n_items in (8, 24):
        data, _ = simulate(
            spread_parameters(ModelKey.TWO_PL, n_items), 800, seed=53
        )
        result = fit(data, ModelKey.TWO_PL)
        assert result.converged
        report = local_independence(
            data, result.item_parameters, n_bootstrap=BOOTSTRAP, seed=4
        )
        critical[n_items] = report.critical_value
        assert any("critical value is empirical" in n for n in report.notes)

    assert critical[8] != pytest.approx(critical[24], abs=0.01)


def test_q3_star_removes_the_structural_negative_bias():
    """Q3 has a mean near -1/(J-1); Q3* must have a mean of zero."""
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 20), 1500, seed=59)
    result = fit(data, ModelKey.TWO_PL)

    report = local_independence(
        data, result.item_parameters, n_bootstrap=10, seed=4
    )

    assert report.q3_mean < 0
    assert report.q3_mean == pytest.approx(-1.0 / 19, abs=0.04)

    off_diagonal = [p.q3_star for p in report.pairs]
    assert np.mean(off_diagonal) == pytest.approx(0.0, abs=1e-10)


def test_bootstrap_can_be_declined_without_inventing_a_cutoff():
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 10), 500, seed=61)
    result = fit(data, ModelKey.TWO_PL)

    report = local_independence(
        data, result.item_parameters, n_bootstrap=0, seed=4
    )

    assert report.critical_value is None
    assert report.flagged == []
    assert any("no pair can be flagged" in n for n in report.notes)
    # Q3* is still reported; only the decision rule is withheld.
    assert all(np.isfinite(p.q3_star) for p in report.pairs)


def test_local_independence_is_reproducible_from_its_seed():
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 10), 600, seed=67)
    result = fit(data, ModelKey.TWO_PL)

    first = local_independence(data, result.item_parameters, n_bootstrap=25, seed=8)
    second = local_independence(data, result.item_parameters, n_bootstrap=25, seed=8)

    assert first.critical_value == second.critical_value


def test_local_independence_rejects_mismatched_parameters():
    data, _ = simulate(spread_parameters(ModelKey.TWO_PL, 10), 400, seed=71)
    result = fit(data, ModelKey.TWO_PL)

    with pytest.raises(ValueError, match="for 10 columns"):
        local_independence(data, result.item_parameters[:4], n_bootstrap=5)


def test_polytomous_local_independence_runs():
    """Q3 and LD X2 must generalise past binary items."""
    data, _ = simulate(
        spread_parameters(ModelKey.GRM, 10, n_categories=4), 1000, seed=73
    )
    result = fit(data, ModelKey.GRM)
    assert result.converged

    report = local_independence(
        data, result.item_parameters, n_bootstrap=25, seed=4
    )

    assert len(report.pairs) == 45
    assert all(p.ld_df == 9 for p in report.pairs)
    assert report.flagged == []
