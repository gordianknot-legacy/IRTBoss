"""
Data validation and ingestion for IRTBoss.

This module handles:
- CSV file parsing and validation
- Response data structure detection (dichotomous vs polytomous)
- Data quality checks and warnings
- Early feedback to users about their data

The goal is to catch data issues early and provide actionable feedback
before any model fitting begins.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .config import (
    DATA_QUALITY,
    SAMPLE_SIZE,
    DICHOTOMOUS_VALUES,
    POLYTOMOUS_MIN_CATEGORIES,
)

logger = logging.getLogger(__name__)


class ResponseType(Enum):
    """Type of response data detected in the dataset."""
    DICHOTOMOUS = "dichotomous"   # Binary (0/1) responses
    POLYTOMOUS = "polytomous"     # Ordinal responses (e.g., 0-4 Likert)
    UNKNOWN = "unknown"           # Could not determine


class ValidationSeverity(Enum):
    """Severity level for validation messages."""
    INFO = "info"        # Informational, no action needed
    WARNING = "warning"  # Potential issue, user should review
    ERROR = "error"      # Critical issue, cannot proceed


@dataclass
class ValidationMessage:
    """A single validation message with context."""
    severity: ValidationSeverity
    code: str           # Machine-readable code (e.g., "LOW_SAMPLE_SIZE")
    message: str        # Human-readable message
    details: Optional[str] = None  # Additional context
    affected_items: Optional[list[str]] = None  # Item IDs affected, if applicable


@dataclass
class DataSummary:
    """Summary statistics about the uploaded dataset."""
    n_respondents: int
    n_items: int
    response_type: ResponseType
    n_categories: int  # For polytomous: number of response categories
    missing_percentage: float
    item_names: list[str]

    # Item-level statistics
    item_means: dict[str, float] = field(default_factory=dict)
    item_variances: dict[str, float] = field(default_factory=dict)
    item_missing: dict[str, float] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """
    Complete result of data validation.

    Contains the validated data (if successful), summary statistics,
    and any validation messages.
    """
    is_valid: bool
    summary: Optional[DataSummary]
    messages: list[ValidationMessage]
    data: Optional[pd.DataFrame] = None  # Cleaned data, if validation passed

    @property
    def has_errors(self) -> bool:
        """Check if there are any error-level messages."""
        return any(m.severity == ValidationSeverity.ERROR for m in self.messages)

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warning-level messages."""
        return any(m.severity == ValidationSeverity.WARNING for m in self.messages)

    def get_errors(self) -> list[ValidationMessage]:
        """Get all error-level messages."""
        return [m for m in self.messages if m.severity == ValidationSeverity.ERROR]

    def get_warnings(self) -> list[ValidationMessage]:
        """Get all warning-level messages."""
        return [m for m in self.messages if m.severity == ValidationSeverity.WARNING]


class DataValidator:
    """
    Validates and prepares response data for IRT analysis.

    This class performs comprehensive validation of uploaded CSV data,
    detecting the response type, checking data quality, and providing
    actionable feedback to users.

    Example:
        validator = DataValidator()
        result = validator.validate_file("responses.csv")

        if result.is_valid:
            print(f"Found {result.summary.n_items} items")
        else:
            for error in result.get_errors():
                print(f"Error: {error.message}")
    """

    def validate_file(self, file_path: str | Path) -> ValidationResult:
        """
        Validate a CSV file containing response data.

        Args:
            file_path: Path to the CSV file

        Returns:
            ValidationResult with validation status and any messages
        """
        messages: list[ValidationMessage] = []

        # Check file exists and is readable
        path = Path(file_path)
        if not path.exists():
            messages.append(ValidationMessage(
                severity=ValidationSeverity.ERROR,
                code="FILE_NOT_FOUND",
                message=f"File not found: {file_path}",
            ))
            return ValidationResult(is_valid=False, summary=None, messages=messages)

        if not path.suffix.lower() == ".csv":
            messages.append(ValidationMessage(
                severity=ValidationSeverity.ERROR,
                code="INVALID_FILE_TYPE",
                message="Only CSV files are supported",
                details=f"Received file with extension: {path.suffix}",
            ))
            return ValidationResult(is_valid=False, summary=None, messages=messages)

        # Try to parse CSV
        try:
            df = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            messages.append(ValidationMessage(
                severity=ValidationSeverity.ERROR,
                code="EMPTY_FILE",
                message="The uploaded file is empty",
            ))
            return ValidationResult(is_valid=False, summary=None, messages=messages)
        except pd.errors.ParserError as e:
            messages.append(ValidationMessage(
                severity=ValidationSeverity.ERROR,
                code="PARSE_ERROR",
                message="Could not parse CSV file",
                details=str(e),
            ))
            return ValidationResult(is_valid=False, summary=None, messages=messages)

        return self.validate_dataframe(df, messages)

    def validate_dataframe(
        self,
        df: pd.DataFrame,
        existing_messages: Optional[list[ValidationMessage]] = None
    ) -> ValidationResult:
        """
        Validate a DataFrame containing response data.

        Args:
            df: DataFrame with response data (rows=respondents, cols=items)
            existing_messages: Any pre-existing validation messages

        Returns:
            ValidationResult with validation status and any messages
        """
        messages = existing_messages or []

        # Basic structure checks
        n_respondents, n_items = df.shape

        if n_respondents < SAMPLE_SIZE.MINIMUM_RESPONDENTS:
            messages.append(ValidationMessage(
                severity=ValidationSeverity.ERROR,
                code="INSUFFICIENT_RESPONDENTS",
                message=f"Not enough respondents for IRT analysis",
                details=(
                    f"Found {n_respondents} respondents. "
                    f"Minimum required: {SAMPLE_SIZE.MINIMUM_RESPONDENTS}. "
                    f"IRT parameter estimates become unreliable with small samples."
                ),
            ))

        if n_items < SAMPLE_SIZE.MINIMUM_ITEMS:
            messages.append(ValidationMessage(
                severity=ValidationSeverity.ERROR,
                code="INSUFFICIENT_ITEMS",
                message=f"Not enough items for IRT analysis",
                details=(
                    f"Found {n_items} items. "
                    f"Minimum required: {SAMPLE_SIZE.MINIMUM_ITEMS}."
                ),
            ))

        # Stop early if we have critical errors
        if any(m.severity == ValidationSeverity.ERROR for m in messages):
            return ValidationResult(is_valid=False, summary=None, messages=messages)

        # Detect response type and validate values
        response_type, n_categories, type_messages = self._detect_response_type(df)
        messages.extend(type_messages)

        if response_type == ResponseType.UNKNOWN:
            return ValidationResult(is_valid=False, summary=None, messages=messages)

        # Check for missing data
        missing_messages = self._check_missing_data(df)
        messages.extend(missing_messages)

        # Check item quality
        quality_messages = self._check_item_quality(df, response_type)
        messages.extend(quality_messages)

        # Check sample size warnings for different models
        sample_messages = self._check_sample_size_warnings(n_respondents)
        messages.extend(sample_messages)

        # Build summary
        summary = self._build_summary(df, response_type, n_categories)

        # Determine overall validity
        is_valid = not any(m.severity == ValidationSeverity.ERROR for m in messages)

        # Clean data if valid
        cleaned_data = self._clean_data(df) if is_valid else None

        return ValidationResult(
            is_valid=is_valid,
            summary=summary,
            messages=messages,
            data=cleaned_data,
        )

    def _detect_response_type(
        self, df: pd.DataFrame
    ) -> tuple[ResponseType, int, list[ValidationMessage]]:
        """
        Detect whether responses are dichotomous or polytomous.

        Returns:
            Tuple of (response_type, n_categories, messages)
        """
        messages: list[ValidationMessage] = []

        # Get all unique values across all items (excluding NaN)
        all_values = set()
        for col in df.columns:
            values = df[col].dropna().unique()
            all_values.update(values)

        # Check if values are numeric
        try:
            numeric_values = {float(v) for v in all_values}
            int_values = {int(v) for v in numeric_values if float(v).is_integer()}
        except (ValueError, TypeError):
            messages.append(ValidationMessage(
                severity=ValidationSeverity.ERROR,
                code="NON_NUMERIC_RESPONSES",
                message="Response data must be numeric",
                details=(
                    "Found non-numeric values in the data. "
                    "Please ensure all response values are integers."
                ),
            ))
            return ResponseType.UNKNOWN, 0, messages

        # Check for non-integer values
        if len(int_values) != len(numeric_values):
            messages.append(ValidationMessage(
                severity=ValidationSeverity.ERROR,
                code="NON_INTEGER_RESPONSES",
                message="Response data must be integers",
                details="Found non-integer values. IRT requires integer response codes.",
            ))
            return ResponseType.UNKNOWN, 0, messages

        # Check value range
        min_val = min(int_values)
        max_val = max(int_values)

        if min_val < 0:
            messages.append(ValidationMessage(
                severity=ValidationSeverity.ERROR,
                code="NEGATIVE_RESPONSES",
                message="Response values must be non-negative",
                details=f"Found minimum value: {min_val}",
            ))
            return ResponseType.UNKNOWN, 0, messages

        n_categories = max_val - min_val + 1

        # Determine type
        if int_values == DICHOTOMOUS_VALUES or int_values == {0} or int_values == {1}:
            # Special case: if only 0s or only 1s, still dichotomous but warn
            if int_values in ({0}, {1}):
                messages.append(ValidationMessage(
                    severity=ValidationSeverity.WARNING,
                    code="NO_VARIANCE",
                    message="Data has no variance in responses",
                    details="All responses are the same value across all items.",
                ))
            return ResponseType.DICHOTOMOUS, 2, messages

        if n_categories >= POLYTOMOUS_MIN_CATEGORIES:
            # Polytomous data
            messages.append(ValidationMessage(
                severity=ValidationSeverity.INFO,
                code="POLYTOMOUS_DETECTED",
                message=f"Detected polytomous responses with {n_categories} categories",
                details=f"Response values range from {min_val} to {max_val}.",
            ))

            # Check if categories are contiguous
            expected_values = set(range(min_val, max_val + 1))
            if int_values != expected_values:
                missing_cats = expected_values - int_values
                messages.append(ValidationMessage(
                    severity=ValidationSeverity.WARNING,
                    code="MISSING_CATEGORIES",
                    message="Some response categories are unused",
                    details=f"Categories {missing_cats} have no responses.",
                ))

            return ResponseType.POLYTOMOUS, n_categories, messages

        # Edge case: only 2 categories but not 0/1
        if n_categories == 2:
            messages.append(ValidationMessage(
                severity=ValidationSeverity.WARNING,
                code="NON_STANDARD_DICHOTOMOUS",
                message="Binary responses should use 0 and 1",
                details=f"Found values: {int_values}. Data will be recoded to 0/1.",
            ))
            return ResponseType.DICHOTOMOUS, 2, messages

        messages.append(ValidationMessage(
            severity=ValidationSeverity.ERROR,
            code="UNKNOWN_RESPONSE_TYPE",
            message="Could not determine response type",
        ))
        return ResponseType.UNKNOWN, 0, messages

    def _check_missing_data(self, df: pd.DataFrame) -> list[ValidationMessage]:
        """Check for missing data issues."""
        messages: list[ValidationMessage] = []

        total_cells = df.size
        total_missing = df.isna().sum().sum()
        missing_pct = total_missing / total_cells if total_cells > 0 else 0

        if missing_pct > DATA_QUALITY.MAX_MISSING_TOTAL:
            messages.append(ValidationMessage(
                severity=ValidationSeverity.ERROR,
                code="EXCESSIVE_MISSING_DATA",
                message="Too much missing data",
                details=(
                    f"Dataset has {missing_pct:.1%} missing values. "
                    f"Maximum allowed: {DATA_QUALITY.MAX_MISSING_TOTAL:.0%}. "
                    f"Consider collecting more complete data."
                ),
            ))
            return messages

        if missing_pct > 0:
            messages.append(ValidationMessage(
                severity=ValidationSeverity.INFO,
                code="MISSING_DATA_PRESENT",
                message=f"Dataset contains {missing_pct:.1%} missing values",
                details="Missing data will be handled using maximum likelihood estimation.",
            ))

        # Check per-item missing
        items_high_missing = []
        for col in df.columns:
            item_missing = df[col].isna().mean()
            if item_missing > DATA_QUALITY.MAX_MISSING_PER_ITEM:
                items_high_missing.append(col)

        if items_high_missing:
            messages.append(ValidationMessage(
                severity=ValidationSeverity.WARNING,
                code="ITEMS_HIGH_MISSING",
                message=f"{len(items_high_missing)} items have excessive missing data",
                details=(
                    f"Items with >{DATA_QUALITY.MAX_MISSING_PER_ITEM:.0%} missing: "
                    "consider removing or reviewing these items."
                ),
                affected_items=items_high_missing,
            ))

        # Check per-respondent missing
        respondent_missing = df.isna().mean(axis=1)
        n_high_missing = (respondent_missing > DATA_QUALITY.MAX_MISSING_PER_RESPONDENT).sum()

        if n_high_missing > 0:
            messages.append(ValidationMessage(
                severity=ValidationSeverity.WARNING,
                code="RESPONDENTS_HIGH_MISSING",
                message=f"{n_high_missing} respondents have excessive missing data",
                details=(
                    f"These respondents have >{DATA_QUALITY.MAX_MISSING_PER_RESPONDENT:.0%} "
                    "missing. They may not contribute reliable information."
                ),
            ))

        return messages

    def _check_item_quality(
        self, df: pd.DataFrame, response_type: ResponseType
    ) -> list[ValidationMessage]:
        """Check for item quality issues."""
        messages: list[ValidationMessage] = []

        # For dichotomous data, check item means (difficulty proxies)
        if response_type == ResponseType.DICHOTOMOUS:
            too_easy = []
            too_hard = []
            no_variance = []

            for col in df.columns:
                item_mean = df[col].mean()
                item_var = df[col].var()

                if item_var < DATA_QUALITY.MIN_ITEM_VARIANCE:
                    no_variance.append(col)
                elif item_mean > DATA_QUALITY.MAX_ITEM_MEAN:
                    too_easy.append(col)
                elif item_mean < DATA_QUALITY.MIN_ITEM_MEAN:
                    too_hard.append(col)

            if no_variance:
                messages.append(ValidationMessage(
                    severity=ValidationSeverity.ERROR,
                    code="ITEMS_NO_VARIANCE",
                    message=f"{len(no_variance)} items have no response variance",
                    details="Items with identical responses cannot be analyzed.",
                    affected_items=no_variance,
                ))

            if too_easy:
                messages.append(ValidationMessage(
                    severity=ValidationSeverity.WARNING,
                    code="ITEMS_TOO_EASY",
                    message=f"{len(too_easy)} items may be too easy",
                    details=(
                        f"Items with >{DATA_QUALITY.MAX_ITEM_MEAN:.0%} correct "
                        "responses provide limited discrimination."
                    ),
                    affected_items=too_easy,
                ))

            if too_hard:
                messages.append(ValidationMessage(
                    severity=ValidationSeverity.WARNING,
                    code="ITEMS_TOO_HARD",
                    message=f"{len(too_hard)} items may be too hard",
                    details=(
                        f"Items with <{DATA_QUALITY.MIN_ITEM_MEAN:.0%} correct "
                        "responses provide limited information."
                    ),
                    affected_items=too_hard,
                ))

        return messages

    def _check_sample_size_warnings(self, n: int) -> list[ValidationMessage]:
        """Check sample size against model requirements."""
        messages: list[ValidationMessage] = []

        if n < SAMPLE_SIZE.WARNING_RESPONDENTS_1PL:
            messages.append(ValidationMessage(
                severity=ValidationSeverity.WARNING,
                code="SMALL_SAMPLE_1PL",
                message="Sample size is small for 1PL model",
                details=(
                    f"Found {n} respondents. "
                    f"Recommended minimum for 1PL: {SAMPLE_SIZE.RECOMMENDED_RESPONDENTS_1PL}. "
                    "Parameter estimates may be unstable."
                ),
            ))

        if n < SAMPLE_SIZE.WARNING_RESPONDENTS_2PL:
            messages.append(ValidationMessage(
                severity=ValidationSeverity.WARNING,
                code="SMALL_SAMPLE_2PL",
                message="Sample size is marginal for 2PL model",
                details=(
                    f"With {n} respondents, 2PL estimation may be unstable. "
                    f"Recommended: {SAMPLE_SIZE.RECOMMENDED_RESPONDENTS_2PL}+ respondents."
                ),
            ))

        if n < SAMPLE_SIZE.WARNING_RESPONDENTS_3PL:
            messages.append(ValidationMessage(
                severity=ValidationSeverity.WARNING,
                code="SMALL_SAMPLE_3PL",
                message="Sample size is too small for 3PL model",
                details=(
                    f"3PL model requires estimating guessing parameters. "
                    f"With {n} respondents, 3PL will NOT be fitted. "
                    f"Minimum for 3PL: {SAMPLE_SIZE.WARNING_RESPONDENTS_3PL} respondents."
                ),
            ))

        return messages

    def _build_summary(
        self, df: pd.DataFrame, response_type: ResponseType, n_categories: int
    ) -> DataSummary:
        """Build a summary of the dataset."""
        n_respondents, n_items = df.shape

        # Calculate item-level statistics
        item_means = {col: df[col].mean() for col in df.columns}
        item_variances = {col: df[col].var() for col in df.columns}
        item_missing = {col: df[col].isna().mean() for col in df.columns}

        total_missing = df.isna().sum().sum() / df.size if df.size > 0 else 0

        return DataSummary(
            n_respondents=n_respondents,
            n_items=n_items,
            response_type=response_type,
            n_categories=n_categories,
            missing_percentage=total_missing,
            item_names=list(df.columns),
            item_means=item_means,
            item_variances=item_variances,
            item_missing=item_missing,
        )

    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean and prepare data for analysis.

        This applies minimal transformations to make data ready for IRT fitting.
        We intentionally avoid aggressive imputation or transformation.
        """
        # Make a copy to avoid modifying original
        cleaned = df.copy()

        # Ensure all columns are numeric
        for col in cleaned.columns:
            cleaned[col] = pd.to_numeric(cleaned[col], errors="coerce")

        # Log any rows that will be dropped due to all-missing
        all_missing_rows = cleaned.isna().all(axis=1).sum()
        if all_missing_rows > 0:
            logger.warning(f"Removing {all_missing_rows} rows with all missing values")
            cleaned = cleaned.dropna(how="all")

        return cleaned
