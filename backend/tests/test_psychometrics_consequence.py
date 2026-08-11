"""Consequence analysis: does the model choice change any decision?

The design hazard here is not arithmetic, it is metric. Rasch leaves the latent
variance free and the 2PL fixes it, so two models that rank every respondent
identically still produce θ vectors on different scales. A naive difference would
report that convention as a consequence — a large one — and the report would say
the model choice mattered when nothing had changed hands. Most of what follows
exists to pin that down.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.psychometrics import ScoreMethod
from app.psychometrics.consequence import (
    STABLE_MAX_RECLASSIFIED,
    STABLE_MIN_CORRELATION,
    consequence,
)
from app.psychometrics.scoring import PersonScores


def _scores(theta: np.ndarray, *, se: float | np.ndarray = 0.3) -> PersonScores:
    theta = np.asarray(theta, dtype=float)
    errors = np.full(theta.shape, se) if np.isscalar(se) else np.asarray(se, dtype=float)
    return PersonScores(
        method=ScoreMethod.EAP,
        theta=theta,
        standard_error=errors,
        n_responses=np.full(theta.shape, 10),
    )


def _theta(n: int = 400, seed: int = 11) -> np.ndarray:
    return np.random.default_rng(seed).normal(size=n)


# --------------------------------------------------------------------------
# the metric problem
# --------------------------------------------------------------------------


def test_a_pure_rescaling_is_not_reported_as_a_consequence():
    """The defect this module is built to avoid.

    A Rasch fit with latent SD 1.4 and a 2PL fit that ranked every respondent
    identically differ by a linear transformation and nothing else. If that shows
    up as a difference, every report on Rasch-and-2PL data — the default request —
    carries a false finding.
    """
    theta = _theta()
    report = consequence({"rasch": _scores(theta * 1.4 + 0.7), "2pl": _scores(theta)})

    pair = report.pairs[0]
    assert pair.pearson_r == pytest.approx(1.0, abs=1e-9)
    assert pair.spearman_rho == pytest.approx(1.0, abs=1e-9)
    assert pair.max_absolute_difference == pytest.approx(0.0, abs=1e-9)
    assert all(r.n_reclassified == 0 for r in pair.reclassification)
    assert report.stable is True


def test_a_rank_reversal_is_reported_even_when_the_scales_match():
    """The complement: same scale, different decisions."""
    theta = _theta()
    shuffled = theta.copy()
    rng = np.random.default_rng(3)
    swap = rng.permutation(theta.size)[:200]
    shuffled[swap] = shuffled[swap][::-1]

    report = consequence({"a": _scores(theta), "b": _scores(shuffled)})

    pair = report.pairs[0]
    assert pair.pearson_r is not None and pair.pearson_r < STABLE_MIN_CORRELATION
    assert pair.max_proportion_reclassified > STABLE_MAX_RECLASSIFIED
    assert report.stable is False


# --------------------------------------------------------------------------
# what it reports
# --------------------------------------------------------------------------


def test_reclassification_counts_who_changes_side_of_the_cut():
    """A fixed selection rate, so the question is who and not how many."""
    theta = np.linspace(-2, 2, 100)
    # Swap the two respondents either side of the 25% cut, leaving everyone else
    # in place: exactly two people change status, and no others.
    other = theta.copy()
    other[74], other[75] = theta[75], theta[74]

    report = consequence({"a": _scores(theta), "b": _scores(other)}, selection_rates=(0.25,))

    entry = report.pairs[0].reclassification[0]
    assert entry.n_selected_a == 25
    assert entry.n_selected_b == 25
    assert entry.n_reclassified == 2
    assert entry.proportion_reclassified == pytest.approx(0.02)
    assert entry.kappa is not None and entry.kappa < 1.0


def test_kappa_is_absent_rather_than_perfect_when_nobody_is_selected():
    """A selection rate that selects everyone leaves nothing to agree about."""
    theta = _theta(50)
    report = consequence({"a": _scores(theta), "b": _scores(theta)}, selection_rates=(1.0,))

    entry = report.pairs[0].reclassification[0]
    assert entry.n_selected_a == 0
    assert entry.kappa is None


def test_standard_errors_are_compared_on_the_same_footing():
    """WLE-style wider errors show up as a ratio, not as noise.

    The SEs are divided by the same scale factor as the scores, so a model on a
    wider metric does not appear to be less precise merely for being on a wider
    metric.
    """
    theta = _theta()
    tight = _scores(theta, se=0.30)
    wide = _scores(theta * 2.0, se=np.full(theta.shape, 0.90))

    pair = consequence({"tight": tight, "wide": wide}).pairs[0]

    # 0.90 / 2.0 = 0.45 against 0.30 — 1.5x, after removing the metric.
    assert pair.se_ratio_median == pytest.approx(1.5, rel=1e-6)


def test_respondents_unscorable_under_any_model_are_excluded_from_all_pairs():
    theta = _theta(100)
    with_gaps = theta.copy()
    with_gaps[[4, 9, 14]] = np.nan

    report = consequence({"a": _scores(theta), "b": _scores(with_gaps)})

    assert report.n_respondents_compared == 97
    assert all(p.n_compared == 97 for p in report.pairs)


def test_every_pair_is_compared():
    theta = _theta(120)
    report = consequence(
        {"rasch": _scores(theta), "2pl": _scores(theta * 1.1), "3pl": _scores(theta * 0.9)}
    )
    assert len(report.pairs) == 3
    assert {(p.model_a, p.model_b) for p in report.pairs} == {
        ("rasch", "2pl"),
        ("rasch", "3pl"),
        ("2pl", "3pl"),
    }


# --------------------------------------------------------------------------
# refusals, and the verdict
# --------------------------------------------------------------------------


def test_one_model_yields_no_verdict_rather_than_a_reassuring_one():
    """Absence of a comparison is not evidence that the choice does not matter."""
    report = consequence({"2pl": _scores(_theta())})

    assert report.pairs == []
    assert report.stable is None
    assert "nothing here to compare" in report.verdict
    assert "not the same as the model choice not mattering" in report.verdict


def test_too_few_scorable_respondents_is_a_refusal():
    theta = np.array([0.4, np.nan, np.nan, np.nan])
    report = consequence({"a": _scores(theta), "b": _scores(theta)})

    assert report.stable is None
    assert report.pairs == []
    assert "too few" in report.verdict


def test_a_degenerate_score_vector_is_flagged_rather_than_divided_by_zero():
    flat = np.zeros(50)
    report = consequence({"flat": _scores(flat), "real": _scores(_theta(50))})

    assert any("same score for every respondent" in note for note in report.notes)
    assert any("raw logits" in note for note in report.notes)


def test_the_verdict_carries_the_numbers_it_was_computed_from():
    """ARCHITECTURE §3.3: a rationale may not assert what was not computed.

    v1's model selection wrote fixed prose that read as a finding. So the verdict
    has to contain the statistics behind it, and the thresholds it applied, and
    this is the test that keeps it that way.
    """
    theta = _theta()
    report = consequence({"a": _scores(theta), "b": _scores(theta * 1.4)})

    pair = report.pairs[0]
    assert f"r = {pair.pearson_r:.4f}" in report.verdict
    assert f"{report.n_respondents_compared} respondents" in report.verdict
    assert f"{STABLE_MIN_CORRELATION}" in report.verdict
    assert f"{STABLE_MAX_RECLASSIFIED:.0%} reclassified" in report.verdict
    # And it does not overclaim: a stable verdict is about decisions, not fit.
    assert "not a statement that the models fit equally well" in report.verdict


def test_the_standardisation_is_disclosed():
    """A reader has to know the differences are in sample SD units."""
    theta = _theta()
    report = consequence({"a": _scores(theta), "b": _scores(theta * 1.2)})

    assert any("standard deviations of this sample" in note for note in report.notes)
    assert any("not a policy" in note for note in report.notes)


def test_a_tie_group_straddling_the_cut_is_reported_rather_than_split():
    """Ties are the honest awkwardness in a selection-rate comparison.

    A Rasch fit scores by sum score, so respondents tie in groups. Splitting a tie
    to hit the nominal count would report a reclassification caused by `argsort`
    order; taking the group whole makes the two selections different sizes. The
    second is the defensible choice, and it is only defensible if the report says
    the counts differ and why.
    """
    # Ten distinct scores, ten respondents each: any cut inside a group is
    # undecidable, which is exactly the Rasch situation.
    tied = np.repeat(np.arange(10.0), 10)
    distinct = np.arange(100.0)

    report = consequence(
        {"tied": _scores(tied), "distinct": _scores(distinct)}, selection_rates=(0.25,)
    )

    entry = report.pairs[0].reclassification[0]
    assert entry.n_selected_a == 30      # the whole tied group, not 25 of it
    assert entry.n_selected_b == 25
    assert any("tie exactly on score" in note for note in report.notes)
    assert any("30 against 25" in note for note in report.notes)
