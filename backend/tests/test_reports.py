"""Tests for report rendering.

The report is where every earlier refusal to fabricate either holds or is
quietly undone. A template that prints an empty cell for a missing statistic
converts "we could not compute this" into "this looked fine", which is the
single most consequential bug this product can have — so most of what is tested
here is that absence stays visible.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from jinja2 import UndefinedError

from app.analysis import run_analysis
from app.irt import ModelKey
from app.irt.simulate import simulate, spread_parameters
from app.reports import ABSENT, build_context, render
from app.reports.formatting import (
    estimate_with_se,
    interval,
    num,
    percent,
    pvalue,
)

# --------------------------------------------------------------------------
# formatting
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value", [None, float("nan"), float("inf"), float("-inf"), "n/a", object()]
)
def test_every_kind_of_absence_renders_as_the_marker(value):
    assert num(value) == ABSENT
    assert percent(value) == ABSENT
    assert pvalue(value) == ABSENT


def test_zero_is_not_absence():
    """The distinction the whole module exists for."""
    assert num(0.0) == "0.000"
    assert num(0.0) != ABSENT
    assert percent(0.0) == "0.0%"


def test_small_p_values_are_bounded_not_rounded_to_zero():
    """`0.000` reads as "the probability is zero", which it is not."""
    assert pvalue(1e-9) == "< 0.001"
    assert pvalue(0.0) == "< 0.001"
    assert pvalue(0.04) == "0.040"


def test_a_half_open_interval_is_refused():
    """One endpoint is not an interval, and showing it invites reading the
    bound as the result."""
    assert interval(0.04, None) == ABSENT
    assert interval(None, 0.08) == ABSENT
    assert interval(float("nan"), 0.08) == ABSENT
    assert interval(0.041, 0.083) == "[0.041, 0.083]"


def test_a_missing_standard_error_is_stated_not_dropped():
    """An unqualified number reads as a precise one."""
    assert estimate_with_se(1.25, 0.10) == "1.250 ± 0.100"
    assert estimate_with_se(1.25, None) == f"1.250 (SE {ABSENT})"
    assert estimate_with_se(None, 0.10) == ABSENT


# --------------------------------------------------------------------------
# fixtures mimicking persisted rows
# --------------------------------------------------------------------------


def _item_row(position: int, params) -> SimpleNamespace:
    return SimpleNamespace(
        item_id=params.item_id,
        position=position,
        n_categories=getattr(params, "n_categories", 2),
        discrimination=params.discrimination,
        difficulty=params.difficulty,
        guessing=params.guessing,
        thresholds=list(params.thresholds or []),
        se_discrimination=params.se_discrimination,
        se_difficulty=params.se_difficulty,
        se_guessing=params.se_guessing,
        se_thresholds=list(params.se_thresholds or []),
    )


def _fit_row(fit) -> SimpleNamespace:
    return SimpleNamespace(
        model_key=fit.model.value,
        converged=fit.converged,
        n_cycles=fit.n_cycles,
        log_likelihood=fit.log_likelihood,
        n_free_parameters=fit.n_free_parameters,
        n_persons=fit.n_persons,
        aic=fit.aic,
        bic=fit.bic,
        latent_sd=fit.latent_sd,
        elapsed_seconds=fit.elapsed_seconds,
        failure_reason=fit.failure_reason,
        notes=list(fit.notes),
        item_parameters=[
            _item_row(i, p) for i, p in enumerate(fit.item_parameters)
        ],
    )


def _rows(result, *, status="succeeded", stakes="high", use="certification"):
    run = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        status=status,
        requested_models=[f.model_key for f in map(_fit_row, result.fits)],
        seed=5,
        engine_version="2.0.0-test",
        created_at=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
        started_at=datetime(2026, 8, 6, 9, 0, 1, tzinfo=UTC),
        finished_at=datetime(2026, 8, 6, 9, 2, 30, tzinfo=UTC),
        failure_reason=None,
        notes=list(result.notes),
        fits=[_fit_row(f) for f in result.fits],
        diagnostics=SimpleNamespace(payload=result.diagnostics),
    )
    dataset = SimpleNamespace(
        id="22222222-2222-2222-2222-222222222222",
        original_filename="responses.csv",
        checksum_sha256="a" * 64,
        size_bytes=4096,
        n_persons=500,
        n_items=10,
        column_metadata={},
        created_at=datetime(2026, 8, 6, 8, 0, tzinfo=UTC),
    )
    project = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333",
        name="Certification Pilot",
        description="Form A, spring administration.",
        stakes_level=stakes,
        intended_use=use,
    )
    return run, dataset, project


@pytest.fixture(scope="module")
def analysis():
    true = spread_parameters(ModelKey.TWO_PL, 10)
    data, _ = simulate(true, 500, seed=71)
    frame = pd.DataFrame(
        data.values, columns=[f"i{j}" for j in range(data.n_items)]
    )
    return run_analysis(frame, ["rasch", "2pl"], seed=5)


def _render(result, **kwargs) -> str:
    run, dataset, project = _rows(result, **kwargs)
    return render(build_context(run=run, dataset=dataset, project=project))


@pytest.fixture(scope="module")
def html(analysis):
    return _render(analysis)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def test_a_real_analysis_renders(html):
    assert html.lstrip().startswith("<!doctype html>")
    assert "Certification Pilot" in html
    assert "Model comparison" in html
    assert "Item fit" in html
    assert "Assumptions" in html
    assert "Reproducing this analysis" in html


def test_the_report_never_names_a_best_model(html):
    """The product's central reversal. v1's flagship feature was picking one."""
    assert "does not name a best model" in html
    for phrase in ("best model is", "recommended model", "winning model", "Best model:"):
        assert phrase not in html


def test_reproducibility_metadata_is_present(html):
    assert "a" * 64 in html            # dataset checksum
    assert "2.0.0-test" in html        # engine version
    assert "responses.csv" in html
    assert "Random seed" in html


def test_statistics_that_were_computed_actually_reach_the_page(analysis, html):
    """The mirror image of the absence tests, and the more dangerous direction.

    Every payload field is read with `.get(...)`, so a field name that does not
    match the payload renders as "not computed" — indistinguishable from a
    statistic that genuinely failed. A whole section can therefore go missing
    while the report still looks well-formed. This pins the field names of every
    headline statistic against a real payload.

    It caught exactly that: RMSEA2 was being read as `rmsea`, the local
    independence pairs as `flagged_pairs`, and the DIF group labels as
    `reference`/`focal` — and `flagged` reached the payload for nothing at all,
    because it is a property and the serialiser walked declared fields only.
    """
    diag = analysis.diagnostics
    two_pl = diag["per_model"]["2pl"]

    # The values must exist in the payload...
    assert two_pl["global_fit"]["rmsea2"] is not None
    assert two_pl["reliability"]["marginal_bayesian"] is not None
    assert diag["assumptions"]["unidimensionality"]["n_factors_parallel"] is not None
    assert all("flagged" in item for item in two_pl["item_fit"]["items"])

    # ...and they must appear on the page as numbers.
    for label in (
        "RMSEA2",
        "Marginal reliability (Bayesian)",
        "Factors retained (parallel analysis)",
        "McDonald's omega",
    ):
        assert label in html
        section = html.split(label, 1)[1][:220]
        assert ABSENT not in section, f"{label} rendered as absent"


def test_absent_values_render_as_the_marker_not_as_blank_cells(analysis):
    """Blank out a statistic and check the report says so."""
    payload = {k: v for k, v in analysis.diagnostics.items()}
    payload["per_model"] = {
        key: {**value, "reliability": None}
        for key, value in payload["per_model"].items()
    }
    stripped = SimpleNamespace(
        fits=analysis.fits, diagnostics=payload, notes=analysis.notes
    )
    out = _render(stripped)

    assert ABSENT in out
    # An empty cell is the failure mode; there must be none where a number went.
    assert "<td class=\"n\"></td>" not in out


def test_failed_diagnostics_are_shown_with_their_reasons(analysis):
    payload = dict(analysis.diagnostics)
    payload["failures"] = [
        {"diagnostic": "local_independence", "error": "MemoryError: bootstrap"}
    ]
    payload["n_diagnostics_failed"] = 1
    stripped = SimpleNamespace(
        fits=analysis.fits, diagnostics=payload, notes=analysis.notes
    )
    out = _render(stripped)

    assert "could not be computed" in out
    assert "local_independence" in out
    assert "MemoryError: bootstrap" in out
    assert "not evidence that nothing was wrong" in out


def test_a_failed_run_is_not_dressed_up_as_a_result(analysis):
    run, dataset, project = _rows(analysis, status="failed")
    run.failure_reason = "LinAlgError: singular matrix"
    run.fits = []
    run.diagnostics = None

    out = render(build_context(run=run, dataset=dataset, project=project))

    assert "This run did not produce results" in out
    assert "LinAlgError: singular matrix" in out
    assert "no results to report" in out


def test_stakes_and_intended_use_reach_the_report(analysis):
    high = _render(analysis, stakes="high")
    low = _render(analysis, stakes="low", use="research")

    assert "declared high-stakes" in high
    assert "declared low-stakes" in low
    assert "precision at the cut" in high
    # Guidance changes the framing and never the numbers.
    assert "has been filtered, reordered or hidden" in high


def test_run_notes_are_rendered_as_content(analysis, html):
    assert analysis.notes
    for note in analysis.notes[:3]:
        # Notes may contain characters the template escapes; compare on a
        # distinctive escaped-safe fragment.
        fragment = re.sub(r"[<>&\"']", "", note)[:60]
        assert fragment in re.sub(r"[<>&\"']", "", html)


def test_alpha_is_named_only_to_explain_its_absence(html):
    assert "Cronbach's alpha is deliberately not reported" in html


def test_user_supplied_text_is_escaped(analysis):
    run, dataset, project = _rows(analysis)
    project.name = "<script>alert(1)</script>"
    dataset.original_filename = "a\"><img src=x onerror=alert(1)>.csv"

    out = render(build_context(run=run, dataset=dataset, project=project))

    # The property that matters is that no *tag* is formed. The inert text
    # "onerror=alert(1)" surviving inside an escaped string is harmless; an
    # unescaped angle bracket is not.
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out
    assert "<img src=x" not in out
    assert "&lt;img src=x" in out


def test_a_renamed_field_raises_rather_than_rendering_blank():
    """StrictUndefined is the point: a silent blank is the dangerous outcome."""
    from app.reports.render import _environment

    template = _environment().from_string("{{ ctx.nonexistent_field }}")
    with pytest.raises(UndefinedError):
        template.render(ctx=SimpleNamespace())
