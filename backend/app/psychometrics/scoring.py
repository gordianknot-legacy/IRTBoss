"""
Person ability estimation.

Three estimators are offered because they fail in different directions and no
single one is right for every use:

* **EAP** (expected a posteriori) - the posterior mean. Always finite, lowest
  average error, but shrinks towards the population mean, so the highest and
  lowest scorers are systematically pulled inward. Fine for group-level work,
  wrong for reporting an individual's standing at the extremes.
* **MAP** (maximum a posteriori) - the posterior mode. Shares EAP's shrinkage,
  cheaper to reason about, and reported mainly for comparability.
* **WLE** (Warm's weighted likelihood) - removes the first-order bias of the
  maximum-likelihood estimate without a prior pulling scores inward, and stays
  finite for perfect and zero scores where plain ML diverges. This is the right
  default when individual scores are reported back to individual people.

All three skip missing responses per cell. A respondent who answered nothing is
not scored at all rather than being handed the prior mean, which would be a
number about the population wearing a person's name.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from app.irt.em import MISSING, ResponseMatrix
from app.irt.families import ItemParameters, get_family

from .information import (
    category_derivative,
    category_probabilities,
    category_second_derivative,
    test_information,
)

_FLOOR = 1e-12
_BOUND = 6.0


class ScoreMethod(str, Enum):
    EAP = "eap"
    MAP = "map"
    WLE = "wle"

    @property
    def label(self) -> str:
        return {
            ScoreMethod.EAP: "Expected a posteriori",
            ScoreMethod.MAP: "Maximum a posteriori",
            ScoreMethod.WLE: "Weighted likelihood (Warm)",
        }[self]


@dataclass(frozen=True)
class PersonScores:
    """Ability estimates and their standard errors.

    ``theta`` and ``standard_error`` are NaN for respondents with no observed
    responses. ``n_responses`` lets a caller filter on how much evidence each
    score rests on, which matters more than the score itself when a respondent
    answered three items.
    """

    method: ScoreMethod
    theta: np.ndarray
    standard_error: np.ndarray
    n_responses: np.ndarray
    latent_sd: float = 1.0

    @property
    def scorable(self) -> np.ndarray:
        return np.isfinite(self.theta)


def score(
    data: ResponseMatrix,
    items: list[ItemParameters],
    method: ScoreMethod | str = ScoreMethod.EAP,
    *,
    latent_sd: float = 1.0,
    quadrature_points: int = 61,
    max_iter: int = 50,
    tolerance: float = 1e-6,
) -> PersonScores:
    """Estimate every respondent's ability under a fitted item set."""
    method = ScoreMethod(method) if isinstance(method, str) else method
    if len(items) != data.n_items:
        raise ValueError(
            f"{len(items)} item parameter sets for {data.n_items} columns"
        )

    answered = (data.values != MISSING).sum(axis=1)

    if method is ScoreMethod.EAP:
        theta, sem = _eap(data.values, items, latent_sd, quadrature_points)
    elif method is ScoreMethod.MAP:
        theta, sem = _newton(
            data.values, items, latent_sd, max_iter, tolerance, warm=False
        )
    else:
        theta, sem = _newton(
            data.values, items, latent_sd, max_iter, tolerance, warm=True
        )

    unscorable = answered == 0
    theta = np.where(unscorable, np.nan, theta)
    sem = np.where(unscorable, np.nan, sem)

    return PersonScores(
        method=method,
        theta=theta,
        standard_error=sem,
        n_responses=answered,
        latent_sd=latent_sd,
    )


# --------------------------------------------------------------------------- #
# EAP
# --------------------------------------------------------------------------- #


def _eap(
    values: np.ndarray,
    items: list[ItemParameters],
    latent_sd: float,
    n_points: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Posterior mean and posterior standard deviation over a fixed grid."""
    nodes = np.linspace(-_BOUND, _BOUND, n_points)
    log_prior = -0.5 * (nodes / latent_sd) ** 2

    log_lik = _grid_loglik(values, items, nodes)
    joint = log_lik + log_prior[None, :]
    joint -= joint.max(axis=1, keepdims=True)

    posterior = np.exp(joint)
    posterior /= posterior.sum(axis=1, keepdims=True)

    mean = posterior @ nodes
    variance = posterior @ (nodes**2) - mean**2
    return mean, np.sqrt(np.clip(variance, 0.0, None))


def _grid_loglik(
    values: np.ndarray, items: list[ItemParameters], nodes: np.ndarray
) -> np.ndarray:
    """log P(responses | theta) for every respondent and grid node."""
    n_persons = values.shape[0]
    out = np.zeros((n_persons, nodes.size), dtype=float)

    for j, params in enumerate(items):
        family = get_family(params.model)
        u = family.from_natural(params)
        # (n_nodes, n_cat) -> transpose so a fancy index by response picks
        # the whole node axis for each respondent at once.
        log_p = family.log_probabilities(nodes, u, params.n_categories)
        column = values[:, j]
        observed = column != MISSING
        if not observed.any():
            continue
        out[observed] += log_p[:, column[observed]].T
    return out


# --------------------------------------------------------------------------- #
# MAP and WLE, by damped Newton iteration
# --------------------------------------------------------------------------- #


def _newton(
    values: np.ndarray,
    items: list[ItemParameters],
    latent_sd: float,
    max_iter: int,
    tolerance: float,
    *,
    warm: bool,
) -> tuple[np.ndarray, np.ndarray]:
    """Solve the estimating equation for every respondent simultaneously.

    Both estimators solve ``g(theta) = 0`` for a different ``g``: MAP adds the
    prior's derivative to the score function, WLE adds Warm's bias correction.
    Because every family evaluates probabilities elementwise over a theta
    vector, one Newton step serves the whole sample at once - there is no
    per-respondent optimiser loop.

    The step is damped and clamped. Respondents with extreme or degenerate
    response patterns produce near-zero curvature, and an undamped Newton step
    would throw them to the boundary on the first iteration.
    """
    n_persons = values.shape[0]
    theta = np.zeros(n_persons, dtype=float)
    active = np.ones(n_persons, dtype=bool)

    for _ in range(max_iter):
        if not active.any():
            break

        g = _estimating_function(theta, values, items, latent_sd, warm=warm)
        # Derivative of the estimating function, taken numerically so the Warm
        # correction needs no third derivative in closed form.
        h = 1e-4
        g_plus = _estimating_function(
            theta + h, values, items, latent_sd, warm=warm
        )
        g_minus = _estimating_function(
            theta - h, values, items, latent_sd, warm=warm
        )
        slope = (g_plus - g_minus) / (2.0 * h)

        # A flat or wrongly-signed slope means Newton has nothing to work with;
        # fall back to a small gradient step in the direction of the score.
        safe = np.where(np.abs(slope) < 1e-8, -1.0, slope)
        step = np.where(safe < 0, -g / safe, np.sign(g) * 0.1)
        step = np.clip(step, -1.0, 1.0)

        theta = np.clip(theta + np.where(active, step, 0.0), -_BOUND, _BOUND)
        active = np.abs(step) > tolerance

    info = test_information(items, theta)
    if warm:
        sem = 1.0 / np.sqrt(np.clip(info, 1e-8, None))
    else:
        sem = 1.0 / np.sqrt(info + 1.0 / float(latent_sd) ** 2)
    return theta, np.clip(sem, 0.0, 1e3)


def _estimating_function(
    theta: np.ndarray,
    values: np.ndarray,
    items: list[ItemParameters],
    latent_sd: float,
    *,
    warm: bool,
) -> np.ndarray:
    """The function whose root is the ability estimate."""
    score_fn = _score_function(theta, values, items)
    if warm:
        return score_fn + _warm_correction(theta, items)
    return score_fn - theta / float(latent_sd) ** 2


def _score_function(
    theta: np.ndarray, values: np.ndarray, items: list[ItemParameters]
) -> np.ndarray:
    """d/dtheta of the log-likelihood, evaluated at each respondent's own theta."""
    total = np.zeros_like(theta)
    for j, params in enumerate(items):
        column = values[:, j]
        observed = column != MISSING
        if not observed.any():
            continue
        sub = theta[observed]
        probs = category_probabilities(params, sub)
        deriv = category_derivative(params, sub)
        picked = column[observed]
        rows = np.arange(sub.size)
        total[observed] += (
            deriv[rows, picked] / np.clip(probs[rows, picked], _FLOOR, None)
        )
    return total


def _warm_correction(
    theta: np.ndarray, items: list[ItemParameters]
) -> np.ndarray:
    """Warm's ``J(theta) / (2 I(theta))`` bias-correction term.

    ``J = sum_j sum_k P'_jk P''_jk / P_jk`` generalises Warm's dichotomous
    formula to any number of categories, so one implementation covers the
    graded and partial-credit families as well.

    The correction is a property of the test, not of the response pattern, so
    it is summed over every item regardless of what each respondent answered.
    Respondents with substantial missingness therefore get a correction that
    slightly overstates the information they actually supplied.
    """
    j_term = np.zeros_like(theta)
    for params in items:
        probs = category_probabilities(params, theta)
        d1 = category_derivative(params, theta)
        d2 = category_second_derivative(params, theta)
        j_term += np.sum(d1 * d2 / np.clip(probs, _FLOOR, None), axis=1)

    info = test_information(items, theta)
    return j_term / (2.0 * np.clip(info, 1e-8, None))
