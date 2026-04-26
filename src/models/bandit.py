"""Models for multi-armed bandit weight optimization."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class BanditArmStats(BaseModel):
    """Statistics for a single bandit arm."""
    arm: str  # Weight preset name
    successes: int = 0  # Conversions
    failures: int = 0  # Non-conversions
    impressions: int = 0
    conversion_rate: float = 0.0
    last_updated: Optional[datetime] = None

    @property
    def total_trials(self) -> int:
        return self.successes + self.failures


class BanditConfig(BaseModel):
    """Bandit configuration for a tenant."""
    enabled: bool = False
    arms: list[str] = Field(default_factory=lambda: ["default", "preference_heavy", "behavior_heavy"])
    exploration_bonus: int = 1  # Prior strength (higher = more exploration)


class BanditSelection(BaseModel):
    """Result of bandit arm selection."""
    arm: str  # Selected arm name
    sampled_value: float  # The Thompson Sampling value that won
    is_exploration: bool  # True if this arm has few trials


class BanditSummary(BaseModel):
    """Summary of bandit state for a tenant."""
    tenant_id: str
    enabled: bool
    arms: list[BanditArmStats]
    total_impressions: int
    best_arm: Optional[str] = None
    best_conversion_rate: float = 0.0
