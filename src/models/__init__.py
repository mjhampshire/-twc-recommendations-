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

__all__ = [
    "Customer",
    "CustomerPreferences",
    "CustomerDislikes",
    "PreferenceItem",
    "PreferenceSource",
    "PurchaseHistory",
    "WishlistSummary",
    "BrowsingBehavior",
    "Product",
    "ProductAttributes",
    "ProductSizing",
    "ProductMetrics",
    "ScoredProduct",
]
