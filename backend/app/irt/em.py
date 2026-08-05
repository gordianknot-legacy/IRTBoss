"""
Marginal maximum likelihood estimation by the Bock-Aitkin EM algorithm.

The latent trait is integrated out over a fixed Gauss-Hermite-style grid, which
turns an intractable marginal likelihood into a weighted sum. Each EM cycle:

* **E-step** - compute each response pattern's posterior over the grid, and
  accumulate the expected number of respondents at each node who chose each
  category of each item (the ``r`` accumulators).
* **M-step** - with those expected counts held fixed, items become independent,
  so each item's parameters are found by its own small optimisation.

Two properties of this implementation are worth stating explicitly because the
implementation it replaces got both wrong:

1. **Non-convergence is terminal.** If the algorithm does not converge, the
   result says so and carries no parameters. It is never downgraded to a
   warning that no caller reads.
2. **Missing responses are skipped per cell, not imputed.** A respondent who
   skipped item 7 contributes to every other item's accumulators and to their
   own posterior, which is full-information maximum likelihood behaviour and
   requires no substitution of invented data.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np
from scipy import optimize

from .families import (
    ItemFamily,
    ItemParameters,
    ModelKey,
    SlopeMode,
    get_family,
)

logger = logging.getLogger(__name__)

MISSING = -1
"""Sentinel for a missing response in a :class:`ResponseMatrix`."""


@dataclass(frozen=True)
class ResponseMatrix:
    """Scored responses, already validated and recoded to 0-based categories.

    ``values`` holds integers in ``[0, n_categories[j])`` with :data:`MISSING`
    for absent responses. Recoding to 0-based happens upstream, in validation,
    so the estimator never has to guess what a response code means.
    """

    values: np.ndarray          # int16, (n_persons, n_items)
    item_ids: list[str]
    n_categories: np.ndarray    # int, (n_items,)

    def __post_init__(self) -> None:
        if self.values.ndim != 2:
            raise ValueError("response values must be a 2-D array")
        if len(self.item_ids) != self.values.shape[1]:
            raise ValueError(
                f"{len(self.item_ids)} item ids for {self.values.shape[1]} columns"
            )
        if self.n_categories.shape[0] != self.values.shape[1]:
            raise ValueError("n_categories must have one entry per item")

    @property
    def n_persons(self) -> int:
        return int(self.values.shape[0])

    @property
    def n_items(self) -> int:
        return int(self.values.shape[1])

    @property
    def is_polytomous(self) -> bool:
        return bool((self.n_categories > 2).any())


@dataclass(frozen=True)
class Quadrature:
    """Fixed grid over the latent trait, with normal weights."""

    nodes: np.ndarray
    weights: np.ndarray

    @classmethod
    def normal(cls, n_points: int = 61, bound: float = 6.0) -> Quadrature:
        """Equally spaced grid with standard normal weights.

        A rectangular grid with normal weights is used rather than true
        Gauss-Hermite nodes because the accumulators in the E-step are indexed
        by node, and a fixed evenly spaced grid keeps every downstream
        quantity - information curves, EAP scores, conditional SEs - on the
        same nodes as the fit. 61 points over +/-6 SD is dense enough that the
        quadrature error is far below the sampling error of any real dataset.
        """
        nodes = np.linspace(-bound, bound, n_points)
        weights = np.exp(-0.5 * nodes**2)
        weights /= weights.sum()
        return cls(nodes=nodes, weights=weights)

    def reweight(self, sd: float) -> np.ndarray:
        """Weights for a N(0, sd^2) latent distribution on the same nodes."""
        w = np.exp(-0.5 * (self.nodes / sd) ** 2)
        return w / w.sum()

    @property
    def n_points(self) -> int:
        return int(self.nodes.size)


@dataclass
class EMOptions:
    """Estimation controls. Defaults are the supported configuration."""

    max_cycles: int = 500
    tolerance: float = 1e-4
    quadrature_points: int = 61
    quadrature_bound: float = 6.0
    m_step_max_iter: int = 60
    compute_standard_errors: bool = True
    seed: int = 20260803


@dataclass
class FitResult:
    """Outcome of one model fit.

    ``converged`` is the gate for everything downstream. When it is ``False``,
    ``item_parameters`` is empty and the fit statistics are ``None`` - there is
    no partial-credit path where unconverged estimates leak into a report.
    """

    model: ModelKey
    converged: bool
    n_cycles: int
    elapsed_seconds: float

    item_parameters: list[ItemParameters] = field(default_factory=list)
    log_likelihood: float | None = None
    n_free_parameters: int | None = None
    n_persons: int | None = None
    latent_sd: float = 1.0
    quadrature: Quadrature | None = None
    failure_reason: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def aic(self) -> float | None:
        if self.log_likelihood is None or self.n_free_parameters is None:
            return None
        return -2.0 * self.log_likelihood + 2.0 * self.n_free_parameters

    @property
    def bic(self) -> float | None:
        if (
            self.log_likelihood is None
            or self.n_free_parameters is None
            or not self.n_persons
        ):
            return None
        return -2.0 * self.log_likelihood + self.n_free_parameters * np.log(
            self.n_persons
        )


class _ParameterIndex:
    """Maps each item's local parameter slots onto the global free-parameter vector.

    The mapping is what lets one estimator serve three different slope regimes.
    A slot resolves to ``None`` when the slope is fixed at 1 (Rasch, PCM), to a
    single shared index for every item when the slope is common (1PL), and to a
    distinct index per item otherwise.
    """

    def __init__(
        self,
        family: ItemFamily,
        n_categories: np.ndarray,
        estimate_variance: bool,
    ) -> None:
        self.slots: list[list[int | None]] = []
        cursor = 0
        shared_slope_index: int | None = None

        if family.slope_mode is SlopeMode.SHARED:
            shared_slope_index = cursor
            cursor += 1

        for n_cat in n_categories:
            n_local = family.n_params(int(n_cat))
            row: list[int | None] = []
            for t in range(n_local):
                if t == 0:
                    if family.slope_mode is SlopeMode.FIXED:
                        row.append(None)
                    elif family.slope_mode is SlopeMode.SHARED:
                        row.append(shared_slope_index)
                    else:
                        row.append(cursor)
                        cursor += 1
                else:
                    row.append(cursor)
                    cursor += 1
            self.slots.append(row)

        self.n_item_parameters = cursor
        self.variance_index = cursor if estimate_variance else None
        self.n_free = cursor + (1 if estimate_variance else 0)


def fit(
    data: ResponseMatrix,
    model: ModelKey | str,
    options: EMOptions | None = None,
) -> FitResult:
    """Fit one IRT model by marginal maximum likelihood.

    Raises ``ValueError`` for a model/data mismatch (a dichotomous model on
    polytomous data, for example) rather than fitting something meaningless.
    """
    options = options or EMOptions()
    model = ModelKey(model) if isinstance(model, str) else model
    family = get_family(model)
    started = time.perf_counter()

    _check_model_applies(data, model)

    quad = Quadrature.normal(options.quadrature_points, options.quadrature_bound)
    theta = quad.nodes
    n_items = data.n_items
    n_cat = data.n_categories.astype(int)

    estimate_variance = family.slope_mode is SlopeMode.FIXED
    index = _ParameterIndex(family, n_cat, estimate_variance)

    patterns, pattern_counts = _compress(data.values)
    n_pat = patterns.shape[0]

    # Starting values from each item's own observed responses.
    u = []
    for j in range(n_items):
        observed = data.values[:, j]
        observed = observed[observed != MISSING]
        if observed.size == 0:
            return _failed(
                model, started, f"item '{data.item_ids[j]}' has no observed responses"
            )
        u.append(family.initial(observed.astype(float), int(n_cat[j])))

    latent_sd = 1.0
    prior = quad.weights.copy()
    log_likelihood = -np.inf
    converged = False
    cycles = 0
    notes: list[str] = []

    for cycle in range(1, options.max_cycles + 1):
        cycles = cycle

        log_probs = [
            family.log_probabilities(theta, u[j], int(n_cat[j])) for j in range(n_items)
        ]
        pattern_ll = _pattern_loglik(patterns, log_probs)

        joint = pattern_ll + np.log(np.clip(prior, 1e-300, None))[None, :]
        peak = joint.max(axis=1, keepdims=True)
        lse = peak[:, 0] + np.log(np.exp(joint - peak).sum(axis=1))
        new_ll = float(np.dot(pattern_counts, lse))

        posterior = np.exp(joint - lse[:, None])
        weighted_posterior = pattern_counts[:, None] * posterior

        r = _accumulate(patterns, weighted_posterior, n_cat)

        previous = np.concatenate([np.asarray(v, dtype=float) for v in u])
        u = _m_step(family, u, r, theta, n_cat, index, options)
        current = np.concatenate([np.asarray(v, dtype=float) for v in u])

        if estimate_variance:
            node_mass = weighted_posterior.sum(axis=0)
            total = node_mass.sum()
            variance = float(np.dot(node_mass, theta**2) / total)
            latent_sd = float(np.sqrt(max(variance, 1e-6)))
            prior = quad.reweight(latent_sd)

        shift = float(np.max(np.abs(current - previous)))
        ll_gain = new_ll - log_likelihood
        log_likelihood = new_ll

        if shift < options.tolerance:
            converged = True
            break
        if cycle > 1 and abs(ll_gain) < 1e-9:
            converged = True
            notes.append(
                "Converged on log-likelihood change; parameters were still "
                f"moving by {shift:.2e}."
            )
            break

    if not converged:
        return _failed(
            model,
            started,
            f"did not converge within {options.max_cycles} EM cycles "
            f"(largest parameter change {shift:.2e}, tolerance {options.tolerance:.0e})",
            cycles=cycles,
        )

    parameters = [
        family.to_natural(data.item_ids[j], u[j], int(n_cat[j])) for j in range(n_items)
    ]

    if options.compute_standard_errors:
        try:
            parameters = _attach_standard_errors(
                family, parameters, u, patterns, pattern_counts,
                theta, prior, n_cat, index, data.item_ids,
            )
        except (np.linalg.LinAlgError, ValueError) as exc:
            # An information matrix that will not invert is a real finding about
            # the fit, not something to paper over. Parameters still ship; their
            # standard errors stay None and the reason is recorded.
            notes.append(f"Standard errors unavailable: {exc}")
            logger.warning("SE computation failed for %s: %s", model.value, exc)

    return FitResult(
        model=model,
        converged=True,
        n_cycles=cycles,
        elapsed_seconds=time.perf_counter() - started,
        item_parameters=parameters,
        log_likelihood=log_likelihood,
        n_free_parameters=index.n_free,
        n_persons=data.n_persons,
        latent_sd=latent_sd,
        quadrature=quad,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# EM internals
# --------------------------------------------------------------------------- #


def _check_model_applies(data: ResponseMatrix, model: ModelKey) -> None:
    if model.is_polytomous and not data.is_polytomous:
        raise ValueError(
            f"{model.label} is a polytomous model but every item is binary; "
            "fit a dichotomous model instead"
        )
    if not model.is_polytomous and data.is_polytomous:
        worst = int(data.n_categories.max())
        raise ValueError(
            f"{model.label} models binary responses, but this data has items "
            f"with up to {worst} categories; fit GRM, PCM or GPCM instead"
        )


def _compress(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Collapse identical response patterns.

    Real assessment data repeats patterns heavily - short tests especially - and
    the E-step cost is linear in the number of *distinct* patterns, so this is
    usually a large saving for no loss of exactness.
    """
    patterns, counts = np.unique(values, axis=0, return_counts=True)
    return patterns, counts.astype(float)


def _pattern_loglik(patterns: np.ndarray, log_probs: list[np.ndarray]) -> np.ndarray:
    """Log P(pattern | theta_k) for every pattern and node, shape (n_pat, n_quad)."""
    n_pat = patterns.shape[0]
    n_quad = log_probs[0].shape[0]
    out = np.zeros((n_pat, n_quad), dtype=float)
    for j, lp in enumerate(log_probs):
        column = patterns[:, j]
        observed = column != MISSING
        if not observed.any():
            continue
        out[observed] += lp[:, column[observed]].T
    return out


def _accumulate(
    patterns: np.ndarray,
    weighted_posterior: np.ndarray,
    n_cat: np.ndarray,
) -> list[np.ndarray]:
    """Expected counts per node per category, one ``(n_quad, n_cat)`` array per item."""
    n_quad = weighted_posterior.shape[1]
    out: list[np.ndarray] = []
    for j in range(patterns.shape[1]):
        counts = np.zeros((n_quad, int(n_cat[j])), dtype=float)
        column = patterns[:, j]
        for c in range(int(n_cat[j])):
            rows = column == c
            if rows.any():
                counts[:, c] = weighted_posterior[rows].sum(axis=0)
        out.append(counts)
    return out


def _item_objective(
    family: ItemFamily, r: np.ndarray, theta: np.ndarray, n_cat: int
):
    """Negative expected complete-data log-likelihood for one item, plus its prior."""

    def negative_q(vec: np.ndarray) -> float:
        log_p = family.log_probabilities(theta, vec, n_cat)
        return -(float(np.sum(r * log_p)) + family.log_prior(vec, n_cat))

    return negative_q


def _m_step(
    family: ItemFamily,
    u: list[np.ndarray],
    r: list[np.ndarray],
    theta: np.ndarray,
    n_cat: np.ndarray,
    index: _ParameterIndex,
    options: EMOptions,
) -> list[np.ndarray]:
    """Maximise the expected complete-data log-likelihood."""
    if family.slope_mode is SlopeMode.SHARED:
        return _m_step_shared_slope(family, u, r, theta, n_cat, options)

    updated: list[np.ndarray] = []
    for j, vec in enumerate(u):
        n_local = int(n_cat[j])
        objective = _item_objective(family, r[j], theta, n_local)
        free = [t for t, slot in enumerate(index.slots[j]) if slot is not None]

        if len(free) == len(vec):
            result = optimize.minimize(
                objective,
                vec,
                method="L-BFGS-B",
                options={"maxiter": options.m_step_max_iter},
            )
            updated.append(result.x if result.x.shape == vec.shape else vec)
        else:
            # Slope is pinned at a = 1 (log a = 0); optimise the rest around it.
            fixed = vec.copy()
            fixed[0] = 0.0

            def partial(sub: np.ndarray, _fixed=fixed, _obj=objective) -> float:
                full = _fixed.copy()
                full[1:] = sub
                return _obj(full)

            result = optimize.minimize(
                partial,
                fixed[1:],
                method="L-BFGS-B",
                options={"maxiter": options.m_step_max_iter},
            )
            out = fixed.copy()
            out[1:] = result.x
            updated.append(out)
    return updated


def _m_step_shared_slope(
    family: ItemFamily,
    u: list[np.ndarray],
    r: list[np.ndarray],
    theta: np.ndarray,
    n_cat: np.ndarray,
    options: EMOptions,
) -> list[np.ndarray]:
    """M-step for the 1PL, where one slope is common to every item.

    Optimising all J+1 parameters jointly would be correct but slow, since each
    objective evaluation touches every item. Coordinate ascent - difficulties
    given the slope, then the slope given the difficulties - increases the same
    objective and keeps every sub-problem one-dimensional. A partial M-step is
    all that generalised EM requires for convergence.
    """
    current = [vec.copy() for vec in u]
    log_a = float(current[0][0])

    for vec, counts, n in zip(current, r, n_cat, strict=True):
        vec[0] = log_a
        objective = _item_objective(family, counts, theta, int(n))

        def one_dim(b: float, _vec=vec, _obj=objective) -> float:
            trial = _vec.copy()
            trial[1] = b
            return _obj(trial)

        result = optimize.minimize_scalar(
            one_dim, bracket=(vec[1] - 1.0, vec[1] + 1.0), method="brent"
        )
        vec[1] = float(result.x)

    def slope_objective(candidate: float) -> float:
        total = 0.0
        for vec, counts, n in zip(current, r, n_cat, strict=True):
            trial = vec.copy()
            trial[0] = candidate
            total += _item_objective(family, counts, theta, int(n))(trial)
        return total

    result = optimize.minimize_scalar(
        slope_objective, bracket=(log_a - 0.5, log_a + 0.5), method="brent"
    )
    log_a = float(result.x)
    for vec in current:
        vec[0] = log_a

    return current


# --------------------------------------------------------------------------- #
# Standard errors
# --------------------------------------------------------------------------- #


def _attach_standard_errors(
    family: ItemFamily,
    parameters: list[ItemParameters],
    u: list[np.ndarray],
    patterns: np.ndarray,
    pattern_counts: np.ndarray,
    theta: np.ndarray,
    prior: np.ndarray,
    n_cat: np.ndarray,
    index: _ParameterIndex,
    item_ids: list[str],
) -> list[ItemParameters]:
    """Standard errors from the cross-product (BHHH) observed information matrix.

    By the Fisher identity the gradient of the marginal log-likelihood for one
    respondent is the posterior expectation of the complete-data gradient::

        d/dphi log L_i = sum_k posterior_ik * d/dphi log P(x_i | theta_k)

    which makes the per-respondent score computable from quantities the E-step
    already produced. Summing their outer products gives an estimate of the
    observed information whose inverse is the parameter covariance matrix.

    Derivatives of the log category probabilities are taken by central
    differences. Each one costs two evaluations of a cheap (n_quad x n_cat)
    function, and at 1e-5 step size the truncation error is orders of magnitude
    below the sampling error these standard errors describe - a worthwhile
    trade for not hand-deriving gradients for seven model families.

    Note: for Rasch and PCM the estimated latent variance is not included in the
    information matrix, so item standard errors there are very slightly
    optimistic. This is recorded rather than hidden.
    """
    n_pat, n_items = patterns.shape
    n_free = index.n_item_parameters
    if n_free == 0:
        return parameters

    log_probs = [
        family.log_probabilities(theta, u[j], int(n_cat[j])) for j in range(n_items)
    ]
    pattern_ll = _pattern_loglik(patterns, log_probs)
    joint = pattern_ll + np.log(np.clip(prior, 1e-300, None))[None, :]
    peak = joint.max(axis=1, keepdims=True)
    lse = peak[:, 0] + np.log(np.exp(joint - peak).sum(axis=1))
    posterior = np.exp(joint - lse[:, None])

    scores = np.zeros((n_pat, n_free), dtype=float)
    step = 1e-5

    for j in range(n_items):
        n_local = int(n_cat[j])
        column = patterns[:, j]
        observed = column != MISSING
        if not observed.any():
            continue

        for t, slot in enumerate(index.slots[j]):
            if slot is None:
                continue
            forward = u[j].copy()
            backward = u[j].copy()
            forward[t] += step
            backward[t] -= step
            derivative = (
                family.log_probabilities(theta, forward, n_local)
                - family.log_probabilities(theta, backward, n_local)
            ) / (2.0 * step)

            # d log P for the category each pattern actually chose, per node.
            per_node = derivative[:, column[observed]].T   # (n_observed, n_quad)
            scores[observed, slot] += np.einsum(
                "pk,pk->p", posterior[observed], per_node
            )

    information = np.einsum("p,pi,pj->ij", pattern_counts, scores, scores)

    # A ridge proportional to the matrix scale keeps a near-singular information
    # matrix invertible without materially changing well-identified standard
    # errors. If it is singular beyond that, the caller is told.
    scale = float(np.trace(information)) / max(n_free, 1)
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("information matrix is degenerate")
    covariance = np.linalg.inv(information + np.eye(n_free) * scale * 1e-10)

    variances = np.diag(covariance)
    if (variances < 0).any():
        raise ValueError("information matrix is not positive definite")

    out: list[ItemParameters] = []
    for j, params in enumerate(parameters):
        n_local = int(n_cat[j])
        slots = index.slots[j]
        block = [s for s in slots if s is not None]
        if not block:
            out.append(params)
            continue

        sub = covariance[np.ix_(block, block)]
        jacobian = _natural_jacobian(family, u[j], n_local, slots)
        natural_cov = jacobian @ sub @ jacobian.T
        natural_se = np.sqrt(np.clip(np.diag(natural_cov), 0.0, None))

        out.append(_with_standard_errors(family, params, natural_se, n_local))
    return out


def _natural_vector(family: ItemFamily, vec: np.ndarray, n_cat: int) -> np.ndarray:
    """Item parameters as a flat array on the natural scale: [a, b.../thresholds, c]."""
    natural = family.to_natural("_", vec, n_cat)
    values = [natural.discrimination]
    if natural.difficulty is not None:
        values.append(natural.difficulty)
    values.extend(natural.thresholds)
    if natural.guessing is not None:
        values.append(natural.guessing)
    return np.asarray(values, dtype=float)


def _natural_jacobian(
    family: ItemFamily,
    vec: np.ndarray,
    n_cat: int,
    slots: list[int | None],
) -> np.ndarray:
    """Jacobian of the natural parameters with respect to the free unconstrained ones.

    The delta method turns the covariance of the unconstrained estimates into
    the covariance of the numbers a user reads. Doing it numerically means the
    graded model's ordered-increment encoding needs no special case.
    """
    free = [t for t, slot in enumerate(slots) if slot is not None]
    base = _natural_vector(family, vec, n_cat)
    jac = np.zeros((base.size, len(free)), dtype=float)
    step = 1e-6
    for col, t in enumerate(free):
        forward = vec.copy()
        backward = vec.copy()
        forward[t] += step
        backward[t] -= step
        jac[:, col] = (
            _natural_vector(family, forward, n_cat)
            - _natural_vector(family, backward, n_cat)
        ) / (2.0 * step)
    return jac


def _with_standard_errors(
    family: ItemFamily,
    params: ItemParameters,
    natural_se: np.ndarray,
    n_cat: int,
) -> ItemParameters:
    """Attach standard errors positionally, matching :func:`_natural_vector`."""
    cursor = 0
    se_a = float(natural_se[cursor])
    cursor += 1

    se_b: float | None = None
    if params.difficulty is not None:
        se_b = float(natural_se[cursor])
        cursor += 1

    se_thresholds: list[float] | None = None
    if params.thresholds:
        se_thresholds = [
            float(x) for x in natural_se[cursor : cursor + len(params.thresholds)]
        ]
        cursor += len(params.thresholds)

    se_c: float | None = None
    if params.guessing is not None:
        se_c = float(natural_se[cursor])

    # A fixed slope has no sampling variability of its own; reporting an SE for
    # a constant would be a category error.
    if family.slope_mode is SlopeMode.FIXED:
        se_a = None  # type: ignore[assignment]

    return ItemParameters(
        item_id=params.item_id,
        model=params.model,
        discrimination=params.discrimination,
        difficulty=params.difficulty,
        guessing=params.guessing,
        thresholds=params.thresholds,
        n_categories=params.n_categories,
        se_discrimination=se_a,
        se_difficulty=se_b,
        se_guessing=se_c,
        se_thresholds=se_thresholds,
    )


def _failed(
    model: ModelKey, started: float, reason: str, cycles: int = 0
) -> FitResult:
    logger.info("Fit of %s failed: %s", model.value, reason)
    return FitResult(
        model=model,
        converged=False,
        n_cycles=cycles,
        elapsed_seconds=time.perf_counter() - started,
        failure_reason=reason,
    )
