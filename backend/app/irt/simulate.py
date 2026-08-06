"""
Response generation from known item parameters.

This exists for two reasons that both matter to the product's credibility:

* **Parameter recovery tests.** The only way to know an estimator works is to
  hand it data whose true parameters you already know and check it gets them
  back. Every model family has a recovery test built on this module.
* **Honest example datasets.** The shipped examples are generated here from
  documented parameters with a recorded seed, so the "right answer" for each
  sample dataset is a known quantity rather than a claim.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .em import MISSING, ResponseMatrix
from .families import ModelKey, get_family


@dataclass(frozen=True)
class TrueParameters:
    """Generating parameters, on the natural scale."""

    model: ModelKey
    discrimination: np.ndarray                 # (n_items,)
    difficulty: np.ndarray | None = None       # (n_items,) dichotomous
    guessing: np.ndarray | None = None         # (n_items,) 3PL
    thresholds: np.ndarray | None = None       # (n_items, n_cat - 1) polytomous


def _unconstrained(true: TrueParameters, j: int, n_cat: int) -> np.ndarray:
    """Encode one item's true parameters the way the families expect them."""
    log_a = float(np.log(true.discrimination[j]))

    if true.model in (ModelKey.GRM,):
        bounds = np.asarray(true.thresholds)[j]
        vec = [log_a, float(bounds[0])]
        for k in range(1, len(bounds)):
            vec.append(float(np.log(max(bounds[k] - bounds[k - 1], 1e-6))))
        return np.asarray(vec, dtype=float)

    if true.model in (ModelKey.PCM, ModelKey.GPCM):
        steps = np.asarray(true.thresholds)[j]
        return np.asarray([log_a, *steps.astype(float)], dtype=float)

    vec = [log_a, float(true.difficulty[j])]
    if true.model is ModelKey.THREE_PL:
        c = float(np.clip(true.guessing[j], 1e-4, 1 - 1e-4))
        vec.append(float(np.log(c / (1 - c))))
    return np.asarray(vec, dtype=float)


def simulate(
    true: TrueParameters,
    n_persons: int,
    *,
    seed: int = 20260803,
    latent_sd: float = 1.0,
    missing_rate: float = 0.0,
    item_prefix: str = "item_",
) -> tuple[ResponseMatrix, np.ndarray]:
    """Draw responses for ``n_persons`` respondents.

    Returns the response matrix and the true abilities that generated it, so a
    test can check person-score recovery as well as item recovery.
    """
    rng = np.random.default_rng(seed)
    family = get_family(true.model)

    n_items = int(true.discrimination.size)
    n_cat = (
        int(np.asarray(true.thresholds).shape[1]) + 1
        if true.thresholds is not None
        else 2
    )
    categories = np.full(n_items, n_cat, dtype=int)

    theta = rng.normal(0.0, latent_sd, size=n_persons)
    values = np.empty((n_persons, n_items), dtype=np.int16)

    for j in range(n_items):
        vec = _unconstrained(true, j, n_cat)
        probs = family.probabilities(theta, vec, n_cat)      # (n_persons, n_cat)
        # One multinomial draw per respondent, vectorised by inverse-CDF.
        cumulative = np.cumsum(probs, axis=1)
        draws = rng.random(n_persons)[:, None]
        values[:, j] = (draws > cumulative).sum(axis=1).astype(np.int16)

    np.clip(values, 0, n_cat - 1, out=values)

    if missing_rate > 0:
        mask = rng.random(values.shape) < missing_rate
        values[mask] = MISSING

    item_ids = [f"{item_prefix}{j + 1:02d}" for j in range(n_items)]
    data = ResponseMatrix(
        values=values, item_ids=item_ids, n_categories=categories
    )
    return data, theta


def spread_parameters(
    model: ModelKey,
    n_items: int,
    *,
    seed: int = 20260803,
    n_categories: int = 2,
) -> TrueParameters:
    """A realistic, well-spread parameter set for a test of ``n_items`` items."""
    rng = np.random.default_rng(seed)

    if model in (ModelKey.RASCH, ModelKey.PCM):
        a = np.ones(n_items)
    elif model is ModelKey.ONE_PL:
        a = np.full(n_items, 1.2)
    else:
        a = rng.uniform(0.8, 2.0, size=n_items)

    if model.is_polytomous:
        base = np.linspace(-1.5, 1.5, n_items)
        offsets = np.linspace(-1.0, 1.0, n_categories - 1)
        thresholds = base[:, None] + offsets[None, :]
        return TrueParameters(model=model, discrimination=a, thresholds=thresholds)

    b = np.linspace(-2.0, 2.0, n_items)
    guessing = None
    if model is ModelKey.THREE_PL:
        guessing = rng.uniform(0.15, 0.25, size=n_items)
    return TrueParameters(
        model=model, discrimination=a, difficulty=b, guessing=guessing
    )
