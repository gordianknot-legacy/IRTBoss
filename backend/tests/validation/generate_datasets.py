"""
Generate the fixed datasets that both estimators are validated against.

The datasets are written to disk and committed rather than simulated inside the
test, because the comparison is between two programs in two languages that
cannot share a random number generator. Both must see byte-identical input for
a disagreement to mean anything.

Run this only to add or change a fixture::

    python -m tests.validation.generate_datasets

Regenerating existing fixtures invalidates the stored mirt reference output, so
the R side must be re-run afterwards.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.irt.families import ModelKey
from app.irt.simulate import simulate, spread_parameters

FIXTURES = Path(__file__).parent / "fixtures"

# (name, model, n_persons, n_items, n_categories, seed)
DATASETS = [
    ("rasch_20x1500", ModelKey.RASCH, 1500, 20, 2, 8101),
    ("twopl_25x2000", ModelKey.TWO_PL, 2000, 25, 2, 8102),
    ("threepl_30x3000", ModelKey.THREE_PL, 3000, 30, 2, 8103),
    ("grm_12x2000", ModelKey.GRM, 2000, 12, 5, 8104),
]


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    manifest = {}

    for name, model, n_persons, n_items, n_cat, seed in DATASETS:
        true = spread_parameters(model, n_items, n_categories=n_cat, seed=seed)
        data, _ = simulate(true, n_persons, seed=seed)

        path = FIXTURES / f"{name}.csv"
        header = ",".join(data.item_ids)
        np.savetxt(path, data.values, fmt="%d", delimiter=",", header=header,
                   comments="")

        manifest[name] = {
            "model": model.value,
            "n_persons": n_persons,
            "n_items": n_items,
            "n_categories": n_cat,
            "seed": seed,
            "true_discrimination": true.discrimination.tolist(),
            "true_difficulty": (
                true.difficulty.tolist() if true.difficulty is not None else None
            ),
            "true_guessing": (
                true.guessing.tolist() if true.guessing is not None else None
            ),
            "true_thresholds": (
                np.asarray(true.thresholds).tolist()
                if true.thresholds is not None
                else None
            ),
        }
        print(f"wrote {path} ({n_persons} x {n_items})")

    (FIXTURES / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"wrote {FIXTURES / 'manifest.json'}")


if __name__ == "__main__":
    main()
