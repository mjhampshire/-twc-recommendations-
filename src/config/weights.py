"""Configurable weights for the recommendation engine.

These weights control how much each factor contributes to the final
recommendation score. All weights should sum to 1.0 for interpretability,
but the engine will normalize them if needed.

Retailers can customize these weights to match their business priorities.
"""
from pydantic import BaseModel, field_validator


class RecommendationWeights(BaseModel):
    """Weights for each scoring component."""

    # Preference matching (stated preferences)
    preference_category: float = 0.12
    preference_color: float = 0.08
    preference_fabric: float = 0.04
    preference_style: float = 0.08
    preference_brand: float = 0.08

    # Purchase history signals (what they've bought)
    purchase_history_category: float = 0.08
    purchase_history_brand: float = 0.06
    purchase_history_color: float = 0.04

    # Wishlist signals (what they want)
    wishlist_similarity: float = 0.10

    # Browsing behavior signals (from website activity)
    browsing_viewed_category: float = 0.06  # Categories they've browsed
    browsing_viewed_brand: float = 0.04     # Brands they've looked at
    browsing_cart_similarity: float = 0.12  # Added to cart = high intent!

    # Product performance
    product_popularity: float = 0.04

    # Recency/novelty
    new_arrival_boost: float = 0.04

    # Availability
    in_stock_requirement: bool = True  # Filter, not a weight

    # Size availability
    size_match_boost: float = 0.02

    # Source multipliers (applied to preference scores based on who entered them)
    # Values > 1.0 boost that source, < 1.0 reduce it
    customer_source_multiplier: float = 1.0  # Preferences entered by customer
    staff_source_multiplier: float = 1.0     # Preferences entered by staff

    @field_validator('*', mode='before')
    @classmethod
    def validate_weight(cls, v, info):
        if info.field_name == 'in_stock_requirement':
            return v
        # Source multipliers can be > 1.0 (they're multipliers, not weights)
        if info.field_name in ('customer_source_multiplier', 'staff_source_multiplier'):
            if isinstance(v, (int, float)) and v < 0:
                raise ValueError(f"Multiplier must be non-negative")
            return v
        if isinstance(v, (int, float)) and (v < 0 or v > 1):
            raise ValueError(f"Weight must be between 0 and 1")
        return v

    def total_weight(self) -> float:
        """Sum of all weights (for normalization)."""
        return (
            self.preference_category +
            self.preference_color +
            self.preference_fabric +
            self.preference_style +
            self.preference_brand +
            self.purchase_history_category +
            self.purchase_history_brand +
            self.purchase_history_color +
            self.wishlist_similarity +
            self.browsing_viewed_category +
            self.browsing_viewed_brand +
            self.browsing_cart_similarity +
            self.product_popularity +
            self.new_arrival_boost +
            self.size_match_boost
        )


# Default weights - balanced approach
DEFAULT_WEIGHTS = RecommendationWeights()

# Alternative presets for different scenarios
PREFERENCE_HEAVY_WEIGHTS = RecommendationWeights(
    preference_category=0.18,
    preference_color=0.12,
    preference_fabric=0.08,
    preference_style=0.12,
    preference_brand=0.12,
    purchase_history_category=0.05,
    purchase_history_brand=0.04,
    purchase_history_color=0.02,
    wishlist_similarity=0.06,
    browsing_viewed_category=0.04,
    browsing_viewed_brand=0.03,
    browsing_cart_similarity=0.06,
    product_popularity=0.03,
    new_arrival_boost=0.03,
    size_match_boost=0.02,
)

BEHAVIOR_HEAVY_WEIGHTS = RecommendationWeights(
    # Prioritizes actual behavior over stated preferences
    preference_category=0.06,
    preference_color=0.04,
    preference_fabric=0.02,
    preference_style=0.04,
    preference_brand=0.04,
    purchase_history_category=0.12,
    purchase_history_brand=0.10,
    purchase_history_color=0.06,
    wishlist_similarity=0.14,
    browsing_viewed_category=0.10,
    browsing_viewed_brand=0.08,
    browsing_cart_similarity=0.14,  # Cart is strongest signal
    product_popularity=0.03,
    new_arrival_boost=0.02,
    size_match_boost=0.01,
)

NEW_CUSTOMER_WEIGHTS = RecommendationWeights(
    # For customers with little history, lean on popularity and any browsing data
    preference_category=0.15,
    preference_color=0.08,
    preference_fabric=0.04,
    preference_style=0.08,
    preference_brand=0.08,
    purchase_history_category=0.02,
    purchase_history_brand=0.02,
    purchase_history_color=0.01,
    wishlist_similarity=0.04,
    browsing_viewed_category=0.08,  # Browsing data more useful for new customers
    browsing_viewed_brand=0.06,
    browsing_cart_similarity=0.10,
    product_popularity=0.15,
    new_arrival_boost=0.06,
    size_match_boost=0.03,
)
