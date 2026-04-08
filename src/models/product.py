"""Product data models."""
from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class ProductAttributes(BaseModel):
    """Product attributes used for matching."""
    category: Optional[str] = None       # e.g., "Dresses"
    subcategory: Optional[str] = None    # e.g., "Midi Dresses"
    collection: Optional[str] = None     # e.g., "Summer 2025"
    color: Optional[str] = None          # Primary color
    colors: list[str] = []               # All colors
    fabric: Optional[str] = None         # Primary fabric
    fabrics: list[str] = []              # All fabrics
    style: Optional[str] = None          # e.g., "Classic", "Bohemian"
    brand: Optional[str] = None
    season: Optional[str] = None         # e.g., "SS24", "AW24"
    occasions: list[str] = []            # e.g., ["Work", "Evening", "Casual"]


class ProductSizing(BaseModel):
    """Available sizes for a product."""
    available_sizes: list[str] = []
    size_type: Optional[str] = None      # "clothing", "shoes", "accessories"


class ProductMetrics(BaseModel):
    """Performance metrics for a product."""
    total_purchases: int = 0
    total_wishlisted: int = 0
    view_count: int = 0
    conversion_rate: float = 0.0
    trending_score: float = 0.0          # Recent velocity


class Product(BaseModel):
    """Complete product for recommendations."""
    product_id: str  # variantRef - unique per size/color combination
    product_ref: Optional[str] = None  # Base product ID - same across all variants
    retailer_id: str
    name: str
    description: Optional[str] = None
    price: float
    original_price: Optional[float] = None  # If on sale
    image_url: Optional[str] = None
    product_url: Optional[str] = None
    attributes: ProductAttributes = ProductAttributes()
    sizing: ProductSizing = ProductSizing()
    metrics: ProductMetrics = ProductMetrics()
    is_new_arrival: bool = False
    stock_status: Optional[str] = None  # Variant status from TWCVARIANT (e.g., "in_stock", "out_of_stock", "low_stock")
    created_at: Optional[datetime] = None


class ScoredProduct(BaseModel):
    """Product with recommendation score and explanation."""
    product: Product
    score: float
    score_breakdown: dict[str, float] = {}  # Component scores
    reasons: list[str] = []                  # Human-readable reasons
