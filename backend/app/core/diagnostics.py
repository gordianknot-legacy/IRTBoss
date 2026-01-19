"""
Diagnostics generation for IRTBoss.

This module handles:
- Item Characteristic Curves (ICCs)
- Test Information Function (TIF)
- Item fit statistics
- Visual diagnostic data preparation

The goal is to provide interpretable visual diagnostics that help
users understand how their items and test are functioning.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np

from .config import MODEL_FIT, REPORTING
from .model_selection import FittedModel, IRTModel, ItemParameters

logger = logging.getLogger(__name__)


class ItemStatus(Enum):
    """Overall status of an item based on diagnostics."""
    GOOD = "good"           # Item is functioning well
    ACCEPTABLE = "acceptable"  # Minor issues, usable
    FLAGGED = "flagged"     # Significant issues, review recommended
    PROBLEMATIC = "problematic"  # Serious issues, consider removal


@dataclass
class ICCData:
    """
    Data for plotting an Item Characteristic Curve.

    An ICC shows the probability of a correct response as a function
    of ability (theta). This is the fundamental visualization for
    understanding item behavior.

    Attributes:
        item_id: Identifier for the item
        theta_values: Array of ability values (typically -4 to 4)
        probabilities: P(correct) at each theta value
        information: Item information at each theta value
        difficulty: The item's difficulty parameter
        discrimination: The item's discrimination parameter
        guessing: The item's guessing parameter (0 for 1PL/2PL)
    """
    item_id: str
    theta_values: np.ndarray
    probabilities: np.ndarray
    information: np.ndarray
    difficulty: float
    discrimination: float
    guessing: float = 0.0


@dataclass
class TIFData:
    """
    Data for plotting the Test Information Function.

    The TIF shows how precisely the test measures at different
    ability levels. Higher information means more precise measurement.

    Attributes:
        theta_values: Array of ability values
        information: Total test information at each theta
        standard_error: Standard error of measurement at each theta
        peak_theta: Theta value where information is maximized
        peak_information: Maximum information value
    """
    theta_values: np.ndarray
    information: np.ndarray
    standard_error: np.ndarray
    peak_theta: float
    peak_information: float


@dataclass
class ItemFlag:
    """
    A flag indicating a potential issue with an item.

    Flags are generated during diagnostics to highlight items
    that may need attention.
    """
    code: str           # Machine-readable code
    description: str    # Human-readable description
    severity: str       # "warning" or "error"
    value: Optional[float] = None  # The problematic value


@dataclass
class ItemDiagnostics:
    """
    Complete diagnostics for a single item.

    Combines ICC data, fit statistics, and flags for comprehensive
    item-level analysis.
    """
    item_id: str
    status: ItemStatus
    icc: ICCData
    flags: list[ItemFlag] = field(default_factory=list)

    # Key statistics (for display)
    discrimination: float = 0.0
    difficulty: float = 0.0
    guessing: float = 0.0
    max_information: float = 0.0
    theta_at_max_info: float = 0.0


@dataclass
class TestDiagnostics:
    """
    Complete diagnostics for the full test.

    Combines test-level metrics with item-level diagnostics
    for comprehensive analysis.
    """
    tif: TIFData
    items: list[ItemDiagnostics]
    reliability_marginal: float  # Marginal reliability estimate
    theta_coverage: tuple[float, float]  # Range with adequate information
    n_flagged_items: int
    n_problematic_items: int


class DiagnosticsGenerator:
    """
    Generates diagnostic visualizations and statistics from fitted IRT models.

    This class produces the data needed for visual diagnostics including:
    - Item Characteristic Curves (ICCs)
    - Test Information Function (TIF)
    - Item-level flags and recommendations

    Example:
        generator = DiagnosticsGenerator()
        diagnostics = generator.generate(fitted_model)

        # Plot TIF
        plt.plot(diagnostics.tif.theta_values, diagnostics.tif.information)

        # Check for flagged items
        for item in diagnostics.items:
            if item.status == ItemStatus.FLAGGED:
                print(f"Review item: {item.item_id}")
    """

    def __init__(
        self,
        theta_range: tuple[float, float] = (-4.0, 4.0),
        theta_points: int = 81,
    ):
        """
        Initialize the diagnostics generator.

        Args:
            theta_range: Range of theta values to compute over
            theta_points: Number of points in the theta grid
        """
        self.theta_range = theta_range
        self.theta_points = theta_points
        self.theta_values = np.linspace(
            theta_range[0], theta_range[1], theta_points
        )

    def generate(self, model: FittedModel) -> TestDiagnostics:
        """
        Generate complete diagnostics for a fitted model.

        Args:
            model: A fitted IRT model

        Returns:
            TestDiagnostics with all diagnostic information
        """
        # Generate ICC data for each item
        item_diagnostics = [
            self._generate_item_diagnostics(item, model.model_type)
            for item in model.item_parameters
        ]

        # Generate TIF
        tif = self._generate_tif(model.item_parameters, model.model_type)

        # Compute marginal reliability
        reliability = self._estimate_marginal_reliability(tif)

        # Compute theta coverage
        coverage = self._compute_theta_coverage(tif)

        # Count flagged items
        n_flagged = sum(
            1 for item in item_diagnostics
            if item.status in (ItemStatus.FLAGGED, ItemStatus.PROBLEMATIC)
        )
        n_problematic = sum(
            1 for item in item_diagnostics
            if item.status == ItemStatus.PROBLEMATIC
        )

        return TestDiagnostics(
            tif=tif,
            items=item_diagnostics,
            reliability_marginal=reliability,
            theta_coverage=coverage,
            n_flagged_items=n_flagged,
            n_problematic_items=n_problematic,
        )

    def _generate_item_diagnostics(
        self, item: ItemParameters, model_type: IRTModel
    ) -> ItemDiagnostics:
        """Generate diagnostics for a single item."""
        # Compute ICC
        icc = self._compute_icc(item, model_type)

        # Generate flags
        flags = self._generate_item_flags(item, icc)

        # Determine overall status
        status = self._determine_item_status(flags)

        # Find theta at maximum information
        max_info_idx = np.argmax(icc.information)
        theta_at_max = float(self.theta_values[max_info_idx])
        max_info = float(icc.information[max_info_idx])

        return ItemDiagnostics(
            item_id=item.item_id,
            status=status,
            icc=icc,
            flags=flags,
            discrimination=item.discrimination,
            difficulty=item.difficulty,
            guessing=item.guessing,
            max_information=max_info,
            theta_at_max_info=theta_at_max,
        )

    def _compute_icc(
        self, item: ItemParameters, model_type: IRTModel
    ) -> ICCData:
        """
        Compute Item Characteristic Curve data.

        Uses the standard IRT probability model:
        - 1PL: P(θ) = 1 / (1 + exp(-(θ - b)))
        - 2PL: P(θ) = 1 / (1 + exp(-a(θ - b)))
        - 3PL: P(θ) = c + (1-c) / (1 + exp(-a(θ - b)))
        """
        a = item.discrimination
        b = item.difficulty
        c = item.guessing

        # Compute probability at each theta
        z = a * (self.theta_values - b)
        if model_type == IRTModel.RASCH:
            # Rasch assumes a = 1
            z = self.theta_values - b
            probs = 1.0 / (1.0 + np.exp(-z))
        elif model_type == IRTModel.THREE_PL:
            probs = c + (1.0 - c) / (1.0 + np.exp(-z))
        else:  # 2PL
            probs = 1.0 / (1.0 + np.exp(-z))

        # Compute item information
        info = self._compute_item_information(a, b, c, model_type)

        return ICCData(
            item_id=item.item_id,
            theta_values=self.theta_values.copy(),
            probabilities=probs,
            information=info,
            difficulty=b,
            discrimination=a,
            guessing=c,
        )

    def _compute_item_information(
        self,
        a: float,
        b: float,
        c: float,
        model_type: IRTModel,
    ) -> np.ndarray:
        """
        Compute item information function.

        Information is highest where the item best discriminates
        between ability levels.
        """
        theta = self.theta_values

        if model_type == IRTModel.RASCH:
            # Rasch: I(θ) = P(θ) * Q(θ) where Q = 1-P
            z = theta - b
            p = 1.0 / (1.0 + np.exp(-z))
            info = p * (1.0 - p)

        elif model_type == IRTModel.TWO_PL:
            # 2PL: I(θ) = a² * P(θ) * Q(θ)
            z = a * (theta - b)
            p = 1.0 / (1.0 + np.exp(-z))
            info = (a ** 2) * p * (1.0 - p)

        else:  # 3PL
            # 3PL: I(θ) = a² * Q(θ) * (P(θ) - c)² / (P(θ) * (1-c)²)
            z = a * (theta - b)
            exp_neg_z = np.exp(-z)
            p = c + (1.0 - c) / (1.0 + exp_neg_z)
            q = 1.0 - p

            # Avoid division by zero
            p_safe = np.maximum(p, 1e-10)
            numerator = (a ** 2) * q * ((p - c) ** 2)
            denominator = p_safe * ((1.0 - c) ** 2)
            info = numerator / denominator

        return info

    def _generate_tif(
        self,
        items: list[ItemParameters],
        model_type: IRTModel,
    ) -> TIFData:
        """
        Generate Test Information Function by summing item information.

        TIF = Σ I_i(θ) for all items i
        """
        total_info = np.zeros_like(self.theta_values)

        for item in items:
            item_info = self._compute_item_information(
                item.discrimination,
                item.difficulty,
                item.guessing,
                model_type,
            )
            total_info += item_info

        # Standard error = 1 / sqrt(Information)
        # Avoid division by zero
        info_safe = np.maximum(total_info, 1e-10)
        se = 1.0 / np.sqrt(info_safe)

        # Find peak
        peak_idx = np.argmax(total_info)
        peak_theta = float(self.theta_values[peak_idx])
        peak_info = float(total_info[peak_idx])

        return TIFData(
            theta_values=self.theta_values.copy(),
            information=total_info,
            standard_error=se,
            peak_theta=peak_theta,
            peak_information=peak_info,
        )

    def _generate_item_flags(
        self, item: ItemParameters, icc: ICCData
    ) -> list[ItemFlag]:
        """Generate warning flags for an item."""
        flags = []

        # Check discrimination
        if item.discrimination < MODEL_FIT.MIN_DISCRIMINATION:
            flags.append(ItemFlag(
                code="LOW_DISCRIMINATION",
                description=(
                    f"Discrimination ({item.discrimination:.2f}) is below minimum "
                    f"({MODEL_FIT.MIN_DISCRIMINATION}). This item does not effectively "
                    "distinguish between ability levels."
                ),
                severity="warning",
                value=item.discrimination,
            ))

        if item.discrimination > MODEL_FIT.MAX_DISCRIMINATION:
            flags.append(ItemFlag(
                code="HIGH_DISCRIMINATION",
                description=(
                    f"Discrimination ({item.discrimination:.2f}) is unusually high. "
                    "This may indicate estimation issues."
                ),
                severity="warning",
                value=item.discrimination,
            ))

        # Check difficulty
        if item.difficulty < MODEL_FIT.MIN_DIFFICULTY:
            flags.append(ItemFlag(
                code="EXTREME_LOW_DIFFICULTY",
                description=(
                    f"Difficulty ({item.difficulty:.2f}) is extremely low. "
                    "This item is too easy for most respondents."
                ),
                severity="warning",
                value=item.difficulty,
            ))

        if item.difficulty > MODEL_FIT.MAX_DIFFICULTY:
            flags.append(ItemFlag(
                code="EXTREME_HIGH_DIFFICULTY",
                description=(
                    f"Difficulty ({item.difficulty:.2f}) is extremely high. "
                    "This item is too hard for most respondents."
                ),
                severity="warning",
                value=item.difficulty,
            ))

        # Check guessing
        if item.guessing > MODEL_FIT.MAX_GUESSING:
            flags.append(ItemFlag(
                code="HIGH_GUESSING",
                description=(
                    f"Guessing parameter ({item.guessing:.2f}) is high. "
                    "Low-ability respondents may be able to eliminate distractors."
                ),
                severity="warning",
                value=item.guessing,
            ))

        # Check for near-zero maximum information
        max_info = np.max(icc.information)
        if max_info < 0.1:
            flags.append(ItemFlag(
                code="LOW_INFORMATION",
                description=(
                    f"Maximum information ({max_info:.3f}) is very low. "
                    "This item contributes little to measurement precision."
                ),
                severity="error",
                value=max_info,
            ))

        return flags

    def _determine_item_status(self, flags: list[ItemFlag]) -> ItemStatus:
        """Determine overall item status based on flags."""
        if not flags:
            return ItemStatus.GOOD

        errors = [f for f in flags if f.severity == "error"]
        warnings = [f for f in flags if f.severity == "warning"]

        if errors:
            return ItemStatus.PROBLEMATIC
        elif len(warnings) >= 2:
            return ItemStatus.FLAGGED
        elif warnings:
            return ItemStatus.ACCEPTABLE
        else:
            return ItemStatus.GOOD

    def _estimate_marginal_reliability(self, tif: TIFData) -> float:
        """
        Estimate marginal reliability from the TIF.

        Uses empirical reliability formula:
        ρ = 1 - (1 / average_information)

        This assumes a standard normal ability distribution.
        """
        # Weight by standard normal distribution
        weights = np.exp(-0.5 * tif.theta_values ** 2)
        weights /= weights.sum()

        # Weighted average information
        avg_info = np.sum(weights * tif.information)

        # Reliability estimate
        if avg_info > 1:
            reliability = 1.0 - (1.0 / avg_info)
        else:
            reliability = 0.0

        return float(np.clip(reliability, 0.0, 1.0))

    def _compute_theta_coverage(
        self,
        tif: TIFData,
        min_information: float = 1.0,
    ) -> tuple[float, float]:
        """
        Compute the theta range where the test provides adequate information.

        Returns the range where information exceeds the minimum threshold.
        """
        adequate = tif.information >= min_information

        if not np.any(adequate):
            # No adequate information anywhere
            return (0.0, 0.0)

        # Find first and last points with adequate information
        adequate_indices = np.where(adequate)[0]
        low_idx = adequate_indices[0]
        high_idx = adequate_indices[-1]

        return (
            float(tif.theta_values[low_idx]),
            float(tif.theta_values[high_idx]),
        )


def format_diagnostics_summary(diagnostics: TestDiagnostics) -> str:
    """
    Format diagnostics for text display.

    Creates a human-readable summary of diagnostic information.
    """
    lines = [
        "=" * 60,
        "TEST DIAGNOSTICS SUMMARY",
        "=" * 60,
        "",
        f"Marginal Reliability: {diagnostics.reliability_marginal:.3f}",
        f"Peak Information: {diagnostics.tif.peak_information:.2f} at θ = {diagnostics.tif.peak_theta:.2f}",
        f"Adequate Coverage: θ ∈ [{diagnostics.theta_coverage[0]:.2f}, {diagnostics.theta_coverage[1]:.2f}]",
        "",
        f"Items Analyzed: {len(diagnostics.items)}",
        f"Items Flagged: {diagnostics.n_flagged_items}",
        f"Items Problematic: {diagnostics.n_problematic_items}",
        "",
    ]

    # List flagged items
    flagged = [i for i in diagnostics.items
               if i.status in (ItemStatus.FLAGGED, ItemStatus.PROBLEMATIC)]

    if flagged:
        lines.append("FLAGGED ITEMS:")
        for item in flagged:
            status_emoji = "⚠️" if item.status == ItemStatus.FLAGGED else "❌"
            lines.append(f"  {status_emoji} {item.item_id}")
            lines.append(f"     Discrimination: {item.discrimination:.2f}, "
                        f"Difficulty: {item.difficulty:.2f}")
            for flag in item.flags:
                lines.append(f"     - {flag.description}")
            lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)
