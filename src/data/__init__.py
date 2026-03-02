"""Data access layer for TWC Recommendations."""
from .repository import CustomerRepository, ProductRepository
from .clickhouse_repository import ClickHouseCustomerRepository, ClickHouseProductRepository
from .logging_repository import RecommendationLogRepository

__all__ = [
    # Mock repositories (for development/testing)
    "CustomerRepository",
    "ProductRepository",
    # ClickHouse repositories (for production)
    "ClickHouseCustomerRepository",
    "ClickHouseProductRepository",
    "RecommendationLogRepository",
]
