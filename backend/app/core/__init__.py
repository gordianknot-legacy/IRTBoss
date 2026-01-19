# Core business logic for IRTBoss
"""
Core modules for IRT analysis workflow:
- data_validation: CSV ingestion and validation
- model_selection: Model fitting and comparison
- recommendations: Automated model recommendations
- diagnostics: Item and test diagnostics
"""

from .data_validation import DataValidator, ValidationResult
from .model_selection import ModelSelector, ModelComparisonResult
from .recommendations import RecommendationEngine, Recommendation
from .diagnostics import DiagnosticsGenerator, ItemDiagnostics

__all__ = [
    "DataValidator",
    "ValidationResult",
    "ModelSelector",
    "ModelComparisonResult",
    "RecommendationEngine",
    "Recommendation",
    "DiagnosticsGenerator",
    "ItemDiagnostics",
]
