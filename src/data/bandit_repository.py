"""Repository for multi-armed bandit statistics."""

from typing import Optional
import clickhouse_connect

from ..config.clickhouse import ClickHouseConfig
from ..models.bandit import BanditArmStats, BanditConfig


class BanditRepository:
    """Repository for bandit arm statistics and configuration."""

    def __init__(self, config: ClickHouseConfig):
        self.client = clickhouse_connect.get_client(
            host=config.host,
            port=config.port,
            username=config.username,
            password=config.password,
            database=config.database,
        )

    def get_arm_stats(self, tenant_id: str) -> list[BanditArmStats]:
        """Get all arm statistics for a tenant."""
        result = self.client.query(
            """
            SELECT arm, successes, failures, impressions, lastUpdated
            FROM TWCBANDIT_STATS FINAL
            WHERE tenantId = {tenant_id:String}
            ORDER BY arm
            """,
            parameters={"tenant_id": tenant_id},
        )

        stats = []
        for row in result.result_rows:
            arm, successes, failures, impressions, last_updated = row
            cvr = successes / impressions if impressions > 0 else 0.0
            stats.append(BanditArmStats(
                arm=arm,
                successes=successes,
                failures=failures,
                impressions=impressions,
                conversion_rate=cvr,
                last_updated=last_updated,
            ))

        return stats

    def get_arm_stat(self, tenant_id: str, arm: str) -> Optional[BanditArmStats]:
        """Get statistics for a specific arm."""
        result = self.client.query(
            """
            SELECT arm, successes, failures, impressions, lastUpdated
            FROM TWCBANDIT_STATS FINAL
            WHERE tenantId = {tenant_id:String}
              AND arm = {arm:String}
            """,
            parameters={"tenant_id": tenant_id, "arm": arm},
        )

        if result.row_count == 0:
            return None

        row = result.first_row
        arm, successes, failures, impressions, last_updated = row
        cvr = successes / impressions if impressions > 0 else 0.0

        return BanditArmStats(
            arm=arm,
            successes=successes,
            failures=failures,
            impressions=impressions,
            conversion_rate=cvr,
            last_updated=last_updated,
        )

    def update_arm_stats(
        self,
        tenant_id: str,
        arm: str,
        successes: int,
        failures: int,
        impressions: int,
    ) -> None:
        """Update statistics for an arm (replaces existing)."""
        self.client.command(
            """
            INSERT INTO TWCBANDIT_STATS (tenantId, arm, successes, failures, impressions)
            VALUES ({tenant_id:String}, {arm:String}, {successes:UInt64}, {failures:UInt64}, {impressions:UInt64})
            """,
            parameters={
                "tenant_id": tenant_id,
                "arm": arm,
                "successes": successes,
                "failures": failures,
                "impressions": impressions,
            },
        )

    def increment_arm_impression(self, tenant_id: str, arm: str) -> None:
        """Increment impression count for an arm."""
        # Get current stats
        current = self.get_arm_stat(tenant_id, arm)

        if current:
            self.update_arm_stats(
                tenant_id=tenant_id,
                arm=arm,
                successes=current.successes,
                failures=current.failures + 1,  # Initially a failure until converted
                impressions=current.impressions + 1,
            )
        else:
            # Initialize arm with first impression
            self.update_arm_stats(
                tenant_id=tenant_id,
                arm=arm,
                successes=0,
                failures=1,
                impressions=1,
            )

    def record_conversion(self, tenant_id: str, arm: str) -> None:
        """Record a conversion for an arm (moves from failure to success)."""
        current = self.get_arm_stat(tenant_id, arm)

        if current and current.failures > 0:
            self.update_arm_stats(
                tenant_id=tenant_id,
                arm=arm,
                successes=current.successes + 1,
                failures=current.failures - 1,  # Move one from failures to successes
                impressions=current.impressions,
            )

    def get_bandit_config(self, tenant_id: str) -> BanditConfig:
        """Get bandit configuration for a tenant."""
        result = self.client.query(
            """
            SELECT key, value
            FROM TWCTENANT_CONFIG FINAL
            WHERE tenantId IN ({tenant_id:String}, '__default__')
              AND key IN ('BANDIT_ENABLED', 'BANDIT_ARMS', 'BANDIT_EXPLORATION_BONUS')
            ORDER BY tenantId DESC  -- Tenant-specific overrides default
            """,
            parameters={"tenant_id": tenant_id},
        )

        # Start with defaults
        config = {
            "enabled": False,
            "arms": ["default", "preference_heavy", "behavior_heavy"],
            "exploration_bonus": 1,
        }

        # Apply values from database
        seen_keys = set()
        for row in result.result_rows:
            key, value = row
            if key in seen_keys:
                continue  # Already got tenant-specific value
            seen_keys.add(key)

            if key == "BANDIT_ENABLED":
                config["enabled"] = value.lower() == "true"
            elif key == "BANDIT_ARMS":
                config["arms"] = [a.strip() for a in value.split(",")]
            elif key == "BANDIT_EXPLORATION_BONUS":
                config["exploration_bonus"] = int(value)

        return BanditConfig(**config)

    def set_bandit_enabled(self, tenant_id: str, enabled: bool) -> None:
        """Enable or disable bandit for a tenant."""
        self.client.command(
            """
            INSERT INTO TWCTENANT_CONFIG (tenantId, key, value)
            VALUES ({tenant_id:String}, 'BANDIT_ENABLED', {value:String})
            """,
            parameters={
                "tenant_id": tenant_id,
                "value": "true" if enabled else "false",
            },
        )

    def set_bandit_arms(self, tenant_id: str, arms: list[str]) -> None:
        """Set the arms to use for a tenant."""
        self.client.command(
            """
            INSERT INTO TWCTENANT_CONFIG (tenantId, key, value)
            VALUES ({tenant_id:String}, 'BANDIT_ARMS', {value:String})
            """,
            parameters={
                "tenant_id": tenant_id,
                "value": ",".join(arms),
            },
        )

    def reset_arm_stats(self, tenant_id: str, arm: Optional[str] = None) -> None:
        """Reset statistics for an arm or all arms for a tenant."""
        if arm:
            self.update_arm_stats(tenant_id, arm, 0, 0, 0)
        else:
            # Reset all arms
            config = self.get_bandit_config(tenant_id)
            for arm_name in config.arms:
                self.update_arm_stats(tenant_id, arm_name, 0, 0, 0)

    def get_stats_from_logs(
        self,
        tenant_id: str,
        arm: str,
        days_back: int = 30,
    ) -> tuple[int, int, int]:
        """
        Calculate arm stats from recommendation logs and outcomes.

        Returns (successes, failures, impressions)
        """
        # Get impressions and conversions from logs
        result = self.client.query(
            """
            SELECT
                count(DISTINCT r.eventId) as impressions,
                count(DISTINCT o.eventId) as conversions
            FROM TWCRECOMMENDATION_LOG r
            LEFT JOIN TWCRECOMMENDATION_OUTCOME o
                ON r.eventId = o.recommendationEventId
                AND o.outcomeType = 'purchased'
            WHERE r.tenantId = {tenant_id:String}
              AND r.weightsConfig = {arm:String}
              AND r.createdAt >= now() - INTERVAL {days:UInt32} DAY
            """,
            parameters={
                "tenant_id": tenant_id,
                "arm": arm,
                "days": days_back,
            },
        )

        if result.row_count == 0:
            return 0, 0, 0

        row = result.first_row
        impressions = row[0] or 0
        successes = row[1] or 0
        failures = impressions - successes

        return successes, failures, impressions
