"""
Fisher information for items and tests.

One definition serves every model family::

    I(theta) = sum_k  (dP_k/dtheta)^2 / P_k

For the 2PL this reduces to the familiar ``a^2 P Q``; for the 3PL it reduces to
``a^2 (Q/P) ((P - c)/(1 - c))^2``, which is *not* ``a^2 P Q`` and is not
maximised at ``theta = b``. Deriving each family's closed form separately is how
the previous implementation ended up with a 3PL information function that
overstated precision for guessable items, so this module derives none of them:
it differentiates the category probabilities the family itself defines.

The derivative is taken by central difference. The step is chosen well above the
point where floating-point cancellation matters and well below the scale on
which the probability curves bend, so the truncation error is negligible next to
the sampling error of any parameter these curves are drawn from.
"""

from __future__ import annotations

import numpy as np

from app.irt.families import ItemParameters, get_family

# Separate steps for the first and second derivatives. The second difference
# divides by h^2, so it needs the larger step to stay clear of cancellation.
_H1 = 1e-4
_H2 = 1e-3
_FLOOR = 1e-12


def category_probabilities(
    params: ItemParameters, theta: np.ndarray
) -> np.ndarray:
    """Category response probabilities, shape ``(len(theta), n_categories)``."""
    family = get_family(params.model)
    u = family.from_natural(params)
    return family.probabilities(
        np.asarray(theta, dtype=float), u, params.n_categories
    )


def category_derivative(params: ItemParameters, theta: np.ndarray) -> np.ndarray:
    """dP_k/dtheta for every category, shape ``(len(theta), n_categories)``."""
    theta = np.asarray(theta, dtype=float)
    forward = category_probabilities(params, theta + _H1)
    backward = category_probabilities(params, theta - _H1)
    return (forward - backward) / (2.0 * _H1)


def category_second_derivative(
    params: ItemParameters, theta: np.ndarray
) -> np.ndarray:
    """d2P_k/dtheta2, needed only by the Warm bias correction in scoring."""
    theta = np.asarray(theta, dtype=float)
    centre = category_probabilities(params, theta)
    forward = category_probabilities(params, theta + _H2)
    backward = category_probabilities(params, theta - _H2)
    return (forward - 2.0 * centre + backward) / (_H2**2)


def item_information(params: ItemParameters, theta: np.ndarray) -> np.ndarray:
    """Fisher information contributed by one item at each point of ``theta``."""
    probs = category_probabilities(params, theta)
    deriv = category_derivative(params, theta)
    return np.sum(deriv**2 / np.clip(probs, _FLOOR, None), axis=1)


def test_information(
    items: list[ItemParameters], theta: np.ndarray
) -> np.ndarray:
    """Total information, the sum over items.

    Additivity is a consequence of local independence, which is an assumption
    this platform tests rather than presumes. When the local-independence check
    flags an item pair, this curve is optimistic and the report says so.
    """
    theta = np.asarray(theta, dtype=float)
    total = np.zeros_like(theta)
    for params in items:
        total += item_information(params, theta)
    return total


def standard_error(
    items: list[ItemParameters], theta: np.ndarray
) -> np.ndarray:
    """Conditional standard error of measurement, ``1 / sqrt(I(theta))``.

    This is the standard error of a maximum-likelihood ability estimate. It
    diverges where the test carries no information, which is a true statement
    about the test and is left unclipped.
    """
    info = test_information(items, theta)
    with np.errstate(divide="ignore"):
        return 1.0 / np.sqrt(np.clip(info, 0.0, None))


def posterior_standard_error(
    items: list[ItemParameters], theta: np.ndarray, latent_sd: float = 1.0
) -> np.ndarray:
    """Standard error of a Bayesian (EAP/MAP) score, ``1 / sqrt(I + 1/sd^2)``.

    The prior contributes information of its own, so this is always finite and
    always smaller than the ML standard error. Which of the two belongs in a
    reliability coefficient depends on how the scores were produced, so both are
    computed and the report labels them.
    """
    info = test_information(items, theta)
    return 1.0 / np.sqrt(info + 1.0 / float(latent_sd) ** 2)


def information_peak(
    items: list[ItemParameters],
    lower: float = -6.0,
    upper: float = 6.0,
    n_points: int = 601,
) -> float:
    """The trait level the test measures most precisely."""
    grid = np.linspace(lower, upper, n_points)
    return float(grid[int(np.argmax(test_information(items, grid)))])
