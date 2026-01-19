"""
Pytest configuration and fixtures for IRTBoss tests.
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path


@pytest.fixture
def sample_dichotomous_data() -> pd.DataFrame:
    """Generate sample dichotomous response data for testing."""
    np.random.seed(42)
    n_respondents = 200
    n_items = 20

    # Simulate abilities
    abilities = np.random.normal(0, 1, n_respondents)

    # Simulate item difficulties
    difficulties = np.linspace(-2, 2, n_items)

    # Generate responses using Rasch model
    data = {}
    for i, diff in enumerate(difficulties):
        prob = 1 / (1 + np.exp(-(abilities - diff)))
        responses = (np.random.random(n_respondents) < prob).astype(int)
        data[f"item_{i+1:02d}"] = responses

    return pd.DataFrame(data)


@pytest.fixture
def sample_polytomous_data() -> pd.DataFrame:
    """Generate sample polytomous response data for testing."""
    np.random.seed(42)
    n_respondents = 200
    n_items = 15
    n_categories = 5

    # Simulate abilities
    abilities = np.random.normal(0, 1, n_respondents)

    # Generate ordinal responses
    data = {}
    for i in range(n_items):
        # Simple ordinal simulation
        base = abilities + np.random.normal(0, 0.5, n_respondents)
        responses = np.clip(
            np.round((base + 2) / 4 * (n_categories - 1) + 1),
            1, n_categories
        ).astype(int)
        data[f"q{i+1:02d}"] = responses

    return pd.DataFrame(data)


@pytest.fixture
def small_sample_data() -> pd.DataFrame:
    """Generate data with too few respondents."""
    np.random.seed(42)
    return pd.DataFrame({
        f"item_{i}": np.random.randint(0, 2, 50)
        for i in range(10)
    })


@pytest.fixture
def data_with_missing() -> pd.DataFrame:
    """Generate data with missing values."""
    np.random.seed(42)
    df = pd.DataFrame({
        f"item_{i}": np.random.randint(0, 2, 200).astype(float)
        for i in range(20)
    })
    # Introduce 5% missing data
    mask = np.random.random(df.shape) < 0.05
    df = df.mask(mask)
    return df


@pytest.fixture
def temp_csv_path(tmp_path: Path, sample_dichotomous_data: pd.DataFrame) -> Path:
    """Create a temporary CSV file with sample data."""
    csv_path = tmp_path / "test_data.csv"
    sample_dichotomous_data.to_csv(csv_path, index=False)
    return csv_path
