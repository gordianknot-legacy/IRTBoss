"""Consequence analysis: does the model choice change any decision?

ARCHITECTURE §3.3 item 5, after Robitzsch (2022). The comparison dossier answers
"which model describes the data better", declines to name a winner, and can leave
a reader with a question it does not address: *does it matter?* If two models
place the same respondents in the same order, with the same precision, and select
the same people at the same cut, then the selection question is moot and saying so
is worth more than a verdict nobody can defend.

This is deliberately not a fit statistic. Every quantity here is a difference
between two models' *outputs* over the same respondents, which is the thing a
programme actually lives with.

**The metric problem, and what is done about it.** Rasch and PCM leave the latent
variance free, so their θ is on a different scale from a 2PL's. Comparing raw θ
across models would therefore measure the identification convention rather than
any disagreement, and would report a large "consequence" for two models that
ranked every respondent identically. So:

* **Correlation and rank agreement are reported raw.** Both are invariant under
  the linear transformations that separate these metrics, so no adjustment is
  needed and none is applied.
* **Differences are reported after standardising each model's θ** to zero mean
  and unit standard deviation over the respondents compared. Units are therefore
  "standard deviations of this sample", and what is being compared is *relative
  standing*, not absolute location — because absolute location is not comparable
  across identifications, and pretending otherwise is how a metric artefact ends
  up in a report as a finding. Standard errors are divided by the same scale
  factor, so an SE ratio stays interpretable.
* **Classification is by selection rate, not by a θ cut.** A fixed θ cut is not
  transferable between metrics either. Taking "the top 10% under each model" holds
  the decision fixed and asks who changes hands, which is the question a
  programme with a quota has, and is invariant to the scale entirely.

**No cut score is invented.** The selection rates below are not policy: they are
a spread of plausible decision points, and the report says so. A caller who has a
real cut can pass its selection rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

import numpy as np

from app.irt import ModelKey

from .scoring import PersonScores

# Selection rates the classification comparison is evaluated at, as proportions
# selected from the top. Chosen to span the range where a cut is usually placed —
# a bursary, a pass mark, a median split — because reclassification depends on how
# dense the distribution is where the cut falls, and one rate would hide that.
DEFAULT_SELECTION_RATES: tuple[float, ...] = (0.10, 0.25, 0.50)

# Thresholds for the stability verdict. These are conventions adopted for this
# report and not standards from anywhere: no literature fixes a reclassification
# rate at which a model choice becomes consequential, because the answer depends
# on what the decision costs. They are stated in the verdict alongside the
# computed values, so a reader who disagrees with them can apply their own to the
# same numbers.
STABLE_MIN_CORRELATION = 0.99
STABLE_MAX_P95_DIFFERENCE = 0.10        # sample SD units
STABLE_MAX_RECLASSIFIED = 0.05          # proportion of those classified


@dataclass(frozen=True)
class Reclassification:
    """How many respondents change side of one cut when the model changes.

    Both selection counts are reported, not one. They can differ, and the reason
    matters: a Rasch fit scores by sum score, so many respondents tie exactly, and
    a tie group straddling the cut is taken whole rather than split. When the two
    counts differ, part of ``n_reclassified`` is that boundary and not a
    disagreement about anybody's standing — and the difference is itself worth
    seeing, because it says the cut is not decidable at that rate under that model.
    """

    selection_rate: float
    n_selected_a: int
    n_selected_b: int
    n_reclassified: int
    proportion_reclassified: float | None
    # Cohen's κ for the two-by-two agreement. Reported alongside the raw count
    # because κ corrects for the agreement that a common selection rate produces
    # by construction: at a 50% cut, two unrelated models already agree half the
    # time.
    kappa: float | None


@dataclass(frozen=True)
class PairwiseConsequence:
    """One pair of models, compared on what they would do rather than on fit."""

    model_a: str
    model_b: str
    n_compared: int

    pearson_r: float | None
    spearman_rho: float | None

    # All in standard deviations of this sample. See the module docstring.
    mean_absolute_difference: float | None
    rms_difference: float | None
    p95_absolute_difference: float | None
    max_absolute_difference: float | None

    # Median of SE_b / SE_a after the same standardisation. Above 1 means model B
    # reports less precision for the same respondents.
    se_ratio_median: float | None

    reclassification: list[Reclassification] = field(default_factory=list)

    JSON_PROPERTIES = ("max_proportion_reclassified",)

    @property
    def max_proportion_reclassified(self) -> float | None:
        values = [
            r.proportion_reclassified
            for r in self.reclassification
            if r.proportion_reclassified is not None
        ]
        return max(values) if values else None


@dataclass(frozen=True)
class ConsequenceReport:
    """The answer to "does the model choice change anything here?"."""

    models: list[str]
    n_respondents_compared: int
    score_method: str
    selection_rates: list[float]
    pairs: list[PairwiseConsequence]

    # ``None`` when there was nothing to compare — one model, or no respondent
    # scored under two of them. Absence is not stability.
    stable: bool | None
    verdict: str
    notes: list[str] = field(default_factory=list)


def _standardise(theta: np.ndarray) -> tuple[np.ndarray, float]:
    """Centre and scale, returning the scale used so SEs can follow it."""

    sd = float(np.std(theta, ddof=1)) if theta.size > 1 else 0.0
    if not np.isfinite(sd) or sd <= 0:
        # A degenerate θ vector — every respondent identical — has no scale to
        # divide by. Centring alone keeps the differences finite and honest;
        # they are then in raw logits, and the note says so.
        return theta - float(np.mean(theta)), 1.0
    return (theta - float(np.mean(theta))) / sd, sd


def _spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    """Rank correlation without pulling in scipy.stats for one number."""

    if a.size < 3:
        return None
    ranks_a = np.argsort(np.argsort(a)).astype(float)
    ranks_b = np.argsort(np.argsort(b)).astype(float)
    return _pearson(ranks_a, ranks_b)


def _pearson(a: np.ndarray, b: np.ndarray) -> float | None:
    if a.size < 3:
        return None
    sd_a = float(np.std(a))
    sd_b = float(np.std(b))
    if sd_a <= 0 or sd_b <= 0:
        return None
    value = float(np.corrcoef(a, b)[0, 1])
    return value if np.isfinite(value) else None


def _kappa(selected_a: np.ndarray, selected_b: np.ndarray) -> float | None:
    """Cohen's κ for two binary classifications of the same respondents."""

    n = selected_a.size
    if n == 0:
        return None
    observed = float(np.mean(selected_a == selected_b))
    p_a = float(np.mean(selected_a))
    p_b = float(np.mean(selected_b))
    expected = p_a * p_b + (1.0 - p_a) * (1.0 - p_b)
    if expected >= 1.0:
        # Both models selected everyone, or nobody. Agreement is total and κ is
        # undefined rather than perfect: there is no variation to agree about.
        return None
    return (observed - expected) / (1.0 - expected)


def _select_top(theta: np.ndarray, rate: float) -> np.ndarray:
    """Boolean mask for the top ``rate`` of respondents by θ.

    Ties at the boundary are resolved by taking the whole tied group, so the
    selected count can exceed the nominal one. That is the honest resolution:
    splitting a tie arbitrarily would report a reclassification caused by
    ``argsort`` order rather than by the model.
    """

    n = theta.size
    k = round(rate * n)
    if k <= 0 or k >= n:
        return np.zeros(n, dtype=bool)
    cut = float(np.sort(theta)[n - k])
    return theta >= cut


def consequence(
    scores: dict[ModelKey | str, PersonScores],
    *,
    selection_rates: tuple[float, ...] | list[float] = DEFAULT_SELECTION_RATES,
) -> ConsequenceReport:
    """Compare what each model would decide about the same respondents.

    ``scores`` maps a model to the person scores computed under it. They must all
    come from the same respondents in the same order, which is what the
    orchestrator guarantees by scoring one response matrix.
    """

    labels = {
        key: (key.value if isinstance(key, ModelKey) else str(key)) for key in scores
    }
    ordered = list(scores)
    notes: list[str] = []

    method = ""
    if ordered:
        first = scores[ordered[0]]
        method = getattr(first.method, "value", str(first.method))

    if len(ordered) < 2:
        return ConsequenceReport(
            models=[labels[k] for k in ordered],
            n_respondents_compared=0,
            score_method=method,
            selection_rates=list(selection_rates),
            pairs=[],
            stable=None,
            verdict=(
                "Consequence analysis needs at least two models that converged and "
                "were scored. There is nothing here to compare, which is not the "
                "same as the model choice not mattering."
            ),
            notes=notes,
        )

    # One mask for the whole report, so every pair is compared over the same
    # respondents and the numbers are commensurable across pairs. A respondent
    # unscorable under any one model is excluded from all of them.
    finite = np.ones(np.asarray(scores[ordered[0]].theta).size, dtype=bool)
    for key in ordered:
        theta = np.asarray(scores[key].theta, dtype=float)
        finite &= np.isfinite(theta)
    n_compared = int(finite.sum())

    if n_compared < 3:
        return ConsequenceReport(
            models=[labels[k] for k in ordered],
            n_respondents_compared=n_compared,
            score_method=method,
            selection_rates=list(selection_rates),
            pairs=[],
            stable=None,
            verdict=(
                f"Only {n_compared} respondents could be scored under every model, "
                "which is too few to compare what the models would decide."
            ),
            notes=notes,
        )

    standardised: dict[ModelKey | str, np.ndarray] = {}
    scaled_errors: dict[ModelKey | str, np.ndarray] = {}
    degenerate: list[str] = []
    for key in ordered:
        theta = np.asarray(scores[key].theta, dtype=float)[finite]
        z, scale = _standardise(theta)
        standardised[key] = z
        if scale == 1.0 and float(np.std(theta, ddof=1) if theta.size > 1 else 0.0) <= 0:
            degenerate.append(labels[key])
        errors = np.asarray(scores[key].standard_error, dtype=float)[finite]
        scaled_errors[key] = errors / scale

    if degenerate:
        notes.append(
            f"{', '.join(degenerate)} produced the same score for every respondent, "
            "so there was no spread to standardise by and its differences below are "
            "in raw logits rather than sample standard deviations."
        )

    pairs: list[PairwiseConsequence] = []
    for key_a, key_b in combinations(ordered, 2):
        z_a, z_b = standardised[key_a], standardised[key_b]
        difference = z_b - z_a
        absolute = np.abs(difference)

        se_a, se_b = scaled_errors[key_a], scaled_errors[key_b]
        usable_se = np.isfinite(se_a) & np.isfinite(se_b) & (se_a > 0)
        se_ratio = (
            float(np.median(se_b[usable_se] / se_a[usable_se]))
            if usable_se.any()
            else None
        )

        reclassification = []
        for rate in selection_rates:
            mask_a = _select_top(z_a, float(rate))
            mask_b = _select_top(z_b, float(rate))
            changed = int(np.sum(mask_a != mask_b))
            selected = int(mask_a.sum())
            reclassification.append(
                Reclassification(
                    selection_rate=float(rate),
                    n_selected_a=selected,
                    n_selected_b=int(mask_b.sum()),
                    n_reclassified=changed,
                    proportion_reclassified=(
                        changed / z_a.size if z_a.size else None
                    ),
                    kappa=_kappa(mask_a, mask_b),
                )
            )

        pairs.append(
            PairwiseConsequence(
                model_a=labels[key_a],
                model_b=labels[key_b],
                n_compared=n_compared,
                pearson_r=_pearson(z_a, z_b),
                spearman_rho=_spearman(z_a, z_b),
                mean_absolute_difference=float(np.mean(absolute)),
                rms_difference=float(np.sqrt(np.mean(difference**2))),
                p95_absolute_difference=float(np.percentile(absolute, 95)),
                max_absolute_difference=float(np.max(absolute)),
                se_ratio_median=se_ratio,
                reclassification=reclassification,
            )
        )

    tied = [
        f"{p.model_a} vs {p.model_b} at the "
        f"{r.selection_rate:.0%} cut ({r.n_selected_a} against {r.n_selected_b})"
        for p in pairs
        for r in p.reclassification
        if r.n_selected_a != r.n_selected_b
    ]
    if tied:
        notes.append(
            "The two models selected different numbers of respondents at the same "
            f"rate: {'; '.join(tied[:4])}"
            + (f", and {len(tied) - 4} more" if len(tied) > 4 else "")
            + ". That happens when respondents tie exactly on score — a Rasch or "
            "PCM fit scores by sum score, so ties are common — and a tied group "
            "straddling the cut is taken whole rather than split arbitrarily. Part "
            "of the reclassification at those rates is therefore that boundary "
            "rather than a disagreement about anyone's standing, and the difference "
            "in counts is the measure of how much."
        )

    stable, verdict = _verdict(pairs, n_compared)
    notes.append(
        "Differences are in standard deviations of this sample, after "
        "standardising each model's scores: Rasch and PCM leave the latent "
        "variance free, so their metric differs from a 2PL's by construction and "
        "an unstandardised difference would report that convention as a finding. "
        "Correlations and the reclassification counts need no such adjustment — "
        "both are invariant to the scale."
    )
    notes.append(
        "The selection rates are illustrative decision points, not a policy. "
        "Reclassification depends on how densely respondents sit where the cut "
        "falls, so a programme with a real cut should read the rate closest to it."
    )

    return ConsequenceReport(
        models=[labels[k] for k in ordered],
        n_respondents_compared=n_compared,
        score_method=method,
        selection_rates=[float(r) for r in selection_rates],
        pairs=pairs,
        stable=stable,
        verdict=verdict,
        notes=notes,
    )


def _verdict(pairs: list[PairwiseConsequence], n_compared: int) -> tuple[bool | None, str]:
    """Compose the verdict out of the computed extremes.

    Every number in the returned sentence is one that was calculated. §3.3
    prohibits a rationale string that asserts something the code did not compute,
    which is the v1 pattern this whole design is a reaction to.
    """

    correlations = [p.pearson_r for p in pairs if p.pearson_r is not None]
    spreads = [
        p.p95_absolute_difference
        for p in pairs
        if p.p95_absolute_difference is not None
    ]
    reclassified = [
        p.max_proportion_reclassified
        for p in pairs
        if p.max_proportion_reclassified is not None
    ]

    if not correlations or not spreads or not reclassified:
        return None, (
            "The models could not be compared on what they would decide: one or "
            "more of the correlation, the score spread and the reclassification "
            "rate could not be computed."
        )

    worst_r = min(correlations)
    worst_spread = max(spreads)
    worst_reclassified = max(reclassified)
    worst_pair = max(
        pairs,
        key=lambda p: p.max_proportion_reclassified or 0.0,
    )

    stable = (
        worst_r >= STABLE_MIN_CORRELATION
        and worst_spread <= STABLE_MAX_P95_DIFFERENCE
        and worst_reclassified <= STABLE_MAX_RECLASSIFIED
    )

    common = (
        f"Across {len(pairs)} model pair(s) and {n_compared} respondents scored "
        f"under all of them, the weakest agreement between two models was "
        f"r = {worst_r:.4f}; 95% of respondents were placed within "
        f"{worst_spread:.3f} sample standard deviations of each other; and at "
        f"worst {worst_reclassified:.1%} of respondents changed side of a "
        f"selection cut ({worst_pair.model_a} vs {worst_pair.model_b})."
    )

    if stable:
        return True, (
            f"{common} By the thresholds this report uses — r ≥ "
            f"{STABLE_MIN_CORRELATION}, 95th percentile difference ≤ "
            f"{STABLE_MAX_P95_DIFFERENCE} SD, and ≤ "
            f"{STABLE_MAX_RECLASSIFIED:.0%} reclassified — the candidates would "
            "make substantively the same decisions about these respondents, so "
            "which one is selected does not change the conclusions drawn from "
            "this data. That is not a statement that the models fit equally well; "
            "read the comparison dossier for that."
        )

    return False, (
        f"{common} That exceeds at least one of the thresholds this report uses "
        f"— r ≥ {STABLE_MIN_CORRELATION}, 95th percentile difference ≤ "
        f"{STABLE_MAX_P95_DIFFERENCE} SD, ≤ {STABLE_MAX_RECLASSIFIED:.0%} "
        "reclassified — so the model choice has consequences for individual "
        "respondents here and cannot be treated as a technicality. The "
        "thresholds are conventions adopted for this report rather than standards; "
        "the numbers above are what they were applied to."
    )
