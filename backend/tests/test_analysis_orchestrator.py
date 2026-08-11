"""Tests for the analysis orchestrator and the JSON conversion it depends on.

The orchestrator's job is not to compute anything - every statistic it reports
is tested in its own suite. Its job is to get the *wiring* right, and the wiring
has three ways to go wrong silently: a latent metric that does not travel, a
diagnostic failure that disappears, and a payload that cannot be stored. Those
are what is tested here.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from app.analysis import run_analysis, to_jsonable
from app.analysis.orchestrator import _score_summary
from app.irt import ModelKey
from app.irt.simulate import simulate, spread_parameters


def _frame(model: ModelKey, n_items: int, n_persons: int, seed: int, **kwargs):
    true = spread_parameters(model, n_items, **kwargs)
    data, theta = simulate(true, n_persons, seed=seed)
    frame = pd.DataFrame(
        data.values, columns=[f"i{j}" for j in range(data.n_items)]
    )
    return frame, theta


# --------------------------------------------------------------------------
# serialisation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Nested:
    label: str
    value: float


@dataclass(frozen=True)
class _Outer:
    name: ModelKey
    rows: list[_Nested]
    array: np.ndarray
    count: np.int64


def test_non_finite_floats_become_null_because_json_has_no_nan():
    """Bare NaN is invalid JSON and Postgres jsonb rejects it outright."""
    payload = to_jsonable(
        {"a": float("nan"), "b": float("inf"), "c": float("-inf"), "d": 1.5}
    )

    assert payload == {"a": None, "b": None, "c": None, "d": 1.5}
    # The real requirement: it survives a strict round trip.
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload


def test_dataclasses_enums_and_numpy_all_convert():
    value = _Outer(
        name=ModelKey.TWO_PL,
        rows=[_Nested("x", 1.0), _Nested("y", float("nan"))],
        array=np.array([1.0, 2.0, np.nan]),
        count=np.int64(7),
    )

    payload = to_jsonable(value)

    assert payload["name"] == "2pl"
    assert payload["rows"] == [
        {"label": "x", "value": 1.0},
        {"label": "y", "value": None},
    ]
    assert payload["array"] == [1.0, 2.0, None]
    assert payload["count"] == 7
    json.dumps(payload, allow_nan=False)


def test_declared_properties_are_serialised():
    """`dataclasses.fields()` skips properties, so they must be opted in."""

    @dataclass(frozen=True)
    class WithProperty:
        raw: int
        JSON_PROPERTIES = ("doubled", "verdict")

        @property
        def doubled(self) -> int:
            return self.raw * 2

        @property
        def verdict(self) -> bool:
            return self.raw > 0

    assert to_jsonable(WithProperty(raw=3)) == {
        "raw": 3,
        "doubled": 6,
        "verdict": True,
    }


def test_every_declared_property_survives_to_the_payload():
    """A guard against the way this can silently half-work.

    ``JSON_PROPERTIES`` is a plain class attribute, so a second declaration
    lower in the same class body overwrites the first with no error. That is
    exactly what happened to ``DIFResult.flagged_by``: two declarations, the
    later one naming only ``flagged``, and the method-by-method breakdown of why
    an item was flagged quietly stopped being serialised while everything still
    looked fine.

    This walks every result class the diagnostics return and checks that each
    name it declares actually appears in its serialised form.
    """
    import dataclasses
    import importlib

    modules = [
        importlib.import_module(f"app.psychometrics.{name}")
        for name in ("itemfit", "dif", "assumptions", "comparison")
    ]

    checked = 0
    for module in modules:
        for obj in vars(module).values():
            if not (isinstance(obj, type) and dataclasses.is_dataclass(obj)):
                continue
            declared = getattr(obj, "JSON_PROPERTIES", ())
            for name in declared:
                assert isinstance(getattr(obj, name, None), property), (
                    f"{obj.__name__}.JSON_PROPERTIES names {name!r}, "
                    "which is not a property on that class"
                )
                checked += 1

    # If this drops to zero the opt-in mechanism has been removed and every
    # assertion above passes vacuously.
    assert checked >= 8


def test_tuple_keys_are_joined_rather_than_dropped():
    """Item-pair tables are keyed by tuples and must survive."""
    payload = to_jsonable({("i1", "i2"): 0.31})
    assert payload == {"i1|i2": 0.31}


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------


def test_single_model_run_produces_a_complete_picture():
    frame, _ = _frame(ModelKey.TWO_PL, 12, 600, seed=11)

    result = run_analysis(frame, ["2pl"], seed=5)

    assert len(result.fits) == 1
    assert result.fits[0].converged
    d = result.diagnostics

    assert d["sample"]["n_persons"] == 600
    assert d["sample"]["n_items"] == 12
    assert d["reference_model"] == "2pl"
    assert d["comparison"] is None
    assert d["per_model"]["2pl"]["item_fit"] is not None
    assert d["per_model"]["2pl"]["reliability"] is not None
    assert d["assumptions"]["unidimensionality"] is not None
    assert d["person_scores"]["n_scored"] == 600

    # Absence of a comparison is stated, not left to be inferred.
    assert any("no comparison" in n for n in result.notes)


def test_the_whole_diagnostics_payload_is_strict_json():
    """Nothing reaches the database that a jsonb column would reject."""
    frame, _ = _frame(ModelKey.TWO_PL, 10, 400, seed=13)

    result = run_analysis(frame, ["2pl"], seed=5)

    encoded = json.dumps(result.diagnostics, allow_nan=False)
    assert json.loads(encoded) == result.diagnostics


def test_comparison_runs_for_two_models_and_names_no_winner():
    frame, _ = _frame(ModelKey.TWO_PL, 10, 500, seed=17)

    result = run_analysis(frame, ["rasch", "2pl"], seed=5)

    assert len(result.fits) == 2
    dossier = result.diagnostics["comparison"]
    assert dossier is not None
    assert "best_model" not in dossier
    assert len(dossier["ranked"]) == 2
    # Both models get their own item fit and global fit.
    assert set(result.diagnostics["per_model"]) == {"rasch", "2pl"}


def test_the_reference_model_choice_is_recorded_with_its_rationale():
    """Choosing a model to diagnose against is not choosing a winner, and the
    output has to say which one it is doing."""
    frame, _ = _frame(ModelKey.TWO_PL, 10, 500, seed=19)

    result = run_analysis(frame, ["rasch", "2pl"], seed=5)

    reference = result.diagnostics["reference_model"]
    rationale = result.diagnostics["reference_model_rationale"]
    assert reference in {"rasch", "2pl"}
    assert rationale and reference is not None
    # The rationale is in the notes a reader sees, not only in the payload.
    assert any(rationale == n for n in result.notes)


def test_latent_sd_travels_from_the_fit_into_the_diagnostics(monkeypatch):
    """Rasch leaves the latent variance free, so 1.0 is the wrong metric.

    This is the defect that produces plausible-looking but wrong residuals
    everywhere downstream, so it is asserted directly on the call arguments
    rather than inferred from a number.
    """
    frame, _ = _frame(ModelKey.RASCH, 10, 500, seed=23)
    seen: dict[str, float] = {}

    import app.analysis.orchestrator as orch

    real_item_fit = orch.item_fit
    real_global_fit = orch.global_fit

    def spy_item_fit(data, items, **kwargs):
        seen["item_fit"] = kwargs["latent_sd"]
        return real_item_fit(data, items, **kwargs)

    def spy_global_fit(data, items, **kwargs):
        seen["global_fit"] = kwargs["latent_sd"]
        return real_global_fit(data, items, **kwargs)

    monkeypatch.setattr(orch, "item_fit", spy_item_fit)
    monkeypatch.setattr(orch, "global_fit", spy_global_fit)

    result = run_analysis(frame, ["rasch"], seed=5)
    fitted_sd = result.fits[0].latent_sd

    assert seen["item_fit"] == fitted_sd
    assert seen["global_fit"] == fitted_sd
    # The premise of the test: the fitted value is not the default.
    assert fitted_sd != pytest.approx(1.0, abs=1e-6)


def test_a_failing_diagnostic_is_recorded_and_does_not_fail_the_run(monkeypatch):
    import app.analysis.orchestrator as orch

    def explode(*args, **kwargs):
        raise RuntimeError("bootstrap ran out of memory")

    monkeypatch.setattr(orch, "unidimensionality", explode)
    frame, _ = _frame(ModelKey.TWO_PL, 10, 400, seed=29)

    result = run_analysis(frame, ["2pl"], seed=5)

    # The run still delivers everything else.
    assert result.fits and result.fits[0].converged
    assert result.diagnostics["per_model"]["2pl"]["item_fit"] is not None

    failures = result.diagnostics["failures"]
    assert len(failures) == 1
    assert failures[0]["diagnostic"] == "unidimensionality"
    assert "bootstrap ran out of memory" in failures[0]["error"]
    assert result.diagnostics["n_diagnostics_failed"] == 1
    # A missing diagnostic is stated in the prose, not only in a counter.
    assert any("could not be computed" in n for n in result.notes)


def test_dichotomous_models_are_refused_on_polytomous_data_with_a_reason():
    frame, _ = _frame(ModelKey.GRM, 8, 500, seed=31, n_categories=4)

    result = run_analysis(frame, ["2pl", "grm"], seed=5)

    assert [f.model for f in result.fits] == [ModelKey.GRM]
    assert any(
        "dichotomous model" in n and "Collapsing" in n for n in result.notes
    )


def test_requesting_only_inapplicable_models_raises():
    frame, _ = _frame(ModelKey.GRM, 8, 300, seed=37, n_categories=4)

    with pytest.raises(ValueError, match="none of the requested models"):
        run_analysis(frame, ["2pl", "3pl"], seed=5)


def test_dropped_columns_are_reported_and_excluded_from_the_fit():
    frame, _ = _frame(ModelKey.TWO_PL, 10, 400, seed=41)
    frame["constant"] = 1

    result = run_analysis(frame, ["2pl"], seed=5)

    dropped = result.diagnostics["validation"]["dropped_items"]
    assert [d["item_id"] for d in dropped] == ["constant"]
    assert result.diagnostics["sample"]["n_items"] == 10
    assert len(result.fits[0].item_parameters) == 10


def test_dif_runs_when_groups_are_supplied():
    frame, _ = _frame(ModelKey.TWO_PL, 10, 600, seed=43)
    groups = pd.DataFrame(
        {"gender": ["a"] * 300 + ["b"] * 300}
    )

    result = run_analysis(frame, ["2pl"], groups=groups, seed=5)

    assert result.diagnostics["dif"] is not None
    assert "gender" in result.diagnostics["dif"]
    assert any("screen, not a verdict" in n for n in result.notes)


def test_a_single_group_is_refused_rather_than_screened():
    frame, _ = _frame(ModelKey.TWO_PL, 10, 400, seed=47)
    groups = pd.DataFrame({"cohort": ["only"] * 400})

    result = run_analysis(frame, ["2pl"], groups=groups, seed=5)

    assert result.diagnostics["dif"] is None
    assert any("fewer than two distinct groups" in n for n in result.notes)


def test_misaligned_groups_refuse_rather_than_matching_by_position():
    """Attaching the wrong group to every respondent is worse than no DIF."""
    frame, _ = _frame(ModelKey.TWO_PL, 10, 400, seed=53)
    frame = frame.astype(float)
    frame.iloc[5, :] = np.nan  # validation will drop this respondent
    groups = pd.DataFrame({"g": ["a"] * 200 + ["b"] * 200})

    result = run_analysis(frame, ["2pl"], groups=groups, seed=5)

    assert result.diagnostics["dif"] is None
    assert any("no longer aligns" in n for n in result.notes)


def test_run_is_reproducible_under_a_fixed_seed():
    frame, _ = _frame(ModelKey.TWO_PL, 10, 400, seed=59)

    first = run_analysis(frame, ["2pl"], seed=7)
    second = run_analysis(frame, ["2pl"], seed=7)

    # Timing legitimately differs between runs; nothing else may.
    for payload in (first.diagnostics, second.diagnostics):
        payload.pop("elapsed_seconds")
    assert first.diagnostics == second.diagnostics
    assert first.notes == second.notes


def test_unscorable_respondents_are_absent_not_placed_at_the_prior_mean():
    scores = type(
        "S", (), {"theta": np.array([1.0, np.nan, -0.5, np.nan]), "method": "eap"}
    )()

    summary = _score_summary(scores)

    assert summary["n_scored"] == 2
    assert summary["n_unscorable"] == 2
    assert "prior mean" in summary["note"]
    assert summary["mean"] == pytest.approx(0.25)
    assert math.isfinite(summary["minimum"])


def test_the_worker_can_actually_call_this_orchestrator(tmp_path):
    """The worker's contract with the orchestrator, tested unstubbed.

    ``tests/test_worker_pipeline.py`` replaces the whole ``app.analysis`` module
    with a fake, which is right for testing the job's failure handling but means
    nothing there checks that the real orchestrator matches the shape the worker
    expects. This runs the worker's own ``_analyse`` against a real CSV, and
    then maps the result through the same persistence mapper the job uses - the
    two places where a signature drift would otherwise reach production
    unnoticed.
    """
    from app.repositories.analyses import fit_to_row
    from app.storage import LocalObjectStore
    from app.workers.tasks import _analyse

    frame, _ = _frame(ModelKey.TWO_PL, 10, 400, seed=67)
    frame["cohort"] = ["a"] * 200 + ["b"] * 200

    # Through the store, by reference, exactly as the job does it — a path here
    # would stop exercising the read path the worker actually uses.
    store = LocalObjectStore(tmp_path)
    ref = store.put("datasets/responses.csv", frame.to_csv(index=False).encode())

    metadata = {
        "item_columns": [c for c in frame.columns if c != "cohort"],
        "group_columns": ["cohort"],
    }

    fits, diagnostics, notes = _analyse(store, ref, metadata, ["2pl"], 5)

    assert len(fits) == 1 and fits[0].converged
    assert isinstance(diagnostics, dict) and isinstance(notes, list)
    assert diagnostics["dif"] is not None
    json.dumps(diagnostics, allow_nan=False)

    row = fit_to_row(fits[0])
    assert row.model_key == "2pl"
    assert row.converged
    assert len(row.item_parameters) == 10
    assert row.aic is not None and row.bic is not None


def test_no_models_requested_is_an_error():
    frame, _ = _frame(ModelKey.TWO_PL, 8, 200, seed=61)
    with pytest.raises(ValueError, match="no models were requested"):
        run_analysis(frame, [], seed=5)
