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
    OutcomeActor,
)
from .ab_test import (
    ABTestAssignment,
    ABTestConfig,
    ABTestMetrics,
    ABTestResults,
    TenantWeights,
    TenantConfig,
    WeightPreset,
)
from .bandit import (
    BanditArmStats,
    BanditConfig,
    BanditSelection,
    BanditSummary,
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
    "OutcomeActor",
    # A/B test models
    "ABTestAssignment",
    "ABTestConfig",
    "ABTestMetrics",
    "ABTestResults",
    "TenantWeights",
    "TenantConfig",
    "WeightPreset",
    # Bandit models
    "BanditArmStats",
    "BanditConfig",
    "BanditSelection",
    "BanditSummary",
]
