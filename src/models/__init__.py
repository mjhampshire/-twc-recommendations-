"""Data models for TWC Recommendations."""
from .customer import (
    Customer,
    CustomerPreferences,
    CustomerDislikes,
    PreferenceItem,
    PreferenceSource,
    PurchaseHistory,
    WishlistSummary,
    BrowsingBehavior,
)
from .product import Product, ProductAttributes, ProductSizing, ProductMetrics, ScoredProduct
from .logging import (
    RecommendationEvent,
    RecommendationOutcome,
    RecommendationMetrics,
    RecommendationType,
    OutcomeType,
    ABTestConfig,
)

__all__ = [
    # Customer models
    "Customer",
    "CustomerPreferences",
    "CustomerDislikes",
    "PreferenceItem",
    "PreferenceSource",
    "PurchaseHistory",
    "WishlistSummary",
    "BrowsingBehavior",
    # Product models
    "Product",
    "ProductAttributes",
    "ProductSizing",
    "ProductMetrics",
    "ScoredProduct",
    # Logging models
    "RecommendationEvent",
    "RecommendationOutcome",
    "RecommendationMetrics",
    "RecommendationType",
    "OutcomeType",
    "ABTestConfig",
]
