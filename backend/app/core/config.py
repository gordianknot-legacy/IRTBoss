"""
Configuration for IRTBoss core components.

This module defines thresholds, defaults, and guardrails used throughout
the analysis pipeline. These values are based on psychometric best practices
and are intentionally not user-configurable to maintain valid analyses.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Final


class StakesLevel(Enum):
    """Assessment stakes level - affects recommendation stringency."""
    LOW = "low"         # Classroom quizzes, practice tests
    MEDIUM = "medium"   # Course grades, placement tests
    HIGH = "high"       # Certification, licensure, high-stakes decisions


class IntendedUse(Enum):
    """Intended use of the assessment - affects recommendation criteria."""
    RESEARCH = "research"           # Academic research, exploratory
    OPERATIONAL = "operational"     # Regular use in production
    CERTIFICATION = "certification" # High-stakes certification/licensure


@dataclass(frozen=True)
class SampleSizeThresholds:
    """
    Minimum sample sizes for reliable IRT estimation.

    These thresholds are based on simulation studies in the psychometric
    literature. Below these thresholds, parameter estimates become unstable.
    """
    # Absolute minimums - below these, we refuse to fit
    MINIMUM_RESPONDENTS: int = 100
    MINIMUM_ITEMS: int = 5

    # Warnings - fitting is possible but results may be unstable
    WARNING_RESPONDENTS_1PL: int = 200
    WARNING_RESPONDENTS_2PL: int = 250
    WARNING_RESPONDENTS_3PL: int = 500

    # Recommended - for reliable estimation
    RECOMMENDED_RESPONDENTS_1PL: int = 300
    RECOMMENDED_RESPONDENTS_2PL: int = 500
    RECOMMENDED_RESPONDENTS_3PL: int = 1000


@dataclass(frozen=True)
class DataQualityThresholds:
    """
    Thresholds for data quality checks.

    These values trigger warnings or errors during data validation.
    """
    # Missing data thresholds
    MAX_MISSING_PER_ITEM: float = 0.20      # 20% missing per item
    MAX_MISSING_PER_RESPONDENT: float = 0.30 # 30% missing per respondent
    MAX_MISSING_TOTAL: float = 0.10          # 10% total missing data

    # Response pattern thresholds
    MIN_ITEM_VARIANCE: float = 0.05  # Items must have some variation
    MAX_ITEM_MEAN: float = 0.95      # Items too easy (ceiling effect)
    MIN_ITEM_MEAN: float = 0.05      # Items too hard (floor effect)

    # Polytomous data thresholds
    MIN_CATEGORY_FREQUENCY: float = 0.01  # Each category needs some responses


@dataclass(frozen=True)
class ModelFitThresholds:
    """
    Thresholds for evaluating model fit.

    These are used to flag problematic items or models.
    """
    # Item parameter bounds
    MIN_DISCRIMINATION: float = 0.25    # Below this, item doesn't discriminate
    MAX_DISCRIMINATION: float = 4.0     # Above this, likely estimation issue
    MIN_DIFFICULTY: float = -4.0        # Extreme low difficulty
    MAX_DIFFICULTY: float = 4.0         # Extreme high difficulty
    MAX_GUESSING: float = 0.35          # Reasonable upper bound for guessing

    # Model comparison thresholds
    AIC_DIFFERENCE_MEANINGFUL: float = 10.0  # Difference to prefer one model
    BIC_DIFFERENCE_MEANINGFUL: float = 10.0  # BIC difference threshold

    # Convergence criteria
    MAX_ITERATIONS: int = 500
    CONVERGENCE_THRESHOLD: float = 0.001


@dataclass(frozen=True)
class ReportingThresholds:
    """
    Thresholds that affect reporting and recommendations.
    """
    # Reliability thresholds
    MIN_RELIABILITY_LOW_STAKES: float = 0.70
    MIN_RELIABILITY_MEDIUM_STAKES: float = 0.80
    MIN_RELIABILITY_HIGH_STAKES: float = 0.90

    # Test information thresholds
    MIN_INFORMATION_COVERAGE: float = 0.80  # % of theta range with adequate info


# Global configuration instances
SAMPLE_SIZE = SampleSizeThresholds()
DATA_QUALITY = DataQualityThresholds()
MODEL_FIT = ModelFitThresholds()
REPORTING = ReportingThresholds()


# Response type detection
DICHOTOMOUS_VALUES: Final[set] = {0, 1}
POLYTOMOUS_MIN_CATEGORIES: Final[int] = 3


def get_min_sample_for_model(model_type: str) -> int:
    """
    Get minimum recommended sample size for a given model type.

    Args:
        model_type: One of "1PL", "2PL", "3PL"

    Returns:
        Minimum recommended sample size

    Raises:
        ValueError: If model_type is not recognized
    """
    thresholds = {
        "1PL": SAMPLE_SIZE.RECOMMENDED_RESPONDENTS_1PL,
        "2PL": SAMPLE_SIZE.RECOMMENDED_RESPONDENTS_2PL,
        "3PL": SAMPLE_SIZE.RECOMMENDED_RESPONDENTS_3PL,
    }
    if model_type not in thresholds:
        raise ValueError(f"Unknown model type: {model_type}. Must be one of: 1PL, 2PL, 3PL")
    return thresholds[model_type]


def get_reliability_threshold(stakes: StakesLevel) -> float:
    """
    Get minimum acceptable reliability for a given stakes level.

    Higher stakes assessments require higher reliability.

    Args:
        stakes: The stakes level of the assessment

    Returns:
        Minimum acceptable reliability coefficient
    """
    thresholds = {
        StakesLevel.LOW: REPORTING.MIN_RELIABILITY_LOW_STAKES,
        StakesLevel.MEDIUM: REPORTING.MIN_RELIABILITY_MEDIUM_STAKES,
        StakesLevel.HIGH: REPORTING.MIN_RELIABILITY_HIGH_STAKES,
    }
    return thresholds[stakes]
