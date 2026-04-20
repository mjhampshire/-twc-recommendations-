"""Logging models for recommendation tracking.

These models capture recommendation events and outcomes to enable:
- Model performance measurement (click-through rates, conversion rates)
- A/B testing of weight configurations
- Training data generation for ML models
- Business analytics on recommendation effectiveness
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
import uuid


class RecommendationType(str, Enum):
    """Types of recommendations generated."""
    PERSONALIZED = "personalized"  # Main recommendations based on full profile
    ALTERNATIVES = "alternatives"  # Alternatives for sold-out items
    SIMILAR = "similar"  # Similar items to a product
    NEW_ARRIVALS = "new_arrivals"  # New products matching preferences
    TRENDING = "trending"  # Popular items in customer's categories


class OutcomeType(str, Enum):
    """Types of outcomes that can occur after a recommendation."""
    VIEWED = "viewed"  # Customer viewed recommendation details
    CLICKED = "clicked"  # Customer clicked to product page
    ADDED_TO_CART = "added_to_cart"  # Added to cart
    ADDED_TO_WISHLIST = "added_to_wishlist"  # Added to wishlist
    PURCHASED = "purchased"  # Purchased the item
    IGNORED = "ignored"  # Recommendation shown but not interacted with
    DISMISSED = "dismissed"  # Explicitly dismissed/hidden


class OutcomeActor(str, Enum):
    """Who initiated the outcome action."""
    CUSTOMER = "customer"  # Customer took action themselves
    STAFF = "staff"  # Staff member took action on behalf of customer


class RecommendationEvent(BaseModel):
    """
    Captures a single recommendation event.

    Logged every time recommendations are generated for a customer.
    Links to outcomes via event_id.

    ClickHouse table: TWCRECOMMENDATION_LOG
    """
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    customer_id: str  # Anonymized customer identifier
    staff_id: Optional[str] = None  # If staff-assisted
    session_id: Optional[str] = None  # Browser/app session

    # What was recommended
    recommendation_type: RecommendationType
    recommended_items: list[str]  # Product IDs in order shown
    scores: list[float]  # Corresponding scores
    positions: list[int]  # Display positions (1-indexed)

    # Context for the recommendation
    context_features: dict = Field(default_factory=dict)  # Serialized as JSON
    # Example context: {"has_preferences": true, "purchase_count": 5,
    #                   "days_since_last_visit": 3, "device": "mobile"}

    # Model/algorithm version
    model_version: str = "rule-based-v1"
    weights_config: Optional[str] = None  # Name of weights preset used

    # A/B test tracking
    ab_test_id: Optional[str] = None  # ID of active A/B test
    ab_test_variant: Optional[str] = None  # "control" or "treatment"

    # Timing
    recommended_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(use_enum_values=True)


class RecommendationOutcome(BaseModel):
    """
    Captures an outcome/interaction with a recommendation.

    Links back to the original recommendation event.
    Multiple outcomes can occur for a single recommendation event.

    ClickHouse table: TWCRECOMMENDATION_OUTCOME
    """
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    recommendation_event_id: str  # Links to RecommendationEvent
    tenant_id: str
    customer_id: str

    # What happened
    outcome_type: OutcomeType
    item_id: str  # Which product was interacted with
    position: int  # Position in the recommendation list (1-indexed)

    # Who initiated the action
    actor: OutcomeActor = OutcomeActor.CUSTOMER
    staff_id: Optional[str] = None  # If actor is STAFF

    # Purchase details (if outcome is PURCHASED)
    purchase_value: Optional[float] = None
    purchase_order_id: Optional[str] = None

    # Time tracking
    days_to_conversion: Optional[int] = None  # Days from recommendation to outcome
    occurred_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(use_enum_values=True)


class RecommendationMetrics(BaseModel):
    """
    Aggregated metrics for a recommendation model/configuration.

    Used for A/B test analysis and model evaluation.
    """
    tenant_id: str
    model_version: str
    weights_config: Optional[str] = None

    # Date range
    start_date: datetime
    end_date: datetime

    # Volume metrics
    total_recommendations: int = 0
    total_items_recommended: int = 0
    unique_customers: int = 0

    # Engagement metrics
    total_views: int = 0
    total_clicks: int = 0
    total_add_to_cart: int = 0
    total_add_to_wishlist: int = 0
    total_purchases: int = 0

    # Calculated rates
    @property
    def click_through_rate(self) -> float:
        """Percentage of recommendations that led to a click."""
        if self.total_recommendations == 0:
            return 0.0
        return self.total_clicks / self.total_recommendations

    @property
    def conversion_rate(self) -> float:
        """Percentage of recommendations that led to purchase."""
        if self.total_recommendations == 0:
            return 0.0
        return self.total_purchases / self.total_recommendations

    @property
    def cart_rate(self) -> float:
        """Percentage of recommendations added to cart."""
        if self.total_recommendations == 0:
            return 0.0
        return self.total_add_to_cart / self.total_recommendations

    # Revenue metrics
    total_revenue: float = 0.0
    avg_order_value: float = 0.0

    @property
    def revenue_per_recommendation(self) -> float:
        """Average revenue generated per recommendation event."""
        if self.total_recommendations == 0:
            return 0.0
        return self.total_revenue / self.total_recommendations


