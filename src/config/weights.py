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
    preference_category: float = 0.15
    preference_color: float = 0.10
    preference_fabric: float = 0.05
    preference_style: float = 0.10
    preference_brand: float = 0.10

    # Behavioral signals (what they've actually done)
    purchase_history_category: float = 0.10
    purchase_history_brand: float = 0.08
    purchase_history_color: float = 0.05

    # Wishlist signals (what they want)
    wishlist_similarity: float = 0.12

    # Product performance
    product_popularity: float = 0.05

    # Recency/novelty
    new_arrival_boost: float = 0.05

    # Availability
    in_stock_requirement: bool = True  # Filter, not a weight

    # Size availability
    size_match_boost: float = 0.05

    @field_validator('*', mode='before')
    @classmethod
    def validate_weight(cls, v, info):
        if info.field_name == 'in_stock_requirement':
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
            self.product_popularity +
            self.new_arrival_boost +
            self.size_match_boost
        )


# Default weights - balanced approach
DEFAULT_WEIGHTS = RecommendationWeights()

# Alternative presets for different scenarios
PREFERENCE_HEAVY_WEIGHTS = RecommendationWeights(
    preference_category=0.20,
    preference_color=0.15,
    preference_fabric=0.10,
    preference_style=0.15,
    preference_brand=0.15,
    purchase_history_category=0.05,
    purchase_history_brand=0.05,
    purchase_history_color=0.03,
    wishlist_similarity=0.07,
    product_popularity=0.02,
    new_arrival_boost=0.02,
    size_match_boost=0.01,
)

BEHAVIOR_HEAVY_WEIGHTS = RecommendationWeights(
    preference_category=0.08,
    preference_color=0.05,
    preference_fabric=0.03,
    preference_style=0.05,
    preference_brand=0.05,
    purchase_history_category=0.18,
    purchase_history_brand=0.15,
    purchase_history_color=0.10,
    wishlist_similarity=0.20,
    product_popularity=0.05,
    new_arrival_boost=0.03,
    size_match_boost=0.03,
)

NEW_CUSTOMER_WEIGHTS = RecommendationWeights(
    # For customers with little history, lean on popularity and trends
    preference_category=0.20,
    preference_color=0.10,
    preference_fabric=0.05,
    preference_style=0.10,
    preference_brand=0.10,
    purchase_history_category=0.02,
    purchase_history_brand=0.02,
    purchase_history_color=0.01,
    wishlist_similarity=0.05,
    product_popularity=0.25,
    new_arrival_boost=0.07,
    size_match_boost=0.03,
)
