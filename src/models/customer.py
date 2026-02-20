"""Customer data models."""
from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class CustomerPreferences(BaseModel):
    """Customer's stated preferences."""
    categories: list[str] = []      # e.g., ["Dresses", "Tops", "Accessories"]
    colors: list[str] = []          # e.g., ["Navy", "Black", "Cream"]
    fabrics: list[str] = []         # e.g., ["Silk", "Cotton", "Linen"]
    styles: list[str] = []          # e.g., ["Classic", "Bohemian", "Minimalist"]
    brands: list[str] = []          # e.g., ["Zimmermann", "Scanlan Theodore"]
    size_top: Optional[str] = None
    size_bottom: Optional[str] = None
    size_dress: Optional[str] = None
    size_shoe: Optional[str] = None
    price_sensitivity: Optional[str] = None  # "budget", "mid", "luxury", "any"


class PurchaseHistory(BaseModel):
    """Summary of customer's purchase history."""
    total_purchases: int = 0
    total_spend: float = 0.0
    average_order_value: float = 0.0
    last_purchase_date: Optional[datetime] = None
    top_categories: list[str] = []
    top_brands: list[str] = []
    top_colors: list[str] = []
    recent_product_ids: list[str] = []  # Last N purchased product IDs


class WishlistSummary(BaseModel):
    """Summary of customer's wishlist activity."""
    total_wishlisted: int = 0
    active_wishlist_items: list[str] = []  # Current wishlist product IDs
    wishlist_categories: list[str] = []
    wishlist_brands: list[str] = []
    wishlist_colors: list[str] = []


class Customer(BaseModel):
    """Complete customer profile for recommendations."""
    customer_id: str
    retailer_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    is_vip: bool = False
    preferences: CustomerPreferences = CustomerPreferences()
    purchase_history: PurchaseHistory = PurchaseHistory()
    wishlist: WishlistSummary = WishlistSummary()
    created_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
