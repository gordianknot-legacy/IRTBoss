"""
Reliability, conditional precision, and the range a test can actually measure.

The previous implementation computed marginal reliability as
``1 - 1 / mean(information)``. That is not the marginal reliability; it is a
number that is always at least as large as it, because by Jensen's inequality
``1 / E[I] <= E[1 / I]``. The error is one-directional, so every test the
platform had ever scored was reported as more precise than it was, and the
worse the test the larger the overstatement. The correct definition integrates
the *error variance*, not the information::

    rho = 1 - E_theta[SE^2(theta)] / var(theta)

Two versions of that are reported, because ``SE`` means different things
depending on how scores were produced:

* **Bayesian** - ``SE^2 = 1 / (I(theta) + 1/sigma^2)``. Matches EAP and MAP
  scores, is bounded above by ``sigma^2``, and is the figure to quote when the
  platform's own scores are used.
* **Information-based** - ``SE^2 = 1 / I(theta)``. The classical test-information
  form, matching ML or WLE scores. It is unbounded where the test carries little
  information, so it can be far lower, and for a 3PL it can be dominated
  entirely by the low-ability tail. That instability is itself a finding, and it
  is flagged rather than smoothed away.

Cronbach's alpha is deliberately absent. Alpha is a lower bound that is exact
only under tau-equivalence - equal item discriminations. Fitting a 2PL, GRM or
GPCM is an explicit statement that discriminations differ, so reporting alpha
beside those models would contradict the model that produced the scores. Where
alpha is defensible at all (Rasch, PCM) it adds nothing that the model-based
figures do not already give with a conditional standard error attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.irt.families import ItemParameters, ModelKey

from .information import test_information
from .scoring import PersonScores

# The logistic-to-normal-ogive scaling constant. Converting a logistic slope to
# a factor loading without it inflates every loading.
_D = 1.702


@dataclass(frozen=True)
class PrecisionBand:
    """The contiguous trait range over which measurement meets a precision bar."""

    max_sem: float
    lower: float | None
    upper: float | None
    reliability_equivalent: float

    @property
    def width(self) -> float | None:
        if self.lower is None or self.upper is None:
            return None
        return self.upper - self.lower


@dataclass(frozen=True)
class ReliabilityReport:
    """Every precision figure the report is allowed to quote."""

    marginal_bayesian: float
    marginal_information: float
    empirical: float | None
    omega: float | None
    latent_sd: float

    theta_grid: np.ndarray
    test_information: np.ndarray
    conditional_sem_bayesian: np.ndarray
    conditional_sem_ml: np.ndarray

    peak_information_at: float
    bands: list[PrecisionBand] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def reliability(
    items: list[ItemParameters],
    *,
    latent_sd: float = 1.0,
    scores: PersonScores | None = None,
    n_points: int = 121,
    bound: float = 4.0,
) -> ReliabilityReport:
    """Compute the full precision picture for a fitted item set.

    ``scores`` is optional; supplying it adds the empirical reliability, which
    is the only figure here computed from the respondents rather than from the
    model, and therefore the only one that can disagree with the model.
    """
    if not items:
        raise ValueError("reliability needs at least one item")

    grid = np.linspace(-bound, bound, n_points)
    info = test_information(items, grid)

    # Population weights on the same grid. Trapezoid weighting keeps the
    # integral honest at the ends rather than double-counting the edge nodes.
    density = np.exp(-0.5 * (grid / latent_sd) ** 2)
    spacing = np.gradient(grid)
    weights = density * spacing
    weights /= weights.sum()

    var_bayes = 1.0 / (info + 1.0 / latent_sd**2)
    var_ml = 1.0 / np.clip(info, 1e-12, None)

    total_variance = latent_sd**2
    marginal_bayes = float(1.0 - np.dot(weights, var_bayes) / total_variance)
    marginal_info = float(1.0 - np.dot(weights, var_ml) / total_variance)

    notes: list[str] = []
    if marginal_info < 0:
        notes.append(
            "The information-based reliability is negative because the test "
            "carries almost no information across part of the trait range. "
            "Treat the Bayesian figure as the usable one and read the "
            "conditional standard error curve before quoting any single number."
        )
    if marginal_bayes < 0.7:
        notes.append(
            f"Marginal reliability of {marginal_bayes:.2f} is below the level "
            "usually considered adequate for group-level reporting (0.70) and "
            "well below the level for individual decisions (0.90)."
        )

    bands = [
        _band(grid, var_bayes, max_sem=0.50),
        _band(grid, var_bayes, max_sem=0.33),
    ]
    if bands[0].lower is None:
        notes.append(
            "No part of the trait range is measured with a standard error of "
            "0.50 or better, so this test does not support individual-level "
            "interpretation anywhere on the scale."
        )

    omega, omega_note = _omega(items)
    if omega_note:
        notes.append(omega_note)

    empirical = _empirical(scores) if scores is not None else None
    if empirical is not None and abs(empirical - marginal_bayes) > 0.10:
        notes.append(
            f"Empirical reliability ({empirical:.2f}) and model-implied "
            f"marginal reliability ({marginal_bayes:.2f}) disagree by more "
            "than 0.10. That gap usually means the trait distribution in this "
            "sample is not the normal distribution the model assumed."
        )

    return ReliabilityReport(
        marginal_bayesian=marginal_bayes,
        marginal_information=marginal_info,
        empirical=empirical,
        omega=omega,
        latent_sd=latent_sd,
        theta_grid=grid,
        test_information=info,
        conditional_sem_bayesian=np.sqrt(var_bayes),
        conditional_sem_ml=np.sqrt(var_ml),
        peak_information_at=float(grid[int(np.argmax(info))]),
        bands=bands,
        notes=notes,
    )


def _band(
    grid: np.ndarray, error_variance: np.ndarray, *, max_sem: float
) -> PrecisionBand:
    """Widest contiguous span of the grid meeting a standard-error bar.

    Contiguity matters: a test can meet the bar in two disconnected pockets,
    and reporting min-to-max across both would claim precision in the gap
    between them that the test does not have.
    """
    meets = np.sqrt(error_variance) <= max_sem
    lower = upper = None

    if meets.any():
        best_start = best_len = 0
        start = None
        for i, ok in enumerate(meets):
            if ok and start is None:
                start = i
            if (not ok or i == meets.size - 1) and start is not None:
                end = i if not ok else i + 1
                if end - start > best_len:
                    best_start, best_len = start, end - start
                start = None
        lower = float(grid[best_start])
        upper = float(grid[best_start + best_len - 1])

    return PrecisionBand(
        max_sem=max_sem,
        lower=lower,
        upper=upper,
        reliability_equivalent=1.0 - max_sem**2,
    )


def _empirical(scores: PersonScores) -> float | None:
    """Reliability from the realised scores: ``(var(theta_hat) - mean(SE^2)) / var(theta_hat)``.

    This uses the observed spread of estimates rather than the assumed
    population variance, so it is the figure that will disagree with the
    model-based one when the sample is not normally distributed on the trait.
    """
    keep = scores.scorable
    if keep.sum() < 2:
        return None
    theta = scores.theta[keep]
    sem = scores.standard_error[keep]

    observed_variance = float(np.var(theta, ddof=1))
    if observed_variance <= 0:
        return None
    error_variance = float(np.mean(sem**2))
    return (observed_variance - error_variance) / observed_variance


def _omega(items: list[ItemParameters]) -> tuple[float | None, str | None]:
    """McDonald's omega from the model-implied factor loadings.

    A dichotomous IRT model is a normal-ogive factor model in disguise:
    ``lambda_j = a*_j / sqrt(1 + a*_j^2)`` where ``a* = a / 1.702``. Omega is
    then the congeneric reliability of that factor model, which - unlike alpha -
    does not require the loadings to be equal.

    It is not computed for the 3PL, where a lower asymptote breaks the
    factor-model equivalence, nor for polytomous models, where the loading
    depends on the category thresholds as well as the slope and the
    single-coefficient form would understate reliability.
    """
    models = {p.model for p in items}
    if any(m.is_polytomous for m in models):
        return None, (
            "McDonald's omega is not reported for polytomous models, where a "
            "single loading per item does not capture the category structure."
        )
    if ModelKey.THREE_PL in models:
        return None, (
            "McDonald's omega is not reported for the 3PL: a non-zero lower "
            "asymptote breaks the factor-model equivalence omega relies on."
        )

    slopes = np.array([p.discrimination for p in items], dtype=float) / _D
    loadings = slopes / np.sqrt(1.0 + slopes**2)
    common = loadings.sum() ** 2
    unique = float(np.sum(1.0 - loadings**2))
    if common + unique <= 0:
        return None, None
    return float(common / (common + unique)), None
