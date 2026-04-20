"""A/B Test Analyzer for statistical analysis and auto-promotion.

Provides statistical analysis of A/B test results and automatic
promotion of winning variants with new test generation.
"""
import random
import uuid
from datetime import datetime
from typing import Optional

from scipy import stats

from ..config.clickhouse import ClickHouseConfig
from ..config.weights import RecommendationWeights
from ..data.ab_test_repository import ABTestRepository
from ..models.ab_test import (
    ABTestConfig,
    ABTestResults,
    ABTestMetrics,
    WeightPreset,
    TenantConfig,
)


# Weight dimensions that can be varied in auto-generated tests
VARIABLE_DIMENSIONS = [
    "preference_category",
    "preference_color",
    "preference_style",
    "preference_brand",
    "purchase_history_category",
    "purchase_history_brand",
    "wishlist_similarity",
    "browsing_viewed_category",
    "browsing_cart_similarity",
    "product_popularity",
    "new_arrival_boost",
]


class ABTestAnalyzer:
    """
    Analyzes A/B test results and handles auto-promotion.

    Calculates statistical significance using chi-squared tests
    and automatically promotes winners while generating new test
    variations.
    """

    def __init__(self, config: ClickHouseConfig):
        self.config = config
        self.repository = ABTestRepository(config)

    def analyze_test(self, test_id: str) -> ABTestResults:
        """
        Calculate metrics and statistical significance for an A/B test.

        Args:
            test_id: The ID of the test to analyze

        Returns:
            ABTestResults with metrics, significance, and recommendation
        """
        test = self.repository.get_test(test_id)
        if not test:
            raise ValueError(f"Test {test_id} not found")

        control, treatment = self.repository.get_test_metrics(test_id)
        tenant_config = self.repository.get_tenant_config(test.tenant_id)

        # Calculate lift
        control_cvr = control.conversion_rate
        treatment_cvr = treatment.conversion_rate

        if control_cvr > 0:
            lift = (treatment_cvr - control_cvr) / control_cvr
        else:
            lift = 0.0 if treatment_cvr == 0 else float('inf')

        # Calculate statistical significance using chi-squared test
        p_value = self._calculate_significance(control, treatment)

        # Check if we have enough samples
        total_samples = control.total_recommendations + treatment.total_recommendations
        has_enough_samples = total_samples >= tenant_config.min_samples_for_significance

        # Determine if significant
        is_significant = (
            has_enough_samples and
            p_value < tenant_config.p_value_threshold
        )

        # Recommend action
        recommended_action, recommended_weights = self._recommend_action(
            control=control,
            treatment=treatment,
            lift=lift,
            is_significant=is_significant,
            has_enough_samples=has_enough_samples,
            tenant_config=tenant_config,
            test=test,
        )

        # Calculate days running
        days_running = (datetime.utcnow() - test.start_date).days

        return ABTestResults(
            test_id=test.test_id,
            test_name=test.name,
            tenant_id=test.tenant_id,
            control=control,
            treatment=treatment,
            lift=lift,
            p_value=p_value,
            is_significant=is_significant,
            confidence_level=1 - p_value,
            total_samples=total_samples,
            has_enough_samples=has_enough_samples,
            min_samples_required=tenant_config.min_samples_for_significance,
            recommended_action=recommended_action,
            recommended_weights=recommended_weights,
            start_date=test.start_date,
            end_date=test.end_date,
            days_running=days_running,
        )

    def _calculate_significance(
        self,
        control: ABTestMetrics,
        treatment: ABTestMetrics,
    ) -> float:
        """
        Calculate p-value using chi-squared test.

        Compares conversion rates between control and treatment.
        """
        # Create contingency table
        # [[control_conversions, control_non_conversions],
        #  [treatment_conversions, treatment_non_conversions]]
        control_conversions = control.total_purchases
        control_non_conversions = control.total_recommendations - control_conversions
        treatment_conversions = treatment.total_purchases
        treatment_non_conversions = treatment.total_recommendations - treatment_conversions

        # Handle edge cases
        if (control.total_recommendations == 0 or
            treatment.total_recommendations == 0):
            return 1.0  # Not significant - need more data

        if control_conversions + treatment_conversions == 0:
            return 1.0  # No conversions at all - can't compare

        contingency_table = [
            [control_conversions, control_non_conversions],
            [treatment_conversions, treatment_non_conversions],
        ]

        try:
            chi2, p_value, dof, expected = stats.chi2_contingency(contingency_table)
            return p_value
        except ValueError:
            # Stats library may raise if expected frequencies are too low
            return 1.0

    def _recommend_action(
        self,
        control: ABTestMetrics,
        treatment: ABTestMetrics,
        lift: float,
        is_significant: bool,
        has_enough_samples: bool,
        tenant_config: TenantConfig,
        test: ABTestConfig,
    ) -> tuple[str, Optional[str]]:
        """
        Determine recommended action based on test results.

        Returns:
            Tuple of (action, weights_to_promote)
            action: "promote_treatment", "keep_control", or "continue_test"
        """
        if not has_enough_samples:
            return "continue_test", None

        if not is_significant:
            return "continue_test", None

        # Significant result - determine winner
        if lift >= tenant_config.min_lift_for_promotion:
            # Treatment wins
            return "promote_treatment", test.treatment_weights
        elif lift <= -tenant_config.min_lift_for_promotion:
            # Control wins (treatment significantly worse)
            return "keep_control", test.control_weights
        else:
            # Significant but lift below threshold - keep control
            return "keep_control", test.control_weights

    def auto_promote_and_iterate(self) -> list[dict]:
        """
        Check all active tests and promote winners.

        This is the main scheduled job entry point.

        Flow:
        1. Check if test has enough samples and is significant
        2. Promote winner as new default
        3. Generate variation of winner for next test (if enabled)
        4. Start new test: winner vs variation

        Returns:
            List of actions taken (for logging/reporting)
        """
        actions = []

        for test in self.repository.get_active_tests_all():
            try:
                action = self._process_test(test)
                if action:
                    actions.append(action)
            except Exception as e:
                actions.append({
                    "test_id": test.test_id,
                    "tenant_id": test.tenant_id,
                    "action": "error",
                    "error": str(e),
                })

        return actions

    def _process_test(self, test: ABTestConfig) -> Optional[dict]:
        """Process a single test for potential promotion."""
        tenant_config = self.repository.get_tenant_config(test.tenant_id)

        # Skip if auto-promote is disabled for this tenant
        if not tenant_config.auto_promote_enabled:
            return None

        results = self.analyze_test(test.test_id)

        if not results.has_enough_samples:
            return None  # Need more data

        if not results.is_significant:
            return None  # Not ready to make a decision

        # Determine winner
        if results.recommended_action == "promote_treatment":
            winner_weights = test.treatment_weights
        elif results.recommended_action == "keep_control":
            winner_weights = test.control_weights
        else:
            return None  # No action needed

        action_log = {
            "test_id": test.test_id,
            "tenant_id": test.tenant_id,
            "action": results.recommended_action,
            "winner_weights": winner_weights,
            "lift": results.lift,
            "p_value": results.p_value,
        }

        # 1. Update default weights for this tenant
        self.repository.set_tenant_weights(
            tenant_id=test.tenant_id,
            weights_preset=winner_weights,
            updated_by="auto",
        )

        # 2. End current test
        self.repository.end_test(test.test_id, winner=winner_weights)

        # 3. Generate variation and start new test (if enabled)
        if tenant_config.auto_start_new_tests:
            new_test = self._create_next_test(
                test=test,
                winner_weights=winner_weights,
                traffic_percentage=tenant_config.new_test_traffic_percentage,
            )
            if new_test:
                action_log["new_test_id"] = new_test.test_id
                action_log["new_treatment_weights"] = new_test.treatment_weights

        return action_log

    def _create_next_test(
        self,
        test: ABTestConfig,
        winner_weights: str,
        traffic_percentage: int,
    ) -> Optional[ABTestConfig]:
        """Create the next iteration test with a variation of the winner."""
        # Generate variation of winner
        variation_name = self._generate_variation(winner_weights, test.tenant_id)
        if not variation_name:
            return None

        # Create new test
        new_test = ABTestConfig(
            tenant_id=test.tenant_id,
            name=f"auto_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            description=f"Auto-generated: {winner_weights} vs {variation_name}",
            control_weights=winner_weights,
            treatment_weights=variation_name,
            traffic_percentage=float(traffic_percentage),
            is_active=True,
        )

        return self.repository.create_test(new_test)

    def _generate_variation(
        self,
        winner_weights: str,
        tenant_id: str,
    ) -> Optional[str]:
        """
        Generate a variation of the winning weights for the next test.

        Strategy: Perturb 2-3 weight dimensions by +/-10-20%
        """
        # Get base weights
        from .ab_test_manager import ABTestManager
        manager = ABTestManager(self.config)
        base_weights = manager._get_weights(winner_weights, tenant_id)

        # Convert to dict for manipulation
        weights_dict = base_weights.model_dump()

        # Pick 2-3 dimensions to vary
        num_dimensions = random.randint(2, 3)
        dimensions_to_vary = random.sample(VARIABLE_DIMENSIONS, num_dimensions)

        # Apply variations
        for dim in dimensions_to_vary:
            current = weights_dict[dim]
            # Randomly increase or decrease by 10-20%
            adjustment = random.uniform(0.10, 0.20) * random.choice([-1, 1])
            new_value = current * (1 + adjustment)
            # Clamp to valid range [0, 1]
            weights_dict[dim] = max(0.0, min(1.0, new_value))

        # Create new weights
        variation_weights = RecommendationWeights(**weights_dict)

        # Save as new preset
        variation_name = f"{winner_weights}_var_{uuid.uuid4().hex[:6]}"
        preset = WeightPreset(
            preset_name=variation_name,
            tenant_id=tenant_id,
            weights=variation_weights,
            created_by="auto",
        )

        self.repository.save_weight_preset(preset)
        manager.clear_weights_cache()

        return variation_name

    def get_test_summary(self, tenant_id: str) -> list[dict]:
        """
        Get a summary of all tests for a tenant.

        Returns list of test summaries with current status.
        """
        active_tests = self.repository.get_active_tests(tenant_id)
        summaries = []

        for test in active_tests:
            try:
                results = self.analyze_test(test.test_id)
                summaries.append({
                    "test_id": test.test_id,
                    "name": test.name,
                    "status": "active",
                    "control_weights": test.control_weights,
                    "treatment_weights": test.treatment_weights,
                    "control_cvr": results.control.conversion_rate,
                    "treatment_cvr": results.treatment.conversion_rate,
                    "lift": results.lift,
                    "p_value": results.p_value,
                    "is_significant": results.is_significant,
                    "total_samples": results.total_samples,
                    "days_running": results.days_running,
                    "recommended_action": results.recommended_action,
                })
            except Exception as e:
                summaries.append({
                    "test_id": test.test_id,
                    "name": test.name,
                    "status": "error",
                    "error": str(e),
                })

        return summaries
