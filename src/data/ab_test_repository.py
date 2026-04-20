"""ClickHouse repository for A/B test management.

Handles CRUD operations for A/B tests and tenant configuration,
as well as metrics queries for test analysis.
"""
from datetime import datetime, timedelta
from typing import Optional

import clickhouse_connect

from ..config.clickhouse import ClickHouseConfig
from ..config.weights import RecommendationWeights
from ..models.ab_test import (
    ABTestConfig,
    ABTestMetrics,
    TenantWeights,
    TenantConfig,
    WeightPreset,
)
from ..models.logging import OutcomeType


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


class ABTestRepository:
    """Repository for A/B test configuration and metrics."""

    def __init__(self, config: ClickHouseConfig):
        self.config = config

    # ==================== A/B Test CRUD ====================

    def get_active_tests(self, tenant_id: str) -> list[ABTestConfig]:
        """Get all active A/B tests for a tenant."""
        client = _get_client(self.config)

        try:
            query = """
                SELECT
                    testId,
                    tenantId,
                    name,
                    description,
                    controlWeights,
                    treatmentWeights,
                    trafficPercentage,
                    startDate,
                    endDate,
                    isActive,
                    createdAt,
                    updatedAt
                FROM TWCAB_TEST FINAL
                WHERE tenantId = {tenant_id:String}
                  AND isActive = 1
                  AND (endDate IS NULL OR endDate > now())
                ORDER BY startDate DESC
            """

            result = client.query(query, parameters={"tenant_id": tenant_id})

            tests = []
            for row in result.result_rows:
                (
                    test_id, tenant_id, name, description, control_weights,
                    treatment_weights, traffic_percentage, start_date, end_date,
                    is_active, created_at, updated_at
                ) = row

                tests.append(ABTestConfig(
                    test_id=test_id,
                    tenant_id=tenant_id,
                    name=name,
                    description=description or "",
                    control_weights=control_weights,
                    treatment_weights=treatment_weights,
                    traffic_percentage=traffic_percentage,
                    start_date=start_date,
                    end_date=end_date,
                    is_active=bool(is_active),
                    created_at=created_at,
                    updated_at=updated_at,
                ))

            return tests
        finally:
            client.close()

    def get_active_tests_all(self) -> list[ABTestConfig]:
        """Get all active A/B tests across all tenants."""
        client = _get_client(self.config)

        try:
            query = """
                SELECT
                    testId,
                    tenantId,
                    name,
                    description,
                    controlWeights,
                    treatmentWeights,
                    trafficPercentage,
                    startDate,
                    endDate,
                    isActive,
                    createdAt,
                    updatedAt
                FROM TWCAB_TEST FINAL
                WHERE isActive = 1
                  AND (endDate IS NULL OR endDate > now())
                ORDER BY tenantId, startDate DESC
            """

            result = client.query(query)

            tests = []
            for row in result.result_rows:
                (
                    test_id, tenant_id, name, description, control_weights,
                    treatment_weights, traffic_percentage, start_date, end_date,
                    is_active, created_at, updated_at
                ) = row

                tests.append(ABTestConfig(
                    test_id=test_id,
                    tenant_id=tenant_id,
                    name=name,
                    description=description or "",
                    control_weights=control_weights,
                    treatment_weights=treatment_weights,
                    traffic_percentage=traffic_percentage,
                    start_date=start_date,
                    end_date=end_date,
                    is_active=bool(is_active),
                    created_at=created_at,
                    updated_at=updated_at,
                ))

            return tests
        finally:
            client.close()

    def get_test(self, test_id: str) -> Optional[ABTestConfig]:
        """Get a single A/B test by ID."""
        client = _get_client(self.config)

        try:
            query = """
                SELECT
                    testId,
                    tenantId,
                    name,
                    description,
                    controlWeights,
                    treatmentWeights,
                    trafficPercentage,
                    startDate,
                    endDate,
                    isActive,
                    createdAt,
                    updatedAt
                FROM TWCAB_TEST FINAL
                WHERE testId = {test_id:String}
            """

            result = client.query(query, parameters={"test_id": test_id})

            if not result.result_rows:
                return None

            row = result.first_row
            (
                test_id, tenant_id, name, description, control_weights,
                treatment_weights, traffic_percentage, start_date, end_date,
                is_active, created_at, updated_at
            ) = row

            return ABTestConfig(
                test_id=test_id,
                tenant_id=tenant_id,
                name=name,
                description=description or "",
                control_weights=control_weights,
                treatment_weights=treatment_weights,
                traffic_percentage=traffic_percentage,
                start_date=start_date,
                end_date=end_date,
                is_active=bool(is_active),
                created_at=created_at,
                updated_at=updated_at,
            )
        finally:
            client.close()

    def create_test(self, config: ABTestConfig) -> ABTestConfig:
        """Create a new A/B test."""
        client = _get_client(self.config)

        try:
            client.insert(
                "TWCAB_TEST",
                [[
                    config.test_id,
                    config.tenant_id,
                    config.name,
                    config.description,
                    config.control_weights,
                    config.treatment_weights,
                    config.traffic_percentage,
                    config.start_date,
                    config.end_date,
                    1 if config.is_active else 0,
                    config.created_at,
                    config.updated_at,
                ]],
                column_names=[
                    "testId", "tenantId", "name", "description",
                    "controlWeights", "treatmentWeights", "trafficPercentage",
                    "startDate", "endDate", "isActive", "createdAt", "updatedAt"
                ]
            )
            return config
        finally:
            client.close()

    def end_test(self, test_id: str, winner: Optional[str] = None) -> None:
        """End an A/B test by setting is_active to false and end_date to now."""
        client = _get_client(self.config)

        try:
            # Get current test to preserve other fields
            test = self.get_test(test_id)
            if not test:
                return

            # Insert updated row (ReplacingMergeTree will handle deduplication)
            client.insert(
                "TWCAB_TEST",
                [[
                    test.test_id,
                    test.tenant_id,
                    test.name,
                    test.description,
                    test.control_weights,
                    test.treatment_weights,
                    test.traffic_percentage,
                    test.start_date,
                    datetime.utcnow(),  # end_date
                    0,  # is_active = false
                    test.created_at,
                    datetime.utcnow(),  # updated_at
                ]],
                column_names=[
                    "testId", "tenantId", "name", "description",
                    "controlWeights", "treatmentWeights", "trafficPercentage",
                    "startDate", "endDate", "isActive", "createdAt", "updatedAt"
                ]
            )
        finally:
            client.close()

    def update_test(
        self,
        test_id: str,
        is_active: Optional[bool] = None,
        traffic_percentage: Optional[float] = None,
        end_date: Optional[datetime] = None,
    ) -> Optional[ABTestConfig]:
        """Update an A/B test."""
        client = _get_client(self.config)

        try:
            test = self.get_test(test_id)
            if not test:
                return None

            # Apply updates
            if is_active is not None:
                test.is_active = is_active
            if traffic_percentage is not None:
                test.traffic_percentage = traffic_percentage
            if end_date is not None:
                test.end_date = end_date

            test.updated_at = datetime.utcnow()

            # Insert updated row
            client.insert(
                "TWCAB_TEST",
                [[
                    test.test_id,
                    test.tenant_id,
                    test.name,
                    test.description,
                    test.control_weights,
                    test.treatment_weights,
                    test.traffic_percentage,
                    test.start_date,
                    test.end_date,
                    1 if test.is_active else 0,
                    test.created_at,
                    test.updated_at,
                ]],
                column_names=[
                    "testId", "tenantId", "name", "description",
                    "controlWeights", "treatmentWeights", "trafficPercentage",
                    "startDate", "endDate", "isActive", "createdAt", "updatedAt"
                ]
            )

            return test
        finally:
            client.close()

    # ==================== A/B Test Metrics ====================

    def get_test_metrics(
        self,
        test_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> tuple[ABTestMetrics, ABTestMetrics]:
        """
        Get metrics for both variants of an A/B test.

        Returns (control_metrics, treatment_metrics).
        """
        test = self.get_test(test_id)
        if not test:
            raise ValueError(f"Test {test_id} not found")

        # Use test dates if not specified
        if not start_date:
            start_date = test.start_date
        if not end_date:
            end_date = test.end_date or datetime.utcnow()

        control = self._get_variant_metrics(
            test.tenant_id,
            test_id,
            "control",
            test.control_weights,
            start_date,
            end_date,
        )

        treatment = self._get_variant_metrics(
            test.tenant_id,
            test_id,
            "treatment",
            test.treatment_weights,
            start_date,
            end_date,
        )

        return control, treatment

    def _get_variant_metrics(
        self,
        tenant_id: str,
        test_id: str,
        variant: str,
        weights_config: str,
        start_date: datetime,
        end_date: datetime,
    ) -> ABTestMetrics:
        """Get metrics for a single variant."""
        client = _get_client(self.config)

        try:
            # Get recommendation volume
            volume_query = """
                SELECT
                    count(*) as total_recommendations,
                    uniq(customerId) as unique_customers
                FROM TWCRECOMMENDATION_LOG
                WHERE tenantId = {tenant_id:String}
                  AND abTestId = {test_id:String}
                  AND abTestVariant = {variant:String}
                  AND recommendedAt >= {start_date:DateTime}
                  AND recommendedAt <= {end_date:DateTime}
            """

            volume_result = client.query(
                volume_query,
                parameters={
                    "tenant_id": tenant_id,
                    "test_id": test_id,
                    "variant": variant,
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )

            volume_row = volume_result.first_row
            total_recommendations = volume_row[0] or 0
            unique_customers = volume_row[1] or 0

            # Get outcome metrics
            outcome_query = """
                SELECT
                    o.outcomeType,
                    count(*) as cnt,
                    sum(o.purchaseValue) as revenue
                FROM TWCRECOMMENDATION_OUTCOME o
                JOIN TWCRECOMMENDATION_LOG l ON o.recommendationEventId = l.eventId
                WHERE l.tenantId = {tenant_id:String}
                  AND l.abTestId = {test_id:String}
                  AND l.abTestVariant = {variant:String}
                  AND l.recommendedAt >= {start_date:DateTime}
                  AND l.recommendedAt <= {end_date:DateTime}
                  AND o.actor = 'customer'  -- Exclude staff-initiated outcomes
                GROUP BY o.outcomeType
            """

            outcome_result = client.query(
                outcome_query,
                parameters={
                    "tenant_id": tenant_id,
                    "test_id": test_id,
                    "variant": variant,
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )

            clicks = 0
            cart_adds = 0
            wishlist_adds = 0
            purchases = 0
            total_revenue = 0.0

            for row in outcome_result.result_rows:
                outcome_type, count, revenue = row
                if outcome_type == OutcomeType.CLICKED.value:
                    clicks = count
                elif outcome_type == OutcomeType.ADDED_TO_CART.value:
                    cart_adds = count
                elif outcome_type == OutcomeType.ADDED_TO_WISHLIST.value:
                    wishlist_adds = count
                elif outcome_type == OutcomeType.PURCHASED.value:
                    purchases = count
                    total_revenue = float(revenue or 0)

            return ABTestMetrics(
                variant=variant,
                weights_config=weights_config,
                total_recommendations=total_recommendations,
                unique_customers=unique_customers,
                total_clicks=clicks,
                total_add_to_cart=cart_adds,
                total_add_to_wishlist=wishlist_adds,
                total_purchases=purchases,
                total_revenue=total_revenue,
            )
        finally:
            client.close()

    # ==================== Tenant Weights ====================

    def get_tenant_weights(self, tenant_id: str) -> Optional[TenantWeights]:
        """Get the current best weights for a tenant."""
        client = _get_client(self.config)

        try:
            query = """
                SELECT
                    tenantId,
                    weightsPreset,
                    updatedAt,
                    updatedBy,
                    previousPreset
                FROM TWCTENANT_WEIGHTS FINAL
                WHERE tenantId = {tenant_id:String}
            """

            result = client.query(query, parameters={"tenant_id": tenant_id})

            if not result.result_rows:
                return None

            row = result.first_row
            return TenantWeights(
                tenant_id=row[0],
                weights_preset=row[1],
                updated_at=row[2],
                updated_by=row[3] or "",
                previous_preset=row[4] or "",
            )
        finally:
            client.close()

    def set_tenant_weights(
        self,
        tenant_id: str,
        weights_preset: str,
        updated_by: str = "auto",
    ) -> TenantWeights:
        """Set the current best weights for a tenant."""
        client = _get_client(self.config)

        try:
            # Get previous preset for rollback tracking
            current = self.get_tenant_weights(tenant_id)
            previous_preset = current.weights_preset if current else ""

            tenant_weights = TenantWeights(
                tenant_id=tenant_id,
                weights_preset=weights_preset,
                updated_at=datetime.utcnow(),
                updated_by=updated_by,
                previous_preset=previous_preset,
            )

            client.insert(
                "TWCTENANT_WEIGHTS",
                [[
                    tenant_weights.tenant_id,
                    tenant_weights.weights_preset,
                    tenant_weights.updated_at,
                    tenant_weights.updated_by,
                    tenant_weights.previous_preset,
                ]],
                column_names=[
                    "tenantId", "weightsPreset", "updatedAt", "updatedBy", "previousPreset"
                ]
            )

            return tenant_weights
        finally:
            client.close()

    # ==================== Tenant Config ====================

    def get_tenant_config(self, tenant_id: str) -> TenantConfig:
        """Get A/B testing configuration for a tenant."""
        client = _get_client(self.config)

        try:
            # Get tenant-specific config, falling back to defaults
            query = """
                SELECT key, value
                FROM TWCTENANT_CONFIG FINAL
                WHERE tenantId IN ({tenant_id:String}, '__default__')
                ORDER BY tenantId = '__default__' ASC  -- Tenant-specific overrides defaults
            """

            result = client.query(query, parameters={"tenant_id": tenant_id})

            # Build config from key-value pairs
            config_dict = {}
            for row in result.result_rows:
                key, value = row
                config_dict[key] = value

            return TenantConfig(
                tenant_id=tenant_id,
                auto_promote_enabled=config_dict.get("AUTO_PROMOTE_ENABLED", "true").lower() == "true",
                auto_start_new_tests=config_dict.get("AUTO_START_NEW_TESTS", "true").lower() == "true",
                min_samples_for_significance=int(config_dict.get("MIN_SAMPLES_FOR_SIGNIFICANCE", "1000")),
                p_value_threshold=float(config_dict.get("P_VALUE_THRESHOLD", "0.05")),
                min_lift_for_promotion=float(config_dict.get("MIN_LIFT_FOR_PROMOTION", "0.05")),
                new_test_traffic_percentage=int(config_dict.get("NEW_TEST_TRAFFIC_PERCENTAGE", "20")),
            )
        finally:
            client.close()

    def set_tenant_config(self, tenant_id: str, key: str, value: str) -> None:
        """Set a single configuration value for a tenant."""
        client = _get_client(self.config)

        try:
            client.insert(
                "TWCTENANT_CONFIG",
                [[tenant_id, key, value, datetime.utcnow()]],
                column_names=["tenantId", "key", "value", "updatedAt"]
            )
        finally:
            client.close()

    # ==================== Weight Presets ====================

    def get_weight_preset(
        self,
        preset_name: str,
        tenant_id: str = "__global__",
    ) -> Optional[WeightPreset]:
        """Get a weight preset by name."""
        client = _get_client(self.config)

        try:
            query = """
                SELECT
                    presetName,
                    tenantId,
                    preferenceCategory,
                    preferenceColor,
                    preferenceFabric,
                    preferenceStyle,
                    preferenceBrand,
                    purchaseHistoryCategory,
                    purchaseHistoryBrand,
                    purchaseHistoryColor,
                    wishlistSimilarity,
                    browsingViewedCategory,
                    browsingViewedBrand,
                    browsingCartSimilarity,
                    productPopularity,
                    newArrivalBoost,
                    sizeMatchBoost,
                    customerSourceMultiplier,
                    staffSourceMultiplier,
                    inStockRequirement,
                    createdAt,
                    createdBy
                FROM TWCWEIGHT_PRESETS FINAL
                WHERE presetName = {preset_name:String}
                  AND tenantId IN ({tenant_id:String}, '__global__')
                ORDER BY tenantId = '__global__' ASC  -- Tenant-specific overrides global
                LIMIT 1
            """

            result = client.query(
                query,
                parameters={"preset_name": preset_name, "tenant_id": tenant_id}
            )

            if not result.result_rows:
                return None

            row = result.first_row
            return WeightPreset(
                preset_name=row[0],
                tenant_id=row[1],
                weights=RecommendationWeights(
                    preference_category=row[2],
                    preference_color=row[3],
                    preference_fabric=row[4],
                    preference_style=row[5],
                    preference_brand=row[6],
                    purchase_history_category=row[7],
                    purchase_history_brand=row[8],
                    purchase_history_color=row[9],
                    wishlist_similarity=row[10],
                    browsing_viewed_category=row[11],
                    browsing_viewed_brand=row[12],
                    browsing_cart_similarity=row[13],
                    product_popularity=row[14],
                    new_arrival_boost=row[15],
                    size_match_boost=row[16],
                    customer_source_multiplier=row[17],
                    staff_source_multiplier=row[18],
                    in_stock_requirement=bool(row[19]),
                ),
                created_at=row[20],
                created_by=row[21] or "",
            )
        finally:
            client.close()

    def save_weight_preset(self, preset: WeightPreset) -> WeightPreset:
        """Save a weight preset."""
        client = _get_client(self.config)

        try:
            client.insert(
                "TWCWEIGHT_PRESETS",
                [[
                    preset.preset_name,
                    preset.tenant_id,
                    preset.weights.preference_category,
                    preset.weights.preference_color,
                    preset.weights.preference_fabric,
                    preset.weights.preference_style,
                    preset.weights.preference_brand,
                    preset.weights.purchase_history_category,
                    preset.weights.purchase_history_brand,
                    preset.weights.purchase_history_color,
                    preset.weights.wishlist_similarity,
                    preset.weights.browsing_viewed_category,
                    preset.weights.browsing_viewed_brand,
                    preset.weights.browsing_cart_similarity,
                    preset.weights.product_popularity,
                    preset.weights.new_arrival_boost,
                    preset.weights.size_match_boost,
                    preset.weights.customer_source_multiplier,
                    preset.weights.staff_source_multiplier,
                    1 if preset.weights.in_stock_requirement else 0,
                    preset.created_at,
                    preset.created_by,
                ]],
                column_names=[
                    "presetName", "tenantId",
                    "preferenceCategory", "preferenceColor", "preferenceFabric",
                    "preferenceStyle", "preferenceBrand",
                    "purchaseHistoryCategory", "purchaseHistoryBrand", "purchaseHistoryColor",
                    "wishlistSimilarity",
                    "browsingViewedCategory", "browsingViewedBrand", "browsingCartSimilarity",
                    "productPopularity", "newArrivalBoost", "sizeMatchBoost",
                    "customerSourceMultiplier", "staffSourceMultiplier", "inStockRequirement",
                    "createdAt", "createdBy"
                ]
            )

            return preset
        finally:
            client.close()
