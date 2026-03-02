"""Configuration for TWC Recommendations."""
from .weights import (
    RecommendationWeights,
    DEFAULT_WEIGHTS,
    PREFERENCE_HEAVY_WEIGHTS,
    BEHAVIOR_HEAVY_WEIGHTS,
    NEW_CUSTOMER_WEIGHTS,
)
from .clickhouse import ClickHouseConfig, get_clickhouse_config

__all__ = [
    "RecommendationWeights",
    "DEFAULT_WEIGHTS",
    "PREFERENCE_HEAVY_WEIGHTS",
    "BEHAVIOR_HEAVY_WEIGHTS",
    "NEW_CUSTOMER_WEIGHTS",
    "ClickHouseConfig",
    "get_clickhouse_config",
]
