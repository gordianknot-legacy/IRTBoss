"""Assembling what a report needs, from persisted data only.

The context is built from the run row, its fits and its stored diagnostics
payload — nothing is recomputed at render time. That is what makes a report
reproducible rather than merely repeatable (P4): re-rendering last month's run
next year produces the same document, because rendering reads storage and never
touches the estimator.

Nothing here interprets a statistic. The context selects, groups and labels;
every threshold and every caveat belongs to the template, where a reader can see
it stated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Conventional reading guides, shown to the reader as guides and never applied
# silently. They do not change any number and nothing is filtered by them.
#
# The bands differ by stakes because the consequence of a misfitting item
# differs: a flagged item on a classroom quiz is worth a look, and the same item
# on a licensure exam is worth a defensible decision before the exam is used.
STAKES_GUIDANCE: dict[str, str] = {
    "low": (
        "This project is declared low-stakes. The guides below are the "
        "conventional ones; treat them as prompts for a second look rather than "
        "as decision rules."
    ),
    "medium": (
        "This project is declared medium-stakes. Items flagged below warrant "
        "review before the instrument is used for decisions about individuals."
    ),
    "high": (
        "This project is declared high-stakes. Every flag below should be "
        "resolved or documented before use, and the assumption checks matter as "
        "much as the item statistics: a defensible score depends on the model "
        "being appropriate, not only on the items fitting it."
    ),
}

USE_GUIDANCE: dict[str, str] = {
    "research": (
        "Intended use is declared as research. Individual scores here carry the "
        "standard errors reported below and are generally not precise enough to "
        "act on one at a time."
    ),
    "operational": (
        "Intended use is declared as operational. The conditional standard "
        "errors below, not the single reliability figure, are what determine "
        "whether a given score is precise enough to act on."
    ),
    "certification": (
        "Intended use is declared as certification. A pass/fail decision "
        "depends on precision *at the cut score*, which the conditional "
        "standard error curve reports directly; the marginal reliability "
        "figure averages over the whole scale and can look reassuring while "
        "precision at the cut is poor."
    ),
}


@dataclass
class ReportContext:
    """Everything the template renders, already resolved."""

    generated_at: datetime
    run: dict[str, Any]
    dataset: dict[str, Any]
    project: dict[str, Any]
    reproducibility: dict[str, Any]
    fits: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    guidance: list[str] = field(default_factory=list)

    @property
    def has_results(self) -> bool:
        return bool(self.fits) or bool(self.diagnostics)


def _fit_dict(fit: Any) -> dict[str, Any]:
    """Flatten one persisted fit, including its item parameter rows."""

    return {
        "model_key": fit.model_key,
        "converged": fit.converged,
        "n_cycles": fit.n_cycles,
        "log_likelihood": fit.log_likelihood,
        "n_free_parameters": fit.n_free_parameters,
        "n_persons": fit.n_persons,
        "aic": fit.aic,
        "bic": fit.bic,
        "latent_sd": fit.latent_sd,
        "elapsed_seconds": fit.elapsed_seconds,
        "failure_reason": fit.failure_reason,
        "notes": list(fit.notes or []),
        "items": [
            {
                "item_id": row.item_id,
                "position": row.position,
                "n_categories": row.n_categories,
                "discrimination": row.discrimination,
                "difficulty": row.difficulty,
                "guessing": row.guessing,
                "thresholds": list(row.thresholds or []),
                "se_discrimination": row.se_discrimination,
                "se_difficulty": row.se_difficulty,
                "se_guessing": row.se_guessing,
                "se_thresholds": list(row.se_thresholds or []),
            }
            for row in sorted(fit.item_parameters, key=lambda r: r.position)
        ],
    }


def build_context(
    *,
    run: Any,
    dataset: Any,
    project: Any,
    generated_at: datetime | None = None,
) -> ReportContext:
    """Build the render context from ORM rows.

    Every attribute is read eagerly into plain data. The template therefore
    cannot trigger a lazy load, which on an async session raises at attribute
    access and would turn a report into a 500 during rendering.
    """

    diagnostics = dict(run.diagnostics.payload) if run.diagnostics else {}
    fits = [_fit_dict(f) for f in run.fits]

    stakes = getattr(project.stakes_level, "value", str(project.stakes_level))
    use = getattr(project.intended_use, "value", str(project.intended_use))
    guidance = [g for g in (STAKES_GUIDANCE.get(stakes), USE_GUIDANCE.get(use)) if g]

    return ReportContext(
        generated_at=generated_at or datetime.now(UTC),
        run={
            "id": str(run.id),
            "status": getattr(run.status, "value", str(run.status)),
            "requested_models": list(run.requested_models or []),
            "score_method": run.score_method,
            "seed": run.seed,
            "engine_version": run.engine_version,
            "created_at": run.created_at,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "failure_reason": run.failure_reason,
        },
        dataset={
            "id": str(dataset.id),
            "original_filename": dataset.original_filename,
            "checksum_sha256": dataset.checksum_sha256,
            "size_bytes": dataset.size_bytes,
            "n_persons": dataset.n_persons,
            "n_items": dataset.n_items,
            "column_metadata": dict(dataset.column_metadata or {}),
            "created_at": dataset.created_at,
        },
        project={
            "id": str(project.id),
            "name": project.name,
            "description": project.description,
            "stakes_level": stakes,
            "intended_use": use,
        },
        # Grouped so the template renders one block rather than scattering these
        # across a footer. Everything needed to reproduce the run is here.
        reproducibility={
            "engine_version": run.engine_version,
            "seed": run.seed,
            "dataset_checksum_sha256": dataset.checksum_sha256,
            "dataset_filename": dataset.original_filename,
            "requested_models": list(run.requested_models or []),
            # The requested method, from the run row. The score distribution
            # section reports the method the scores were actually computed under;
            # those agree unless scoring failed, and a reader has to be able to
            # tell the two apart.
            "score_method": run.score_method,
            "fitted_models": [f["model_key"] for f in fits],
            "run_id": str(run.id),
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        },
        fits=fits,
        diagnostics=diagnostics,
        notes=list(run.notes or []),
        guidance=guidance,
    )
