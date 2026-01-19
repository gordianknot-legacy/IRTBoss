"""
Tests for diagnostics module.
"""

import pytest
import numpy as np

from app.core.diagnostics import (
    DiagnosticsGenerator,
    ItemStatus,
    format_diagnostics_summary,
)
from app.core.model_selection import (
    FittedModel,
    FitStatistics,
    ItemParameters,
    IRTModel,
)


def create_test_model(n_items: int = 10) -> FittedModel:
    """Create a test model for diagnostics."""
    fit_stats = FitStatistics(
        log_likelihood=-1000,
        aic=2050,
        bic=2100,
        n_parameters=n_items * 2,
        converged=True,
        n_iterations=50,
    )

    item_params = [
        ItemParameters(
            item_id=f"item_{i+1}",
            discrimination=0.5 + i * 0.2,  # Range from 0.5 to 2.3
            difficulty=-2 + 4 * i / n_items,  # Range from -2 to 2
            guessing=0.0,
        )
        for i in range(n_items)
    ]

    return FittedModel(
        model_type=IRTModel.TWO_PL,
        fit_stats=fit_stats,
        item_parameters=item_params,
    )


def create_model_with_problems() -> FittedModel:
    """Create a model with problematic items."""
    fit_stats = FitStatistics(
        log_likelihood=-1000,
        aic=2050,
        bic=2100,
        n_parameters=20,
        converged=True,
        n_iterations=50,
    )

    item_params = [
        # Good items
        ItemParameters(item_id="item_1", discrimination=1.0, difficulty=0.0),
        ItemParameters(item_id="item_2", discrimination=1.2, difficulty=-0.5),
        # Low discrimination
        ItemParameters(item_id="item_3", discrimination=0.1, difficulty=0.0),
        # High discrimination
        ItemParameters(item_id="item_4", discrimination=5.0, difficulty=0.0),
        # Extreme difficulty
        ItemParameters(item_id="item_5", discrimination=1.0, difficulty=-5.0),
        ItemParameters(item_id="item_6", discrimination=1.0, difficulty=5.0),
    ]

    return FittedModel(
        model_type=IRTModel.TWO_PL,
        fit_stats=fit_stats,
        item_parameters=item_params,
    )


class TestDiagnosticsGenerator:
    """Tests for DiagnosticsGenerator class."""

    def test_generate_diagnostics(self):
        """Should generate complete diagnostics."""
        model = create_test_model()
        generator = DiagnosticsGenerator()
        diagnostics = generator.generate(model)

        assert diagnostics.tif is not None
        assert len(diagnostics.items) == 10
        assert 0 <= diagnostics.reliability_marginal <= 1

    def test_tif_data(self):
        """Should generate valid TIF data."""
        model = create_test_model()
        generator = DiagnosticsGenerator()
        diagnostics = generator.generate(model)

        tif = diagnostics.tif
        assert len(tif.theta_values) == 81  # Default grid
        assert len(tif.information) == 81
        assert len(tif.standard_error) == 81
        assert all(tif.information >= 0)  # Information is non-negative
        assert all(tif.standard_error > 0)  # SE is positive

    def test_icc_data(self):
        """Should generate valid ICC data for each item."""
        model = create_test_model()
        generator = DiagnosticsGenerator()
        diagnostics = generator.generate(model)

        for item in diagnostics.items:
            icc = item.icc
            assert len(icc.theta_values) == 81
            assert len(icc.probabilities) == 81
            assert all(0 <= p <= 1 for p in icc.probabilities)  # Probabilities in [0,1]
            assert icc.probabilities[0] < icc.probabilities[-1]  # Monotonic

    def test_flag_low_discrimination(self):
        """Should flag items with low discrimination."""
        model = create_model_with_problems()
        generator = DiagnosticsGenerator()
        diagnostics = generator.generate(model)

        # Find item_3 which has low discrimination
        item_3 = next(i for i in diagnostics.items if i.item_id == "item_3")
        flag_codes = [f.code for f in item_3.flags]
        assert "LOW_DISCRIMINATION" in flag_codes

    def test_flag_high_discrimination(self):
        """Should flag items with unusually high discrimination."""
        model = create_model_with_problems()
        generator = DiagnosticsGenerator()
        diagnostics = generator.generate(model)

        item_4 = next(i for i in diagnostics.items if i.item_id == "item_4")
        flag_codes = [f.code for f in item_4.flags]
        assert "HIGH_DISCRIMINATION" in flag_codes

    def test_flag_extreme_difficulty(self):
        """Should flag items with extreme difficulty."""
        model = create_model_with_problems()
        generator = DiagnosticsGenerator()
        diagnostics = generator.generate(model)

        item_5 = next(i for i in diagnostics.items if i.item_id == "item_5")
        flag_codes = [f.code for f in item_5.flags]
        assert "EXTREME_LOW_DIFFICULTY" in flag_codes

        item_6 = next(i for i in diagnostics.items if i.item_id == "item_6")
        flag_codes = [f.code for f in item_6.flags]
        assert "EXTREME_HIGH_DIFFICULTY" in flag_codes

    def test_item_status(self):
        """Should assign appropriate status to items."""
        model = create_model_with_problems()
        generator = DiagnosticsGenerator()
        diagnostics = generator.generate(model)

        # Good items should have GOOD or ACCEPTABLE status
        item_1 = next(i for i in diagnostics.items if i.item_id == "item_1")
        assert item_1.status in (ItemStatus.GOOD, ItemStatus.ACCEPTABLE)

        # Problem items should be flagged or problematic
        item_3 = next(i for i in diagnostics.items if i.item_id == "item_3")
        assert item_3.status in (ItemStatus.FLAGGED, ItemStatus.PROBLEMATIC, ItemStatus.ACCEPTABLE)

    def test_count_flagged_items(self):
        """Should count flagged items correctly."""
        model = create_model_with_problems()
        generator = DiagnosticsGenerator()
        diagnostics = generator.generate(model)

        assert diagnostics.n_flagged_items >= 1

    def test_theta_coverage(self):
        """Should compute theta coverage range."""
        model = create_test_model()
        generator = DiagnosticsGenerator()
        diagnostics = generator.generate(model)

        low, high = diagnostics.theta_coverage
        assert low < high
        assert -4 <= low <= 4
        assert -4 <= high <= 4

    def test_reliability_estimation(self):
        """Should estimate marginal reliability."""
        model = create_test_model()
        generator = DiagnosticsGenerator()
        diagnostics = generator.generate(model)

        assert 0 < diagnostics.reliability_marginal < 1


class TestDiagnosticsSummary:
    """Tests for diagnostics summary formatting."""

    def test_format_summary(self):
        """Should format diagnostics as readable summary."""
        model = create_model_with_problems()
        generator = DiagnosticsGenerator()
        diagnostics = generator.generate(model)

        summary = format_diagnostics_summary(diagnostics)

        assert "DIAGNOSTICS" in summary
        assert "Reliability" in summary
        assert "Items" in summary
