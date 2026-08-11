"""
Tier 2 validation: agreement with R's mirt.

Tier 1 - the parameter recovery tests in ``test_irt_engine.py`` - proves the
estimator recovers parameters it generated itself. That catches a broken
estimator but not a subtly wrong one, because the simulator and the estimator
share this project's assumptions about what each model means. If both encode
the same misunderstanding of, say, the partial credit model, recovery still
succeeds.

Tier 2 closes that gap by fitting the same data with an independently written
estimator that has been used and scrutinised for over a decade. Two programs,
two languages, two authors, one likelihood: a disagreement beyond quadrature
noise means one of them is wrong, and it is worth finding out which.

mirt is not a runtime dependency. These tests skip when the reference output is
absent, so the ordinary test run needs no R at all. The scheduled CI job
installs R, regenerates the reference, and fails the build on disagreement.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.irt.em import ResponseMatrix, fit
from app.irt.families import ModelKey

FIXTURES = Path(__file__).parent / "fixtures"

# Agreement tolerances. Both estimators maximise the same marginal likelihood,
# so the residual difference is quadrature placement and convergence criteria,
# not statistical error. These are therefore far tighter than the recovery
# tolerances in tier 1 - anything looser would stop catching real defects.
TOLERANCES = {
    ModelKey.RASCH:    {"difficulty": 0.05, "discrimination": 0.0},
    ModelKey.TWO_PL:   {"difficulty": 0.06, "discrimination": 0.08},
    ModelKey.THREE_PL: {"difficulty": 0.20, "discrimination": 0.25,
                        "guessing": 0.06},
    ModelKey.GRM:      {"thresholds": 0.06, "discrimination": 0.08},
}


def _reference_cases() -> list[str]:
    if not FIXTURES.exists():
        return []
    return sorted(p.stem.replace(".mirt", "") for p in FIXTURES.glob("*.mirt.json"))


def _load(name: str) -> tuple[ResponseMatrix, dict, dict]:
    manifest = json.loads((FIXTURES / "manifest.json").read_text())[name]
    reference = json.loads((FIXTURES / f"{name}.mirt.json").read_text())

    raw = np.loadtxt(FIXTURES / f"{name}.csv", delimiter=",", skiprows=1,
                     dtype=np.int16)
    header = (FIXTURES / f"{name}.csv").read_text().splitlines()[0]
    item_ids = header.split(",")

    data = ResponseMatrix(
        values=raw,
        item_ids=item_ids,
        n_categories=np.full(raw.shape[1], manifest["n_categories"], dtype=int),
    )
    return data, manifest, reference


pytestmark = pytest.mark.skipif(
    not _reference_cases(),
    reason=(
        "No mirt reference output found. Run tests/validation/mirt_reference.R "
        "with R and the mirt package installed to generate it."
    ),
)


@pytest.mark.parametrize("name", _reference_cases() or ["_none"])
def test_agrees_with_mirt(name: str) -> None:
    data, manifest, reference = _load(name)
    model = ModelKey(manifest["model"])

    assert reference["converged"], f"the mirt reference fit for {name} did not converge"

    result = fit(data, model)
    assert result.converged, result.failure_reason

    tol = TOLERANCES[model]
    ours = result.item_parameters
    theirs = reference["items"]

    _compare(
        "discrimination",
        np.array([p.discrimination for p in ours]),
        np.asarray(theirs["discrimination"], dtype=float),
        tol["discrimination"],
        name,
    )

    if model.is_polytomous:
        _compare(
            "thresholds",
            np.array([p.thresholds for p in ours]),
            np.asarray(theirs["thresholds"], dtype=float),
            tol["thresholds"],
            name,
        )
    else:
        _compare(
            "difficulty",
            np.array([p.difficulty for p in ours]),
            np.asarray(theirs["difficulty"], dtype=float),
            tol["difficulty"],
            name,
        )

    if model is ModelKey.THREE_PL:
        _compare(
            "guessing",
            np.array([p.guessing for p in ours]),
            np.asarray(theirs["guessing"], dtype=float),
            tol["guessing"],
            name,
        )


def _compare(
    label: str,
    ours: np.ndarray,
    theirs: np.ndarray,
    tolerance: float,
    fixture: str,
) -> None:
    if tolerance == 0.0:
        # A parameter both estimators hold fixed; assert it really is fixed
        # rather than pretending to compare it.
        np.testing.assert_allclose(ours, theirs, atol=1e-6)
        return

    assert ours.shape == theirs.shape, (
        f"{fixture}/{label}: shape {ours.shape} vs mirt {theirs.shape}"
    )
    difference = np.abs(ours - theirs)
    worst = int(np.argmax(difference.reshape(difference.shape[0], -1).max(axis=1)))

    assert difference.max() < tolerance, (
        f"{fixture}: {label} differs from mirt by {difference.max():.4f} "
        f"(tolerance {tolerance}), worst at item index {worst}: "
        f"ours={ours[worst]}, mirt={theirs[worst]}"
    )


@pytest.mark.parametrize("name", _reference_cases() or ["_none"])
def test_log_likelihood_agrees_with_mirt(name: str) -> None:
    """The likelihood is the thing both estimators are maximising.

    Parameters can differ slightly through quadrature placement while the
    likelihood agrees closely. A likelihood gap is the more serious signal: it
    means one estimator found a worse optimum, or the two are not maximising
    the same function at all.
    """
    data, manifest, reference = _load(name)
    model = ModelKey(manifest["model"])

    result = fit(data, model)
    assert result.converged, result.failure_reason

    theirs = float(reference["log_likelihood"])
    gap = abs(result.log_likelihood - theirs)

    # Scaled by sample size: a fixed absolute tolerance would be vacuous on a
    # 3000-respondent fixture and impossible on a small one.
    allowed = max(1.0, 0.001 * abs(theirs))
    assert gap < allowed, (
        f"{name}: log-likelihood {result.log_likelihood:.3f} vs mirt "
        f"{theirs:.3f} (gap {gap:.3f}, allowed {allowed:.3f})"
    )


@pytest.mark.parametrize("name", _reference_cases() or ["_none"])
def test_free_parameter_count_agrees_with_mirt(name: str) -> None:
    """Disagreement here silently corrupts every AIC and BIC in the product."""
    data, manifest, reference = _load(name)
    result = fit(data, ModelKey(manifest["model"]))

    assert result.converged
    assert result.n_free_parameters == reference["n_estimated_parameters"], (
        f"{name}: we count {result.n_free_parameters} free parameters, "
        f"mirt counts {reference['n_estimated_parameters']}"
    )
