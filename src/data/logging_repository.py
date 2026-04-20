"""ClickHouse repository for recommendation logging.

Handles writing recommendation events and outcomes to ClickHouse,
and querying for analytics and model evaluation.
"""
import json
from datetime import datetime, timedelta
from typing import Optional

import clickhouse_connect

from ..config.clickhouse import ClickHouseConfig
from ..models.logging import (
    RecommendationEvent,
    RecommendationOutcome,
    RecommendationMetrics,
    OutcomeType,
)


def _get_client(config: ClickHouseConfig):
    """Create a ClickHouse client from config."""
    return clickhouse_connect.get_client(
        host=config.host,
        port=config.port,
        username=config.username,
        password=config.password,
        database=config.database,
        secure=config.secure,
    )


class RecommendationLogRepository:
    """Repository for logging and querying recommendation events."""

    def __init__(self, config: ClickHouseConfig):
        self.config = config

    def log_recommendation(self, event: RecommendationEvent) -> None:
        """
        Log a recommendation event to ClickHouse.

        Called when recommendations are generated for a customer.
        """
        client = _get_client(self.config)

        try:
            query = """
                INSERT INTO TWCRECOMMENDATION_LOG (
                    eventId,
                    tenantId,
                    customerId,
                    staffId,
                    sessionId,
                    recommendationType,
                    recommendedItems,
                    scores,
                    positions,
                    contextFeatures,
                    modelVersion,
                    weightsConfig,
                    recommendedAt
                ) VALUES
            """

            client.insert(
                "TWCRECOMMENDATION_LOG",
                [[
                    event.event_id,
                    event.tenant_id,
                    event.customer_id,
                    event.staff_id or "",
                    event.session_id or "",
                    event.recommendation_type,
                    event.recommended_items,
                    event.scores,
                    event.positions,
                    json.dumps(event.context_features),
                    event.model_version,
                    event.weights_config or "",
                    event.recommended_at,
                ]],
                column_names=[
                    "eventId", "tenantId", "customerId", "staffId", "sessionId",
                    "recommendationType", "recommendedItems", "scores", "positions",
                    "contextFeatures", "modelVersion", "weightsConfig", "recommendedAt"
                ]
            )
        finally:
            client.close()

    def log_outcome(self, outcome: RecommendationOutcome) -> None:
        """
        Log an outcome/interaction with a recommendation.

        Called when a customer interacts with a recommended product.
        """
        client = _get_client(self.config)

        try:
            client.insert(
                "TWCRECOMMENDATION_OUTCOME",
                [[
                    outcome.event_id,
                    outcome.recommendation_event_id,
                    outcome.tenant_id,
                    outcome.customer_id,
                    outcome.outcome_type,
                    outcome.item_id,
                    outcome.position,
                    outcome.actor,
                    outcome.staff_id or "",
                    outcome.purchase_value,
                    outcome.purchase_order_id or "",
                    outcome.days_to_conversion,
                    outcome.occurred_at,
                ]],
                column_names=[
                    "eventId", "recommendationEventId", "tenantId", "customerId",
                    "outcomeType", "itemId", "position", "actor", "staffId",
                    "purchaseValue", "purchaseOrderId", "daysToConversion", "occurredAt"
                ]
            )
        finally:
            client.close()

    def get_metrics(
        self,
        tenant_id: str,
        model_version: Optional[str] = None,
        weights_config: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> RecommendationMetrics:
        """
        Calculate aggregated metrics for recommendations.

        Used for model evaluation and A/B test analysis.
        """
        client = _get_client(self.config)

        # Default to last 30 days
        if not end_date:
            end_date = datetime.utcnow()
        if not start_date:
            start_date = end_date - timedelta(days=30)

        try:
            # Build filters
            filters = ["tenantId = {tenant_id:String}"]
            params = {"tenant_id": tenant_id, "start_date": start_date, "end_date": end_date}

            if model_version:
                filters.append("modelVersion = {model_version:String}")
                params["model_version"] = model_version

            if weights_config:
                filters.append("weightsConfig = {weights_config:String}")
                params["weights_config"] = weights_config

            filter_clause = " AND ".join(filters)

            # Get recommendation volume metrics
            volume_query = f"""
                SELECT
                    count(*) as total_recommendations,
                    sum(length(recommendedItems)) as total_items,
                    uniq(customerId) as unique_customers
                FROM TWCRECOMMENDATION_LOG
                WHERE {filter_clause}
                  AND recommendedAt >= {{start_date:DateTime}}
                  AND recommendedAt <= {{end_date:DateTime}}
            """

            volume_result = client.query(volume_query, parameters=params)
            volume_row = volume_result.first_row

            total_recommendations = volume_row[0] or 0
            total_items = volume_row[1] or 0
            unique_customers = volume_row[2] or 0

            # Get outcome metrics by joining log and outcomes
            outcome_query = f"""
                SELECT
                    o.outcomeType,
                    count(*) as cnt,
                    sum(o.purchaseValue) as revenue
                FROM TWCRECOMMENDATION_OUTCOME o
                JOIN TWCRECOMMENDATION_LOG l ON o.recommendationEventId = l.eventId
                WHERE l.{filter_clause}
                  AND l.recommendedAt >= {{start_date:DateTime}}
                  AND l.recommendedAt <= {{end_date:DateTime}}
                GROUP BY o.outcomeType
            """

            outcome_result = client.query(outcome_query, parameters=params)

            # Parse outcome counts
            views = 0
            clicks = 0
            cart_adds = 0
            wishlist_adds = 0
            purchases = 0
            total_revenue = 0.0

            for row in outcome_result.result_rows:
                outcome_type, count, revenue = row
                if outcome_type == OutcomeType.VIEWED.value:
                    views = count
                elif outcome_type == OutcomeType.CLICKED.value:
                    clicks = count
                elif outcome_type == OutcomeType.ADDED_TO_CART.value:
                    cart_adds = count
                elif outcome_type == OutcomeType.ADDED_TO_WISHLIST.value:
                    wishlist_adds = count
                elif outcome_type == OutcomeType.PURCHASED.value:
                    purchases = count
                    total_revenue = float(revenue or 0)

            return RecommendationMetrics(
                tenant_id=tenant_id,
                model_version=model_version or "all",
                weights_config=weights_config,
                start_date=start_date,
                end_date=end_date,
                total_recommendations=total_recommendations,
                total_items_recommended=total_items,
                unique_customers=unique_customers,
                total_views=views,
                total_clicks=clicks,
                total_add_to_cart=cart_adds,
                total_add_to_wishlist=wishlist_adds,
                total_purchases=purchases,
                total_revenue=total_revenue,
                avg_order_value=total_revenue / purchases if purchases > 0 else 0.0,
            )
        finally:
            client.close()

    def get_recommendation_history(
        self,
        tenant_id: str,
        customer_id: str,
        limit: int = 10,
    ) -> list[RecommendationEvent]:
        """
        Get recent recommendation events for a customer.

        Useful for debugging and understanding recommendation behavior.
        """
        client = _get_client(self.config)

        try:
            query = """
                SELECT
                    eventId,
                    tenantId,
                    customerId,
                    staffId,
                    sessionId,
                    recommendationType,
                    recommendedItems,
                    scores,
                    positions,
                    contextFeatures,
                    modelVersion,
                    weightsConfig,
                    recommendedAt
                FROM TWCRECOMMENDATION_LOG
                WHERE tenantId = {tenant_id:String}
                  AND customerId = {customer_id:String}
                ORDER BY recommendedAt DESC
                LIMIT {limit:UInt32}
            """

            result = client.query(
                query,
                parameters={
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "limit": limit,
                }
            )

            events = []
            for row in result.result_rows:
                (
                    event_id, tenant_id, customer_id, staff_id, session_id,
                    rec_type, items, scores, positions, context_json,
                    model_version, weights, recommended_at
                ) = row

                try:
                    context = json.loads(context_json) if context_json else {}
                except json.JSONDecodeError:
                    context = {}

                events.append(RecommendationEvent(
                    event_id=event_id,
                    tenant_id=tenant_id,
                    customer_id=customer_id,
                    staff_id=staff_id if staff_id else None,
                    session_id=session_id if session_id else None,
                    recommendation_type=rec_type,
                    recommended_items=list(items),
                    scores=list(scores),
                    positions=list(positions),
                    context_features=context,
                    model_version=model_version,
                    weights_config=weights if weights else None,
                    recommended_at=recommended_at,
                ))

            return events
        finally:
            client.close()

    def get_conversion_by_position(
        self,
        tenant_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> dict[int, dict]:
        """
        Analyze conversion rates by position in recommendation list.

        Helps understand if position bias affects performance.
        Returns dict mapping position -> {impressions, clicks, conversions, ctr, cvr}
        """
        client = _get_client(self.config)

        if not end_date:
            end_date = datetime.utcnow()
        if not start_date:
            start_date = end_date - timedelta(days=30)

        try:
            # Count impressions by position
            impressions_query = """
                SELECT
                    arrayJoin(positions) as position,
                    count(*) as impressions
                FROM TWCRECOMMENDATION_LOG
                WHERE tenantId = {tenant_id:String}
                  AND recommendedAt >= {start_date:DateTime}
                  AND recommendedAt <= {end_date:DateTime}
                GROUP BY position
            """

            impressions_result = client.query(
                impressions_query,
                parameters={
                    "tenant_id": tenant_id,
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )

            impressions_by_position = {row[0]: row[1] for row in impressions_result.result_rows}

            # Count outcomes by position
            outcomes_query = """
                SELECT
                    o.position,
                    o.outcomeType,
                    count(*) as cnt
                FROM TWCRECOMMENDATION_OUTCOME o
                JOIN TWCRECOMMENDATION_LOG l ON o.recommendationEventId = l.eventId
                WHERE l.tenantId = {tenant_id:String}
                  AND l.recommendedAt >= {start_date:DateTime}
                  AND l.recommendedAt <= {end_date:DateTime}
                GROUP BY o.position, o.outcomeType
            """

            outcomes_result = client.query(
                outcomes_query,
                parameters={
                    "tenant_id": tenant_id,
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )

            # Aggregate outcomes by position
            outcomes_by_position: dict[int, dict] = {}
            for row in outcomes_result.result_rows:
                position, outcome_type, count = row
                if position not in outcomes_by_position:
                    outcomes_by_position[position] = {"clicks": 0, "conversions": 0}

                if outcome_type == OutcomeType.CLICKED.value:
                    outcomes_by_position[position]["clicks"] = count
                elif outcome_type == OutcomeType.PURCHASED.value:
                    outcomes_by_position[position]["conversions"] = count

            # Combine into final result
            result = {}
            for position, impressions in impressions_by_position.items():
                outcomes = outcomes_by_position.get(position, {"clicks": 0, "conversions": 0})
                clicks = outcomes["clicks"]
                conversions = outcomes["conversions"]

                result[position] = {
                    "impressions": impressions,
                    "clicks": clicks,
                    "conversions": conversions,
                    "ctr": clicks / impressions if impressions > 0 else 0.0,
                    "cvr": conversions / impressions if impressions > 0 else 0.0,
                }

            return result
        finally:
            client.close()
