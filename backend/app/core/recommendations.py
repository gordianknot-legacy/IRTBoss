"""
Recommendation engine for IRTBoss.

THIS IS A STRATEGIC FILE - Keep it readable and well-documented.

This module handles:
- Generating actionable recommendations based on IRT analysis
- Translating statistical findings into plain language
- Flagging items that need attention
- Providing guidance based on assessment context

The goal is to bridge the gap between statistical output and practical action.
Users should receive clear, prioritized recommendations without needing to
interpret statistics themselves.

Key Principles:
1. Every recommendation must be actionable
2. Prioritize by impact and urgency
3. Explain the "why" behind each recommendation
4. Never overwhelm users with too many items
5. Consider the assessment context
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .config import (
    MODEL_FIT,
    REPORTING,
    StakesLevel,
    IntendedUse,
    get_reliability_threshold,
)
from .model_selection import FittedModel, IRTModel, ItemParameters, ModelComparisonResult

logger = logging.getLogger(__name__)


class RecommendationPriority(Enum):
    """Priority level for recommendations."""
    CRITICAL = "critical"  # Must address before using assessment
    HIGH = "high"          # Should address soon
    MEDIUM = "medium"      # Worth addressing when possible
    LOW = "low"            # Minor improvement opportunity


class RecommendationCategory(Enum):
    """Category of recommendation."""
    ITEM_QUALITY = "item_quality"      # Issues with specific items
    TEST_QUALITY = "test_quality"      # Issues with overall test
    SAMPLE = "sample"                  # Data/sample issues
    MODEL_FIT = "model_fit"            # Model fitting issues
    INTERPRETATION = "interpretation"  # Guidance on interpreting results


@dataclass
class Recommendation:
    """
    A single actionable recommendation.

    Each recommendation includes:
    - What the issue is
    - Why it matters
    - What action to take
    - Which items are affected (if applicable)
    """
    priority: RecommendationPriority
    category: RecommendationCategory
    title: str               # Short summary (e.g., "Remove poorly discriminating items")
    description: str         # Full explanation
    action: str              # What to do about it
    affected_items: list[str] = field(default_factory=list)
    evidence: Optional[str] = None  # Supporting statistics


@dataclass
class RecommendationReport:
    """
    Complete set of recommendations from an analysis.

    Recommendations are organized by priority and category
    to help users focus on what matters most.
    """
    recommendations: list[Recommendation]
    overall_assessment: str  # High-level summary
    reliability_estimate: Optional[float] = None
    is_ready_for_use: bool = True  # Whether assessment is usable as-is

    @property
    def critical_issues(self) -> list[Recommendation]:
        """Get all critical priority recommendations."""
        return [r for r in self.recommendations
                if r.priority == RecommendationPriority.CRITICAL]

    @property
    def high_priority(self) -> list[Recommendation]:
        """Get high priority recommendations."""
        return [r for r in self.recommendations
                if r.priority == RecommendationPriority.HIGH]

    def by_category(self, category: RecommendationCategory) -> list[Recommendation]:
        """Get recommendations in a specific category."""
        return [r for r in self.recommendations if r.category == category]


class RecommendationEngine:
    """
    Generates actionable recommendations from IRT analysis results.

    This engine analyzes fitted IRT models and produces prioritized
    recommendations that non-experts can understand and act on.

    The engine considers:
    - Item-level parameters (discrimination, difficulty)
    - Model fit statistics
    - Assessment context (stakes level, intended use)
    - Reliability and measurement precision

    Example:
        engine = RecommendationEngine(
            stakes=StakesLevel.HIGH,
            intended_use=IntendedUse.CERTIFICATION
        )
        report = engine.generate_recommendations(
            fitted_model=model,
            comparison_result=comparison
        )

        if not report.is_ready_for_use:
            print("Assessment needs attention before use:")
            for rec in report.critical_issues:
                print(f"  - {rec.title}")
    """

    def __init__(
        self,
        stakes: StakesLevel = StakesLevel.MEDIUM,
        intended_use: IntendedUse = IntendedUse.OPERATIONAL,
    ):
        """
        Initialize the recommendation engine.

        Args:
            stakes: Stakes level affects threshold strictness
            intended_use: Intended use affects recommendation focus
        """
        self.stakes = stakes
        self.intended_use = intended_use
        self.reliability_threshold = get_reliability_threshold(stakes)

    def generate_recommendations(
        self,
        fitted_model: FittedModel,
        comparison_result: Optional[ModelComparisonResult] = None,
        reliability: Optional[float] = None,
    ) -> RecommendationReport:
        """
        Generate a complete recommendation report.

        Args:
            fitted_model: The selected/fitted IRT model
            comparison_result: Optional model comparison results
            reliability: Optional pre-computed reliability coefficient

        Returns:
            RecommendationReport with prioritized recommendations
        """
        recommendations: list[Recommendation] = []

        # Analyze item parameters
        item_recs = self._analyze_items(fitted_model)
        recommendations.extend(item_recs)

        # Analyze model fit
        if comparison_result:
            fit_recs = self._analyze_model_fit(comparison_result)
            recommendations.extend(fit_recs)

        # Analyze reliability
        if reliability is not None:
            rel_recs = self._analyze_reliability(reliability)
            recommendations.extend(rel_recs)

        # Check for convergence warnings
        if fitted_model.warnings:
            for warning in fitted_model.warnings:
                recommendations.append(Recommendation(
                    priority=RecommendationPriority.MEDIUM,
                    category=RecommendationCategory.MODEL_FIT,
                    title="Model fitting warning",
                    description=warning,
                    action="Review the warning and consider if it affects your use case.",
                ))

        # Sort by priority
        priority_order = {
            RecommendationPriority.CRITICAL: 0,
            RecommendationPriority.HIGH: 1,
            RecommendationPriority.MEDIUM: 2,
            RecommendationPriority.LOW: 3,
        }
        recommendations.sort(key=lambda r: priority_order[r.priority])

        # Generate overall assessment
        overall = self._generate_overall_assessment(recommendations, reliability)

        # Determine if ready for use
        is_ready = not any(
            r.priority == RecommendationPriority.CRITICAL
            for r in recommendations
        )

        return RecommendationReport(
            recommendations=recommendations,
            overall_assessment=overall,
            reliability_estimate=reliability,
            is_ready_for_use=is_ready,
        )

    def _analyze_items(self, model: FittedModel) -> list[Recommendation]:
        """
        Analyze item parameters and generate item-level recommendations.

        Checks for:
        - Low discrimination (item doesn't differentiate ability)
        - Extreme difficulty (too easy or too hard)
        - High guessing parameters
        - Parameter estimation issues
        """
        recommendations: list[Recommendation] = []

        low_discrimination = []
        high_discrimination = []
        too_easy = []
        too_hard = []
        high_guessing = []

        for item in model.item_parameters:
            # Check discrimination
            if item.discrimination < MODEL_FIT.MIN_DISCRIMINATION:
                low_discrimination.append(item.item_id)
            elif item.discrimination > MODEL_FIT.MAX_DISCRIMINATION:
                high_discrimination.append(item.item_id)

            # Check difficulty
            if item.difficulty < MODEL_FIT.MIN_DIFFICULTY:
                too_easy.append(item.item_id)
            elif item.difficulty > MODEL_FIT.MAX_DIFFICULTY:
                too_hard.append(item.item_id)

            # Check guessing (for 3PL)
            if item.guessing > MODEL_FIT.MAX_GUESSING:
                high_guessing.append(item.item_id)

        # Generate recommendations for each issue type
        if low_discrimination:
            severity = (
                RecommendationPriority.HIGH
                if len(low_discrimination) > model.n_items * 0.2
                else RecommendationPriority.MEDIUM
            )
            recommendations.append(Recommendation(
                priority=severity,
                category=RecommendationCategory.ITEM_QUALITY,
                title="Items with low discrimination",
                description=(
                    f"{len(low_discrimination)} items have discrimination values below "
                    f"{MODEL_FIT.MIN_DISCRIMINATION}. These items do not effectively "
                    "distinguish between respondents of different ability levels. "
                    "They contribute little to measurement precision."
                ),
                action=(
                    "Review these items for potential issues: unclear wording, "
                    "multiple correct answers, or content not aligned with the construct. "
                    "Consider revising or removing them."
                ),
                affected_items=low_discrimination,
                evidence=f"Discrimination < {MODEL_FIT.MIN_DISCRIMINATION}",
            ))

        if high_discrimination:
            recommendations.append(Recommendation(
                priority=RecommendationPriority.LOW,
                category=RecommendationCategory.ITEM_QUALITY,
                title="Items with unusually high discrimination",
                description=(
                    f"{len(high_discrimination)} items have discrimination values above "
                    f"{MODEL_FIT.MAX_DISCRIMINATION}. This may indicate estimation "
                    "issues rather than genuinely exceptional items."
                ),
                action=(
                    "Verify these items are functioning correctly. Very high "
                    "discrimination can sometimes indicate scoring errors or "
                    "items that are too similar to each other."
                ),
                affected_items=high_discrimination,
                evidence=f"Discrimination > {MODEL_FIT.MAX_DISCRIMINATION}",
            ))

        if too_easy:
            severity = (
                RecommendationPriority.HIGH
                if len(too_easy) > model.n_items * 0.3
                else RecommendationPriority.MEDIUM
            )
            recommendations.append(Recommendation(
                priority=severity,
                category=RecommendationCategory.ITEM_QUALITY,
                title="Items may be too easy",
                description=(
                    f"{len(too_easy)} items have very low difficulty values, meaning "
                    "almost everyone answers them correctly. These items don't help "
                    "differentiate among most respondents."
                ),
                action=(
                    "If the assessment is intended to measure across a wide ability "
                    "range, consider replacing these items with more challenging ones. "
                    "If targeting low-ability populations, these may be appropriate."
                ),
                affected_items=too_easy,
                evidence=f"Difficulty < {MODEL_FIT.MIN_DIFFICULTY}",
            ))

        if too_hard:
            severity = (
                RecommendationPriority.HIGH
                if len(too_hard) > model.n_items * 0.3
                else RecommendationPriority.MEDIUM
            )
            recommendations.append(Recommendation(
                priority=severity,
                category=RecommendationCategory.ITEM_QUALITY,
                title="Items may be too difficult",
                description=(
                    f"{len(too_hard)} items have very high difficulty values, meaning "
                    "almost no one answers them correctly. These items don't help "
                    "differentiate among most respondents."
                ),
                action=(
                    "Review these items for: excessive complexity, unclear wording, "
                    "or content that wasn't taught. Consider revising or removing them."
                ),
                affected_items=too_hard,
                evidence=f"Difficulty > {MODEL_FIT.MAX_DIFFICULTY}",
            ))

        if high_guessing:
            recommendations.append(Recommendation(
                priority=RecommendationPriority.MEDIUM,
                category=RecommendationCategory.ITEM_QUALITY,
                title="Items with high guessing parameters",
                description=(
                    f"{len(high_guessing)} items have guessing parameters above "
                    f"{MODEL_FIT.MAX_GUESSING}. This suggests low-ability respondents "
                    "can answer these items correctly at rates higher than expected "
                    "from random guessing alone."
                ),
                action=(
                    "Check if these items have obvious wrong answers that respondents "
                    "can eliminate. Consider revising distractors to be more plausible."
                ),
                affected_items=high_guessing,
                evidence=f"Guessing parameter > {MODEL_FIT.MAX_GUESSING}",
            ))

        return recommendations

    def _analyze_model_fit(
        self, comparison: ModelComparisonResult
    ) -> list[Recommendation]:
        """Analyze model fit and generate fit-related recommendations."""
        recommendations: list[Recommendation] = []

        # Add interpretation guidance based on selected model
        selected = comparison.selected_model
        recommendations.append(Recommendation(
            priority=RecommendationPriority.LOW,
            category=RecommendationCategory.INTERPRETATION,
            title=f"Understanding your {selected.value} model",
            description=self._get_model_interpretation_guide(selected),
            action="Keep this in mind when interpreting item parameters and scores.",
        ))

        # Check for warnings from the comparison
        for warning in comparison.warnings:
            recommendations.append(Recommendation(
                priority=RecommendationPriority.MEDIUM,
                category=RecommendationCategory.MODEL_FIT,
                title="Model selection note",
                description=warning,
                action="Consider whether this affects your use case.",
            ))

        return recommendations

    def _analyze_reliability(self, reliability: float) -> list[Recommendation]:
        """Analyze reliability and generate recommendations."""
        recommendations: list[Recommendation] = []

        if reliability < self.reliability_threshold:
            gap = self.reliability_threshold - reliability

            if gap > 0.15:
                priority = RecommendationPriority.CRITICAL
            elif gap > 0.05:
                priority = RecommendationPriority.HIGH
            else:
                priority = RecommendationPriority.MEDIUM

            recommendations.append(Recommendation(
                priority=priority,
                category=RecommendationCategory.TEST_QUALITY,
                title="Reliability below threshold",
                description=(
                    f"The estimated reliability ({reliability:.2f}) is below the "
                    f"recommended threshold ({self.reliability_threshold:.2f}) for "
                    f"{self.stakes.value}-stakes assessments. This means scores "
                    "contain more measurement error than is typically acceptable."
                ),
                action=(
                    "To improve reliability: (1) Add more items measuring the same "
                    "construct, (2) Remove or revise items with low discrimination, "
                    "(3) Ensure items are clearly written and free from ambiguity."
                ),
                evidence=f"Reliability = {reliability:.2f}",
            ))
        else:
            recommendations.append(Recommendation(
                priority=RecommendationPriority.LOW,
                category=RecommendationCategory.TEST_QUALITY,
                title="Reliability is acceptable",
                description=(
                    f"The estimated reliability ({reliability:.2f}) meets the "
                    f"threshold ({self.reliability_threshold:.2f}) for "
                    f"{self.stakes.value}-stakes assessments."
                ),
                action="No action needed. Reliability is adequate for intended use.",
                evidence=f"Reliability = {reliability:.2f}",
            ))

        return recommendations

    def _generate_overall_assessment(
        self,
        recommendations: list[Recommendation],
        reliability: Optional[float],
    ) -> str:
        """Generate a high-level summary of the assessment quality."""
        critical = [r for r in recommendations
                    if r.priority == RecommendationPriority.CRITICAL]
        high = [r for r in recommendations
                if r.priority == RecommendationPriority.HIGH]

        if critical:
            return (
                f"⚠️ This assessment has {len(critical)} critical issue(s) that "
                "should be addressed before operational use. Please review the "
                "recommendations carefully."
            )
        elif high:
            return (
                f"This assessment is functional but has {len(high)} issue(s) that "
                "should be addressed to improve quality. The assessment can be used "
                "with appropriate caution."
            )
        elif reliability and reliability >= self.reliability_threshold:
            return (
                "✓ This assessment meets quality standards for "
                f"{self.stakes.value}-stakes use. All items are functioning "
                "within acceptable ranges."
            )
        else:
            return (
                "This assessment appears to be functioning adequately. Review the "
                "recommendations for potential improvements."
            )

    def _get_model_interpretation_guide(self, model: IRTModel) -> str:
        """Get interpretation guidance for a specific model type."""
        guides = {
            IRTModel.RASCH: (
                "The Rasch model assumes all items are equally discriminating. "
                "This means you can interpret the difficulty parameters directly: "
                "items with higher difficulty require higher ability to answer correctly. "
                "Scores from this model are considered 'interval-level' measurements, "
                "meaning differences between scores are meaningful and comparable."
            ),
            IRTModel.TWO_PL: (
                "The 2PL model allows items to have different discriminations. "
                "Items with higher discrimination are more informative but also more "
                "'sensitive' - small ability differences lead to large probability changes. "
                "When interpreting difficulty, keep discrimination in mind: a difficult "
                "item with low discrimination is different from one with high discrimination."
            ),
            IRTModel.THREE_PL: (
                "The 3PL model accounts for guessing on multiple-choice items. "
                "The guessing parameter represents the probability that very low ability "
                "respondents answer correctly. When interpreting difficulty, remember "
                "that the probability of correct response never goes below the guessing "
                "parameter, even for very low ability respondents."
            ),
        }
        return guides.get(model, "No interpretation guide available.")


def format_recommendations_for_display(report: RecommendationReport) -> str:
    """
    Format a recommendation report for text display.

    This creates a human-readable summary suitable for
    displaying in a terminal or text report.
    """
    lines = [
        "=" * 60,
        "ASSESSMENT QUALITY REPORT",
        "=" * 60,
        "",
        report.overall_assessment,
        "",
    ]

    if report.reliability_estimate is not None:
        lines.append(f"Reliability: {report.reliability_estimate:.2f}")
        lines.append("")

    if report.critical_issues:
        lines.append("🚨 CRITICAL ISSUES (must address):")
        for rec in report.critical_issues:
            lines.extend(_format_recommendation(rec))
        lines.append("")

    if report.high_priority:
        lines.append("⚠️ HIGH PRIORITY (should address):")
        for rec in report.high_priority:
            lines.extend(_format_recommendation(rec))
        lines.append("")

    medium = [r for r in report.recommendations
              if r.priority == RecommendationPriority.MEDIUM]
    if medium:
        lines.append("📋 MEDIUM PRIORITY (worth addressing):")
        for rec in medium:
            lines.extend(_format_recommendation(rec))
        lines.append("")

    low = [r for r in report.recommendations
           if r.priority == RecommendationPriority.LOW]
    if low:
        lines.append("ℹ️ FOR YOUR INFORMATION:")
        for rec in low:
            lines.extend(_format_recommendation(rec))

    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


def _format_recommendation(rec: Recommendation) -> list[str]:
    """Format a single recommendation for display."""
    lines = [
        f"  [{rec.category.value}] {rec.title}",
        f"    {rec.description}",
        f"    → Action: {rec.action}",
    ]
    if rec.affected_items:
        items_str = ", ".join(rec.affected_items[:5])
        if len(rec.affected_items) > 5:
            items_str += f" (and {len(rec.affected_items) - 5} more)"
        lines.append(f"    Affected items: {items_str}")
    if rec.evidence:
        lines.append(f"    Evidence: {rec.evidence}")
    lines.append("")
    return lines
