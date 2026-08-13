#!/usr/bin/env python
"""Generate the shipped example datasets from documented parameters.

``app/irt/simulate.py`` claims in its own docstring that the shipped examples
are generated from documented parameters with a recorded seed. Until this script
existed that claim was false: ``examples/sample_datasets/`` carried files
inherited from v1 whose generating parameters nobody had written down, and a
README describing a fourth file that did not exist.

What this script produces, for each dataset:

* the response CSV itself;
* a sibling ``<name>.parameters.csv`` holding the parameters that generated it,
  so the "right answer" for every example is a known quantity rather than a
  claim;
* an entry in ``MANIFEST.json`` recording the seed, the shape and the SHA-256 of
  the CSV. ``tests/test_sample_datasets.py`` checks the shipped files against
  those digests, so a hand-edited example — the ordinary way a documented
  parameter set stops describing its data — fails the suite instead of quietly
  becoming wrong.

Run from the ``backend`` directory:

    python scripts/generate_sample_datasets.py

Regeneration is byte-identical for a given numpy: the draws come from explicitly
seeded ``PCG64`` streams, whose output numpy's own compatibility policy fixes.

Nothing in the application imports this module. It is a build step for the
repository's examples, kept in the tree because a dataset whose generator has
been lost is exactly the artefact this file exists to stop shipping.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.irt import MISSING, ModelKey  # noqa: E402
from app.irt.simulate import TrueParameters, simulate, spread_parameters  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "examples" / "sample_datasets"


@dataclass(frozen=True)
class Spec:
    """One example dataset, and everything needed to reproduce it."""

    filename: str
    model: ModelKey
    n_persons: int
    n_items: int
    seed: int
    purpose: str
    n_categories: int = 2
    # Response codes are written as ``first_code + category``. A Likert file that
    # ships as 0-4 teaches the wrong thing about survey data; the validator maps
    # categories by value, so 1-5 arrives at the estimator as the same matrix.
    first_code: int = 0
    item_prefix: str = "item_"
    missing_rate: float = 0.0


SPECS: list[Spec] = [
    Spec(
        filename="dichotomous_small.csv",
        model=ModelKey.TWO_PL,
        n_persons=200,
        n_items=20,
        seed=20260803,
        purpose=(
            "Smallest useful dichotomous example. Fits in seconds, which makes it "
            "the one to upload first. At n = 200 the standard errors are wide "
            "enough to be worth reading: several item fit statistics will be "
            "non-significant here purely for want of power."
        ),
    ),
    Spec(
        filename="dichotomous_medium.csv",
        model=ModelKey.THREE_PL,
        n_persons=500,
        n_items=30,
        seed=20260804,
        purpose=(
            "Generated with real lower asymptotes (c between 0.15 and 0.25), so a "
            "3PL fit has something to find. It will find it poorly: at n = 500 the "
            "lower asymptote is weakly identified, and the Beta(5, 17) prior does "
            "most of the work. That is a property of the design rather than of the "
            "estimator, and it is why this file is not described as 'suitable for "
            "the 3PL'."
        ),
    ),
    Spec(
        filename="polytomous_likert.csv",
        model=ModelKey.GRM,
        n_persons=300,
        n_items=15,
        seed=20260805,
        n_categories=5,
        first_code=1,
        item_prefix="q",
        missing_rate=0.06,
        purpose=(
            "A five-point rating scale coded 1-5, as survey data usually arrives. "
            "Validation reports the offset it removes; the estimator sees 0-4 "
            "either way. 6% of responses are missing completely at random, which "
            "is where item nonresponse actually turns up, and the marginal "
            "likelihood absorbs it per cell with nothing imputed."
        ),
    ),
]

# The fourth dataset is not a plain `simulate()` call: it has two groups with
# deliberately different difficulties on three items, so it is built separately.
DIF_SPEC = Spec(
    filename="dichotomous_dif.csv",
    model=ModelKey.TWO_PL,
    n_persons=800,
    n_items=20,
    seed=20260806,
    purpose=(
        "The example for DIF screening. Items 5, 11 and 17 are 0.8 logits harder "
        "for the focal group and nothing else differs: the two groups are drawn "
        "from the same trait distribution, so there is no impact for the "
        "observed-score methods to be confounded by. That makes this the best "
        "case for Mantel-Haenszel rather than a representative one. The file "
        "carries respondent_id and group columns, so it is also the example for "
        "declaring id and grouping columns on upload."
    ),
)
# Complete by design, and that is not an oversight. The observed-score DIF
# methods need a matching score, which is undefined for a respondent who left
# part of the test blank, so they use complete cases only. An earlier draft of
# this dataset carried 8% missing responses spread over 20 items; that leaves
# 140 complete cases out of 800, below the per-group minimum, and the dataset
# whose entire purpose is DIF produced no DIF statistics at all. Missing-data
# handling is demonstrated by polytomous_likert.csv instead.
DIF_ITEMS = (5, 11, 17)      # 1-based positions
DIF_SHIFT = 0.8              # logits, focal minus reference


def _threshold_names(n_categories: int) -> list[str]:
    return [f"boundary_{k + 1}" for k in range(n_categories - 1)]


def _write_responses(
    path: Path,
    values: np.ndarray,
    item_ids: list[str],
    *,
    first_code: int,
    leading: list[tuple[str, list[str]]] | None = None,
) -> None:
    """Write the response matrix, with missing responses as empty cells.

    An empty cell rather than a sentinel: a file that encodes missingness as -1
    or 99 is one careless upload away from being modelled as a category, and the
    validator would be right to accept it.
    """

    leading = leading or []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([name for name, _ in leading] + item_ids)
        for row_index in range(values.shape[0]):
            prefix = [column[row_index] for _, column in leading]
            row = [
                "" if value == MISSING else str(int(value) + first_code)
                for value in values[row_index]
            ]
            writer.writerow(prefix + row)


def _write_parameters(path: Path, true: TrueParameters, item_ids: list[str]) -> None:
    """Write the generating parameters, one row per item."""

    header = ["item_id", "discrimination"]
    if true.difficulty is not None:
        header.append("difficulty")
    if true.guessing is not None:
        header.append("guessing")
    if true.thresholds is not None:
        header.extend(_threshold_names(np.asarray(true.thresholds).shape[1] + 1))

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for index, item_id in enumerate(item_ids):
            row: list[str] = [item_id, f"{true.discrimination[index]:.4f}"]
            if true.difficulty is not None:
                row.append(f"{true.difficulty[index]:.4f}")
            if true.guessing is not None:
                row.append(f"{true.guessing[index]:.4f}")
            if true.thresholds is not None:
                row.extend(f"{v:.4f}" for v in np.asarray(true.thresholds)[index])
            writer.writerow(row)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entry(spec: Spec, path: Path, values: np.ndarray, extra: dict | None = None) -> dict:
    entry = {
        "filename": spec.filename,
        "model": spec.model.value,
        "n_persons": int(values.shape[0]),
        "n_items": int(values.shape[1]),
        "n_categories": spec.n_categories,
        "first_code": spec.first_code,
        "seed": spec.seed,
        "missing_rate": spec.missing_rate,
        "parameters_file": f"{Path(spec.filename).stem}.parameters.csv",
        "sha256": _digest(path),
    }
    if extra:
        entry.update(extra)
    return entry


def _build_plain(spec: Spec) -> dict:
    true = spread_parameters(
        spec.model, spec.n_items, seed=spec.seed, n_categories=spec.n_categories
    )
    data, _theta = simulate(
        true,
        spec.n_persons,
        seed=spec.seed,
        missing_rate=spec.missing_rate,
        item_prefix=spec.item_prefix,
    )
    csv_path = OUTPUT_DIR / spec.filename
    _write_responses(
        csv_path, data.values, data.item_ids, first_code=spec.first_code
    )
    _write_parameters(
        OUTPUT_DIR / f"{Path(spec.filename).stem}.parameters.csv", true, data.item_ids
    )
    return _entry(spec, csv_path, data.values)


def _build_dif() -> dict:
    """Two groups, identical but for three items' difficulties."""

    spec = DIF_SPEC
    base = spread_parameters(spec.model, spec.n_items, seed=spec.seed)
    shifted = np.array(base.difficulty, dtype=float, copy=True)
    for position in DIF_ITEMS:
        shifted[position - 1] += DIF_SHIFT

    focal = TrueParameters(
        model=base.model, discrimination=base.discrimination, difficulty=shifted
    )

    half = spec.n_persons // 2
    # Separate seeds, so the two halves are independent draws rather than the
    # same abilities answering two versions of the test.
    reference_data, _ = simulate(
        base, half, seed=spec.seed, missing_rate=spec.missing_rate
    )
    focal_data, _ = simulate(
        focal, spec.n_persons - half, seed=spec.seed + 1, missing_rate=spec.missing_rate
    )

    values = np.vstack([reference_data.values, focal_data.values])
    groups = ["reference"] * half + ["focal"] * (spec.n_persons - half)
    ids = [f"R{index + 1:04d}" for index in range(spec.n_persons)]

    csv_path = OUTPUT_DIR / spec.filename
    _write_responses(
        csv_path,
        values,
        reference_data.item_ids,
        first_code=spec.first_code,
        leading=[("respondent_id", ids), ("group", groups)],
    )

    # One row per item, with both groups' difficulties side by side: the planted
    # difference is the thing a reader of this dataset needs, and burying it in
    # two separate files would make it derivable rather than stated.
    params_path = OUTPUT_DIR / f"{Path(spec.filename).stem}.parameters.csv"
    with params_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "item_id",
                "discrimination",
                "difficulty_reference",
                "difficulty_focal",
                "dif_planted",
            ]
        )
        for index, item_id in enumerate(reference_data.item_ids):
            writer.writerow(
                [
                    item_id,
                    f"{base.discrimination[index]:.4f}",
                    f"{base.difficulty[index]:.4f}",
                    f"{shifted[index]:.4f}",
                    "yes" if (index + 1) in DIF_ITEMS else "no",
                ]
            )

    return _entry(
        spec,
        csv_path,
        values,
        extra={
            "group_column": "group",
            "id_column": "respondent_id",
            "dif_items": [f"item_{position:02d}" for position in DIF_ITEMS],
            "dif_shift_logits": DIF_SHIFT,
            "focal_seed": spec.seed + 1,
        },
    )


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    entries = [_build_plain(spec) for spec in SPECS]
    entries.append(_build_dif())

    manifest = {
        "generated_by": "backend/scripts/generate_sample_datasets.py",
        "note": (
            "Digests are checked by backend/tests/test_sample_datasets.py. If you "
            "edit a CSV by hand, its documented parameters no longer describe it; "
            "regenerate instead."
        ),
        "datasets": entries,
    }
    # newline="" so this file is written with LF on Windows too. The CSVs already
    # are (csv.writer with an explicit lineterminator), .gitattributes pins the
    # whole directory to LF, and a manifest that came out CRLF would show up as
    # modified after every regeneration on one platform and not the other.
    with (OUTPUT_DIR / "MANIFEST.json").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        handle.write(json.dumps(manifest, indent=2) + "\n")

    for entry in entries:
        print(
            f"{entry['filename']}: {entry['n_persons']}x{entry['n_items']} "
            f"{entry['model']} seed={entry['seed']} sha256={entry['sha256'][:12]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
