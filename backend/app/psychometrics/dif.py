"""
Differential item functioning.

DIF is the question of whether two respondents of the same ability, drawn from
different groups, have the same chance of answering an item correctly. It is
not the question of whether the groups score differently overall - that is
impact, and it is usually a fact about the world rather than a defect in the
item. Every method here therefore conditions on ability before comparing
groups; they differ in what they condition on and in what they can see.

* **Mantel-Haenszel** - conditions on the observed total score and compares
  the two groups' odds of success within each score level. No model is fitted,
  so nothing can be wrong with the model. It is the operational standard in
  large-scale testing and the only method here with a settled effect-size
  taxonomy (ETS A/B/C). It is *blind to non-uniform DIF*: when an item favours
  one group at low ability and the other at high ability, the stratum-specific
  odds ratios point in opposite directions and their pooled average lands near
  1. An item can be badly non-uniform and score a clean ETS A.

* **Logistic regression** (Swaminathan & Rogers; effect size after lordif) -
  regresses the response on the matching score, the group, and their
  interaction. The interaction term is exactly what Mantel-Haenszel cannot see,
  which is why both are reported. Its weakness is the same observed-score
  matching: the total score is measured with error, and under large impact that
  error is correlated with group, which inflates the Type I error rate. The
  change in McFadden pseudo-R-squared is reported alongside every p-value and
  is the criterion for flagging - with a few thousand respondents the
  likelihood-ratio test will find statistically real differences far too small
  to matter to anyone.

* **IRT likelihood ratio** (Thissen, Steinberg & Wainer) - refits the model
  with the studied item's parameters free to differ across groups and compares
  against the model that forces them equal. This matches on the latent trait
  rather than on a fallible observed score, and it says *which* parameter
  differs. It costs a model fit per item, it inherits every assumption of the
  model, and it depends on the anchor set: if a contaminated item is left in
  the anchors, the two groups are linked on a crooked metric and the
  contamination is smeared across every other item. A purification loop
  addresses that, and the anchors actually used are reported.

  One limitation is structural and is stated rather than hidden. The estimator
  in :mod:`app.irt.em` has a single latent population, so group differences in
  the ability distribution (impact) are not modelled; both groups are fitted
  under one common prior. Under substantial impact the IRT-LR results here are
  approximate, and the observed-score methods - which condition on a quantity
  no model had to get right - are the ones to trust.

Because a test has many items, the p-values are adjusted across items by the
Benjamini-Hochberg procedure and both the raw and adjusted values are reported.
The ETS classification deliberately uses the *raw* p-value, because that is how
the classification is defined and how published DIF tables are read.

Nothing here returns a verdict on a sample too small to support one. DIF
detection is a small-effect problem on stratified data, and the standard
minimum of roughly 100 respondents per group is enforced rather than assumed:
below it, the statistics are ``None`` and the reason is in ``notes``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

import numpy as np
from scipy import optimize, stats
from scipy.special import expit

from app.irt.em import MISSING, EMOptions, ResponseMatrix, fit
from app.irt.families import ItemParameters, ModelKey

_FLOOR = 1e-12

MIN_GROUP_SIZE = 100
"""Respondents required in each group before any statistic is reported.

Below roughly this, the stratified tables that Mantel-Haenszel needs are mostly
empty, the logistic models are close to separation, and the chi-square
reference distributions are not approached. This is the conventional operational
floor; it is not a guarantee of adequate power, which for a small DIF effect
needs several hundred per group.
"""

ETS_B_THRESHOLD = 1.0
ETS_C_THRESHOLD = 1.5
LORDIF_R2_THRESHOLD = 0.02
"""Change in McFadden pseudo-R-squared that lordif treats as material DIF."""

_D_DIF_SCALE = -2.35
"""ETS delta-metric constant. The sign makes a negative value mean the item is
harder for the focal group than their ability warrants."""


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MantelHaenszelResult:
    """Mantel-Haenszel DIF for a dichotomous item.

    ``odds_ratio`` is the common odds of success for the reference group
    relative to the focal group. ``d_dif`` is that on the ETS delta scale,
    where negative values mean the item disadvantages the focal group.
    """

    odds_ratio: float | None
    d_dif: float | None
    d_dif_se: float | None
    chi_square: float | None
    p_value: float | None
    ets_class: str | None

    n_reference: int
    n_focal: int
    n_strata: int
    n_strata_used: int
    n_dropped: int
    notes: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return self.ets_class in {"B", "C"}


@dataclass(frozen=True)
class MantelResult:
    """Mantel test and standardised mean difference for a polytomous item.

    The ETS A/B/C classification does **not** apply here. It is calibrated on
    the delta metric of a dichotomous odds ratio and there is no accepted
    translation of it to an ordinal item, so no letter is produced. Judge these
    items on ``smd_standardised``, which is the group difference in mean item
    score after matching, expressed in item-score standard deviations.
    """

    chi_square: float | None
    df: int | None
    p_value: float | None
    smd: float | None
    smd_standardised: float | None

    n_reference: int
    n_focal: int
    n_strata_used: int
    notes: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        # 0.25 SD is the conventional attention threshold for a standardised
        # mean difference in operational DIF review. It is a convention.
        return (
            self.smd_standardised is not None
            and abs(self.smd_standardised) >= 0.25
        )


@dataclass(frozen=True)
class LogisticDIFResult:
    """Nested logistic models on matching score, group and their interaction.

    Three comparisons, all nested: uniform DIF is model 2 against model 1,
    non-uniform DIF is model 3 against model 2, and ``total`` is model 3
    against model 1 - the omnibus test that should be read first, since the
    two components partition it.
    """

    uniform_chi_square: float | None
    uniform_df: int | None
    uniform_p: float | None
    uniform_delta_r2: float | None

    nonuniform_chi_square: float | None
    nonuniform_df: int | None
    nonuniform_p: float | None
    nonuniform_delta_r2: float | None

    total_chi_square: float | None
    total_df: int | None
    total_p: float | None
    total_delta_r2: float | None

    group_coefficient: float | None
    interaction_coefficient: float | None

    n_used: int
    notes: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        """Effect size, not significance. See the module docstring."""
        return (
            self.total_delta_r2 is not None
            and self.total_delta_r2 >= LORDIF_R2_THRESHOLD
        )

    @property
    def is_nonuniform(self) -> bool:
        """Whether the interaction carries the bulk of the effect."""
        if self.nonuniform_delta_r2 is None or self.uniform_delta_r2 is None:
            return False
        return self.nonuniform_delta_r2 > self.uniform_delta_r2


@dataclass(frozen=True)
class IRTLikelihoodRatioResult:
    """Likelihood-ratio DIF from constrained and free model fits."""

    chi_square: float | None
    df: int | None
    p_value: float | None

    log_likelihood_free: float | None
    log_likelihood_constrained: float | None

    anchor_item_ids: list[str] = field(default_factory=list)
    purification_passes: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DIFResult:
    """Everything known about one item in one group comparison.

    A ``None`` statistic always means "not computed", never "no DIF"; the
    reason is in ``notes``.
    """

    item_id: str
    mantel_haenszel: MantelHaenszelResult | None = None
    mantel: MantelResult | None = None
    logistic: LogisticDIFResult | None = None
    irt_lr: IRTLikelihoodRatioResult | None = None

    # Benjamini-Hochberg adjusted across items, one per method.
    mh_p_adjusted: float | None = None
    logistic_p_adjusted: float | None = None
    irt_p_adjusted: float | None = None

    notes: list[str] = field(default_factory=list)

    @property
    def flagged_by(self) -> list[str]:
        """Which methods flag this item, by each method's own criterion."""
        out: list[str] = []
        if self.mantel_haenszel is not None and self.mantel_haenszel.flagged:
            out.append("mantel_haenszel")
        if self.mantel is not None and self.mantel.flagged:
            out.append("mantel")
        if self.logistic is not None and self.logistic.flagged:
            out.append("logistic")
        if (
            self.irt_lr is not None
            and self.irt_p_adjusted is not None
            and self.irt_p_adjusted < 0.05
        ):
            out.append("irt_lr")
        return out

    @property
    def flagged(self) -> bool:
        return bool(self.flagged_by)


@dataclass(frozen=True)
class GroupComparison:
    """One focal group measured against the reference group."""

    reference_label: str
    focal_label: str
    n_reference: int
    n_focal: int
    items: list[DIFResult]
    anchor_item_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> list[DIFResult]:
        return [i for i in self.items if i.flagged]


@dataclass(frozen=True)
class DIFReport:
    comparisons: list[GroupComparison]
    n_persons_used: int
    notes: list[str] = field(default_factory=list)

    @property
    def items(self) -> list[DIFResult]:
        """The single comparison's items.

        Raises when there is more than one comparison, because silently
        returning the first would hide the other groups entirely.
        """
        if len(self.comparisons) != 1:
            raise ValueError(
                f"{len(self.comparisons)} group comparisons were run; read "
                "`comparisons` and name the one you want"
            )
        return self.comparisons[0].items


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def dif(
    data: ResponseMatrix,
    items: list[ItemParameters],
    groups: Sequence | np.ndarray,
    *,
    reference: object | None = None,
    alpha: float = 0.05,
    min_group_size: int = MIN_GROUP_SIZE,
    include_irt_lr: bool = True,
    purification_passes: int = 2,
    em_options: EMOptions | None = None,
) -> DIFReport:
    """Screen every item for differential item functioning.

    ``items`` supplies each item's model family, id and category count. The
    parameter *values* are not used: every method re-derives what it needs from
    the responses, because a set of parameters fitted to the pooled sample is
    the very thing DIF calls into question.

    ``groups`` is one label per respondent. With more than two distinct labels
    the reference group is compared against each other group in turn, and the
    report carries one :class:`GroupComparison` per pair - there is no omnibus
    across groups, and the comparisons are not independent of one another.
    """
    if len(items) != data.n_items:
        raise ValueError(
            f"{len(items)} item parameter sets for {data.n_items} columns"
        )

    labels = np.asarray(groups)
    if labels.shape[0] != data.n_persons:
        raise ValueError(
            f"{labels.shape[0]} group labels for {data.n_persons} respondents"
        )

    notes: list[str] = []

    # Observed-score matching needs a comparable total for every respondent, so
    # partial response vectors cannot be matched. They are excluded from all
    # methods rather than from some, so that every statistic describes the same
    # people.
    complete = (data.values != MISSING).all(axis=1)
    n_complete = int(complete.sum())
    if n_complete < data.n_persons:
        notes.append(
            f"{data.n_persons - n_complete} of {data.n_persons} respondents "
            "have at least one missing response and are excluded: a matching "
            "score is undefined when part of the test is unanswered."
        )

    values = data.values[complete]
    labels = labels[complete]

    present = [lab for lab in _ordered_unique(labels)]
    if len(present) < 2:
        raise ValueError(
            f"DIF needs two groups; the data contains {len(present)}"
        )

    counts = {lab: int((labels == lab).sum()) for lab in present}
    if reference is None:
        # Largest group by default: it gives the most stable metric to link to.
        reference_label = max(present, key=lambda lab: counts[lab])
    else:
        reference_label = reference
        if reference_label not in counts:
            raise ValueError(f"reference group '{reference}' is not in the data")

    focal_labels = [lab for lab in present if lab != reference_label]
    if len(present) > 2:
        notes.append(
            f"{len(present)} groups present. Each is compared with the "
            f"reference group '{reference_label}' separately; the comparisons "
            "share the reference sample and are therefore not independent, and "
            "the FDR adjustment is applied within each comparison, not across "
            "them."
        )

    em_options = em_options or EMOptions(compute_standard_errors=False)

    comparisons = [
        _compare_pair(
            values=values,
            items=items,
            item_ids=data.item_ids,
            n_categories=data.n_categories.astype(int),
            reference_mask=labels == reference_label,
            focal_mask=labels == focal,
            reference_label=str(reference_label),
            focal_label=str(focal),
            alpha=alpha,
            min_group_size=min_group_size,
            include_irt_lr=include_irt_lr,
            purification_passes=purification_passes,
            em_options=em_options,
        )
        for focal in focal_labels
    ]

    return DIFReport(
        comparisons=comparisons, n_persons_used=n_complete, notes=notes
    )


def benjamini_hochberg(p_values: Sequence[float | None]) -> list[float | None]:
    """Benjamini-Hochberg adjusted p-values, preserving ``None`` entries.

    The step-up procedure controls the expected proportion of false discoveries
    among the flagged items. Bonferroni would control the probability of *any*
    false flag, which on a 60-item test costs so much power that genuine DIF
    goes unreported. ``None`` entries take no part and stay ``None``: an item
    whose statistic could not be computed is not a test that was performed.
    """
    finite = [
        (i, float(p))
        for i, p in enumerate(p_values)
        if p is not None and np.isfinite(p)
    ]
    out: list[float | None] = [None] * len(p_values)
    if not finite:
        return out

    m = len(finite)
    order = sorted(range(m), key=lambda k: finite[k][1])
    ranked = np.array([finite[k][1] for k in order], dtype=float)
    adjusted = ranked * m / np.arange(1, m + 1)
    # Enforce monotonicity from the largest p downwards, which is what makes
    # the step-up procedure valid.
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    adjusted = np.clip(adjusted, 0.0, 1.0)

    for rank, k in enumerate(order):
        out[finite[k][0]] = float(adjusted[rank])
    return out


# --------------------------------------------------------------------------- #
# One reference/focal pair
# --------------------------------------------------------------------------- #


def _compare_pair(
    *,
    values: np.ndarray,
    items: list[ItemParameters],
    item_ids: list[str],
    n_categories: np.ndarray,
    reference_mask: np.ndarray,
    focal_mask: np.ndarray,
    reference_label: str,
    focal_label: str,
    alpha: float,
    min_group_size: int,
    include_irt_lr: bool,
    purification_passes: int,
    em_options: EMOptions,
) -> GroupComparison:
    n_ref = int(reference_mask.sum())
    n_foc = int(focal_mask.sum())
    notes: list[str] = []

    pair = reference_mask | focal_mask
    sub_values = values[pair]
    is_focal = focal_mask[pair]

    too_small = min(n_ref, n_foc) < min_group_size
    if too_small:
        notes.append(
            f"Reference group '{reference_label}' has {n_ref} respondents and "
            f"focal group '{focal_label}' has {n_foc}; at least "
            f"{min_group_size} in each is required before any DIF statistic is "
            "reported. No statistics were computed."
        )
        return GroupComparison(
            reference_label=reference_label,
            focal_label=focal_label,
            n_reference=n_ref,
            n_focal=n_foc,
            items=[
                DIFResult(item_id=params.item_id, notes=list(notes))
                for params in items
            ],
            notes=notes,
        )

    # Total raw score over the whole test, the conventional matching variable.
    # The studied item is left in it, as ETS practice prescribes: removing it
    # makes the matching criterion differ from item to item and raises the
    # Type I error rate.
    matching = sub_values.sum(axis=1).astype(int)

    results: list[DIFResult] = []
    for j, params in enumerate(items):
        results.append(
            _one_item_observed_score(
                responses=sub_values[:, j],
                matching=matching,
                is_focal=is_focal,
                params=params,
                n_cat=int(n_categories[j]),
                min_group_size=min_group_size,
            )
        )

    anchors: list[str] = []
    if include_irt_lr:
        irt, anchors, irt_notes = _irt_lr_screen(
            values=sub_values,
            item_ids=item_ids,
            n_categories=n_categories,
            items=items,
            is_focal=is_focal,
            alpha=alpha,
            passes=purification_passes,
            em_options=em_options,
        )
        notes.extend(irt_notes)
        results = [
            replace(r, irt_lr=irt[j]) for j, r in enumerate(results)
        ]

    results = _attach_adjusted_p(results)

    return GroupComparison(
        reference_label=reference_label,
        focal_label=focal_label,
        n_reference=n_ref,
        n_focal=n_foc,
        items=results,
        anchor_item_ids=anchors,
        notes=notes,
    )


def _one_item_observed_score(
    *,
    responses: np.ndarray,
    matching: np.ndarray,
    is_focal: np.ndarray,
    params: ItemParameters,
    n_cat: int,
    min_group_size: int,
) -> DIFResult:
    notes: list[str] = []

    refusal = _degenerate_reason(responses, is_focal, min_group_size)
    if refusal is not None:
        notes.append(f"{params.item_id}: {refusal}")
        return DIFResult(item_id=params.item_id, notes=notes)

    mh = mantel_result = None
    if n_cat == 2:
        mh = _mantel_haenszel(responses, matching, is_focal)
    else:
        mantel_result = _mantel(responses, matching, is_focal)

    logistic = _logistic_dif(responses, matching, is_focal, n_cat)

    return DIFResult(
        item_id=params.item_id,
        mantel_haenszel=mh,
        mantel=mantel_result,
        logistic=logistic,
        notes=notes,
    )


def _degenerate_reason(
    responses: np.ndarray, is_focal: np.ndarray, min_group_size: int
) -> str | None:
    """Why this item cannot support a DIF statistic, or ``None``."""
    for name, mask in (("focal", is_focal), ("reference", ~is_focal)):
        block = responses[mask]
        if block.size < min_group_size:
            return (
                f"only {block.size} responses in the {name} group, below the "
                f"minimum of {min_group_size}"
            )
        if np.unique(block).size < 2:
            return (
                f"every {name}-group respondent gave the same response, so the "
                "item has no within-group variance to compare"
            )
        # A handful of respondents outside the modal category produces an odds
        # ratio driven entirely by those few people.
        modal = int(np.bincount(block.astype(int)).max())
        if block.size - modal < 5:
            return (
                f"fewer than 5 {name}-group respondents fall outside the modal "
                "response category"
            )
    return None


def _attach_adjusted_p(results: list[DIFResult]) -> list[DIFResult]:
    """Benjamini-Hochberg across items, separately per method."""
    mh_p = [
        r.mantel_haenszel.p_value if r.mantel_haenszel else
        (r.mantel.p_value if r.mantel else None)
        for r in results
    ]
    lr_p = [r.logistic.total_p if r.logistic else None for r in results]
    irt_p = [r.irt_lr.p_value if r.irt_lr else None for r in results]

    mh_adj = benjamini_hochberg(mh_p)
    lr_adj = benjamini_hochberg(lr_p)
    irt_adj = benjamini_hochberg(irt_p)

    return [
        replace(
            r,
            mh_p_adjusted=mh_adj[i],
            logistic_p_adjusted=lr_adj[i],
            irt_p_adjusted=irt_adj[i],
        )
        for i, r in enumerate(results)
    ]


def _ordered_unique(labels: np.ndarray) -> list:
    seen: list = []
    for lab in labels.tolist():
        if lab not in seen:
            seen.append(lab)
    return seen


# --------------------------------------------------------------------------- #
# Stratification
# --------------------------------------------------------------------------- #


def _strata(matching: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Thin strata: one level per distinct matching score."""
    levels, index = np.unique(matching, return_inverse=True)
    return levels, index


def _collapse(
    n_levels: int, is_usable: Callable[[np.ndarray], bool]
) -> list[np.ndarray]:
    """Merge adjacent strata until each merged block is usable.

    Thin matching - one stratum per score point - has the most power and is the
    default. It also guarantees empty or one-sided tables at the extremes,
    where almost nobody scores. Merging *adjacent* levels there preserves the
    ordering that gives the statistic its meaning; dropping them would discard
    the respondents whose scores are most extreme, which is exactly the group a
    DIF review cares about.

    In practice this leaves the dense middle of the score distribution thin -
    every level is usable on its own and becomes its own block - and thickens
    only the sparse tails.
    """
    blocks: list[np.ndarray] = []
    bucket: list[int] = []
    for k in range(n_levels):
        bucket.append(k)
        idx = np.asarray(bucket)
        if is_usable(idx):
            blocks.append(idx)
            bucket = []

    if bucket:
        # A trailing run that never became usable joins the last good block
        # rather than being silently discarded.
        idx = np.asarray(bucket)
        if blocks:
            blocks[-1] = np.concatenate([blocks[-1], idx])
        else:
            blocks.append(idx)
    return blocks


# --------------------------------------------------------------------------- #
# Mantel-Haenszel
# --------------------------------------------------------------------------- #


def _mantel_haenszel(
    responses: np.ndarray, matching: np.ndarray, is_focal: np.ndarray
) -> MantelHaenszelResult:
    """Common odds ratio, ETS delta-DIF, and the continuity-corrected chi-square."""
    levels, index = _strata(matching)
    n_levels = levels.size
    notes: list[str] = []

    correct = responses.astype(int) == 1
    focal = is_focal

    # 2 x 2 per stratum: rows reference/focal, columns correct/incorrect.
    a = np.bincount(index[~focal & correct], minlength=n_levels).astype(float)
    b = np.bincount(index[~focal & ~correct], minlength=n_levels).astype(float)
    c = np.bincount(index[focal & correct], minlength=n_levels).astype(float)
    d = np.bincount(index[focal & ~correct], minlength=n_levels).astype(float)

    def usable(idx: np.ndarray) -> bool:
        A_, B_, C_, D_ = a[idx].sum(), b[idx].sum(), c[idx].sum(), d[idx].sum()
        # Both groups present and both outcomes present, or the stratum's
        # contribution to both the numerator and the denominator is zero.
        return bool(
            A_ + B_ > 0 and C_ + D_ > 0 and A_ + C_ > 0 and B_ + D_ > 0
        )

    blocks = _collapse(n_levels, usable)

    A = np.array([a[bl].sum() for bl in blocks])
    B = np.array([b[bl].sum() for bl in blocks])
    C = np.array([c[bl].sum() for bl in blocks])
    D = np.array([d[bl].sum() for bl in blocks])
    n = A + B + C + D

    keep = (A + B > 0) & (C + D > 0) & (A + C > 0) & (B + D > 0) & (n > 1)
    dropped = int((~keep).sum())
    A, B, C, D, n = A[keep], B[keep], C[keep], D[keep], n[keep]

    n_ref = int((~focal).sum())
    n_foc = int(focal.sum())

    if A.size == 0:
        notes.append(
            "no matching-score stratum contains both groups and both outcomes "
            "after collapsing"
        )
        return MantelHaenszelResult(
            odds_ratio=None, d_dif=None, d_dif_se=None, chi_square=None,
            p_value=None, ets_class=None, n_reference=n_ref, n_focal=n_foc,
            n_strata=n_levels, n_strata_used=0, n_dropped=len(blocks),
            notes=notes,
        )

    if dropped:
        notes.append(
            f"{dropped} of {len(blocks)} matching-score strata carried only one "
            "group or only one outcome and contribute nothing to the odds "
            "ratio."
        )

    R = A * D / n
    S = B * C / n
    r_sum, s_sum = float(R.sum()), float(S.sum())

    if r_sum <= _FLOOR or s_sum <= _FLOOR:
        notes.append(
            "the pooled odds ratio is degenerate: one group answered "
            "correctly in every stratum where the other did not"
        )
        odds_ratio = d_dif = d_dif_se = None
    else:
        odds_ratio = r_sum / s_sum
        d_dif = _D_DIF_SCALE * float(np.log(odds_ratio))
        # Robins-Breslow-Greenland variance of log(alpha_MH): consistent both
        # when strata are many and sparse and when they are few and large,
        # which the older Woolf and Phillips-Holland estimators are not.
        P = (A + D) / n
        Q = (B + C) / n
        var_log = (
            float(np.sum(P * R)) / (2.0 * r_sum**2)
            + float(np.sum(P * S + Q * R)) / (2.0 * r_sum * s_sum)
            + float(np.sum(Q * S)) / (2.0 * s_sum**2)
        )
        d_dif_se = abs(_D_DIF_SCALE) * float(np.sqrt(max(var_log, 0.0)))

    # Holland-Thayer continuity-corrected chi-square on the reference-correct
    # cell. The correction matters at the sample sizes where DIF review
    # actually happens; without it the test over-rejects.
    expected = (A + B) * (A + C) / n
    variance = (A + B) * (C + D) * (A + C) * (B + D) / (n**2 * (n - 1))
    total_var = float(variance.sum())

    if total_var <= _FLOOR:
        chi_square = p_value = None
        notes.append("the hypergeometric variance of the tables is zero")
    else:
        deviation = abs(float(A.sum() - expected.sum())) - 0.5
        deviation = max(deviation, 0.0)
        chi_square = deviation**2 / total_var
        p_value = float(stats.chi2.sf(chi_square, 1))

    ets = _ets_class(d_dif, d_dif_se, p_value)

    return MantelHaenszelResult(
        odds_ratio=odds_ratio,
        d_dif=d_dif,
        d_dif_se=d_dif_se,
        chi_square=chi_square,
        p_value=p_value,
        ets_class=ets,
        n_reference=n_ref,
        n_focal=n_foc,
        n_strata=n_levels,
        n_strata_used=int(A.size),
        n_dropped=dropped,
        notes=notes,
    )


def _ets_class(
    d_dif: float | None, d_dif_se: float | None, p_value: float | None
) -> str | None:
    """ETS A/B/C, as the conjunction of an effect size and a significance test.

    Both halves are required, and this is the part that is usually got wrong.
    An implementation that thresholds on |D-DIF| alone will label a noisy
    estimate from a thin stratum as category C; one that thresholds on the
    p-value alone will label a trivially small but precisely estimated
    difference as DIF on a large sample. The published rule is:

    * **C** - ``|D-DIF| >= 1.5`` *and* D-DIF significantly larger than 1.0 in
      absolute value. The second condition is a one-sided test of
      ``|D-DIF| > 1`` using the standard error of D-DIF itself, **not** the
      Mantel-Haenszel chi-square, which only ever tests against zero.
    * **B** - not C, and ``|D-DIF| >= 1.0`` *and* significantly different from
      zero at the 5% level, which is what the MH chi-square tests.
    * **A** - everything else: negligible DIF.
    """
    if d_dif is None:
        return None

    magnitude = abs(d_dif)

    if d_dif_se is not None and d_dif_se > _FLOOR:
        z_from_one = (magnitude - ETS_B_THRESHOLD) / d_dif_se
        # One-sided 5% critical value: the alternative is only "larger than 1".
        significantly_above_one = z_from_one > 1.645
    else:
        significantly_above_one = False

    significantly_nonzero = p_value is not None and p_value < 0.05

    if magnitude >= ETS_C_THRESHOLD and significantly_above_one:
        return "C"
    if magnitude >= ETS_B_THRESHOLD and significantly_nonzero:
        return "B"
    return "A"


# --------------------------------------------------------------------------- #
# Mantel test for ordered polytomous items
# --------------------------------------------------------------------------- #


def _mantel(
    responses: np.ndarray, matching: np.ndarray, is_focal: np.ndarray
) -> MantelResult:
    """Mantel's test for ordered categories, plus the standardised mean difference.

    The statistic compares the focal group's total item score against its
    hypergeometric expectation within each matching stratum - the direct
    generalisation of Mantel-Haenszel from a 2 x 2 table to a 2 x m one. The
    SMD is the effect size that goes with it: the average, over strata weighted
    by focal-group size, of the difference in mean item score.
    """
    levels, index = _strata(matching)
    n_levels = levels.size
    y = responses.astype(float)
    notes: list[str] = []

    n_k = np.bincount(index, minlength=n_levels).astype(float)
    n_f = np.bincount(index[is_focal], minlength=n_levels).astype(float)
    n_r = n_k - n_f
    sum_y = np.bincount(index, weights=y, minlength=n_levels)
    sum_y2 = np.bincount(index, weights=y**2, minlength=n_levels)
    sum_y_focal = np.bincount(index[is_focal], weights=y[is_focal], minlength=n_levels)

    def usable(idx: np.ndarray) -> bool:
        nk = n_k[idx].sum()
        nf = n_f[idx].sum()
        sy = sum_y[idx].sum()
        spread = sum_y2[idx].sum() - sy**2 / max(nk, 1.0)
        return bool(nf > 0 and nk - nf > 0 and nk > 1 and spread > _FLOOR)

    blocks = _collapse(n_levels, usable)

    def pool(arr: np.ndarray) -> np.ndarray:
        return np.array([arr[bl].sum() for bl in blocks])

    Nk, Nf, Sy, Sy2, Sf = (
        pool(n_k), pool(n_f), pool(sum_y), pool(sum_y2), pool(sum_y_focal)
    )
    Nr = Nk - Nf
    Spread = Sy2 - Sy**2 / np.clip(Nk, 1.0, None)

    keep = (Nf > 0) & (Nr > 0) & (Nk > 1) & (Spread > _FLOOR)
    Nk, Nf, Nr, Sy, Sf, Spread = (
        Nk[keep], Nf[keep], Nr[keep], Sy[keep], Sf[keep], Spread[keep]
    )

    n_ref = int((~is_focal).sum())
    n_foc = int(is_focal.sum())

    if Nk.size == 0:
        notes.append("no matching-score stratum contains both groups")
        return MantelResult(
            chi_square=None, df=None, p_value=None, smd=None,
            smd_standardised=None, n_reference=n_ref, n_focal=n_foc,
            n_strata_used=0, notes=notes,
        )

    expected = Nf * Sy / Nk
    variance = Nf * Nr * Spread / (Nk * (Nk - 1.0))
    total_var = float(variance.sum())

    if total_var <= _FLOOR:
        chi_square = p_value = None
        notes.append("the hypergeometric variance of the tables is zero")
    else:
        chi_square = float((Sf.sum() - expected.sum()) ** 2 / total_var)
        p_value = float(stats.chi2.sf(chi_square, 1))

    # SMD: focal-weighted average of the within-stratum mean difference.
    mean_focal = Sf / Nf
    mean_ref = (Sy - Sf) / Nr
    weights = Nf / Nf.sum()
    smd = float(np.sum(weights * (mean_focal - mean_ref)))

    sd = float(np.std(y))
    smd_standardised = smd / sd if sd > _FLOOR else None

    return MantelResult(
        chi_square=chi_square,
        df=1 if chi_square is not None else None,
        p_value=p_value,
        smd=smd,
        smd_standardised=smd_standardised,
        n_reference=n_ref,
        n_focal=n_foc,
        n_strata_used=int(Nk.size),
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Logistic regression DIF
# --------------------------------------------------------------------------- #


def _logistic_dif(
    responses: np.ndarray,
    matching: np.ndarray,
    is_focal: np.ndarray,
    n_cat: int,
) -> LogisticDIFResult | None:
    """Three nested cumulative-logit models, compared by likelihood ratio.

    A cumulative-logit (proportional odds) model is used throughout. For a
    binary item it *is* ordinary logistic regression - one threshold - so one
    implementation serves dichotomous and graded items without a special case,
    which is what lordif does as well.
    """
    y = responses.astype(int)
    notes: list[str] = []

    # Standardising the matching score keeps the interaction column on the same
    # scale as the main effects; an unscaled total score of 0-40 makes the
    # Hessian badly conditioned and slows every fit.
    score = matching.astype(float)
    sd = float(np.std(score))
    if sd <= _FLOOR:
        return None
    score = (score - float(np.mean(score))) / sd
    group = is_focal.astype(float)

    x1 = score[:, None]
    x2 = np.column_stack([score, group])
    x3 = np.column_stack([score, group, score * group])

    ll_null = _null_loglik(y, n_cat)
    fits = [_fit_cumulative_logit(y, x, n_cat) for x in (x1, x2, x3)]
    if any(f is None for f in fits):
        notes.append("a logistic model did not converge")
        return LogisticDIFResult(
            *([None] * 14), n_used=int(y.size), notes=notes
        )

    (ll1, _), (ll2, beta2), (ll3, beta3) = fits

    if not np.isfinite(ll_null) or abs(ll_null) < _FLOOR:
        notes.append("the null model is degenerate; pseudo-R-squared is undefined")
        r2 = [None, None, None]
    else:
        r2 = [1.0 - ll / ll_null for ll in (ll1, ll2, ll3)]

    def lr(free: float, restricted: float, df: int) -> tuple[float, int, float]:
        # Numerical optimisation can leave a nested model a hair above its
        # superset; clamping at zero is honest, a negative chi-square is not.
        stat = max(2.0 * (free - restricted), 0.0)
        return stat, df, float(stats.chi2.sf(stat, df))

    u_stat, u_df, u_p = lr(ll2, ll1, 1)
    n_stat, n_df, n_p = lr(ll3, ll2, 1)
    t_stat, t_df, t_p = lr(ll3, ll1, 2)

    def delta(hi: int, lo: int) -> float | None:
        if r2[hi] is None or r2[lo] is None:
            return None
        return max(float(r2[hi] - r2[lo]), 0.0)

    return LogisticDIFResult(
        uniform_chi_square=u_stat,
        uniform_df=u_df,
        uniform_p=u_p,
        uniform_delta_r2=delta(1, 0),
        nonuniform_chi_square=n_stat,
        nonuniform_df=n_df,
        nonuniform_p=n_p,
        nonuniform_delta_r2=delta(2, 1),
        total_chi_square=t_stat,
        total_df=t_df,
        total_p=t_p,
        total_delta_r2=delta(2, 0),
        group_coefficient=float(beta2[1]),
        interaction_coefficient=float(beta3[2]),
        n_used=int(y.size),
        notes=notes,
    )


def _null_loglik(y: np.ndarray, n_cat: int) -> float:
    """Log-likelihood of the intercept-only cumulative-logit model.

    With no covariates the model is saturated in the category marginals, so its
    MLE reproduces the observed proportions exactly and the log-likelihood has
    a closed form. Fitting it numerically would give the same answer more
    slowly and less accurately, and this value is the denominator of every
    pseudo-R-squared reported here.
    """
    counts = np.bincount(y, minlength=n_cat).astype(float)
    n = counts.sum()
    nonzero = counts > 0
    return float(np.sum(counts[nonzero] * np.log(counts[nonzero] / n)))


def _cumulative_logit_nll(
    params: np.ndarray, y: np.ndarray, x: np.ndarray, n_cat: int
) -> float:
    n_thresh = n_cat - 1
    # Thresholds must stay ordered. tau_1 is free and each later threshold is
    # the previous one minus a positive increment, so ordering holds for any
    # real vector the optimiser proposes and no constraint is needed.
    tau = np.empty(n_thresh, dtype=float)
    tau[0] = params[0]
    for k in range(1, n_thresh):
        tau[k] = tau[k - 1] - np.exp(np.clip(params[k], -30.0, 30.0))
    beta = params[n_thresh:]

    eta = x @ beta if beta.size else np.zeros(y.size)
    cum = np.empty((y.size, n_cat + 1), dtype=float)
    cum[:, 0] = 1.0
    cum[:, n_cat] = 0.0
    for k in range(1, n_cat):
        cum[:, k] = expit(tau[k - 1] + eta)

    probs = np.clip(cum[:, :-1] - cum[:, 1:], _FLOOR, 1.0)
    return -float(np.sum(np.log(probs[np.arange(y.size), y])))


def _fit_cumulative_logit(
    y: np.ndarray, x: np.ndarray, n_cat: int
) -> tuple[float, np.ndarray] | None:
    """Maximum likelihood by L-BFGS-B. Returns ``(log-likelihood, beta)``.

    Written out rather than taken from statsmodels: the whole engine is numpy
    and scipy, and a proportional-odds fit whose only consumers are three
    likelihood values does not justify a dependency.
    """
    n_thresh = n_cat - 1
    counts = np.bincount(y, minlength=n_cat).astype(float)
    n = counts.sum()

    # Start at the marginal thresholds with zero slopes, which is the exact
    # optimum of the null model and therefore already close.
    cumulative = np.clip(1.0 - np.cumsum(counts)[:-1] / n, 1e-4, 1 - 1e-4)
    tau = np.log(cumulative / (1.0 - cumulative))
    start = np.zeros(n_thresh + x.shape[1], dtype=float)
    start[0] = tau[0]
    for k in range(1, n_thresh):
        start[k] = float(np.log(max(tau[k - 1] - tau[k], 1e-3)))

    result = optimize.minimize(
        _cumulative_logit_nll,
        start,
        args=(y, x, n_cat),
        method="L-BFGS-B",
        options={"maxiter": 500, "ftol": 1e-12, "gtol": 1e-8},
    )
    if not np.isfinite(result.fun):
        return None
    # `success` can be False on a flat but perfectly good optimum, so the
    # gradient norm decides rather than the flag alone.
    if not result.success and float(np.max(np.abs(result.jac))) > 1e-3:
        return None

    return -float(result.fun), np.asarray(result.x[n_thresh:], dtype=float)


# --------------------------------------------------------------------------- #
# IRT likelihood-ratio DIF
# --------------------------------------------------------------------------- #


def _irt_lr_screen(
    *,
    values: np.ndarray,
    item_ids: list[str],
    n_categories: np.ndarray,
    items: list[ItemParameters],
    is_focal: np.ndarray,
    alpha: float,
    passes: int,
    em_options: EMOptions,
) -> tuple[list[IRTLikelihoodRatioResult | None], list[str], list[str]]:
    """Likelihood-ratio DIF for every item, with anchor purification.

    Pass 1 uses every item as an anchor. Each later pass removes the items the
    previous pass flagged, so the metric that links the two groups is built
    only from items with no evidence against them. Two passes is the default
    because the flagged set almost always stabilises there and each pass costs
    one model fit per item; more passes on a short test can strip the anchor
    set down to nothing.
    """
    n_items = len(items)
    model = items[0].model
    notes: list[str] = []
    cache: dict[tuple[int, ...], object] = {}

    anchors = list(range(n_items))
    results: list[IRTLikelihoodRatioResult | None] = [None] * n_items
    completed = 0

    for pass_index in range(1, max(passes, 1) + 1):
        completed = pass_index
        results = [
            _irt_lr_item(
                j=j,
                anchors=anchors,
                values=values,
                item_ids=item_ids,
                n_categories=n_categories,
                model=model,
                is_focal=is_focal,
                em_options=em_options,
                cache=cache,
                anchor_ids=[item_ids[k] for k in anchors],
                passes_done=pass_index,
            )
            for j in range(n_items)
        ]

        if pass_index == max(passes, 1):
            break

        flagged = {
            j for j, r in enumerate(results)
            if r is not None and r.p_value is not None and r.p_value < alpha
        }
        purified = [j for j in range(n_items) if j not in flagged]

        if len(purified) < 2:
            notes.append(
                f"Purification pass {pass_index + 1} was skipped: removing the "
                f"{len(flagged)} flagged items would leave fewer than two "
                "anchor items, and a metric cannot be linked on one item. The "
                "IRT-LR results use every item as an anchor and are therefore "
                "vulnerable to contamination."
            )
            break
        if purified == anchors:
            break
        anchors = purified

    anchor_ids = [item_ids[k] for k in anchors]
    if len(anchor_ids) < n_items:
        notes.append(
            f"IRT-LR anchors after purification: {len(anchor_ids)} of "
            f"{n_items} items ({', '.join(anchor_ids)})."
        )
    if any(r is None for r in results):
        notes.append(
            "IRT-LR is missing for at least one item because a constrained or "
            "free fit did not converge."
        )
    return results, anchor_ids, notes


def _irt_lr_item(
    *,
    j: int,
    anchors: list[int],
    values: np.ndarray,
    item_ids: list[str],
    n_categories: np.ndarray,
    model: ModelKey,
    is_focal: np.ndarray,
    em_options: EMOptions,
    cache: dict,
    anchor_ids: list[str],
    passes_done: int,
) -> IRTLikelihoodRatioResult | None:
    """One item's constrained-versus-free comparison.

    The free model is fitted by splitting the studied item into two columns,
    one observed only for the reference group and one only for the focal group.
    The estimator skips missing responses per cell, so each column is estimated
    from its own group alone while every anchor item is estimated from both -
    which is exactly the two-group model with the anchors constrained equal,
    obtained without a separate multi-group estimator. Both fits see identical
    response data, so their log-likelihoods are directly comparable.
    """
    columns = sorted(set(anchors) | {j})
    key = tuple(columns)

    constrained = cache.get(key)
    if constrained is None:
        constrained = fit(
            _submatrix(values, columns, item_ids, n_categories), model, em_options
        )
        cache[key] = constrained

    free = fit(
        _split_matrix(values, columns, j, item_ids, n_categories, is_focal),
        model,
        em_options,
    )

    notes: list[str] = []
    if not constrained.converged or not free.converged:
        reason = constrained.failure_reason or free.failure_reason
        return IRTLikelihoodRatioResult(
            chi_square=None, df=None, p_value=None,
            log_likelihood_free=None, log_likelihood_constrained=None,
            anchor_item_ids=anchor_ids, purification_passes=passes_done,
            notes=[f"model fit failed: {reason}"],
        )

    # Degrees of freedom read off the two fits rather than re-derived from the
    # family, so a slope that is shared or fixed is accounted for automatically.
    df = int(free.n_free_parameters - constrained.n_free_parameters)
    if df < 1:
        return IRTLikelihoodRatioResult(
            chi_square=None, df=None, p_value=None,
            log_likelihood_free=free.log_likelihood,
            log_likelihood_constrained=constrained.log_likelihood,
            anchor_item_ids=anchor_ids, purification_passes=passes_done,
            notes=["the free model added no parameters"],
        )

    statistic = 2.0 * (free.log_likelihood - constrained.log_likelihood)
    if statistic < 0:
        # The free model nests the constrained one, so a negative statistic is
        # EM stopping short rather than evidence of anything.
        notes.append(
            f"the free fit reached a log-likelihood {abs(statistic) / 2:.3g} "
            "below the constrained fit, which is an EM convergence artefact; "
            "the statistic is reported as zero"
        )
        statistic = 0.0

    return IRTLikelihoodRatioResult(
        chi_square=float(statistic),
        df=df,
        p_value=float(stats.chi2.sf(statistic, df)),
        log_likelihood_free=free.log_likelihood,
        log_likelihood_constrained=constrained.log_likelihood,
        anchor_item_ids=anchor_ids,
        purification_passes=passes_done,
        notes=notes,
    )


def _submatrix(
    values: np.ndarray,
    columns: list[int],
    item_ids: list[str],
    n_categories: np.ndarray,
) -> ResponseMatrix:
    return ResponseMatrix(
        values=np.ascontiguousarray(values[:, columns]),
        item_ids=[item_ids[k] for k in columns],
        n_categories=np.asarray([n_categories[k] for k in columns], dtype=int),
    )


def _split_matrix(
    values: np.ndarray,
    columns: list[int],
    studied: int,
    item_ids: list[str],
    n_categories: np.ndarray,
    is_focal: np.ndarray,
) -> ResponseMatrix:
    """``columns`` with the studied item replaced by one column per group."""
    others = [k for k in columns if k != studied]
    block = values[:, others]

    reference_column = values[:, studied].copy()
    focal_column = values[:, studied].copy()
    reference_column[is_focal] = MISSING
    focal_column[~is_focal] = MISSING

    stacked = np.column_stack([block, reference_column, focal_column]).astype(
        values.dtype
    )
    ids = [item_ids[k] for k in others] + [
        f"{item_ids[studied]}__reference",
        f"{item_ids[studied]}__focal",
    ]
    cats = [n_categories[k] for k in others] + [
        n_categories[studied],
        n_categories[studied],
    ]
    return ResponseMatrix(
        values=np.ascontiguousarray(stacked),
        item_ids=ids,
        n_categories=np.asarray(cats, dtype=int),
    )
