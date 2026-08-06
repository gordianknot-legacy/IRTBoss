"""
Model comparison as a dossier of evidence, not a single recommended model.

The product this replaces promised "one recommended model, always". That
promise cannot be kept honestly, and the reasons are documented rather than
asserted:

* **BIC is directionally biased against the 3PL.** Whittaker, Chang and Dodd
  (2012) found BIC never selected the 3PL correctly in any condition they
  examined. The cause is structural, not a small-sample artefact: ``c`` is
  weakly identified, so it buys little likelihood, so a parsimony penalty eats
  it. A tool that reports "2PL" on multiple-choice data may be reporting its
  own penalty function rather than a property of the data.
* **The 2PL-vs-3PL likelihood-ratio test is invalid.** The null ``c = 0`` sits
  on the boundary of the parameter space, which violates a regularity condition
  of Wilks' theorem, so the statistic is not chi-square (Brown, Templin & Cohen
  2015). This module *refuses* that test rather than printing a p-value that is
  known to be wrong.
* **Delta-BIC has no sampling distribution.** An argmin treats a gap of 3 and a
  gap of 300 identically. "These models are not distinguishable here" has to be
  a first-class output, and no information criterion can ever produce it.

So the primary criterion is **k-fold cross-validated held-out predictive log
-likelihood**, split by respondent. Each fold fits the model on the training
respondents and then scores the held-out respondents' full response patterns
under those item parameters, marginalising the latent trait over the
quadrature prior the fit produced. This works for non-nested comparisons, needs
no boundary-valid reference distribution, and - unlike an information criterion
- comes with a *standard error*, which is what makes an indistinguishability
verdict possible at all.

Comparisons between models are made on **paired per-fold differences**: the
same respondents are held out for both models in each fold, so the fold-to-fold
variation that both models share cancels. Comparing two independent means would
throw that pairing away and widen every interval for no reason.

AIC, BIC and (for genuinely nested pairs only) the likelihood-ratio test are
reported as secondary evidence. Where they disagree with the held-out
likelihood or with each other, the disagreement is shown, because a disagreement
between criteria is itself the most informative thing available (Kang & Cohen
2007) and resolving it by fiat would be inventing a result.

Two notes on the nesting table. **Rasch and the 1PL are not nested in each
other**: Rasch fixes every slope at 1 and lets the latent variance float, the
1PL estimates one common slope and fixes the variance, and they place items on
different metrics with identical parameter counts. **GRM and GPCM are not
nested either** - they are different link functions on the same categories.
The Vuong test is the principled tool there; it is not implemented, because the
held-out predictive likelihood already answers the non-nested question with
fewer asymptotic assumptions, and Vuong's variance test would add a second
approximation for no extra information. That choice is stated in the refusal
rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import stats

from app.irt.em import MISSING, EMOptions, ResponseMatrix, fit
from app.irt.families import ItemParameters, ModelKey

from .information import category_probabilities

_FLOOR = 1e-12

# Criterion names, used as the row and column labels of the disagreement matrix.
CV = "held-out log-likelihood"
AIC = "AIC"
BIC = "BIC"


@dataclass(frozen=True)
class FoldResult:
    """One fold's held-out evidence for one model."""

    fold: int
    n_train: int
    n_test: int
    converged: bool
    log_likelihood: float | None      # total over the held-out respondents
    failure_reason: str | None = None


@dataclass(frozen=True)
class ModelEvidence:
    """Everything known about one candidate model."""

    model: ModelKey
    converged: bool

    # Primary criterion. ``cv_log_likelihood`` is the total held-out
    # log-likelihood across folds - every respondent is held out exactly once,
    # so it is a like-for-like total across models.
    cv_log_likelihood: float | None
    cv_per_respondent: float | None
    cv_standard_error: float | None
    folds: list[FoldResult] = field(default_factory=list)

    # Secondary criteria, from the fit to the full sample.
    log_likelihood: float | None = None
    n_free_parameters: int | None = None
    aic: float | None = None
    bic: float | None = None

    failure_reason: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.converged and self.cv_log_likelihood is not None


@dataclass(frozen=True)
class LikelihoodRatioTest:
    """A nested comparison, performed or explicitly refused.

    ``performed`` being ``False`` is a result, not an absence. It carries the
    reason the test would be invalid, which is more useful to a reader than a
    p-value that does not mean what it appears to mean.
    """

    restricted: ModelKey
    full: ModelKey
    performed: bool
    statistic: float | None = None
    df: int | None = None
    p_value: float | None = None
    refusal_reason: str | None = None


@dataclass(frozen=True)
class Disagreement:
    """Two criteria that name different models first."""

    criterion_a: str
    criterion_b: str
    first_a: ModelKey
    first_b: ModelKey


@dataclass(frozen=True)
class ComparisonDossier:
    """The full comparison. There is deliberately no ``best_model`` field."""

    ranked: list[ModelEvidence]                    # by held-out log-likelihood
    rankings: dict[str, list[ModelKey]]
    first_choice: dict[str, ModelKey]
    disagreements: list[Disagreement]
    likelihood_ratio_tests: list[LikelihoodRatioTest]

    indistinguishable: bool
    leader: ModelKey | None
    verdict: str

    n_folds: int
    seed: int
    notes: list[str] = field(default_factory=list)

    @property
    def criteria_agree(self) -> bool:
        return not self.disagreements


def compare(
    data: ResponseMatrix,
    models: list[ModelKey | str],
    *,
    folds: int = 5,
    seed: int = 20260803,
    options: EMOptions | None = None,
    n_points: int = 61,
    bound: float = 6.0,
) -> ComparisonDossier:
    """Build the comparison dossier for ``models`` on ``data``.

    Every model is fitted once on the full sample (for AIC, BIC and the
    likelihood-ratio ladder) and ``folds`` times on training subsets (for the
    held-out predictive likelihood). Models that fail to converge, or that do
    not apply to the data at all, are recorded with their reason rather than
    dropped silently.
    """
    keys = [ModelKey(m) if isinstance(m, str) else m for m in models]
    if len(set(keys)) != len(keys):
        raise ValueError("each model may appear only once")
    if len(keys) < 2:
        raise ValueError("a comparison needs at least two models")
    if folds < 2:
        raise ValueError("cross-validation needs at least two folds")
    if data.n_persons < folds * 2:
        raise ValueError(
            f"{data.n_persons} respondents cannot be split into {folds} folds"
        )

    # Standard errors are an expensive by-product this module never reads, and
    # the fold fits alone would pay for them k times over.
    base = options or EMOptions()
    quiet = EMOptions(
        max_cycles=base.max_cycles,
        tolerance=base.tolerance,
        quadrature_points=base.quadrature_points,
        quadrature_bound=base.quadrature_bound,
        m_step_max_iter=base.m_step_max_iter,
        compute_standard_errors=False,
        seed=base.seed,
    )

    assignments = _fold_assignments(data.n_persons, folds, seed)
    nodes = np.linspace(-bound, bound, n_points)

    notes: list[str] = list(_estimability_notes(data, keys))

    evidence: list[ModelEvidence] = []
    for key in keys:
        evidence.append(_evaluate(data, key, quiet, assignments, folds, nodes))

    usable = [e for e in evidence if e.usable]
    rankings, first_choice = _rankings(evidence)
    disagreements = _disagreements(first_choice)
    tests = _likelihood_ratio_tests(evidence)

    leader, runner_up, indistinguishable, verdict = _verdict(usable, folds)

    if len(usable) < len(evidence):
        notes.append(
            "Only "
            + ", ".join(e.model.label for e in usable)
            + " produced held-out likelihoods; the rest are reported with their "
            "failure reason and take no part in the ranking."
        )
    if disagreements:
        notes.append(
            f"{len(disagreements)} pair(s) of criteria name different models "
            "first. The disagreement is shown rather than resolved: no "
            "criterion here has a claim to arbitrate the others."
        )
    if runner_up is not None and indistinguishable:
        notes.append(
            "The held-out difference between the two leading models is within "
            "one standard error of the paired per-fold differences, so the data "
            "do not separate them. Choose on grounds outside this comparison - "
            "interpretability, an existing scale, or programme policy."
        )

    return ComparisonDossier(
        ranked=sorted(
            evidence,
            key=lambda e: (
                e.cv_log_likelihood is None,
                -(e.cv_log_likelihood or 0.0),
            ),
        ),
        rankings=rankings,
        first_choice=first_choice,
        disagreements=disagreements,
        likelihood_ratio_tests=tests,
        indistinguishable=indistinguishable,
        leader=leader,
        verdict=verdict,
        n_folds=folds,
        seed=seed,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Cross-validation
# --------------------------------------------------------------------------- #


def _fold_assignments(n_persons: int, folds: int, seed: int) -> np.ndarray:
    """Fold index per respondent.

    Splitting by respondent rather than by cell keeps every held-out response
    *pattern* intact, which is what the marginal likelihood is a probability of.
    Holding out scattered cells would instead score partial patterns, which is a
    different and weaker question.
    """
    rng = np.random.default_rng(seed)
    order = rng.permutation(n_persons)
    assignments = np.empty(n_persons, dtype=int)
    for f, block in enumerate(np.array_split(order, folds)):
        assignments[block] = f
    return assignments


def _evaluate(
    data: ResponseMatrix,
    model: ModelKey,
    options: EMOptions,
    assignments: np.ndarray,
    folds: int,
    nodes: np.ndarray,
) -> ModelEvidence:
    try:
        full = fit(data, model, options)
    except ValueError as exc:
        # A dichotomous model on polytomous data, or the reverse. Not a bug and
        # not a fit failure - the model simply does not apply here.
        return ModelEvidence(
            model=model,
            converged=False,
            cv_log_likelihood=None,
            cv_per_respondent=None,
            cv_standard_error=None,
            failure_reason=str(exc),
        )

    if not full.converged:
        return ModelEvidence(
            model=model,
            converged=False,
            cv_log_likelihood=None,
            cv_per_respondent=None,
            cv_standard_error=None,
            failure_reason=full.failure_reason,
        )

    fold_results: list[FoldResult] = []
    for f in range(folds):
        test_rows = assignments == f
        train = _subset(data, ~test_rows)
        held = data.values[test_rows]
        try:
            fitted = fit(train, model, options)
        except ValueError as exc:
            fold_results.append(
                FoldResult(f, int((~test_rows).sum()), int(test_rows.sum()),
                           False, None, str(exc))
            )
            continue
        if not fitted.converged:
            fold_results.append(
                FoldResult(f, train.n_persons, int(test_rows.sum()),
                           False, None, fitted.failure_reason)
            )
            continue
        value = _marginal_log_likelihood(
            held, fitted.item_parameters, fitted.latent_sd, nodes
        )
        fold_results.append(
            FoldResult(f, train.n_persons, int(test_rows.sum()), True, value)
        )

    complete = [f for f in fold_results if f.log_likelihood is not None]
    if len(complete) < folds:
        failed = folds - len(complete)
        return ModelEvidence(
            model=model,
            converged=True,
            cv_log_likelihood=None,
            cv_per_respondent=None,
            cv_standard_error=None,
            folds=fold_results,
            log_likelihood=full.log_likelihood,
            n_free_parameters=full.n_free_parameters,
            aic=full.aic,
            bic=full.bic,
            failure_reason=(
                f"{failed} of {folds} training folds did not converge, so the "
                "held-out likelihood is not comparable across models"
            ),
        )

    totals = np.array([f.log_likelihood for f in complete], dtype=float)
    n_held = sum(f.n_test for f in complete)
    # SE of the sum of k fold totals, treating folds as independent draws. It is
    # deliberately the SE of the *total*, so it is on the same scale as the
    # differences the verdict is built from.
    se = float(np.sqrt(folds) * totals.std(ddof=1)) if folds > 1 else None

    return ModelEvidence(
        model=model,
        converged=True,
        cv_log_likelihood=float(totals.sum()),
        cv_per_respondent=float(totals.sum() / max(n_held, 1)),
        cv_standard_error=se,
        folds=fold_results,
        log_likelihood=full.log_likelihood,
        n_free_parameters=full.n_free_parameters,
        aic=full.aic,
        bic=full.bic,
        notes=list(full.notes),
    )


def _subset(data: ResponseMatrix, rows: np.ndarray) -> ResponseMatrix:
    return ResponseMatrix(
        values=data.values[rows],
        item_ids=list(data.item_ids),
        n_categories=data.n_categories.copy(),
    )


def _marginal_log_likelihood(
    values: np.ndarray,
    items: list[ItemParameters],
    latent_sd: float,
    nodes: np.ndarray,
) -> float:
    """Log P(held-out patterns | item parameters), theta integrated out.

    The latent standard deviation comes from the fit, not from an assumption of
    1.0. Rasch and PCM place items on a metric whose variance was estimated;
    scoring them against a unit-variance prior would charge them for a scaling
    they never claimed.
    """
    prior = np.exp(-0.5 * (nodes / float(latent_sd)) ** 2)
    prior /= prior.sum()

    log_lik = np.zeros((values.shape[0], nodes.size), dtype=float)
    for j, params in enumerate(items):
        column = values[:, j]
        observed = column != MISSING
        if not observed.any():
            continue
        log_p = np.log(np.clip(category_probabilities(params, nodes), _FLOOR, None))
        log_lik[observed] += log_p[:, column[observed]].T

    joint = log_lik + np.log(np.clip(prior, 1e-300, None))[None, :]
    peak = joint.max(axis=1, keepdims=True)
    return float(np.sum(peak[:, 0] + np.log(np.exp(joint - peak).sum(axis=1))))


# --------------------------------------------------------------------------- #
# Rankings and disagreement
# --------------------------------------------------------------------------- #


def _rankings(
    evidence: list[ModelEvidence],
) -> tuple[dict[str, list[ModelKey]], dict[str, ModelKey]]:
    """Each criterion's ordering, best first, over the models it can score."""
    orders: dict[str, list[ModelKey]] = {}

    def order(name: str, value, better_is_larger: bool) -> None:
        scored = [(value(e), e.model) for e in evidence if value(e) is not None]
        if not scored:
            return
        scored.sort(key=lambda pair: -pair[0] if better_is_larger else pair[0])
        orders[name] = [model for _, model in scored]

    order(CV, lambda e: e.cv_log_likelihood if e.usable else None, True)
    order(AIC, lambda e: e.aic, False)
    order(BIC, lambda e: e.bic, False)

    return orders, {name: models[0] for name, models in orders.items()}


def _disagreements(first_choice: dict[str, ModelKey]) -> list[Disagreement]:
    names = list(first_choice)
    out: list[Disagreement] = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            if first_choice[a] is not first_choice[b]:
                out.append(
                    Disagreement(a, b, first_choice[a], first_choice[b])
                )
    return out


def _verdict(
    usable: list[ModelEvidence], folds: int
) -> tuple[ModelKey | None, ModelKey | None, bool, str]:
    if not usable:
        return None, None, False, (
            "No model produced a held-out predictive likelihood, so no "
            "comparison is possible."
        )
    if len(usable) == 1:
        only = usable[0]
        return only.model, None, False, (
            f"Only {only.model.label} could be evaluated on held-out data; "
            "with a single candidate there is nothing to compare it against."
        )

    ordered = sorted(usable, key=lambda e: -(e.cv_log_likelihood or 0.0))
    leader, runner_up = ordered[0], ordered[1]

    difference, se = _paired_difference(leader, runner_up)
    if se is None or se <= 0:
        # Zero spread across folds with a zero margin means the two fits are
        # reparameterisations of each other, which is the strongest possible
        # form of indistinguishable rather than a missing uncertainty estimate.
        if abs(difference) < 1e-6:
            return leader.model, runner_up.model, True, (
                f"Models indistinguishable: {leader.model.label} and "
                f"{runner_up.model.label} produce the same held-out "
                "log-likelihood in every fold. They are reparameterisations of "
                "one another on this data and cannot be separated by fit."
            )
        return leader.model, runner_up.model, False, (
            f"{leader.model.label} has the higher held-out log-likelihood by "
            f"{difference:.1f}, but the fold-to-fold variation could not be "
            "estimated, so the margin carries no uncertainty statement."
        )

    if difference <= se:
        return leader.model, runner_up.model, True, (
            f"Models indistinguishable: {leader.model.label} and "
            f"{runner_up.model.label} differ by {difference:.1f} in held-out "
            f"log-likelihood, within the {se:.1f} standard error of the paired "
            f"per-fold differences across {folds} folds. This comparison does "
            "not identify a better model."
        )

    return leader.model, runner_up.model, False, (
        f"{leader.model.label} predicts held-out responses better than "
        f"{runner_up.model.label} by {difference:.1f} in log-likelihood, "
        f"{difference / se:.1f} times the {se:.1f} standard error of the paired "
        f"per-fold differences. Secondary criteria and the fit diagnostics still "
        "apply; this is one line of evidence, not a decision."
    )


def _paired_difference(
    a: ModelEvidence, b: ModelEvidence
) -> tuple[float, float | None]:
    """Total held-out difference and the SE of that total, paired by fold."""
    by_fold_a = {f.fold: f.log_likelihood for f in a.folds}
    by_fold_b = {f.fold: f.log_likelihood for f in b.folds}
    shared = sorted(set(by_fold_a) & set(by_fold_b))
    differences = np.array(
        [by_fold_a[f] - by_fold_b[f] for f in shared], dtype=float
    )
    total = float(differences.sum())
    if differences.size < 2:
        return total, None
    return total, float(np.sqrt(differences.size) * differences.std(ddof=1))


# --------------------------------------------------------------------------- #
# The nested ladder
# --------------------------------------------------------------------------- #

# ``None`` means the test is valid; a string is the reason it is refused. Every
# pair the product can produce is listed, so an unlisted pair is a genuinely
# unconsidered combination rather than a silent default.
_BOUNDARY = (
    "The 3PL restricts to the {other} by setting c = 0 for every item, which "
    "sits on the boundary of the parameter space. Wilks' theorem does not "
    "apply, the statistic is not chi-square, and any p-value printed for it "
    "would be wrong. Use the held-out predictive log-likelihood instead."
)

_LRT_RULES: dict[frozenset[ModelKey], str | None] = {
    frozenset({ModelKey.RASCH, ModelKey.ONE_PL}): (
        "Rasch and the 1PL are not nested. Rasch fixes every slope at 1 and "
        "estimates the latent variance; the 1PL estimates one common slope and "
        "fixes the variance. They have the same number of free parameters and "
        "place items on different metrics, so there is no restriction to test."
    ),
    frozenset({ModelKey.ONE_PL, ModelKey.TWO_PL}): None,
    frozenset({ModelKey.RASCH, ModelKey.TWO_PL}): None,
    frozenset({ModelKey.TWO_PL, ModelKey.THREE_PL}): _BOUNDARY.format(other="2PL"),
    frozenset({ModelKey.ONE_PL, ModelKey.THREE_PL}): _BOUNDARY.format(other="1PL"),
    frozenset({ModelKey.RASCH, ModelKey.THREE_PL}): _BOUNDARY.format(other="Rasch"),
    frozenset({ModelKey.PCM, ModelKey.GPCM}): None,
    frozenset({ModelKey.GRM, ModelKey.GPCM}): (
        "The GRM and the GPCM are not nested - they are different link "
        "functions on the same categories, neither a restriction of the other. "
        "The Vuong test is the principled tool and is not implemented here: "
        "the held-out predictive log-likelihood answers the same question with "
        "one fewer asymptotic approximation, and is reported above."
    ),
    frozenset({ModelKey.PCM, ModelKey.GRM}): (
        "The PCM and the GRM are not nested; they are different link functions "
        "on the same categories. See the held-out predictive log-likelihood."
    ),
}


def _likelihood_ratio_tests(
    evidence: list[ModelEvidence],
) -> list[LikelihoodRatioTest]:
    """One entry per model pair, performed or refused with a reason."""
    fitted = [e for e in evidence if e.log_likelihood is not None]
    out: list[LikelihoodRatioTest] = []

    for i, a in enumerate(fitted):
        for b in fitted[i + 1 :]:
            # The restricted model is the one with fewer free parameters; ties
            # are ordered by model key so the output is deterministic.
            pair = sorted(
                (a, b),
                key=lambda e: (e.n_free_parameters or 0, e.model.value),
            )
            restricted, full = pair
            rule = frozenset({restricted.model, full.model})

            if rule not in _LRT_RULES:
                out.append(
                    LikelihoodRatioTest(
                        restricted.model, full.model, performed=False,
                        refusal_reason=(
                            f"{restricted.model.label} and {full.model.label} "
                            "are not a nested pair this module recognises, so "
                            "no likelihood-ratio test is defined for them."
                        ),
                    )
                )
                continue

            reason = _LRT_RULES[rule]
            if reason is not None:
                out.append(
                    LikelihoodRatioTest(
                        restricted.model, full.model,
                        performed=False, refusal_reason=reason,
                    )
                )
                continue

            df = (full.n_free_parameters or 0) - (restricted.n_free_parameters or 0)
            statistic = 2.0 * (
                (full.log_likelihood or 0.0) - (restricted.log_likelihood or 0.0)
            )
            if df < 1:
                out.append(
                    LikelihoodRatioTest(
                        restricted.model, full.model, performed=False,
                        refusal_reason=(
                            f"the two fits have the same number of free "
                            f"parameters ({full.n_free_parameters}), leaving no "
                            "degrees of freedom to test"
                        ),
                    )
                )
                continue

            out.append(
                LikelihoodRatioTest(
                    restricted.model, full.model, performed=True,
                    statistic=float(statistic), df=int(df),
                    p_value=float(stats.chi2.sf(max(statistic, 0.0), df)),
                )
            )
    return out


# --------------------------------------------------------------------------- #
# Estimability
# --------------------------------------------------------------------------- #


def _estimability_notes(
    data: ResponseMatrix, models: list[ModelKey]
) -> list[str]:
    """Warn where a candidate is being asked for more than the data can support.

    Hulin, Lissak and Drasgow's minima for the 3PL are a *joint* requirement on
    test length and sample size - roughly 60 items with 1,000 respondents, or 30
    with 2,000 - not a threshold on N alone. Reported as a caveat rather than a
    hard exclusion, because the comparison itself is what shows whether the
    extra parameter earned anything.
    """
    notes: list[str] = []
    if ModelKey.THREE_PL in models:
        n, j = data.n_persons, data.n_items
        if not ((j >= 60 and n >= 1000) or (j >= 30 and n >= 2000)):
            notes.append(
                f"The 3PL is entered with {j} items and {n} respondents, below "
                "the joint minimum for stable guessing estimates (about 60 "
                "items with 1,000 respondents, or 30 with 2,000). Its "
                "parameters carry a Beta(5, 17) prior, so its likelihood is "
                "penalised and its position in this comparison is provisional."
            )
    return notes


__all__ = [
    "AIC",
    "BIC",
    "CV",
    "ComparisonDossier",
    "Disagreement",
    "FoldResult",
    "LikelihoodRatioTest",
    "ModelEvidence",
    "compare",
]
