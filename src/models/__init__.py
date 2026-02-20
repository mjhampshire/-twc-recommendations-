"""Data models for TWC Recommendations."""
from .customer import Customer, CustomerPreferences, PurchaseHistory, WishlistSummary
from .product import Product, ProductAttributes, ProductSizing, ProductMetrics, ScoredProduct

__all__ = [
    "Customer",
    "CustomerPreferences",
    "PurchaseHistory",
    "WishlistSummary",
    "Product",
    "ProductAttributes",
    "ProductSizing",
    "ProductMetrics",
    "ScoredProduct",
]
