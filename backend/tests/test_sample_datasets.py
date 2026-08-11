"""The shipped example datasets still match the parameters they are documented by.

`examples/sample_datasets/` claims, in its README and in `MANIFEST.json`, that
each CSV was generated from a stated model with a stated seed and that the
sibling `*.parameters.csv` holds the parameters that produced it. That claim has
one obvious failure mode: someone edits a CSV — trims rows to make it smaller,
fixes a value by hand — and the parameter files silently stop describing the
data, leaving documentation that reads as authoritative and is wrong.

So the digests are checked here. These tests do not re-run the estimator: what is
being defended is the correspondence between the files and their documentation,
not the estimator, which `tests/validation/` covers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from app.analysis.validate import validate

SAMPLES = Path(__file__).resolve().parents[2] / "examples" / "sample_datasets"
MANIFEST = SAMPLES / "MANIFEST.json"

# Columns that describe the respondent rather than an item. The upload API makes
# the caller declare these, never infers them, so a test that reads the files
# directly has to name them too.
NON_ITEM_COLUMNS = {"respondent_id", "group"}


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _entries() -> list[dict]:
    return _manifest()["datasets"]


def _ids(entries: list[dict]) -> list[str]:
    return [entry["filename"] for entry in entries]


def test_the_manifest_and_the_directory_agree():
    """Neither an undocumented dataset nor a documented missing one."""
    on_disk = {path.name for path in SAMPLES.glob("*.csv")} - {
        path.name for path in SAMPLES.glob("*.parameters.csv")
    }
    documented = set(_ids(_entries()))
    assert on_disk == documented


@pytest.mark.parametrize("entry", _entries(), ids=_ids(_entries()))
def test_the_csv_matches_its_recorded_digest(entry: dict):
    path = SAMPLES / entry["filename"]
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()

    # A CRLF checkout is the one failure here that means nothing about the data,
    # and it is also the one a Windows contributor will hit first. `.gitattributes`
    # pins these files to LF; if that has been lost, say so precisely rather than
    # reporting a hash mismatch that reads as corrupted data.
    if digest != entry["sha256"] and b"\r\n" in raw:
        normalised = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
        assert normalised != entry["sha256"], (
            f"{entry['filename']} differs from its recorded digest only in line "
            "endings: it has been checked out with CRLF. The .gitattributes rule "
            "pinning examples/sample_datasets/*.csv to eol=lf is missing or not "
            "in effect. Re-checkout rather than regenerating."
        )

    assert digest == entry["sha256"], (
        f"{entry['filename']} has changed since MANIFEST.json was written. Its "
        f"documented parameters in {entry['parameters_file']} no longer describe "
        "it. Regenerate with backend/scripts/generate_sample_datasets.py rather "
        "than editing the CSV."
    )


@pytest.mark.parametrize("entry", _entries(), ids=_ids(_entries()))
def test_the_shape_and_coding_are_what_the_manifest_says(entry: dict):
    frame = pd.read_csv(SAMPLES / entry["filename"])
    items = frame[[c for c in frame.columns if c not in NON_ITEM_COLUMNS]]

    assert len(frame) == entry["n_persons"]
    assert items.shape[1] == entry["n_items"]

    observed = sorted(int(v) for v in pd.unique(items.to_numpy().ravel()) if pd.notna(v))
    assert observed[0] == entry["first_code"]
    assert len(observed) == entry["n_categories"]

    # A missing rate of zero has to mean no blanks, not "we did not check".
    missing = float(items.isna().to_numpy().mean())
    assert missing == pytest.approx(entry["missing_rate"], abs=0.02)


@pytest.mark.parametrize("entry", _entries(), ids=_ids(_entries()))
def test_every_item_has_documented_parameters(entry: dict):
    frame = pd.read_csv(SAMPLES / entry["filename"])
    items = [c for c in frame.columns if c not in NON_ITEM_COLUMNS]
    parameters = pd.read_csv(SAMPLES / entry["parameters_file"])

    assert parameters["item_id"].tolist() == items
    assert parameters.notna().all().all()


@pytest.mark.parametrize("entry", _entries(), ids=_ids(_entries()))
def test_validation_keeps_every_item(entry: dict):
    """An example that loses a column to validation is a broken example.

    Whatever the platform goes on to say about these datasets, it should not open
    by dropping part of them.
    """
    frame = pd.read_csv(SAMPLES / entry["filename"])
    items = frame[[c for c in frame.columns if c not in NON_ITEM_COLUMNS]]

    result = validate(items)

    assert result.dropped == []
    assert result.n_persons_dropped == 0
    assert result.data.n_items == entry["n_items"]
    assert result.data.n_persons == entry["n_persons"]
    assert list(result.data.n_categories) == [entry["n_categories"]] * entry["n_items"]


def test_the_dif_example_documents_which_items_carry_dif():
    """The planted difference is stated, not left to be inferred from the file."""
    entry = next(e for e in _entries() if e["filename"] == "dichotomous_dif.csv")
    parameters = pd.read_csv(SAMPLES / entry["parameters_file"])

    planted = parameters.loc[parameters["dif_planted"] == "yes", "item_id"].tolist()
    assert planted == entry["dif_items"]

    shift = (
        parameters["difficulty_focal"] - parameters["difficulty_reference"]
    ).round(6)
    assert set(shift[parameters["dif_planted"] == "yes"]) == {entry["dif_shift_logits"]}
    assert set(shift[parameters["dif_planted"] == "no"]) == {0.0}
