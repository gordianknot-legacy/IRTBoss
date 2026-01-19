"""
IRT model fitting interface.

This module defines the abstract interface for IRT model fitting,
allowing different implementations (R mirt, PyTorch, etc.) to be
used interchangeably.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol

import numpy as np
import pandas as pd

from ..core.model_selection import (
    FittedModel,
    FitStatistics,
    IRTModel,
    ItemParameters,
)

logger = logging.getLogger(__name__)


class FittingStatus(Enum):
    """Status of a model fitting operation."""
    SUCCESS = "success"
    CONVERGED_WITH_WARNINGS = "converged_with_warnings"
    FAILED_TO_CONVERGE = "failed_to_converge"
    ERROR = "error"


@dataclass
class FittingResult:
    """
    Result of fitting a single IRT model.

    Contains the fitted model (if successful), status information,
    and any warnings or errors encountered.
    """
    model_type: IRTModel
    status: FittingStatus
    model: Optional[FittedModel] = None
    error_message: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    fitting_time_seconds: float = 0.0
    n_iterations: int = 0


@dataclass
class FittingOptions:
    """
    Options controlling model fitting behavior.

    These are internal options, not exposed to end users.
    They control the technical aspects of estimation.
    """
    max_iterations: int = 500
    convergence_threshold: float = 0.001
    estimation_method: str = "EM"  # EM, MHRM, QMCEM
    quadrature_points: int = 61
    random_seed: Optional[int] = None


class IRTModelFitter(ABC):
    """
    Abstract base class for IRT model fitting.

    Implementations of this class provide the actual model fitting
    functionality, whether through R, Python libraries, or other means.

    The interface is designed to be simple and opinionated:
    - Take validated data
    - Return fitted parameters
    - Report convergence status
    - Provide interpretable warnings

    Example:
        fitter = MirtWrapper()  # or PytorchFitter()
        result = fitter.fit(data, IRTModel.TWO_PL)

        if result.status == FittingStatus.SUCCESS:
            for item in result.model.item_parameters:
                print(f"{item.item_id}: a={item.discrimination:.2f}")
    """

    @abstractmethod
    def fit(
        self,
        data: pd.DataFrame,
        model_type: IRTModel,
        options: Optional[FittingOptions] = None,
    ) -> FittingResult:
        """
        Fit an IRT model to response data.

        Args:
            data: Response data (rows=respondents, columns=items)
            model_type: Which IRT model to fit (1PL, 2PL, 3PL)
            options: Optional fitting options

        Returns:
            FittingResult with model and status
        """
        pass

    @abstractmethod
    def fit_all(
        self,
        data: pd.DataFrame,
        options: Optional[FittingOptions] = None,
        include_3pl: bool = False,
    ) -> dict[IRTModel, FittingResult]:
        """
        Fit all appropriate IRT models.

        Args:
            data: Response data
            options: Optional fitting options
            include_3pl: Whether to include 3PL (requires larger sample)

        Returns:
            Dictionary mapping model type to fitting result
        """
        pass

    @abstractmethod
    def estimate_abilities(
        self,
        fitted_model: FittedModel,
        data: pd.DataFrame,
        method: str = "EAP",
    ) -> np.ndarray:
        """
        Estimate ability scores for respondents.

        Args:
            fitted_model: A fitted IRT model
            data: Response data for respondents to score
            method: Estimation method (EAP, MAP, ML)

        Returns:
            Array of ability estimates
        """
        pass

    def is_available(self) -> bool:
        """
        Check if this fitter is available (dependencies installed).

        Returns:
            True if the fitter can be used
        """
        return True

    def get_version(self) -> str:
        """
        Get the version of the underlying engine.

        Returns:
            Version string
        """
        return "unknown"


class CallbackProtocol(Protocol):
    """Protocol for progress callbacks during fitting."""

    def __call__(
        self,
        model_type: str,
        progress: float,
        message: Optional[str] = None,
    ) -> None:
        """
        Called to report fitting progress.

        Args:
            model_type: Which model is being fitted
            progress: Progress from 0 to 1
            message: Optional status message
        """
        ...


def validate_for_fitting(
    data: pd.DataFrame,
    model_type: IRTModel,
) -> tuple[bool, list[str]]:
    """
    Validate data before fitting.

    Performs quick checks to ensure data is suitable for the
    requested model type. Returns (is_valid, list_of_issues).
    """
    issues = []

    n_respondents, n_items = data.shape

    if n_respondents < 100:
        issues.append(
            f"Only {n_respondents} respondents. Minimum 100 required."
        )

    if n_items < 5:
        issues.append(
            f"Only {n_items} items. Minimum 5 required."
        )

    if model_type == IRTModel.THREE_PL and n_respondents < 500:
        issues.append(
            f"3PL requires at least 500 respondents. Found {n_respondents}."
        )

    # Check for all-missing rows
    all_missing_rows = data.isna().all(axis=1).sum()
    if all_missing_rows > 0:
        issues.append(
            f"{all_missing_rows} respondents have all missing data."
        )

    # Check for zero-variance items
    zero_var_items = [
        col for col in data.columns
        if data[col].var() == 0
    ]
    if zero_var_items:
        issues.append(
            f"{len(zero_var_items)} items have zero variance: {zero_var_items[:3]}"
        )

    return len(issues) == 0, issues


def compute_reliability(fitted_model: FittedModel) -> float:
    """
    Compute marginal reliability for a fitted model.

    Uses the empirical reliability formula based on test information.
    """
    # Generate theta grid
    theta = np.linspace(-4, 4, 81)

    # Compute total information
    total_info = np.zeros_like(theta)

    for item in fitted_model.item_parameters:
        a = item.discrimination
        b = item.difficulty
        c = item.guessing

        if fitted_model.model_type == IRTModel.RASCH:
            z = theta - b
            p = 1.0 / (1.0 + np.exp(-z))
            item_info = p * (1.0 - p)
        elif fitted_model.model_type == IRTModel.TWO_PL:
            z = a * (theta - b)
            p = 1.0 / (1.0 + np.exp(-z))
            item_info = (a ** 2) * p * (1.0 - p)
        else:  # 3PL
            z = a * (theta - b)
            exp_neg_z = np.exp(-z)
            p = c + (1.0 - c) / (1.0 + exp_neg_z)
            q = 1.0 - p
            p_safe = np.maximum(p, 1e-10)
            item_info = ((a ** 2) * q * ((p - c) ** 2)) / (p_safe * ((1.0 - c) ** 2))

        total_info += item_info

    # Weight by standard normal
    weights = np.exp(-0.5 * theta ** 2)
    weights /= weights.sum()

    # Average information
    avg_info = np.sum(weights * total_info)

    # Reliability
    if avg_info > 1:
        reliability = 1.0 - (1.0 / avg_info)
    else:
        reliability = 0.0

    return float(np.clip(reliability, 0.0, 1.0))
