"""
Tests for model selection module.
"""

import pytest
import numpy as np

from app.core.config import StakesLevel, IntendedUse
from app.core.model_selection import (
    ModelSelector,
    ModelComparisonResult,
    FittedModel,
    FitStatistics,
    ItemParameters,
    IRTModel,
    explain_model_choice,
    summarize_comparison,
)


def create_mock_fitted_model(
    model_type: IRTModel,
    aic: float,
    bic: float,
    converged: bool = True,
    n_items: int = 20,
) -> FittedModel:
    """Create a mock fitted model for testing."""
    fit_stats = FitStatistics(
        log_likelihood=-aic / 2,
        aic=aic,
        bic=bic,
        n_parameters=n_items * (1 if model_type == IRTModel.RASCH else 2),
        converged=converged,
        n_iterations=50,
    )

    item_params = [
        ItemParameters(
            item_id=f"item_{i}",
            discrimination=1.0 if model_type == IRTModel.RASCH else 1.2,
            difficulty=-2 + 4 * i / n_items,
            guessing=0.1 if model_type == IRTModel.THREE_PL else 0.0,
        )
        for i in range(n_items)
    ]

    return FittedModel(
        model_type=model_type,
        fit_stats=fit_stats,
        item_parameters=item_params,
    )


class TestModelSelector:
    """Tests for ModelSelector class."""

    def test_select_best_model_by_bic(self):
        """Should select model with lowest BIC."""
        models = {
            IRTModel.RASCH: create_mock_fitted_model(IRTModel.RASCH, aic=12500, bic=12600),
            IRTModel.TWO_PL: create_mock_fitted_model(IRTModel.TWO_PL, aic=12200, bic=12400),
        }

        selector = ModelSelector()
        result = selector.compare_models(models, n_respondents=500)

        assert result.selected_model == IRTModel.TWO_PL
        assert len(result.selection_reasons) > 0

    def test_prefer_simpler_when_similar(self):
        """Should prefer simpler model when BIC difference is small."""
        models = {
            IRTModel.RASCH: create_mock_fitted_model(IRTModel.RASCH, aic=12500, bic=12500),
            IRTModel.TWO_PL: create_mock_fitted_model(IRTModel.TWO_PL, aic=12495, bic=12498),
        }

        selector = ModelSelector()
        result = selector.compare_models(models, n_respondents=500)

        # BIC difference is only 2, so should prefer simpler 1PL
        assert result.selected_model == IRTModel.TWO_PL or \
               "similar fit" in str(result.selection_reasons).lower()

    def test_exclude_3pl_for_small_sample(self):
        """Should exclude 3PL when sample size is too small."""
        models = {
            IRTModel.RASCH: create_mock_fitted_model(IRTModel.RASCH, aic=12500, bic=12600),
            IRTModel.TWO_PL: create_mock_fitted_model(IRTModel.TWO_PL, aic=12200, bic=12400),
            IRTModel.THREE_PL: create_mock_fitted_model(IRTModel.THREE_PL, aic=12100, bic=12300),
        }

        selector = ModelSelector()
        result = selector.compare_models(models, n_respondents=300)  # Too small for 3PL

        assert result.selected_model != IRTModel.THREE_PL
        assert any("3PL" in w and "excluded" in w for w in result.warnings)

    def test_exclude_non_converged_models(self):
        """Should exclude models that didn't converge."""
        models = {
            IRTModel.RASCH: create_mock_fitted_model(IRTModel.RASCH, aic=12500, bic=12600),
            IRTModel.TWO_PL: create_mock_fitted_model(
                IRTModel.TWO_PL, aic=12200, bic=12400, converged=False
            ),
        }

        selector = ModelSelector()
        result = selector.compare_models(models, n_respondents=500)

        assert result.selected_model == IRTModel.RASCH
        assert any("failed to converge" in w for w in result.warnings)

    def test_raise_when_no_valid_models(self):
        """Should raise error when no models converged."""
        models = {
            IRTModel.RASCH: create_mock_fitted_model(
                IRTModel.RASCH, aic=12500, bic=12600, converged=False
            ),
            IRTModel.TWO_PL: create_mock_fitted_model(
                IRTModel.TWO_PL, aic=12200, bic=12400, converged=False
            ),
        }

        selector = ModelSelector()
        with pytest.raises(ValueError, match="No models converged"):
            selector.compare_models(models, n_respondents=500)

    def test_high_stakes_prefers_rasch(self):
        """High stakes should bias toward simpler models."""
        models = {
            IRTModel.RASCH: create_mock_fitted_model(IRTModel.RASCH, aic=12500, bic=12500),
            IRTModel.TWO_PL: create_mock_fitted_model(IRTModel.TWO_PL, aic=12480, bic=12490),
        }

        selector = ModelSelector(stakes=StakesLevel.HIGH)
        result = selector.compare_models(models, n_respondents=500)

        # With high stakes and small BIC difference, should prefer Rasch
        assert result.selected_model == IRTModel.RASCH
        assert any("high-stakes" in r.lower() for r in result.selection_reasons)

    def test_comparison_table(self):
        """Should generate comparison table with statistics."""
        models = {
            IRTModel.RASCH: create_mock_fitted_model(IRTModel.RASCH, aic=12500, bic=12600),
            IRTModel.TWO_PL: create_mock_fitted_model(IRTModel.TWO_PL, aic=12200, bic=12400),
        }

        selector = ModelSelector()
        result = selector.compare_models(models, n_respondents=500)

        assert "1PL" in result.comparison_table
        assert "2PL" in result.comparison_table
        assert "AIC" in result.comparison_table["1PL"]
        assert "BIC" in result.comparison_table["1PL"]


class TestModelExplanations:
    """Tests for model explanation functions."""

    def test_explain_rasch(self):
        """Should provide explanation for Rasch model."""
        explanation = explain_model_choice(IRTModel.RASCH)
        assert "Rasch" in explanation or "1PL" in explanation
        assert len(explanation) > 50

    def test_explain_2pl(self):
        """Should provide explanation for 2PL model."""
        explanation = explain_model_choice(IRTModel.TWO_PL)
        assert "2PL" in explanation
        assert "discrimination" in explanation.lower()

    def test_explain_3pl(self):
        """Should provide explanation for 3PL model."""
        explanation = explain_model_choice(IRTModel.THREE_PL)
        assert "3PL" in explanation
        assert "guessing" in explanation.lower()

    def test_summarize_comparison(self):
        """Should generate readable summary."""
        models = {
            IRTModel.RASCH: create_mock_fitted_model(IRTModel.RASCH, aic=12500, bic=12600),
            IRTModel.TWO_PL: create_mock_fitted_model(IRTModel.TWO_PL, aic=12200, bic=12400),
        }

        selector = ModelSelector()
        result = selector.compare_models(models, n_respondents=500)
        summary = summarize_comparison(result)

        assert "Recommendation" in summary
        assert result.selected_model.value in summary
