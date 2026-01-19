"""
Model selection logic for IRTBoss.

THIS IS A STRATEGIC FILE - Keep it readable and well-documented.

This module handles:
- Comparing fitted IRT models (1PL, 2PL, 3PL)
- Computing fit statistics (AIC, BIC, log-likelihood)
- Selecting the best model based on principled criteria
- Providing interpretable justifications for selections

The goal is to make complex statistical decisions transparent and defensible.
Users should never have to manually select an IRT model - this module does it
for them with clear explanations.

Key Principles:
1. Prefer simpler models unless complexity is justified
2. Penalize overfitting, especially with small samples
3. Consider the assessment context (stakes level, intended use)
4. Always explain the recommendation in plain language
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np

from .config import (
    MODEL_FIT,
    SAMPLE_SIZE,
    StakesLevel,
    IntendedUse,
)

logger = logging.getLogger(__name__)


class IRTModel(Enum):
    """
    Supported IRT models.

    Each model makes different assumptions about item behavior:

    - RASCH (1PL): All items have equal discrimination.
      Simplest model, most interpretable, requires smallest sample.
      Best when items are well-constructed and similar in quality.

    - TWO_PL: Items can vary in discrimination (slope).
      More flexible, captures real item differences.
      Requires larger sample for stable estimation.

    - THREE_PL: Adds a guessing parameter.
      Appropriate for multiple-choice with low-ability guessing.
      Requires largest sample, can be unstable.
    """
    RASCH = "1PL"      # Rasch model (equal discrimination)
    TWO_PL = "2PL"     # Two-parameter logistic
    THREE_PL = "3PL"   # Three-parameter logistic


@dataclass
class FitStatistics:
    """
    Model fit statistics used for comparison.

    These statistics help determine which model best balances
    fit to the data against model complexity.
    """
    log_likelihood: float  # Higher is better (less negative)
    aic: float             # Lower is better (penalizes parameters)
    bic: float             # Lower is better (stronger penalty for parameters)
    n_parameters: int      # Number of estimated parameters
    converged: bool        # Whether estimation converged
    n_iterations: int      # Number of iterations to convergence

    @property
    def deviance(self) -> float:
        """Deviance (-2 * log-likelihood). Lower is better."""
        return -2 * self.log_likelihood


@dataclass
class ItemParameters:
    """
    Estimated IRT parameters for a single item.

    Parameters:
        item_id: Identifier for the item
        discrimination: 'a' parameter - how well item differentiates ability levels
        difficulty: 'b' parameter - ability level where P(correct) = 0.5
        guessing: 'c' parameter - lower asymptote (probability of guessing correct)
        se_discrimination: Standard error for discrimination
        se_difficulty: Standard error for difficulty
        se_guessing: Standard error for guessing
    """
    item_id: str
    discrimination: float   # 'a' parameter
    difficulty: float       # 'b' parameter
    guessing: float = 0.0   # 'c' parameter (0 for 1PL/2PL)
    se_discrimination: Optional[float] = None
    se_difficulty: Optional[float] = None
    se_guessing: Optional[float] = None


@dataclass
class FittedModel:
    """
    A complete fitted IRT model with parameters and diagnostics.

    This dataclass contains everything needed to understand and use
    a fitted IRT model, including parameters, fit statistics, and
    any warnings generated during fitting.
    """
    model_type: IRTModel
    fit_stats: FitStatistics
    item_parameters: list[ItemParameters]
    theta_estimates: Optional[np.ndarray] = None  # Ability estimates for respondents
    warnings: list[str] = field(default_factory=list)

    @property
    def n_items(self) -> int:
        """Number of items in the model."""
        return len(self.item_parameters)

    def get_item(self, item_id: str) -> Optional[ItemParameters]:
        """Get parameters for a specific item."""
        for item in self.item_parameters:
            if item.item_id == item_id:
                return item
        return None


@dataclass
class ModelComparisonResult:
    """
    Result of comparing multiple fitted IRT models.

    This contains the fitted models, comparison statistics,
    and the selected best model with justification.
    """
    models: dict[IRTModel, FittedModel]
    selected_model: IRTModel
    selection_reasons: list[str]  # Plain-language reasons for selection
    comparison_table: dict[str, dict[str, float]]  # Model -> stat -> value
    warnings: list[str] = field(default_factory=list)


class ModelSelector:
    """
    Selects the best IRT model from a set of fitted alternatives.

    This class implements the core model selection logic, using
    information criteria (AIC, BIC) and contextual factors
    (sample size, stakes level) to recommend a single best model.

    The selection follows these principles:
    1. Prefer parsimony - simpler models unless complexity is justified
    2. Respect sample size - don't fit complex models with small N
    3. Consider context - high-stakes assessments need more conservative choices
    4. Explain everything - every recommendation comes with plain-language reasons

    Example:
        selector = ModelSelector(stakes=StakesLevel.MEDIUM)
        result = selector.compare_models(fitted_models)
        print(f"Recommended: {result.selected_model.value}")
        for reason in result.selection_reasons:
            print(f"  - {reason}")
    """

    def __init__(
        self,
        stakes: StakesLevel = StakesLevel.MEDIUM,
        intended_use: IntendedUse = IntendedUse.OPERATIONAL,
    ):
        """
        Initialize the model selector.

        Args:
            stakes: Stakes level of the assessment (affects conservatism)
            intended_use: Intended use of the assessment
        """
        self.stakes = stakes
        self.intended_use = intended_use

    def compare_models(
        self,
        models: dict[IRTModel, FittedModel],
        n_respondents: int,
    ) -> ModelComparisonResult:
        """
        Compare fitted models and select the best one.

        This method implements a principled model selection procedure:
        1. Filter out models that failed to converge
        2. Check sample size constraints
        3. Compare using BIC (preferred) and AIC
        4. Apply contextual adjustments
        5. Generate plain-language explanation

        Args:
            models: Dictionary of model type to fitted model
            n_respondents: Number of respondents in the data

        Returns:
            ModelComparisonResult with selection and explanation
        """
        reasons: list[str] = []
        warnings: list[str] = []

        # Build comparison table
        comparison_table = self._build_comparison_table(models)

        # Filter to valid models (converged)
        valid_models = {
            k: v for k, v in models.items()
            if v.fit_stats.converged
        }

        if not valid_models:
            # No models converged - this is a serious problem
            logger.error("No models converged during fitting")
            raise ValueError(
                "No models converged. This may indicate a problem with the data. "
                "Please review data quality and sample size."
            )

        # Track which models were excluded and why
        excluded = set(models.keys()) - set(valid_models.keys())
        for model in excluded:
            warnings.append(f"{model.value} model excluded: failed to converge")

        # Apply sample size constraints
        valid_models = self._apply_sample_constraints(
            valid_models, n_respondents, warnings, reasons
        )

        if not valid_models:
            raise ValueError(
                "No models are appropriate for this sample size. "
                f"Minimum sample size is {SAMPLE_SIZE.MINIMUM_RESPONDENTS}."
            )

        # Select using information criteria
        selected, selection_reasons = self._select_by_information_criteria(
            valid_models, reasons
        )

        # Apply context-based adjustments
        selected, selection_reasons = self._apply_context_adjustments(
            selected, valid_models, selection_reasons
        )

        return ModelComparisonResult(
            models=models,
            selected_model=selected,
            selection_reasons=selection_reasons,
            comparison_table=comparison_table,
            warnings=warnings,
        )

    def _build_comparison_table(
        self, models: dict[IRTModel, FittedModel]
    ) -> dict[str, dict[str, float]]:
        """Build a table comparing fit statistics across models."""
        table = {}
        for model_type, fitted in models.items():
            stats = fitted.fit_stats
            table[model_type.value] = {
                "log_likelihood": stats.log_likelihood,
                "AIC": stats.aic,
                "BIC": stats.bic,
                "n_parameters": stats.n_parameters,
                "converged": 1.0 if stats.converged else 0.0,
            }
        return table

    def _apply_sample_constraints(
        self,
        models: dict[IRTModel, FittedModel],
        n: int,
        warnings: list[str],
        reasons: list[str],
    ) -> dict[IRTModel, FittedModel]:
        """
        Remove models that are inappropriate for the sample size.

        We exclude models rather than just warning because fitting
        complex models with inadequate data produces unreliable results
        that could mislead users.
        """
        result = dict(models)

        # 3PL requires substantial sample for guessing parameter
        if IRTModel.THREE_PL in result:
            if n < SAMPLE_SIZE.WARNING_RESPONDENTS_3PL:
                del result[IRTModel.THREE_PL]
                warnings.append(
                    f"3PL model excluded: sample size ({n}) is below "
                    f"minimum ({SAMPLE_SIZE.WARNING_RESPONDENTS_3PL}) for stable "
                    "guessing parameter estimation."
                )

        # 2PL needs reasonable sample for discrimination parameters
        if IRTModel.TWO_PL in result:
            if n < SAMPLE_SIZE.MINIMUM_RESPONDENTS:
                del result[IRTModel.TWO_PL]
                warnings.append(
                    f"2PL model excluded: sample size ({n}) is too small."
                )
            elif n < SAMPLE_SIZE.WARNING_RESPONDENTS_2PL:
                # Don't exclude, but note the risk
                reasons.append(
                    f"Note: Sample size ({n}) is marginal for 2PL. "
                    "Discrimination estimates may be unstable."
                )

        return result

    def _select_by_information_criteria(
        self,
        models: dict[IRTModel, FittedModel],
        existing_reasons: list[str],
    ) -> tuple[IRTModel, list[str]]:
        """
        Select the best model using information criteria.

        We prefer BIC over AIC because:
        1. BIC has stronger penalty for complexity
        2. BIC is consistent (selects true model as N -> infinity)
        3. For assessment, we prefer stable, interpretable models

        However, we also consider AIC and require meaningful differences
        before preferring a more complex model.
        """
        reasons = list(existing_reasons)

        # Sort models by complexity (simpler first)
        model_order = [IRTModel.RASCH, IRTModel.TWO_PL, IRTModel.THREE_PL]
        available = [m for m in model_order if m in models]

        if len(available) == 1:
            selected = available[0]
            reasons.append(f"{selected.value} is the only eligible model.")
            return selected, reasons

        # Get BIC values
        bic_values = {m: models[m].fit_stats.bic for m in available}
        aic_values = {m: models[m].fit_stats.aic for m in available}

        # Find model with lowest BIC
        best_bic = min(available, key=lambda m: bic_values[m])
        best_aic = min(available, key=lambda m: aic_values[m])

        # Check if the difference is meaningful
        min_bic = bic_values[best_bic]
        min_aic = aic_values[best_aic]

        # Decision logic
        if best_bic == best_aic:
            # Both criteria agree - straightforward choice
            selected = best_bic
            reasons.append(
                f"{selected.value} model selected: has lowest AIC and BIC, "
                "indicating best balance of fit and complexity."
            )
        else:
            # Criteria disagree - prefer BIC (more conservative)
            selected = best_bic
            reasons.append(
                f"{selected.value} model selected based on BIC (more conservative criterion)."
            )
            reasons.append(
                f"Note: AIC slightly favors {best_aic.value}, but difference is not "
                "substantial enough to justify additional complexity."
            )

        # Add comparative information
        for model in available:
            if model != selected:
                bic_diff = bic_values[model] - min_bic
                if bic_diff < MODEL_FIT.BIC_DIFFERENCE_MEANINGFUL:
                    reasons.append(
                        f"{model.value} model has similar fit (BIC difference: {bic_diff:.1f}). "
                        "Simpler model preferred when fit is comparable."
                    )

        return selected, reasons

    def _apply_context_adjustments(
        self,
        selected: IRTModel,
        models: dict[IRTModel, FittedModel],
        existing_reasons: list[str],
    ) -> tuple[IRTModel, list[str]]:
        """
        Apply context-specific adjustments to the selection.

        High-stakes assessments should prefer simpler, more stable models.
        Research contexts may tolerate more complexity for better fit.
        """
        reasons = list(existing_reasons)

        if self.stakes == StakesLevel.HIGH:
            # For high-stakes, prefer 1PL unless 2PL is clearly better
            if selected == IRTModel.TWO_PL and IRTModel.RASCH in models:
                bic_diff = (
                    models[IRTModel.RASCH].fit_stats.bic -
                    models[IRTModel.TWO_PL].fit_stats.bic
                )
                # Need substantial improvement to justify complexity
                if bic_diff < MODEL_FIT.BIC_DIFFERENCE_MEANINGFUL * 2:
                    selected = IRTModel.RASCH
                    reasons.append(
                        "For high-stakes assessment, preferring Rasch model for its "
                        "superior interpretability and stability. The 2PL improvement "
                        "is not substantial enough to justify additional complexity."
                    )

            reasons.append(
                "High-stakes context: model stability and interpretability prioritized."
            )

        elif self.stakes == StakesLevel.LOW and self.intended_use == IntendedUse.RESEARCH:
            # Research context can accept more complexity
            reasons.append(
                "Research context: model selected primarily on statistical fit."
            )

        return selected, reasons


def explain_model_choice(model: IRTModel) -> str:
    """
    Provide a plain-language explanation of what a model assumes.

    This helps users understand what it means when we recommend a model,
    without requiring them to understand IRT theory.
    """
    explanations = {
        IRTModel.RASCH: (
            "The Rasch (1PL) model assumes all items are equally good at "
            "distinguishing between high and low ability respondents. This means "
            "items differ only in difficulty (how hard they are), not in quality. "
            "This is the simplest IRT model and produces the most interpretable results. "
            "It's appropriate when your items are well-constructed and you want "
            "scores that can be compared across different test forms."
        ),
        IRTModel.TWO_PL: (
            "The 2PL model allows items to differ in both difficulty AND "
            "discrimination (how well they distinguish between ability levels). "
            "This is more realistic for most assessments, as some items are simply "
            "better at measuring the trait than others. However, it requires more "
            "data to estimate reliably and produces somewhat less interpretable results."
        ),
        IRTModel.THREE_PL: (
            "The 3PL model adds a 'guessing' parameter, accounting for the "
            "possibility that low-ability respondents might guess correctly on "
            "multiple-choice items. This is appropriate for multiple-choice tests "
            "where random guessing is a realistic concern. However, it requires "
            "large samples (500+) for stable estimation and can sometimes produce "
            "counterintuitive results."
        ),
    }
    return explanations.get(model, "Unknown model type")


def summarize_comparison(result: ModelComparisonResult) -> str:
    """
    Generate a human-readable summary of the model comparison.

    This is intended for non-technical users who want to understand
    why a particular model was recommended.
    """
    lines = [
        f"Model Recommendation: {result.selected_model.value}",
        "",
        "Why this model?",
    ]

    for reason in result.selection_reasons:
        lines.append(f"  • {reason}")

    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in result.warnings:
            lines.append(f"  ⚠ {warning}")

    lines.append("")
    lines.append("What this means:")
    lines.append(explain_model_choice(result.selected_model))

    return "\n".join(lines)
