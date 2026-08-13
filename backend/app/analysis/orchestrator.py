"""The one function that turns a table of responses into a full analysis.

Everything the worker needs is behind :func:`run_analysis`. Nothing above this
layer knows how a model is fitted or which diagnostics exist; nothing below it
knows about runs, users or queues.

Three properties this module is responsible for, none of which belong in the
individual statistics:

**A failed diagnostic must not fail the run.** Local independence bootstrapping
on a wide instrument can exhaust memory; DIF can be handed a grouping variable
with one usable group. Each diagnostic is attempted independently and a failure
is recorded as a failure, with its reason, in the output. What must never happen
is a run that reports fewer diagnostics than it attempted without saying so -
so the count of attempts and the list of failures are both in the result.

**The latent standard deviation has to travel.** Rasch and PCM leave the latent
variance free, so their parameters live on a metric where theta does not have
unit variance. Every downstream statistic that integrates over theta - item fit,
global fit, local independence, reliability, scoring - takes ``latent_sd``, and
passing the default of 1.0 for a Rasch fit puts the moments on a different
metric from the parameters and quietly makes every residual wrong. It is
threaded through from each fit explicitly.

**Choosing a model to diagnose is not choosing a winner.** The comparison
returns a dossier with no ``best_model`` field, deliberately. But item fit and
local independence have to be computed against *some* parameterisation, so one
model is designated the reference. That designation is recorded together with
its rationale and, when the candidates are statistically indistinguishable, an
explicit statement that the choice was near-arbitrary and that a different
reference could change which items are flagged.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.irt import (
    FitResult,
    ModelKey,
    ResponseMatrix,
    fit,
)
from app.psychometrics import (
    ScoreMethod,
    compare,
    consequence,
    global_fit,
    item_fit,
    reliability,
    score,
)
from app.psychometrics.assumptions import local_independence, unidimensionality
from app.psychometrics.dif import dif

from .serialise import to_jsonable
from .validate import validate

logger = logging.getLogger(__name__)

DEFAULT_SEED = 20260803

# One note per estimator, stated up front because the choice is not cosmetic: it
# moves the scores, the standard errors, the empirical reliability computed from
# them, and — for MAP and WLE — whether the extremes are estimable at all. A
# reader comparing two runs of the same data needs to know which was used and what
# it does, without having to know the literature.
_SCORE_METHOD_NOTES = {
    ScoreMethod.EAP: (
        "Respondents are scored by expected a posteriori (EAP) estimation: the "
        "mean of each respondent's posterior. Every respondent with at least one "
        "response gets a finite score, including perfect and zero scores, but the "
        "estimates are shrunk towards the population mean — most visibly at the "
        "extremes, where a perfect scorer is placed at a finite ability rather "
        "than at the infinity the likelihood alone implies."
    ),
    ScoreMethod.MAP: (
        "Respondents are scored by maximum a posteriori (MAP) estimation: the mode "
        "of each respondent's posterior rather than its mean. It shares EAP's "
        "shrinkage towards the population mean and differs from it wherever the "
        "posterior is skewed, which is most of the range for a respondent who "
        "answered few items."
    ),
    ScoreMethod.WLE: (
        "Respondents are scored by weighted likelihood estimation (Warm's WLE), "
        "which corrects the first-order bias of maximum likelihood without pulling "
        "estimates towards the population mean. That makes it the choice when "
        "individual scores are reported rather than aggregated — but its standard "
        "errors are larger than EAP's, and the correction is a bias correction "
        "rather than a prior, so extreme response patterns are estimated further "
        "out than EAP would place them."
    ),
}


@dataclass(frozen=True)
class DiagnosticFailure:
    diagnostic: str
    error: str


@dataclass
class AnalysisResult:
    """What the worker persists.

    ``fits`` are :class:`app.irt.FitResult` objects, mapped to rows upstream.
    ``diagnostics`` is already JSON-safe. ``notes`` are the run-level statements
    that belong on the front of a report.
    """

    fits: list[FitResult] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _attempt(
    name: str,
    fn: Callable[[], Any],
    failures: list[DiagnosticFailure],
) -> Any | None:
    """Run one diagnostic, converting a failure into a recorded one.

    Deliberately catches everything. A diagnostic is an independent claim about
    the data; one of them raising is a reason to omit that claim, not a reason
    to discard the fits and every other diagnostic alongside it. The traceback
    is logged because the stored reason is a one-line summary and an operator
    needs more than that.
    """

    try:
        return fn()
    except Exception as exc:
        logger.exception("diagnostic %s failed", name)
        failures.append(
            DiagnosticFailure(diagnostic=name, error=f"{type(exc).__name__}: {exc}")
        )
        return None


def _applicable(
    keys: list[ModelKey], data: ResponseMatrix
) -> tuple[list[ModelKey], list[str]]:
    """Drop models that cannot describe this data, with a reason for each."""

    notes: list[str] = []
    usable: list[ModelKey] = []
    max_categories = int(data.n_categories.max())

    for key in keys:
        if not key.is_polytomous and max_categories > 2:
            notes.append(
                f"{key.label} was requested but not fitted: it is a dichotomous "
                f"model and the data contains items with up to {max_categories} "
                "categories. Collapsing them to right/wrong would discard the "
                "distinctions the extra categories were written to capture."
            )
            continue
        usable.append(key)

    if usable and max_categories == 2:
        polytomous = [k for k in usable if k.is_polytomous]
        if polytomous:
            names = ", ".join(k.label for k in polytomous)
            notes.append(
                f"{names} were fitted to dichotomous data, where they reduce to "
                "their two-category special cases. Their parameters are "
                "interpretable but carry no information a dichotomous model "
                "does not already provide."
            )
    return usable, notes


def _reference(
    fits: dict[ModelKey, FitResult], dossier: Any | None
) -> tuple[ModelKey | None, str]:
    """Pick the model that item-level diagnostics are computed against."""

    converged = [key for key, result in fits.items() if result.converged]
    if not converged:
        return None, "No model converged, so no item-level diagnostics could be computed."

    if len(converged) == 1:
        only = converged[0]
        return only, (
            f"{only.label} is the only model that converged, so all item-level "
            "diagnostics are computed against it."
        )

    if dossier is not None and dossier.leader is not None and dossier.leader in fits:
        leader = dossier.leader
        if dossier.indistinguishable:
            return leader, (
                f"{leader.label} leads on held-out predictive log-likelihood, but "
                "the leading models are statistically indistinguishable on that "
                "criterion. It is used as the reference for item-level "
                "diagnostics because one had to be chosen, not because it is "
                "better. A different reference could change which items are "
                "flagged, and the comparison dossier should be read before "
                "treating any of these flags as a property of the items."
            )
        return leader, (
            f"{leader.label} leads on held-out predictive log-likelihood and is "
            "used as the reference for item-level diagnostics. This is a choice "
            "of vantage point, not a verdict: the comparison dossier reports "
            "every criterion and does not name a winner."
        )

    fallback = converged[0]
    return fallback, (
        f"{fallback.label} is used as the reference for item-level diagnostics "
        "because no comparison was available to order the candidates."
    )


def run_analysis(
    data: pd.DataFrame,
    models: Sequence[str | ModelKey],
    *,
    groups: pd.DataFrame | pd.Series | None = None,
    seed: int | None = None,
    score_method: str | ScoreMethod = ScoreMethod.EAP,
) -> AnalysisResult:
    """Fit every requested model and compute the full diagnostic picture.

    ``data`` is one column per item, one row per respondent, containing the raw
    response codes as uploaded. ``groups`` is optional and, when present,
    supplies the grouping variables DIF is screened over.

    ``score_method`` chooses the person-score estimator. It is a real choice with
    consequences beyond the scores themselves — the empirical reliability and the
    score distribution both follow from it — so which one was used is recorded in
    the output and stated in the notes rather than left to be inferred.

    The result is always a complete description of what happened, including when
    that description is "nothing converged". There is no path on which this
    function returns partial results that look whole.
    """

    started = time.perf_counter()
    seed = DEFAULT_SEED if seed is None else int(seed)
    method = ScoreMethod(score_method)
    notes: list[str] = []
    failures: list[DiagnosticFailure] = []

    validated = validate(data)
    notes.extend(validated.notes)
    matrix = validated.data

    requested = [ModelKey(m) if isinstance(m, str) else m for m in models]
    if not requested:
        raise ValueError("no models were requested")
    # Deduplicated but order-preserving: the request order is the reader's
    # order, and `compare` refuses duplicates outright.
    seen: set[ModelKey] = set()
    requested = [k for k in requested if not (k in seen or seen.add(k))]

    usable, applicability_notes = _applicable(requested, matrix)
    notes.extend(applicability_notes)
    if not usable:
        raise ValueError(
            "none of the requested models can be fitted to this data: "
            + " ".join(applicability_notes)
        )

    fits: dict[ModelKey, FitResult] = {}
    for key in usable:
        result = _attempt(f"fit:{key.value}", lambda k=key: fit(matrix, k), failures)
        if result is not None:
            fits[key] = result

    unconverged = [k.label for k, r in fits.items() if not r.converged]
    if unconverged:
        notes.append(
            f"{', '.join(unconverged)} did not converge. No parameters are "
            "reported for them and they take no part in any diagnostic; an "
            "unconverged fit has no estimates to report, only a failure to."
        )

    converged = {k: r for k, r in fits.items() if r.converged}

    # --- comparison -----------------------------------------------------
    dossier = None
    if len(converged) >= 2:
        dossier = _attempt(
            "comparison",
            lambda: compare(matrix, list(converged), seed=seed),
            failures,
        )
        notes.append(
            "Models are compared on k-fold held-out predictive log-likelihood, "
            "with information criteria and likelihood-ratio tests reported "
            "alongside. Where the criteria disagree, the disagreement is "
            "reported rather than resolved."
        )
    elif len(converged) == 1:
        notes.append(
            "Only one model was fitted, so there is no comparison. A single "
            "model's fit statistics say how well it describes the data, not "
            "whether a different model would describe it better."
        )

    reference, rationale = _reference(fits, dossier)
    if reference is not None:
        notes.append(rationale)

    notes.append(_SCORE_METHOD_NOTES[method])

    # --- assumptions ----------------------------------------------------
    assumptions: dict[str, Any] = {}
    assumptions["unidimensionality"] = _attempt(
        "unidimensionality",
        lambda: unidimensionality(matrix, seed=seed),
        failures,
    )

    if reference is not None:
        ref_fit = fits[reference]
        assumptions["local_independence"] = _attempt(
            "local_independence",
            lambda: local_independence(
                matrix,
                ref_fit.item_parameters,
                latent_sd=ref_fit.latent_sd,
                seed=seed,
            ),
            failures,
        )

    # --- per-model diagnostics ------------------------------------------
    per_model: dict[str, Any] = {}
    scores_summary: dict[str, Any] | None = None
    # Kept per model rather than only for the reference, because consequence
    # analysis is a comparison between what each model would decide and cannot be
    # reconstructed from one model's summary.
    all_scores: dict[ModelKey, Any] = {}

    for key, result in converged.items():
        entry: dict[str, Any] = {}
        entry["item_fit"] = _attempt(
            f"item_fit:{key.value}",
            lambda r=result: item_fit(
                matrix, r.item_parameters, latent_sd=r.latent_sd
            ),
            failures,
        )
        entry["global_fit"] = _attempt(
            f"global_fit:{key.value}",
            lambda r=result: global_fit(
                matrix, r.item_parameters, latent_sd=r.latent_sd
            ),
            failures,
        )

        person_scores = _attempt(
            f"scores:{key.value}",
            lambda r=result: score(
                matrix,
                r.item_parameters,
                method,
                latent_sd=r.latent_sd,
            ),
            failures,
        )
        entry["reliability"] = _attempt(
            f"reliability:{key.value}",
            lambda r=result, s=person_scores: reliability(
                r.item_parameters, latent_sd=r.latent_sd, scores=s
            ),
            failures,
        )

        if person_scores is not None:
            all_scores[key] = person_scores
        if key == reference and person_scores is not None:
            scores_summary = _score_summary(person_scores)

        per_model[key.value] = entry

    # --- consequence analysis -------------------------------------------
    consequences = None
    if len(all_scores) >= 2:
        consequences = _attempt(
            "consequence",
            lambda: consequence(all_scores),
            failures,
        )
        if consequences is not None:
            notes.append(
                "Consequence analysis reports how much the candidate models "
                "disagree about individual respondents rather than about fit. It "
                "is the answer to a question the comparison dossier deliberately "
                "does not settle: if the models would rank and select the same "
                "people, the choice between them changes no conclusion, and that "
                "is worth more than a winner nobody can defend."
            )

    # --- DIF ------------------------------------------------------------
    dif_report = None
    if groups is not None and reference is not None:
        dif_report = _run_dif(
            matrix, fits[reference], groups, validated.n_persons_dropped, failures, notes
        )

    diagnostics = {
        "sample": {
            "n_persons": matrix.n_persons,
            "n_items": matrix.n_items,
            "n_categories": matrix.n_categories.tolist(),
            "missing_rate": float((matrix.values < 0).mean()),
            "is_polytomous": matrix.is_polytomous,
        },
        "validation": {
            "recoding": validated.recoding,
            "dropped_items": validated.dropped,
            "n_persons_dropped": validated.n_persons_dropped,
        },
        "reference_model": reference.value if reference else None,
        "reference_model_rationale": rationale,
        # Recorded even when scoring failed, so a reader can tell "WLE was asked
        # for and could not be computed" from "EAP was used".
        "score_method": method.value,
        "comparison": dossier,
        "consequence": consequences,
        "assumptions": assumptions,
        "per_model": per_model,
        "person_scores": scores_summary,
        "dif": dif_report,
        "failures": failures,
        "n_diagnostics_failed": len(failures),
        "seed": seed,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }

    if failures:
        notes.append(
            f"{len(failures)} diagnostics could not be computed and are listed "
            "with their reasons. The statistics they would have produced are "
            "absent from this report; they are not zero and not reassuring."
        )

    return AnalysisResult(
        fits=[fits[k] for k in usable if k in fits],
        diagnostics=to_jsonable(diagnostics),
        notes=notes,
    )


def _score_summary(scores: Any) -> dict[str, Any]:
    """Summarise person scores without persisting one row per respondent.

    The full theta vector is a per-respondent result and belongs behind its own
    endpoint, not inlined into every report payload. What is kept is the shape
    of the distribution and, importantly, how many respondents could not be
    scored at all.
    """

    theta = np.asarray(scores.theta, dtype=float)
    finite = theta[np.isfinite(theta)]
    unscorable = int(theta.size - finite.size)
    summary: dict[str, Any] = {
        "method": scores.method,
        "n_scored": int(finite.size),
        "n_unscorable": unscorable,
    }
    if finite.size:
        summary.update(
            mean=float(finite.mean()),
            sd=float(finite.std(ddof=1)) if finite.size > 1 else None,
            minimum=float(finite.min()),
            maximum=float(finite.max()),
            percentiles={
                str(p): float(np.percentile(finite, p)) for p in (5, 25, 50, 75, 95)
            },
        )
    if unscorable:
        summary["note"] = (
            f"{unscorable} respondents could not be scored, having answered no "
            "items. They are reported as absent rather than assigned the prior "
            "mean, which would place them at the centre of the distribution as "
            "though they had been measured there."
        )
    return summary


def _run_dif(
    matrix: ResponseMatrix,
    ref_fit: FitResult,
    groups: pd.DataFrame | pd.Series,
    n_persons_dropped: int,
    failures: list[DiagnosticFailure],
    notes: list[str],
) -> dict[str, Any] | None:
    """Screen for DIF over each supplied grouping variable."""

    frame = groups.to_frame() if isinstance(groups, pd.Series) else groups
    if frame.shape[1] == 0:
        return None

    if frame.shape[0] != matrix.n_persons:
        if n_persons_dropped:
            # Validation removed respondents; the grouping column still has the
            # original rows and cannot be realigned here without the mask.
            notes.append(
                "DIF was not screened: respondents were excluded during "
                "validation and the grouping variable no longer aligns with the "
                "response matrix. Aligning them by position would silently "
                "attach the wrong group to every respondent after the first "
                "exclusion."
            )
        else:
            notes.append(
                f"DIF was not screened: the grouping variable has "
                f"{frame.shape[0]} rows for {matrix.n_persons} respondents."
            )
        return None

    out: dict[str, Any] = {}
    for column in frame.columns:
        name = str(column)
        labels = frame[column]
        if labels.nunique(dropna=True) < 2:
            notes.append(
                f"DIF was not screened over {name!r}: it has fewer than two "
                "distinct groups."
            )
            continue
        report = _attempt(
            f"dif:{name}",
            lambda values=labels: dif(
                matrix, ref_fit.item_parameters, values.to_numpy()
            ),
            failures,
        )
        if report is not None:
            out[name] = report

    if out:
        notes.append(
            "DIF results are a screen, not a verdict. An item flagged here "
            "behaves differently between groups conditional on the trait; "
            "deciding whether that difference is bias requires knowing what the "
            "item is asking, which no statistic in this report can see."
        )
    return out or None
