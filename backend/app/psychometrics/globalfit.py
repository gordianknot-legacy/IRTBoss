"""
Limited-information global fit: M2 / M2*, RMSEA2 and SRMSR.

Full-information goodness of fit - Pearson X2 or the likelihood-ratio G2 over
the 2^J (or prod m_j) response patterns - has no usable reference distribution
for a test of any realistic length. With 20 binary items there are a million
cells and a few thousand respondents, so almost every cell is empty and the
asymptotic chi-square approximation is not merely imprecise, it is wrong in a
direction nobody can predict.

Maydeu-Olivares and Joe's M2 solves this by testing only the *low-order*
marginals: the univariate proportions and the bivariate cross-products. Those
are estimated from the whole sample rather than from a sparse cell, so their
sampling distribution is well behaved at realistic N. The statistic is the
quadratic form::

    M2 = N * e' C2 e,      C2 = Xi^-1 - Xi^-1 D (D' Xi^-1 D)^-1 D' Xi^-1

where ``e`` is the vector of residual moments (observed minus model-implied),
``D`` (Delta) is the Jacobian of the model-implied moments with respect to the
free parameters, and ``Xi`` is the asymptotic covariance of the moments. Under
the fitted model M2 is asymptotically chi-square with ``df = s - q``: number of
moments less number of free parameters.

This module computes C2 in its orthogonal-complement form,
``Dc (Dc' Xi Dc)^-1 Dc'`` with ``Dc`` spanning the null space of ``D'``. It is
algebraically identical and never inverts the full s-by-s ``Xi``, which for a
long polytomous test is the ill-conditioned matrix in the expression.

**Polytomous items get M2\\***, the collapsed-category variant (Cai & Hansen
2013): the moments are built from the cumulative dichotomisations
``1[X_j >= c]`` rather than from category indicators. For binary items every cut
is ``c = 1`` and M2* reduces exactly to M2, so one implementation serves both
and the reported name says which one it is.

**Why no CFI or TLI.** Both are ratios against a "null model", and there is no
defensible null for a limited-information categorical fit statistic. The
independence model that CFI uses in covariance-structure modelling is not
estimable in this framework without inventing a parameterisation for it, and
the resulting index would inherit whatever that invention implies. Published
work on M2-based incremental indices is thin and the cutoffs are borrowed
wholesale from continuous SEM, where they were derived. Reporting a number
whose reference point we made up would be worse than reporting nothing, so
CFI and TLI are omitted rather than approximated.

**Why no 0.06 / 0.08 / 0.95 verdicts.** Hu and Bentler's cutoffs were derived
from maximum-likelihood fit to continuous, normally distributed data in
covariance-structure models. They do not transfer here, and the failure is not
subtle:

* Population RMSEA2 *falls as items are added* at a constant degree of
  misspecification (Maydeu-Olivares 2014), so a fixed cutoff is implicitly a
  cutoff on test length. A 60-item test and a 12-item test with identical
  per-item misfit land on different sides of 0.05.
* The distribution of these indices under categorical, limited-information
  estimation differs from the continuous ML case that produced the conventions
  (Maydeu-Olivares & Joe 2014; Xia & Yang 2019).

So this module reports the statistic, its df, its p-value, RMSEA2 with a
confidence interval, and SRMSR - and attaches no verdict to any of them. SRMSR
is the index to lead with, because it is a plain average residual correlation
and carries no test-length dependence.

One more limitation the caller must carry forward: **M2 is insensitive to
within-item multidimensionality.** A large p-value here is not evidence of
unidimensionality and must never be reported as such.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import optimize, stats

from app.irt.em import MISSING, ResponseMatrix, _ParameterIndex
from app.irt.families import ItemParameters, ModelKey, SlopeMode, get_family

_FLOOR = 1e-12

# Central-difference step for the Delta matrix. The moments are smooth functions
# of the unconstrained parameters on an O(1) scale, so this sits far above
# cancellation noise and far below the curvature.
_H = 1e-4


@dataclass(frozen=True)
class GlobalFitResult:
    """Limited-information fit for one fitted model.

    ``statistic`` is ``None`` when the test could not be formed - too few
    moments for the number of parameters, or too few complete cases. The reason
    is in ``failure_reason``; nothing is reported as a fit figure in that case.
    """

    statistic_name: str                     # "M2" or "M2*"
    statistic: float | None
    df: int | None
    p_value: float | None

    n_moments: int
    n_free_parameters: int
    n_persons_used: int

    rmsea2: float | None
    rmsea2_lower: float | None
    rmsea2_upper: float | None
    rmsea2_confidence: float

    srmsr: float | None

    failure_reason: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def statistic_over_df(self) -> float | None:
        if self.statistic is None or not self.df:
            return None
        return self.statistic / self.df


def global_fit(
    data: ResponseMatrix,
    items: list[ItemParameters],
    *,
    latent_sd: float = 1.0,
    n_points: int = 61,
    bound: float = 6.0,
    confidence: float = 0.90,
) -> GlobalFitResult:
    """Compute M2 (binary) or M2* (ordinal) with RMSEA2 and SRMSR.

    ``latent_sd`` must be the value the estimator produced, not 1.0, whenever
    the fitted family let the latent variance float (Rasch, PCM). Passing 1.0
    for a Rasch fit puts the moments on a different metric from the parameters
    and every residual is then wrong.
    """
    if len(items) != data.n_items:
        raise ValueError(
            f"{len(items)} item parameter sets for {data.n_items} columns"
        )
    if not items:
        raise ValueError("no items to test")

    model = items[0].model
    if any(p.model is not model for p in items):
        raise ValueError("every item must come from the same fitted model")

    family = get_family(model)
    n_cat = np.asarray([p.n_categories for p in items], dtype=int)
    name = "M2" if int(n_cat.max()) == 2 else "M2*"

    notes: list[str] = []

    # A rest-of-sample moment cannot be formed from a partially observed
    # pattern without assuming why it is missing, so complete cases only.
    complete = (data.values != MISSING).all(axis=1)
    values = data.values[complete]
    n_used = int(values.shape[0])
    if n_used < data.n_persons:
        notes.append(
            f"{name} uses the {n_used} of {data.n_persons} respondents with no "
            "missing responses; a bivariate moment is undefined when either "
            "item is unanswered."
        )
    if n_used < 100:
        return _unavailable(
            name, 0, 0, n_used, confidence,
            f"only {n_used} complete cases; the asymptotic reference "
            "distribution is not usable below roughly 100",
            notes,
        )

    moments = _moment_index(n_cat)
    n_moments = len(moments)

    estimate_variance = family.slope_mode is SlopeMode.FIXED
    index = _ParameterIndex(family, n_cat, estimate_variance)
    q = index.n_free

    if n_moments - q < 1:
        return _unavailable(
            name, n_moments, q, n_used, confidence,
            f"{n_moments} low-order moments cannot test a model with {q} free "
            "parameters; the test needs more items",
            notes,
        )

    nodes = np.linspace(-bound, bound, n_points)
    templates = [family.from_natural(p) for p in items]
    vartheta = _pack(templates, index, latent_sd)

    def implied(vec: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        cum, weights = _model_state(family, vec, templates, index, n_cat, nodes)
        return _moment_values(cum, weights, moments), weights

    pi, weights = implied(vartheta)
    cum, _ = _model_state(family, vartheta, templates, index, n_cat, nodes)

    observed = _observed_moments(values, moments)
    residual = observed - pi

    delta = np.empty((n_moments, q), dtype=float)
    for t in range(q):
        forward = vartheta.copy()
        backward = vartheta.copy()
        forward[t] += _H
        backward[t] -= _H
        delta[:, t] = (implied(forward)[0] - implied(backward)[0]) / (2.0 * _H)

    xi = _moment_covariance(cum, weights, moments, pi)

    statistic, df, rank = _quadratic_form(residual, delta, xi, n_used)
    if statistic is None:
        return _unavailable(
            name, n_moments, q, n_used, confidence,
            "the moment covariance matrix is singular on the complement of the "
            "Jacobian, so the quadratic form has no stable value",
            notes,
        )
    if rank < q:
        notes.append(
            f"The Jacobian of the moments has rank {rank} against {q} free "
            "parameters, so some parameters are not locally identified from "
            "low-order moments. Degrees of freedom use the rank."
        )
    if df < 1:
        return _unavailable(
            name, n_moments, q, n_used, confidence,
            f"{df} degrees of freedom after accounting for estimated parameters",
            notes,
        )

    p_value = float(stats.chi2.sf(statistic, df))
    rmsea, low, high = _rmsea2(statistic, df, n_used, confidence)
    srmsr = _srmsr(values, cum, weights, n_cat)

    notes.append(
        "M2 is computed from univariate and bivariate margins only. It has no "
        "power against within-item multidimensionality, so a large p-value is "
        "not evidence that the test is unidimensional."
    )
    notes.append(
        "No fixed cutoff is applied to RMSEA2 or SRMSR. Population RMSEA2 "
        "falls as items are added at constant misspecification, so the .05/.06 "
        "conventions are implicitly conventions about test length."
    )

    return GlobalFitResult(
        statistic_name=name,
        statistic=float(statistic),
        df=int(df),
        p_value=p_value,
        n_moments=n_moments,
        n_free_parameters=q,
        n_persons_used=n_used,
        rmsea2=rmsea,
        rmsea2_lower=low,
        rmsea2_upper=high,
        rmsea2_confidence=confidence,
        srmsr=srmsr,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Moments
# --------------------------------------------------------------------------- #

# A moment is a set of (item, cut) constraints; its value is the probability
# that every constraint 1[X_item >= cut] holds simultaneously. Univariate
# moments carry one constraint, bivariate moments two.
_Moment = tuple[tuple[int, int], ...]


def _moment_index(n_cat: np.ndarray) -> list[_Moment]:
    """Every univariate and bivariate cumulative moment, in a fixed order."""
    n_items = int(n_cat.size)
    moments: list[_Moment] = []
    for j in range(n_items):
        for c in range(1, int(n_cat[j])):
            moments.append(((j, c),))
    for j in range(n_items):
        for k in range(j + 1, n_items):
            for c in range(1, int(n_cat[j])):
                for d in range(1, int(n_cat[k])):
                    moments.append(((j, c), (k, d)))
    return moments


def _cumulative(
    family, u: list[np.ndarray], n_cat: np.ndarray, nodes: np.ndarray
) -> list[np.ndarray]:
    """``Q[j][:, c-1] = P(X_j >= c | theta)`` at every quadrature node."""
    out: list[np.ndarray] = []
    for j, vec in enumerate(u):
        m = int(n_cat[j])
        probs = family.probabilities(nodes, vec, m)
        # Reverse cumulative sum, dropping category 0 whose cut is trivially 1.
        tail = np.cumsum(probs[:, ::-1], axis=1)[:, ::-1]
        out.append(np.clip(tail[:, 1:], _FLOOR, 1.0))
    return out


def _model_state(
    family,
    vartheta: np.ndarray,
    templates: list[np.ndarray],
    index: _ParameterIndex,
    n_cat: np.ndarray,
    nodes: np.ndarray,
) -> tuple[list[np.ndarray], np.ndarray]:
    """Cumulative response probabilities and the latent weights, for one parameter vector."""
    u, sd = _unpack(vartheta, templates, index)
    weights = np.exp(-0.5 * (nodes / sd) ** 2)
    weights = weights / weights.sum()
    return _cumulative(family, u, n_cat, nodes), weights


def _node_products(cum: list[np.ndarray], moments: list[_Moment]) -> np.ndarray:
    """``A[i, k]`` = probability of moment ``i`` conditional on node ``k``."""
    n_nodes = cum[0].shape[0]
    out = np.ones((len(moments), n_nodes), dtype=float)
    for i, moment in enumerate(moments):
        for j, c in moment:
            out[i] *= cum[j][:, c - 1]
    return out


def _moment_values(
    cum: list[np.ndarray], weights: np.ndarray, moments: list[_Moment]
) -> np.ndarray:
    return _node_products(cum, moments) @ weights


def _observed_moments(values: np.ndarray, moments: list[_Moment]) -> np.ndarray:
    """Sample proportions for each moment, from complete cases."""
    n = values.shape[0]
    out = np.empty(len(moments), dtype=float)
    for i, moment in enumerate(moments):
        hit = np.ones(n, dtype=bool)
        for j, c in moment:
            hit &= values[:, j] >= c
        out[i] = hit.sum() / n
    return out


def _moment_covariance(
    cum: list[np.ndarray],
    weights: np.ndarray,
    moments: list[_Moment],
    pi: np.ndarray,
) -> np.ndarray:
    """Asymptotic covariance of the sample moments under the fitted model.

    ``Cov(T_a, T_b) = E[T_a T_b] - pi_a pi_b``, and because every T is an
    indicator, ``T_a T_b`` is the indicator of the *merged* constraint set -
    two cuts on the same item collapse to the stricter one. Merged moments are
    therefore not simply products of the two node-probability rows, which is
    why the disjoint case is done as one matmul and the overlapping pairs are
    corrected individually.
    """
    products = _node_products(cum, moments)
    joint = (products * weights[None, :]) @ products.T

    constraint = [dict(m) for m in moments]
    for a, ca in enumerate(constraint):
        for b in range(a, len(constraint)):
            cb = constraint[b]
            if not (ca.keys() & cb.keys()):
                continue
            merged = dict(ca)
            for j, c in cb.items():
                merged[j] = max(merged.get(j, 0), c)
            value = weights.copy()
            for j, c in merged.items():
                value = value * cum[j][:, c - 1]
            total = float(value.sum())
            joint[a, b] = total
            joint[b, a] = total

    return joint - np.outer(pi, pi)


# --------------------------------------------------------------------------- #
# The quadratic form
# --------------------------------------------------------------------------- #


def _quadratic_form(
    residual: np.ndarray, delta: np.ndarray, xi: np.ndarray, n: int
) -> tuple[float | None, int, int]:
    """``N e' Dc (Dc' Xi Dc)^-1 Dc' e`` with ``Dc`` spanning the null space of ``D'``.

    Equivalent to the textbook ``C2`` expression but inverts an
    ``(s - q) x (s - q)`` matrix instead of the full ``s x s`` ``Xi``, which for
    a long test is the badly conditioned one.
    """
    left, singular, _ = np.linalg.svd(delta, full_matrices=True)
    tolerance = max(delta.shape) * float(singular[0]) * np.finfo(float).eps
    rank = int((singular > tolerance).sum())

    complement = left[:, rank:]
    if complement.shape[1] == 0:
        return None, 0, rank

    middle = complement.T @ xi @ complement
    projected = complement.T @ residual
    try:
        solved = np.linalg.solve(middle, projected)
    except np.linalg.LinAlgError:
        return None, complement.shape[1], rank

    statistic = float(n) * float(projected @ solved)
    if not np.isfinite(statistic) or statistic < 0:
        return None, complement.shape[1], rank
    return statistic, complement.shape[1], rank


# --------------------------------------------------------------------------- #
# Derived indices
# --------------------------------------------------------------------------- #


def _rmsea2(
    statistic: float, df: int, n: int, confidence: float
) -> tuple[float, float, float]:
    """RMSEA2 and its confidence interval from the noncentral chi-square.

    The interval inverts the noncentral chi-square: the bounds are the
    noncentrality parameters that would place the observed statistic at the
    tails of their own distributions. This is the only honest way to report
    RMSEA2, because a point estimate alone hides that at n = 500 the interval
    routinely spans "excellent" and "unacceptable" under any convention.
    """
    scale = float(df) * float(n - 1)
    point = np.sqrt(max(statistic - df, 0.0) / scale)

    alpha = 1.0 - confidence
    lower_lambda = _noncentrality(statistic, df, 1.0 - alpha / 2.0)
    upper_lambda = _noncentrality(statistic, df, alpha / 2.0)
    return (
        float(point),
        float(np.sqrt(lower_lambda / scale)),
        float(np.sqrt(upper_lambda / scale)),
    )


def _noncentrality(statistic: float, df: int, target_sf: float) -> float:
    """Smallest ``lambda >= 0`` with ``P(chi2(df, lambda) > statistic) = target``."""
    if float(stats.ncx2.sf(statistic, df, _FLOOR)) >= target_sf:
        return 0.0

    high = max(statistic, 1.0)
    for _ in range(60):
        if float(stats.ncx2.sf(statistic, df, high)) >= target_sf:
            break
        high *= 2.0
    else:
        return high

    return float(
        optimize.brentq(
            lambda lam: float(stats.ncx2.sf(statistic, df, lam)) - target_sf,
            0.0,
            high,
            xtol=1e-8,
        )
    )


def _srmsr(
    values: np.ndarray,
    cum: list[np.ndarray],
    weights: np.ndarray,
    n_cat: np.ndarray,
) -> float | None:
    """Standardised root mean square residual over the item-pair correlations.

    SRMSR averages squared differences between observed and model-implied
    *correlations*, so it is on the correlation scale and reads as "the typical
    amount by which the model misses an item pair's association". Unlike
    RMSEA2 it does not shrink as items are added, which is why it is the index
    to quote when test lengths differ.
    """
    n_items = int(n_cat.size)
    if n_items < 2:
        return None

    scores = [np.arange(int(m), dtype=float) for m in n_cat]

    # Conditional first and second moments of the item score at each node,
    # rebuilt from the cumulative form: E[X | theta] = sum_c P(X >= c | theta).
    mean_by_node = []
    second_by_node = []
    for j in range(n_items):
        q = cum[j]
        mean_by_node.append(q.sum(axis=1))
        # E[X^2] = sum_c (2c - 1) P(X >= c)
        coefficients = 2.0 * np.arange(1, int(n_cat[j])) - 1.0
        second_by_node.append(q @ coefficients)

    model_mean = np.array([weights @ m for m in mean_by_node])
    model_second = np.array([weights @ s for s in second_by_node])
    model_var = np.clip(model_second - model_mean**2, _FLOOR, None)

    observed = values.astype(float)

    total = 0.0
    pairs = 0
    for j in range(n_items):
        for k in range(j + 1, n_items):
            # Local independence: E[X_j X_k] = E_theta[E[X_j|theta] E[X_k|theta]]
            cross = float(weights @ (mean_by_node[j] * mean_by_node[k]))
            model_r = (cross - model_mean[j] * model_mean[k]) / np.sqrt(
                model_var[j] * model_var[k]
            )
            sd_j = observed[:, j].std()
            sd_k = observed[:, k].std()
            if sd_j < 1e-9 or sd_k < 1e-9:
                continue
            observed_r = float(
                np.corrcoef(observed[:, j], observed[:, k])[0, 1]
            )
            total += (observed_r - model_r) ** 2
            pairs += 1

    if pairs == 0:
        return None
    del scores
    return float(np.sqrt(total / pairs))


# --------------------------------------------------------------------------- #
# Free-parameter packing
# --------------------------------------------------------------------------- #

# The Jacobian must be taken with respect to exactly the parameters the
# estimator held free - one shared slope for the 1PL, none for Rasch, plus the
# latent variance where the family lets it float. Re-deriving that mapping here
# would create a second source of truth that could silently drift from the
# estimator's, so the estimator's own index is reused.


def _pack(
    templates: list[np.ndarray], index: _ParameterIndex, latent_sd: float
) -> np.ndarray:
    vec = np.zeros(index.n_free, dtype=float)
    for j, slots in enumerate(index.slots):
        for t, slot in enumerate(slots):
            if slot is not None:
                vec[slot] = templates[j][t]
    if index.variance_index is not None:
        vec[index.variance_index] = float(np.log(max(latent_sd, 1e-6)))
    return vec


def _unpack(
    vec: np.ndarray, templates: list[np.ndarray], index: _ParameterIndex
) -> tuple[list[np.ndarray], float]:
    u = [t.copy() for t in templates]
    for j, slots in enumerate(index.slots):
        for t, slot in enumerate(slots):
            if slot is None:
                u[j][t] = 0.0          # slope pinned at a = 1
            else:
                u[j][t] = vec[slot]
    sd = 1.0
    if index.variance_index is not None:
        sd = float(np.exp(vec[index.variance_index]))
    return u, sd


def _unavailable(
    name: str,
    n_moments: int,
    q: int,
    n_used: int,
    confidence: float,
    reason: str,
    notes: list[str],
) -> GlobalFitResult:
    return GlobalFitResult(
        statistic_name=name,
        statistic=None,
        df=None,
        p_value=None,
        n_moments=n_moments,
        n_free_parameters=q,
        n_persons_used=n_used,
        rmsea2=None,
        rmsea2_lower=None,
        rmsea2_upper=None,
        rmsea2_confidence=confidence,
        srmsr=None,
        failure_reason=reason,
        notes=notes,
    )


__all__ = ["GlobalFitResult", "global_fit"]
