"""
Item-level fit statistics.

Three statistics, reported together because each is blind to something the
others see:

* **S-X2** (Orlando & Thissen, 2000) - compares observed and model-expected
  response proportions within groups defined by the *rest score*, the total on
  every other item. Conditioning on an observed score rather than on an
  estimated theta is what makes it a genuine chi-square: no estimated
  conditioning variable, so no capitalisation on the estimation error. This is
  the statistic to trust when the two disagree.
* **Infit and outfit mean-square** - the average squared standardised residual,
  unweighted (outfit) and information-weighted (infit). Reported as effect
  sizes only. The familiar t-transformations are not reported: their null
  distribution depends on sample size so strongly that with a few thousand
  respondents almost every item is "significantly" misfitting, which tells the
  reader nothing about the item.
* **RMSD** - the root-mean-square distance between the observed and expected
  category response curves, on the probability scale. Unlike the other two it
  does not grow with sample size, so it answers "how wrong is this item?"
  rather than "how confident are we that it is wrong at all?".

A sample size large enough to detect a trivial departure is the normal case in
this domain, so nothing here is presented as a pass/fail test. The report ranks
items by effect size and states the sample size beside every p-value.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import stats

from app.irt.em import MISSING, ResponseMatrix
from app.irt.families import ItemParameters, get_family

from .information import category_probabilities

_FLOOR = 1e-12


@dataclass(frozen=True)
class ItemFitResult:
    """Fit evidence for one item."""

    item_id: str

    s_x2: float | None
    s_x2_df: int | None
    s_x2_p: float | None
    s_x2_z: float | None

    infit: float | None
    outfit: float | None
    rmsd: float | None

    n_used: int
    notes: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        """Whether the *effect sizes* warrant a look, ignoring p-values.

        Mean-squares outside 0.7-1.3 are the conventional productive range for
        a moderate-stakes test, and an RMSD above 0.10 is the threshold used in
        large-scale international assessment. Both are conventions, not laws,
        and the report states them as such wherever this flag is shown.

        The band is asymmetric in practice: an item that discriminates far
        better than the fitted model allows produces unusually small residuals,
        so it drifts towards the lower edge rather than past it and can escape
        this flag entirely. S-X2 catches that case, which is one reason the
        report never reduces to mean-squares alone.
        """
        if self.rmsd is not None and self.rmsd > 0.10:
            return True
        for ms in (self.infit, self.outfit):
            if ms is not None and not (0.7 <= ms <= 1.3):
                return True
        return False


@dataclass(frozen=True)
class ItemFitReport:
    items: list[ItemFitResult]
    n_persons_complete: int
    notes: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> list[ItemFitResult]:
        return [i for i in self.items if i.flagged]


def item_fit(
    data: ResponseMatrix,
    items: list[ItemParameters],
    *,
    latent_sd: float = 1.0,
    n_points: int = 61,
    bound: float = 6.0,
    min_expected: float = 1.0,
) -> ItemFitReport:
    """Compute S-X2, infit, outfit and RMSD for every item."""
    if len(items) != data.n_items:
        raise ValueError(
            f"{len(items)} item parameter sets for {data.n_items} columns"
        )

    nodes = np.linspace(-bound, bound, n_points)
    prior = np.exp(-0.5 * (nodes / latent_sd) ** 2)
    prior /= prior.sum()

    probs = [category_probabilities(p, nodes) for p in items]
    log_lik = _conditional_loglik(data.values, probs)

    complete = (data.values != MISSING).all(axis=1)
    n_complete = int(complete.sum())

    notes: list[str] = []
    if n_complete < data.n_persons:
        notes.append(
            f"S-X2 uses the {n_complete} of {data.n_persons} respondents with "
            "no missing responses, because a rest score is undefined when part "
            "of the test is unanswered. Infit, outfit and RMSD use every "
            "observed response."
        )
    if n_complete < 200:
        notes.append(
            f"Only {n_complete} complete cases. S-X2 is unreliable below "
            "roughly 200 and is reported for completeness rather than for "
            "decisions."
        )

    results = []
    for j, params in enumerate(items):
        results.append(
            _one_item(
                j,
                params,
                data,
                items,
                probs,
                log_lik,
                nodes,
                prior,
                complete,
                min_expected,
            )
        )

    return ItemFitReport(
        items=results, n_persons_complete=n_complete, notes=notes
    )


# --------------------------------------------------------------------------- #
# Per-item assembly
# --------------------------------------------------------------------------- #


def _one_item(
    j: int,
    params: ItemParameters,
    data: ResponseMatrix,
    items: list[ItemParameters],
    probs: list[np.ndarray],
    log_lik: np.ndarray,
    nodes: np.ndarray,
    prior: np.ndarray,
    complete: np.ndarray,
    min_expected: float,
) -> ItemFitResult:
    column = data.values[:, j]
    observed_mask = column != MISSING
    notes: list[str] = []

    rest = _rest_posterior(log_lik, probs[j], column, prior)[observed_mask]
    infit, outfit = _mean_squares(column[observed_mask], probs[j], rest)
    rmsd = _rmsd(column[observed_mask], probs[j], rest, prior)

    s_x2 = df = p_value = z = None
    if complete.sum() >= 50:
        try:
            s_x2, df, p_value, z = _s_x2(
                j, params, data, items, probs, nodes, prior, complete, min_expected
            )
        except ValueError as exc:
            notes.append(f"S-X2 unavailable: {exc}")
    else:
        notes.append("S-X2 needs at least 50 complete cases.")

    return ItemFitResult(
        item_id=params.item_id,
        s_x2=s_x2,
        s_x2_df=df,
        s_x2_p=p_value,
        s_x2_z=z,
        infit=infit,
        outfit=outfit,
        rmsd=rmsd,
        n_used=int(observed_mask.sum()),
        notes=notes,
    )


def _conditional_loglik(
    values: np.ndarray, probs: list[np.ndarray]
) -> np.ndarray:
    """log P(responses | theta_node) for every respondent, summed over items."""
    n_nodes = probs[0].shape[0]
    log_lik = np.zeros((values.shape[0], n_nodes), dtype=float)
    for j, p in enumerate(probs):
        column = values[:, j]
        observed = column != MISSING
        if not observed.any():
            continue
        log_p = np.log(np.clip(p, _FLOOR, None))
        log_lik[observed] += log_p[:, column[observed]].T
    return log_lik


def _rest_posterior(
    log_lik: np.ndarray,
    item_probs: np.ndarray,
    column: np.ndarray,
    prior: np.ndarray,
) -> np.ndarray:
    """Posterior over theta built from every item *except* the one being judged.

    An item that helps locate a respondent on the trait will then be compared
    against a location it helped choose, and will look better fitting than it
    is. The bias is largest on short tests, where each item carries a large
    share of the evidence - which is exactly where fit statistics are most
    likely to be relied on.

    Removing the item is a subtraction rather than a recomputation, because the
    conditional log-likelihood is a sum over items.
    """
    rest = log_lik.copy()
    observed = column != MISSING
    if observed.any():
        log_p = np.log(np.clip(item_probs, _FLOOR, None))
        rest[observed] -= log_p[:, column[observed]].T

    joint = rest + np.log(np.clip(prior, 1e-300, None))[None, :]
    joint -= joint.max(axis=1, keepdims=True)
    post = np.exp(joint)
    return post / post.sum(axis=1, keepdims=True)


# --------------------------------------------------------------------------- #
# Mean-square residual statistics
# --------------------------------------------------------------------------- #


def _mean_squares(
    responses: np.ndarray, probs: np.ndarray, posterior: np.ndarray
) -> tuple[float | None, float | None]:
    """Infit and outfit mean-squares.

    Both are posterior expectations of the conditional standardised residual,
    integrated over the trait rather than evaluated at a point estimate of each
    respondent's ability::

        outfit_j = mean_i  E_post[ (x_ij - E[X | theta])^2 / Var(X | theta) ]
        infit_j  = sum_i E_post[(x - E)^2]  /  sum_i E_post[Var]

    Infit weights each residual by the information behind it, so it is the less
    sensitive of the two to a handful of surprising responses from respondents
    far from the item's difficulty; outfit is the more sensitive. Reporting both
    is the point - a large outfit with an infit near 1 means a few odd
    respondents, not a bad item.

    Both are divided by their model-implied expectation, so a correctly fitting
    item scores exactly 1 rather than approximately 1. That correction matters
    here. The posterior excludes the item under test, which widens it and
    inflates the raw residuals; the full posterior would instead shrink towards
    the very response being judged and deflate them. Neither raw version has 1
    as its true null, and the conventional 0.7-1.3 range is quoted as though it
    does.

    The expectation is available in closed form because the rest-posterior makes
    the model's predictive distribution for this response explicit:
    ``p(x | x_rest) = integral P(x | theta) p(theta | x_rest) d theta``. Taking
    the expectation of the residual under that distribution gives, for each
    node ``n``, ``sum_m post_m [Var_m + (E_m - E_n)^2]`` - the average
    conditional variance plus the spread of the posterior itself.
    """
    if responses.size == 0:
        return None, None

    categories = np.arange(probs.shape[1], dtype=float)
    node_mean = probs @ categories                              # (n_nodes,)
    node_var = np.clip(probs @ (categories**2) - node_mean**2, _FLOOR, None)

    residual = responses.astype(float)[:, None] - node_mean[None, :]
    squared = residual**2

    # Model-implied expectation of that squared residual at each node.
    mean_var = posterior @ node_var                             # (n_persons,)
    mean_e = posterior @ node_mean
    mean_e2 = posterior @ (node_mean**2)
    expected_squared = (
        (mean_var + mean_e2)[:, None]
        - 2.0 * np.outer(mean_e, node_mean)
        + (node_mean**2)[None, :]
    )

    observed_outfit = np.einsum(
        "pn,pn->p", posterior, squared / node_var[None, :]
    )
    expected_outfit = np.einsum(
        "pn,pn->p", posterior, expected_squared / node_var[None, :]
    )
    observed_infit = np.einsum("pn,pn->p", posterior, squared)
    expected_infit = np.einsum("pn,pn->p", posterior, expected_squared)

    outfit = float(np.sum(observed_outfit) / max(np.sum(expected_outfit), _FLOOR))
    infit = float(np.sum(observed_infit) / max(np.sum(expected_infit), _FLOOR))
    return infit, outfit


def _rmsd(
    responses: np.ndarray,
    probs: np.ndarray,
    posterior: np.ndarray,
    prior: np.ndarray,
) -> float | None:
    """Root-mean-square deviation between observed and expected category curves.

    The observed curve is built by spreading each respondent's response across
    the grid in proportion to their posterior - the same pseudo-count logic the
    E-step uses - then normalising within each node.
    """
    if responses.size == 0:
        return None

    n_cat = probs.shape[1]
    node_mass = posterior.sum(axis=0)                           # (n_nodes,)
    usable = node_mass > 1e-8
    if usable.sum() < 3:
        return None

    observed = np.zeros_like(probs)
    for k in range(n_cat):
        rows = responses == k
        if rows.any():
            observed[:, k] = posterior[rows].sum(axis=0)
    observed[usable] /= node_mass[usable, None]

    weights = prior[usable] * node_mass[usable]
    weights = weights / weights.sum()

    squared = (observed[usable] - probs[usable]) ** 2
    return float(np.sqrt(np.dot(weights, squared.sum(axis=1)) / n_cat))


# --------------------------------------------------------------------------- #
# S-X2
# --------------------------------------------------------------------------- #


def _s_x2(
    j: int,
    params: ItemParameters,
    data: ResponseMatrix,
    items: list[ItemParameters],
    probs: list[np.ndarray],
    nodes: np.ndarray,
    prior: np.ndarray,
    complete: np.ndarray,
    min_expected: float,
) -> tuple[float, int, float, float]:
    """Orlando-Thissen S-X2 for one item, generalised to polytomous responses."""
    values = data.values[complete]
    rest_columns = [c for c in range(data.n_items) if c != j]
    if not rest_columns:
        raise ValueError("a single-item test has no rest score")

    rest_probs = [probs[c] for c in rest_columns]
    rest_distribution = _lord_wingersky(rest_probs)             # (n_nodes, n_scores)

    # Marginal probability of each rest score, and the model-expected
    # distribution of this item's responses within each rest-score group.
    weighted = prior[:, None] * rest_distribution               # (n_nodes, n_scores)
    marginal = weighted.sum(axis=0)                             # (n_scores,)

    n_cat = params.n_categories
    expected_prob = np.zeros((rest_distribution.shape[1], n_cat), dtype=float)
    for k in range(n_cat):
        expected_prob[:, k] = weighted.T @ probs[j][:, k]
    usable = marginal > 1e-12
    expected_prob[usable] /= marginal[usable, None]

    rest_score = values[:, rest_columns].sum(axis=1)
    responses = values[:, j]

    n_scores = rest_distribution.shape[1]
    observed_counts = np.zeros((n_scores, n_cat), dtype=float)
    for k in range(n_cat):
        rows = responses == k
        if rows.any():
            observed_counts[:, k] += np.bincount(
                rest_score[rows], minlength=n_scores
            )

    group_n = observed_counts.sum(axis=1)
    groups = _collapse(group_n, expected_prob, min_expected)
    if not groups:
        raise ValueError("no rest-score group retained enough respondents")

    statistic = 0.0
    cells = 0
    for members in groups:
        n = group_n[members].sum()
        if n <= 0:
            continue
        observed = observed_counts[members].sum(axis=0)
        # Pooled expectation, weighted by how many respondents each merged
        # score level contributed.
        expected = (expected_prob[members] * group_n[members, None]).sum(axis=0)
        keep = expected > _FLOOR
        statistic += float(np.sum((observed[keep] - expected[keep]) ** 2 / expected[keep]))
        cells += int(keep.sum()) - 1

    df = cells - _n_item_parameters(params)
    if df < 1:
        raise ValueError(
            f"only {cells} independent cells survive collapsing, fewer than the "
            f"{_n_item_parameters(params)} parameters this item estimates"
        )

    p_value = float(stats.chi2.sf(statistic, df))
    z = float((statistic - df) / np.sqrt(2.0 * df))
    return float(statistic), int(df), p_value, z


def _lord_wingersky(probs: list[np.ndarray]) -> np.ndarray:
    """Distribution of the summed score, conditional on each quadrature node.

    Builds the compound distribution one item at a time. Each step convolves the
    running score distribution with the next item's category probabilities,
    which for ``n`` items costs ``O(n * max_score)`` per node instead of the
    exponential cost of enumerating response patterns.
    """
    n_nodes = probs[0].shape[0]
    distribution = np.ones((n_nodes, 1), dtype=float)

    for p in probs:
        n_cat = p.shape[1]
        width = distribution.shape[1]
        nxt = np.zeros((n_nodes, width + n_cat - 1), dtype=float)
        for k in range(n_cat):
            nxt[:, k : k + width] += distribution * p[:, k : k + 1]
        distribution = nxt

    return distribution


def _collapse(
    group_n: np.ndarray, expected_prob: np.ndarray, min_expected: float
) -> list[np.ndarray]:
    """Merge adjacent rest-score groups until every cell is large enough.

    Sparse cells are what break a chi-square approximation, and rest-score
    groups at the extremes are always sparse because few respondents score near
    zero or near the maximum. Merging adjacent groups preserves the ordering
    that gives the statistic its power, unlike dropping them.
    """
    groups: list[np.ndarray] = []
    bucket: list[int] = []

    for s in range(group_n.size):
        if group_n[s] <= 0:
            continue
        bucket.append(s)
        idx = np.asarray(bucket)
        pooled = (expected_prob[idx] * group_n[idx, None]).sum(axis=0)
        if pooled.min() >= min_expected:
            groups.append(idx)
            bucket = []

    if bucket:
        idx = np.asarray(bucket)
        if groups:
            groups[-1] = np.concatenate([groups[-1], idx])
        elif group_n[idx].sum() > 0:
            groups.append(idx)

    return groups


def _n_item_parameters(params: ItemParameters) -> int:
    """Free parameters this item contributes, for the S-X2 degrees of freedom."""
    family = get_family(params.model)
    n = family.n_params(params.n_categories)
    from app.irt.families import SlopeMode

    if family.slope_mode is SlopeMode.FIXED:
        n -= 1
    return n
