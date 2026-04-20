"""A/B Test Manager for variant assignment.

Handles deterministic assignment of customers to A/B test variants
and provides the appropriate weights configuration for each variant.
"""
import hashlib
from typing import Optional

from ..config.clickhouse import ClickHouseConfig
from ..config.weights import (
    RecommendationWeights,
    DEFAULT_WEIGHTS,
    PREFERENCE_HEAVY_WEIGHTS,
    BEHAVIOR_HEAVY_WEIGHTS,
    NEW_CUSTOMER_WEIGHTS,
)
from ..data.ab_test_repository import ABTestRepository
from ..models.ab_test import ABTestAssignment, ABTestConfig


# Built-in weight presets
WEIGHT_PRESETS: dict[str, RecommendationWeights] = {
    "default": DEFAULT_WEIGHTS,
    "preference_heavy": PREFERENCE_HEAVY_WEIGHTS,
    "behavior_heavy": BEHAVIOR_HEAVY_WEIGHTS,
    "new_customer": NEW_CUSTOMER_WEIGHTS,
}


class ABTestManager:
    """
    Manages A/B test variant assignment for customers.

    Uses deterministic hashing to ensure the same customer always
    sees the same variant during a test.
    """

    def __init__(self, config: ClickHouseConfig):
        self.config = config
        self.repository = ABTestRepository(config)
        self._weights_cache: dict[str, RecommendationWeights] = {}

    def assign_variant(
        self,
        tenant_id: str,
        customer_id: str,
    ) -> Optional[ABTestAssignment]:
        """
        Deterministically assign a customer to an A/B test variant.

        Uses hash(customer_id + test_id) % 100 for consistent assignment.
        Returns None if there are no active tests for the tenant.

        Args:
            tenant_id: The retailer/tenant ID
            customer_id: The customer being assigned

        Returns:
            ABTestAssignment with test info and weights, or None if no active test
        """
        active_tests = self.repository.get_active_tests(tenant_id)
        if not active_tests:
            return None

        # Use the first active test (one active test per tenant at a time)
        test = active_tests[0]

        # Deterministic hash for consistent assignment
        hash_input = f"{customer_id}:{test.test_id}"
        hash_bytes = hashlib.sha256(hash_input.encode()).digest()
        hash_value = int.from_bytes(hash_bytes[:4], byteorder='big') % 100

        # Assign to treatment if hash is less than traffic percentage
        if hash_value < test.traffic_percentage:
            variant = "treatment"
            weights_name = test.treatment_weights
        else:
            variant = "control"
            weights_name = test.control_weights

        # Get weights for the variant
        weights = self._get_weights(weights_name, tenant_id)

        return ABTestAssignment(
            test_id=test.test_id,
            test_name=test.name,
            variant=variant,
            weights=weights,
            weights_name=weights_name,
        )

    def _get_weights(
        self,
        weights_name: str,
        tenant_id: str,
    ) -> RecommendationWeights:
        """
        Get weights by preset name.

        First checks built-in presets, then looks up custom presets
        from the database.

        Args:
            weights_name: Name of the weights preset
            tenant_id: Tenant ID for custom preset lookup

        Returns:
            RecommendationWeights for the preset, or default if not found
        """
        # Check cache first
        cache_key = f"{tenant_id}:{weights_name}"
        if cache_key in self._weights_cache:
            return self._weights_cache[cache_key]

        # Check built-in presets
        if weights_name in WEIGHT_PRESETS:
            weights = WEIGHT_PRESETS[weights_name]
            self._weights_cache[cache_key] = weights
            return weights

        # Look up custom preset from database
        preset = self.repository.get_weight_preset(weights_name, tenant_id)
        if preset:
            self._weights_cache[cache_key] = preset.weights
            return preset.weights

        # Fall back to default
        return DEFAULT_WEIGHTS

    def get_tenant_default_weights(
        self,
        tenant_id: str,
    ) -> tuple[str, RecommendationWeights]:
        """
        Get the current best weights for a tenant.

        Returns the auto-promoted winner from completed A/B tests,
        or the system default if no custom weights are set.

        Args:
            tenant_id: The retailer/tenant ID

        Returns:
            Tuple of (weights_name, weights)
        """
        tenant_weights = self.repository.get_tenant_weights(tenant_id)

        if tenant_weights:
            weights = self._get_weights(tenant_weights.weights_preset, tenant_id)
            return tenant_weights.weights_preset, weights

        return "default", DEFAULT_WEIGHTS

    def clear_weights_cache(self) -> None:
        """Clear the weights cache. Call after saving new presets."""
        self._weights_cache.clear()
