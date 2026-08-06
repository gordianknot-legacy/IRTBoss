"""
Item response model families.

Every family exposes the same interface so the estimator in :mod:`app.irt.em`
can treat them uniformly. The unifying convention is that an item's parameters
live in a single *unconstrained* vector whose first element is always the log
slope::

    2PL          u = [log a, b]
    3PL          u = [log a, b, logit c]
    Rasch / 1PL  u = [log a, b]        (log a held fixed / tied by the estimator)
    GRM          u = [log a, b1, log d2, ..., log d_{m-1}]
    GPCM / PCM   u = [log a, s1, ..., s_{m-1}]

Working in an unconstrained space means the M-step is an ordinary unbounded
optimisation: slopes stay positive, guessing stays in (0, 1), and graded
thresholds stay ordered, without any of the boundary handling that makes
constrained optimisers fragile.

The estimator decides what to do with element 0 — hold it at log(1) for Rasch
and PCM, tie it across items for 1PL, or estimate it freely — so families
themselves never need to know which slope regime they are in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

# Probabilities are clipped away from 0 and 1 before any log is taken. Response
# patterns that a model considers near-impossible are common in real data, and
# an unclipped log turns one of them into a -inf that poisons the entire
# likelihood.
_EPS = 1e-12


class ModelKey(str, Enum):
    """Identifier for a model family, used in the API and on the wire."""

    RASCH = "rasch"
    ONE_PL = "1pl"
    TWO_PL = "2pl"
    THREE_PL = "3pl"
    GRM = "grm"
    PCM = "pcm"
    GPCM = "gpcm"

    @property
    def is_polytomous(self) -> bool:
        return self in {ModelKey.GRM, ModelKey.PCM, ModelKey.GPCM}

    @property
    def label(self) -> str:
        return {
            ModelKey.RASCH: "Rasch",
            ModelKey.ONE_PL: "1PL",
            ModelKey.TWO_PL: "2PL",
            ModelKey.THREE_PL: "3PL",
            ModelKey.GRM: "Graded Response",
            ModelKey.PCM: "Partial Credit",
            ModelKey.GPCM: "Generalised Partial Credit",
        }[self]


class SlopeMode(str, Enum):
    """How the estimator treats the slope element of the parameter vector."""

    FIXED = "fixed"    # a == 1 for every item (Rasch, PCM)
    SHARED = "shared"  # one slope estimated, common to all items (1PL)
    FREE = "free"      # estimated per item (2PL, 3PL, GRM, GPCM)


@dataclass(frozen=True)
class ItemParameters:
    """Item parameters on the natural (interpretable) scale.

    ``difficulty`` is the single b for dichotomous items and ``None`` for
    polytomous ones, where ``thresholds`` carries the category boundaries
    instead. ``guessing`` is only meaningful for the 3PL.
    """

    item_id: str
    model: ModelKey
    discrimination: float
    difficulty: float | None = None
    guessing: float | None = None
    thresholds: list[float] = field(default_factory=list)
    n_categories: int = 2

    # Standard errors, on the natural scale. Populated by the estimator once the
    # observed information matrix has been computed; None means "not estimated",
    # never "zero".
    se_discrimination: float | None = None
    se_difficulty: float | None = None
    se_guessing: float | None = None
    se_thresholds: list[float] | None = None


def _logit(p: np.ndarray | float) -> np.ndarray | float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    # Branch-free stable logistic: exp() is only ever applied to non-positive
    # values, so it cannot overflow.
    out = np.empty_like(z, dtype=float)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    out[~pos] = ez / (1.0 + ez)
    return out


class ItemFamily(ABC):
    """Base class for a model family.

    Implementations are stateless; every method takes the item's unconstrained
    parameter vector explicitly so that a single instance can serve every item
    on the test.
    """

    key: ModelKey
    slope_mode: SlopeMode

    @abstractmethod
    def n_params(self, n_cat: int) -> int:
        """Length of the unconstrained vector, including the slope element."""

    @abstractmethod
    def param_labels(self, n_cat: int) -> list[str]:
        """Human-readable name per element, for SE reporting and debugging."""

    @abstractmethod
    def probabilities(self, theta: np.ndarray, u: np.ndarray, n_cat: int) -> np.ndarray:
        """Category probabilities, shape ``(len(theta), n_cat)``, rows summing to 1."""

    @abstractmethod
    def to_natural(self, item_id: str, u: np.ndarray, n_cat: int) -> ItemParameters:
        """Convert the unconstrained vector to interpretable parameters."""

    @abstractmethod
    def initial(self, observed: np.ndarray, n_cat: int) -> np.ndarray:
        """Starting values from the item's observed responses (missing removed)."""

    @abstractmethod
    def from_natural(self, params: ItemParameters) -> np.ndarray:
        """Inverse of :meth:`to_natural`.

        Diagnostics receive fitted parameters on the natural scale but need to
        evaluate response probabilities, which are defined on the unconstrained
        scale. Without this round trip every diagnostic would have to re-derive
        each family's encoding for itself.
        """

    def log_prior(self, u: np.ndarray, n_cat: int) -> float:
        """Log prior on the unconstrained vector. Zero unless a family needs one."""
        return 0.0

    def log_probabilities(
        self, theta: np.ndarray, u: np.ndarray, n_cat: int
    ) -> np.ndarray:
        return np.log(np.clip(self.probabilities(theta, u, n_cat), _EPS, 1.0))


# --------------------------------------------------------------------------- #
# Dichotomous families
# --------------------------------------------------------------------------- #


class _Dichotomous(ItemFamily):
    """Shared machinery for the 1/2/3-parameter logistic models."""

    has_guessing = False

    def n_params(self, n_cat: int) -> int:
        return 3 if self.has_guessing else 2

    def param_labels(self, n_cat: int) -> list[str]:
        base = ["a", "b"]
        return [*base, "c"] if self.has_guessing else base

    def probabilities(self, theta: np.ndarray, u: np.ndarray, n_cat: int) -> np.ndarray:
        a = float(np.exp(u[0]))
        b = float(u[1])
        c = float(_sigmoid(np.array([u[2]]))[0]) if self.has_guessing else 0.0
        p1 = c + (1.0 - c) * _sigmoid(a * (theta - b))
        p1 = np.clip(p1, _EPS, 1.0 - _EPS)
        return np.column_stack([1.0 - p1, p1])

    def to_natural(self, item_id: str, u: np.ndarray, n_cat: int) -> ItemParameters:
        return ItemParameters(
            item_id=item_id,
            model=self.key,
            discrimination=float(np.exp(u[0])),
            difficulty=float(u[1]),
            guessing=(
                float(_sigmoid(np.array([u[2]]))[0]) if self.has_guessing else None
            ),
            n_categories=2,
        )

    def initial(self, observed: np.ndarray, n_cat: int) -> np.ndarray:
        p = float(np.clip(observed.mean(), 0.02, 0.98))
        # The normal-ogive approximation b ~ -logit(p)/1.7 is a much better
        # starting point than a constant, and cuts EM iterations noticeably on
        # tests with a wide difficulty spread.
        b = float(-_logit(p) / 1.7)
        u = [0.0, b]
        if self.has_guessing:
            u.append(_logit(0.2))
        return np.asarray(u, dtype=float)

    def from_natural(self, params: ItemParameters) -> np.ndarray:
        u = [float(np.log(params.discrimination)), float(params.difficulty)]
        if self.has_guessing:
            u.append(float(_logit(params.guessing or 0.0)))
        return np.asarray(u, dtype=float)


class RaschFamily(_Dichotomous):
    """Rasch model: slope fixed at 1, population variance estimated instead.

    This is *not* the same as the 1PL, and conflating the two was a real defect
    in the previous implementation. Rasch fixes a = 1 and lets the latent
    distribution's variance float; the 1PL estimates one common slope and fixes
    the variance at 1. They place items on different metrics, so anything that
    assumes theta ~ N(0, 1) is wrong for a Rasch fit unless the estimated
    variance is carried along with it.
    """

    key = ModelKey.RASCH
    slope_mode = SlopeMode.FIXED


class OnePLFamily(_Dichotomous):
    """1PL: a single slope estimated and shared across all items."""

    key = ModelKey.ONE_PL
    slope_mode = SlopeMode.SHARED


class TwoPLFamily(_Dichotomous):
    key = ModelKey.TWO_PL
    slope_mode = SlopeMode.FREE


class ThreePLFamily(_Dichotomous):
    """3PL with a Beta prior on the lower asymptote.

    The guessing parameter is famously weakly identified: with a few hundred
    respondents the likelihood is often nearly flat in c, and an unpenalised
    fit will happily wander to implausible values or fail to converge. A mild
    Beta(5, 17) prior (mean 0.227, sd 0.088) keeps c in the region that a
    multiple-choice item can actually produce.

    This is a deliberate, documented modelling choice rather than a hidden one:
    it is reported in the analysis metadata so the prior appears in the
    technical appendix.
    """

    key = ModelKey.THREE_PL
    slope_mode = SlopeMode.FREE
    has_guessing = True

    prior_alpha = 5.0
    prior_beta = 17.0

    def log_prior(self, u: np.ndarray, n_cat: int) -> float:
        c = float(_sigmoid(np.array([u[2]]))[0])
        c = min(max(c, 1e-6), 1 - 1e-6)
        return float(
            (self.prior_alpha - 1.0) * np.log(c)
            + (self.prior_beta - 1.0) * np.log1p(-c)
        )


# --------------------------------------------------------------------------- #
# Polytomous families
# --------------------------------------------------------------------------- #


class GradedResponseFamily(ItemFamily):
    """Samejima's Graded Response Model.

    Category probabilities are differences of cumulative logistic boundaries::

        P*(X >= k) = logistic(a * (theta - b_k)),  k = 1 .. m-1
        P(X = k)   = P*(X >= k) - P*(X >= k+1)

    The boundaries must be strictly increasing or the differences go negative.
    Rather than imposing that as a constraint, b_1 is free and each subsequent
    boundary is b_1 plus a sum of exponentiated increments, so ordering holds
    by construction for any real vector the optimiser proposes.
    """

    key = ModelKey.GRM
    slope_mode = SlopeMode.FREE

    def n_params(self, n_cat: int) -> int:
        return 1 + (n_cat - 1)

    def param_labels(self, n_cat: int) -> list[str]:
        return ["a"] + [f"b{k}" for k in range(1, n_cat)]

    def _boundaries(self, u: np.ndarray, n_cat: int) -> np.ndarray:
        b = np.empty(n_cat - 1, dtype=float)
        b[0] = u[1]
        for k in range(1, n_cat - 1):
            b[k] = b[k - 1] + np.exp(u[1 + k])
        return b

    def probabilities(self, theta: np.ndarray, u: np.ndarray, n_cat: int) -> np.ndarray:
        a = float(np.exp(u[0]))
        b = self._boundaries(u, n_cat)

        # cum[:, k] = P(X >= k); the two sentinel columns (P(X>=0)=1 and
        # P(X>=m)=0) make the differencing below a single vectorised step.
        cum = np.empty((theta.size, n_cat + 1), dtype=float)
        cum[:, 0] = 1.0
        cum[:, n_cat] = 0.0
        for k in range(1, n_cat):
            cum[:, k] = _sigmoid(a * (theta - b[k - 1]))

        probs = cum[:, :-1] - cum[:, 1:]
        return np.clip(probs, _EPS, 1.0)

    def to_natural(self, item_id: str, u: np.ndarray, n_cat: int) -> ItemParameters:
        return ItemParameters(
            item_id=item_id,
            model=self.key,
            discrimination=float(np.exp(u[0])),
            thresholds=[float(x) for x in self._boundaries(u, n_cat)],
            n_categories=n_cat,
        )

    def initial(self, observed: np.ndarray, n_cat: int) -> np.ndarray:
        # Boundaries from the observed cumulative proportions, which places each
        # threshold near the point where responses actually cross it.
        u = np.zeros(self.n_params(n_cat), dtype=float)
        cuts = []
        n = observed.size
        for k in range(1, n_cat):
            prop = float(np.clip((observed >= k).sum() / max(n, 1), 0.02, 0.98))
            cuts.append(-_logit(prop) / 1.7)
        cuts = np.maximum.accumulate(np.asarray(cuts, dtype=float))
        u[1] = cuts[0]
        for k in range(1, n_cat - 1):
            gap = max(cuts[k] - cuts[k - 1], 0.05)
            u[1 + k] = np.log(gap)
        return u

    def from_natural(self, params: ItemParameters) -> np.ndarray:
        b = np.asarray(params.thresholds, dtype=float)
        u = [float(np.log(params.discrimination)), float(b[0])]
        for k in range(1, b.size):
            u.append(float(np.log(max(b[k] - b[k - 1], 1e-9))))
        return np.asarray(u, dtype=float)


class _PartialCredit(ItemFamily):
    """Shared machinery for the PCM and GPCM.

    Both are divide-by-total models over cumulative step logits::

        psi_0 = 0
        psi_k = sum_{v=1..k} a * (theta - s_v)
        P(X = k) = exp(psi_k) / sum_j exp(psi_j)

    Step parameters are *not* required to be ordered — reversed steps are a
    genuine and diagnostically interesting finding about a rating scale, not a
    numerical problem to be constrained away.
    """

    slope_mode: SlopeMode

    def n_params(self, n_cat: int) -> int:
        return 1 + (n_cat - 1)

    def param_labels(self, n_cat: int) -> list[str]:
        return ["a"] + [f"s{k}" for k in range(1, n_cat)]

    def probabilities(self, theta: np.ndarray, u: np.ndarray, n_cat: int) -> np.ndarray:
        a = float(np.exp(u[0]))
        steps = np.asarray(u[1:n_cat], dtype=float)

        # psi[:, k] is the cumulative sum of a*(theta - s_v) up to step k.
        terms = a * (theta[:, None] - steps[None, :])
        psi = np.zeros((theta.size, n_cat), dtype=float)
        psi[:, 1:] = np.cumsum(terms, axis=1)

        psi -= psi.max(axis=1, keepdims=True)  # softmax stabilisation
        expo = np.exp(psi)
        probs = expo / expo.sum(axis=1, keepdims=True)
        return np.clip(probs, _EPS, 1.0)

    def to_natural(self, item_id: str, u: np.ndarray, n_cat: int) -> ItemParameters:
        return ItemParameters(
            item_id=item_id,
            model=self.key,
            discrimination=float(np.exp(u[0])),
            thresholds=[float(x) for x in u[1:n_cat]],
            n_categories=n_cat,
        )

    def initial(self, observed: np.ndarray, n_cat: int) -> np.ndarray:
        u = np.zeros(self.n_params(n_cat), dtype=float)
        n = observed.size
        for k in range(1, n_cat):
            prop = float(np.clip((observed >= k).sum() / max(n, 1), 0.02, 0.98))
            u[k] = -_logit(prop) / 1.7
        return u

    def from_natural(self, params: ItemParameters) -> np.ndarray:
        steps = [float(s) for s in params.thresholds]
        return np.asarray(
            [float(np.log(params.discrimination)), *steps], dtype=float
        )


class PartialCreditFamily(_PartialCredit):
    """PCM: slope fixed at 1 for every item (the polytomous Rasch model)."""

    key = ModelKey.PCM
    slope_mode = SlopeMode.FIXED


class GeneralisedPartialCreditFamily(_PartialCredit):
    """GPCM: slope estimated per item."""

    key = ModelKey.GPCM
    slope_mode = SlopeMode.FREE


_FAMILIES: dict[ModelKey, ItemFamily] = {
    ModelKey.RASCH: RaschFamily(),
    ModelKey.ONE_PL: OnePLFamily(),
    ModelKey.TWO_PL: TwoPLFamily(),
    ModelKey.THREE_PL: ThreePLFamily(),
    ModelKey.GRM: GradedResponseFamily(),
    ModelKey.PCM: PartialCreditFamily(),
    ModelKey.GPCM: GeneralisedPartialCreditFamily(),
}


def get_family(key: ModelKey | str) -> ItemFamily:
    """Look up a family instance. Raises ``KeyError`` for unknown keys."""
    if isinstance(key, str):
        key = ModelKey(key)
    return _FAMILIES[key]


DICHOTOMOUS_MODELS: tuple[ModelKey, ...] = (
    ModelKey.RASCH,
    ModelKey.ONE_PL,
    ModelKey.TWO_PL,
    ModelKey.THREE_PL,
)

POLYTOMOUS_MODELS: tuple[ModelKey, ...] = (
    ModelKey.PCM,
    ModelKey.GPCM,
    ModelKey.GRM,
)
