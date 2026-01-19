"""
Tests for data validation module.
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path

from app.core.data_validation import (
    DataValidator,
    ResponseType,
    ValidationSeverity,
)


class TestDataValidator:
    """Tests for DataValidator class."""

    def test_validate_valid_dichotomous_data(self, sample_dichotomous_data):
        """Valid dichotomous data should pass validation."""
        validator = DataValidator()
        result = validator.validate_dataframe(sample_dichotomous_data)

        assert result.is_valid
        assert result.summary is not None
        assert result.summary.response_type == ResponseType.DICHOTOMOUS
        assert result.summary.n_respondents == 200
        assert result.summary.n_items == 20
        assert not result.has_errors

    def test_validate_valid_polytomous_data(self, sample_polytomous_data):
        """Valid polytomous data should pass validation."""
        validator = DataValidator()
        result = validator.validate_dataframe(sample_polytomous_data)

        assert result.is_valid
        assert result.summary is not None
        assert result.summary.response_type == ResponseType.POLYTOMOUS
        assert result.summary.n_categories == 5

    def test_validate_small_sample(self, small_sample_data):
        """Small sample should generate error."""
        validator = DataValidator()
        result = validator.validate_dataframe(small_sample_data)

        assert not result.is_valid
        assert result.has_errors
        error_codes = [m.code for m in result.get_errors()]
        assert "INSUFFICIENT_RESPONDENTS" in error_codes

    def test_validate_data_with_missing(self, data_with_missing):
        """Data with missing values should generate appropriate messages."""
        validator = DataValidator()
        result = validator.validate_dataframe(data_with_missing)

        assert result.is_valid  # 5% missing is acceptable
        assert result.summary.missing_percentage > 0

    def test_validate_file(self, temp_csv_path):
        """Validation should work with file path."""
        validator = DataValidator()
        result = validator.validate_file(temp_csv_path)

        assert result.is_valid
        assert result.data is not None

    def test_validate_nonexistent_file(self, tmp_path):
        """Nonexistent file should generate error."""
        validator = DataValidator()
        result = validator.validate_file(tmp_path / "nonexistent.csv")

        assert not result.is_valid
        assert result.has_errors
        error_codes = [m.code for m in result.get_errors()]
        assert "FILE_NOT_FOUND" in error_codes

    def test_validate_non_csv_file(self, tmp_path):
        """Non-CSV file should generate error."""
        txt_path = tmp_path / "data.txt"
        txt_path.write_text("some text")

        validator = DataValidator()
        result = validator.validate_file(txt_path)

        assert not result.is_valid
        error_codes = [m.code for m in result.get_errors()]
        assert "INVALID_FILE_TYPE" in error_codes

    def test_validate_empty_dataframe(self):
        """Empty dataframe should generate error."""
        validator = DataValidator()
        result = validator.validate_dataframe(pd.DataFrame())

        assert not result.is_valid

    def test_validate_too_few_items(self):
        """Data with too few items should generate error."""
        df = pd.DataFrame({
            "item_1": np.random.randint(0, 2, 200),
            "item_2": np.random.randint(0, 2, 200),
        })
        validator = DataValidator()
        result = validator.validate_dataframe(df)

        assert not result.is_valid
        error_codes = [m.code for m in result.get_errors()]
        assert "INSUFFICIENT_ITEMS" in error_codes

    def test_validate_zero_variance_items(self):
        """Items with zero variance should be flagged."""
        np.random.seed(42)
        df = pd.DataFrame({
            f"item_{i}": np.random.randint(0, 2, 200)
            for i in range(19)
        })
        df["item_bad"] = 1  # All ones - no variance

        validator = DataValidator()
        result = validator.validate_dataframe(df)

        # Should have error for zero variance
        assert result.has_errors
        error_codes = [m.code for m in result.get_errors()]
        assert "ITEMS_NO_VARIANCE" in error_codes

    def test_detect_dichotomous_type(self, sample_dichotomous_data):
        """Should correctly detect dichotomous response type."""
        validator = DataValidator()
        result = validator.validate_dataframe(sample_dichotomous_data)

        assert result.summary.response_type == ResponseType.DICHOTOMOUS
        assert result.summary.n_categories == 2

    def test_detect_polytomous_type(self, sample_polytomous_data):
        """Should correctly detect polytomous response type."""
        validator = DataValidator()
        result = validator.validate_dataframe(sample_polytomous_data)

        assert result.summary.response_type == ResponseType.POLYTOMOUS
        assert result.summary.n_categories >= 3

    def test_item_statistics(self, sample_dichotomous_data):
        """Should calculate item-level statistics."""
        validator = DataValidator()
        result = validator.validate_dataframe(sample_dichotomous_data)

        assert len(result.summary.item_means) == 20
        assert len(result.summary.item_variances) == 20
        assert all(0 <= m <= 1 for m in result.summary.item_means.values())
