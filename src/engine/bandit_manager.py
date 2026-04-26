"""Multi-Armed Bandit Manager using Thompson Sampling.

Provides automatic weight optimization by tracking conversion rates
per weight preset (arm) and selecting arms using Thompson Sampling.
"""

import random
from typing import Optional

import numpy as np

from ..config.clickhouse import ClickHouseConfig
from ..config.weights import RecommendationWeights, DEFAULT_WEIGHTS
from ..data.bandit_repository import BanditRepository
from ..models.bandit import BanditArmStats, BanditConfig, BanditSelection, BanditSummary
from .ab_test_manager import WEIGHT_PRESETS, ABTestManager


class BanditManager:
    """
    Multi-armed bandit for automatic weight optimization.

    Uses Thompson Sampling to balance exploration (trying uncertain arms)
    and exploitation (using arms with good conversion rates).

    Thompson Sampling:
    - Each arm has a Beta distribution: Beta(successes + α, failures + β)
    - Sample from each arm's distribution
    - Pick the arm with the highest sample
    - This naturally explores uncertain arms while exploiting good ones
    """

    def __init__(self, config: ClickHouseConfig):
        self.config = config
        self.repository = BanditRepository(config)
        self.ab_manager = ABTestManager(config)

    def select_arm(
        self,
        tenant_id: str,
        customer_id: Optional[str] = None,
    ) -> Optional[BanditSelection]:
        """
        Select an arm using Thompson Sampling.

        Args:
            tenant_id: The retailer/tenant ID
            customer_id: Optional customer ID (for logging, not used in selection)

        Returns:
            BanditSelection with chosen arm and metadata, or None if bandit is disabled
        """
        bandit_config = self.repository.get_bandit_config(tenant_id)

        if not bandit_config.enabled:
            return None

        if not bandit_config.arms:
            return None

        # Get stats for all configured arms
        arm_stats = {s.arm: s for s in self.repository.get_arm_stats(tenant_id)}

        # Thompson Sampling: sample from each arm's Beta distribution
        samples = {}
        exploration_bonus = bandit_config.exploration_bonus

        for arm in bandit_config.arms:
            stats = arm_stats.get(arm)

            if stats:
                # Beta(successes + prior, failures + prior)
                alpha = stats.successes + exploration_bonus
                beta = stats.failures + exploration_bonus
            else:
                # No data - use prior only (encourages exploration)
                alpha = exploration_bonus
                beta = exploration_bonus

            # Sample from Beta distribution
            samples[arm] = np.random.beta(alpha, beta)

        # Select arm with highest sample
        selected_arm = max(samples, key=lambda x: samples[x])
        sampled_value = samples[selected_arm]

        # Determine if this is exploration (arm has few trials)
        selected_stats = arm_stats.get(selected_arm)
        is_exploration = (
            selected_stats is None or
            selected_stats.total_trials < 100
        )

        return BanditSelection(
            arm=selected_arm,
            sampled_value=sampled_value,
            is_exploration=is_exploration,
        )

    def get_weights_for_arm(self, arm: str, tenant_id: str) -> RecommendationWeights:
        """Get the weights configuration for an arm."""
        return self.ab_manager._get_weights(arm, tenant_id)

    def record_impression(self, tenant_id: str, arm: str) -> None:
        """Record that an arm was shown (impression)."""
        self.repository.increment_arm_impression(tenant_id, arm)

    def record_conversion(self, tenant_id: str, arm: str) -> None:
        """Record a conversion for an arm."""
        self.repository.record_conversion(tenant_id, arm)

    def get_summary(self, tenant_id: str) -> BanditSummary:
        """Get a summary of bandit state for a tenant."""
        config = self.repository.get_bandit_config(tenant_id)
        arm_stats = self.repository.get_arm_stats(tenant_id)

        # Find best arm
        best_arm = None
        best_cvr = 0.0
        total_impressions = 0

        for stats in arm_stats:
            total_impressions += stats.impressions
            if stats.conversion_rate > best_cvr:
                best_cvr = stats.conversion_rate
                best_arm = stats.arm

        return BanditSummary(
            tenant_id=tenant_id,
            enabled=config.enabled,
            arms=arm_stats,
            total_impressions=total_impressions,
            best_arm=best_arm,
            best_conversion_rate=best_cvr,
        )

    def sync_stats_from_logs(self, tenant_id: str, days_back: int = 30) -> dict:
        """
        Sync bandit stats from recommendation logs.

        Useful for initializing bandit with historical data
        or recovering from data loss.

        Returns dict of arm -> (successes, failures, impressions)
        """
        config = self.repository.get_bandit_config(tenant_id)
        results = {}

        for arm in config.arms:
            successes, failures, impressions = self.repository.get_stats_from_logs(
                tenant_id, arm, days_back
            )

            if impressions > 0:
                self.repository.update_arm_stats(
                    tenant_id=tenant_id,
                    arm=arm,
                    successes=successes,
                    failures=failures,
                    impressions=impressions,
                )

            results[arm] = {
                "successes": successes,
                "failures": failures,
                "impressions": impressions,
            }

        return results

    def is_enabled(self, tenant_id: str) -> bool:
        """Check if bandit is enabled for a tenant."""
        config = self.repository.get_bandit_config(tenant_id)
        return config.enabled

    def enable(self, tenant_id: str) -> None:
        """Enable bandit for a tenant."""
        self.repository.set_bandit_enabled(tenant_id, True)

    def disable(self, tenant_id: str) -> None:
        """Disable bandit for a tenant."""
        self.repository.set_bandit_enabled(tenant_id, False)

    def set_arms(self, tenant_id: str, arms: list[str]) -> None:
        """Set which arms to use for a tenant."""
        self.repository.set_bandit_arms(tenant_id, arms)

    def reset_stats(self, tenant_id: str, arm: Optional[str] = None) -> None:
        """Reset statistics for an arm or all arms."""
        self.repository.reset_arm_stats(tenant_id, arm)
