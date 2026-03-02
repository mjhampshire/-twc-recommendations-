"""Logging service for recommendation tracking.

Provides a high-level interface for logging recommendations and outcomes,
with optional async support and batching for high-throughput scenarios.
"""
from datetime import datetime
from typing import Optional

from ..models import Customer, ScoredProduct
from ..models.logging import (
    RecommendationEvent,
    RecommendationOutcome,
    RecommendationType,
    OutcomeType,
)
from ..data.logging_repository import RecommendationLogRepository
from ..config.clickhouse import ClickHouseConfig


class RecommendationLogger:
    """
    High-level service for logging recommendation events and outcomes.

    Integrates with the RecommendationEngine to automatically log
    when recommendations are generated.

    Usage:
        logger = RecommendationLogger(clickhouse_config)

        # Log when recommendations are generated
        event_id = logger.log_recommendations(
            customer=customer,
            recommendations=scored_products,
            recommendation_type=RecommendationType.PERSONALIZED,
        )

        # Later, log outcomes as they occur
        logger.log_click(event_id, product_id="P123", position=1)
        logger.log_purchase(event_id, product_id="P123", position=1, value=450.00)
    """

    MODEL_VERSION = "rule-based-v1"

    def __init__(
        self,
        config: ClickHouseConfig,
        enabled: bool = True,
    ):
        """
        Initialize the logger.

        Args:
            config: ClickHouse configuration
            enabled: If False, logging calls are no-ops (useful for testing)
        """
        self.repository = RecommendationLogRepository(config)
        self.enabled = enabled

    def log_recommendations(
        self,
        customer: Customer,
        recommendations: list[ScoredProduct],
        recommendation_type: RecommendationType = RecommendationType.PERSONALIZED,
        staff_id: Optional[str] = None,
        session_id: Optional[str] = None,
        weights_config: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> Optional[str]:
        """
        Log a recommendation event.

        Call this after generating recommendations for a customer.

        Args:
            customer: The customer who received recommendations
            recommendations: List of scored products recommended
            recommendation_type: Type of recommendation
            staff_id: ID of staff member if this was staff-assisted
            session_id: Browser/app session ID
            weights_config: Name of weights configuration used
            context: Additional context features for ML training

        Returns:
            Event ID for tracking outcomes, or None if logging is disabled
        """
        if not self.enabled:
            return None

        # Build context features from customer profile
        auto_context = self._extract_context(customer)
        if context:
            auto_context.update(context)

        event = RecommendationEvent(
            tenant_id=customer.retailer_id,
            customer_id=customer.customer_id,
            staff_id=staff_id,
            session_id=session_id,
            recommendation_type=recommendation_type,
            recommended_items=[r.product.product_id for r in recommendations],
            scores=[r.score for r in recommendations],
            positions=list(range(1, len(recommendations) + 1)),
            context_features=auto_context,
            model_version=self.MODEL_VERSION,
            weights_config=weights_config,
        )

        self.repository.log_recommendation(event)
        return event.event_id

    def _extract_context(self, customer: Customer) -> dict:
        """Extract context features from customer profile for ML training."""
        return {
            "has_preferences": bool(
                customer.preferences.categories or
                customer.preferences.brands or
                customer.preferences.colors
            ),
            "has_dislikes": bool(
                customer.dislikes.categories or
                customer.dislikes.brands or
                customer.dislikes.colors
            ),
            "purchase_count": customer.purchase_history.total_purchases,
            "total_spend": customer.purchase_history.total_spend,
            "wishlist_count": customer.wishlist.total_wishlisted,
            "browse_count_30d": customer.browsing.view_count_last_30_days,
            "sessions_30d": customer.browsing.sessions_last_30_days,
            "is_vip": customer.is_vip,
            "days_since_purchase": self._days_since(customer.purchase_history.last_purchase_date),
            "days_since_browse": self._days_since(customer.browsing.last_browse_date),
        }

    def _days_since(self, date: Optional[datetime]) -> Optional[int]:
        """Calculate days since a date, or None if date is not available."""
        if not date:
            return None
        delta = datetime.utcnow() - date
        return delta.days

    def log_view(
        self,
        recommendation_event_id: str,
        tenant_id: str,
        customer_id: str,
        product_id: str,
        position: int,
    ) -> None:
        """Log when a customer views a recommended product."""
        if not self.enabled:
            return

        self._log_outcome(
            recommendation_event_id=recommendation_event_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            outcome_type=OutcomeType.VIEWED,
            product_id=product_id,
            position=position,
        )

    def log_click(
        self,
        recommendation_event_id: str,
        tenant_id: str,
        customer_id: str,
        product_id: str,
        position: int,
    ) -> None:
        """Log when a customer clicks a recommended product."""
        if not self.enabled:
            return

        self._log_outcome(
            recommendation_event_id=recommendation_event_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            outcome_type=OutcomeType.CLICKED,
            product_id=product_id,
            position=position,
        )

    def log_add_to_cart(
        self,
        recommendation_event_id: str,
        tenant_id: str,
        customer_id: str,
        product_id: str,
        position: int,
    ) -> None:
        """Log when a customer adds a recommended product to cart."""
        if not self.enabled:
            return

        self._log_outcome(
            recommendation_event_id=recommendation_event_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            outcome_type=OutcomeType.ADDED_TO_CART,
            product_id=product_id,
            position=position,
        )

    def log_add_to_wishlist(
        self,
        recommendation_event_id: str,
        tenant_id: str,
        customer_id: str,
        product_id: str,
        position: int,
    ) -> None:
        """Log when a customer adds a recommended product to wishlist."""
        if not self.enabled:
            return

        self._log_outcome(
            recommendation_event_id=recommendation_event_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            outcome_type=OutcomeType.ADDED_TO_WISHLIST,
            product_id=product_id,
            position=position,
        )

    def log_purchase(
        self,
        recommendation_event_id: str,
        tenant_id: str,
        customer_id: str,
        product_id: str,
        position: int,
        purchase_value: float,
        order_id: Optional[str] = None,
        recommendation_date: Optional[datetime] = None,
    ) -> None:
        """Log when a customer purchases a recommended product."""
        if not self.enabled:
            return

        days_to_conversion = None
        if recommendation_date:
            delta = datetime.utcnow() - recommendation_date
            days_to_conversion = delta.days

        outcome = RecommendationOutcome(
            recommendation_event_id=recommendation_event_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            outcome_type=OutcomeType.PURCHASED,
            item_id=product_id,
            position=position,
            purchase_value=purchase_value,
            purchase_order_id=order_id,
            days_to_conversion=days_to_conversion,
        )

        self.repository.log_outcome(outcome)

    def log_dismissed(
        self,
        recommendation_event_id: str,
        tenant_id: str,
        customer_id: str,
        product_id: str,
        position: int,
    ) -> None:
        """Log when a customer dismisses a recommended product."""
        if not self.enabled:
            return

        self._log_outcome(
            recommendation_event_id=recommendation_event_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            outcome_type=OutcomeType.DISMISSED,
            product_id=product_id,
            position=position,
        )

    def _log_outcome(
        self,
        recommendation_event_id: str,
        tenant_id: str,
        customer_id: str,
        outcome_type: OutcomeType,
        product_id: str,
        position: int,
    ) -> None:
        """Internal method to log an outcome."""
        outcome = RecommendationOutcome(
            recommendation_event_id=recommendation_event_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            outcome_type=outcome_type,
            item_id=product_id,
            position=position,
        )

        self.repository.log_outcome(outcome)
