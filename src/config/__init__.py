"""Configuration for TWC Recommendations."""
from .weights import (
    RecommendationWeights,
    DEFAULT_WEIGHTS,
    PREFERENCE_HEAVY_WEIGHTS,
    BEHAVIOR_HEAVY_WEIGHTS,
    NEW_CUSTOMER_WEIGHTS,
)

__all__ = [
    "RecommendationWeights",
    "DEFAULT_WEIGHTS",
    "PREFERENCE_HEAVY_WEIGHTS",
    "BEHAVIOR_HEAVY_WEIGHTS",
    "NEW_CUSTOMER_WEIGHTS",
]
