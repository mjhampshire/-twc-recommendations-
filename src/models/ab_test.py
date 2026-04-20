"""A/B test models for weight optimization.

These models capture A/B test configuration, assignments, and results
to enable automated testing and promotion of weight configurations.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid

from ..config.weights import RecommendationWeights


class ABTestAssignment(BaseModel):
    """
    Assignment of a customer to an A/B test variant.

    Returned by ABTestManager.assign_variant() to indicate which weights
    should be used for this customer's recommendations.
    """
    test_id: str
    test_name: str
    variant: str  # "control" or "treatment"
    weights: RecommendationWeights
    weights_name: str  # Name of the weights preset (e.g., "default", "behavior_heavy")


class ABTestConfig(BaseModel):
    """
    Configuration for an A/B test comparing weight configurations.

    Stored in TWCAB_TEST table.
    """
    test_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    name: str
    description: str = ""

    # Control variant (baseline)
    control_weights: str  # Name of weights preset (e.g., "default")

    # Treatment variant (challenger)
    treatment_weights: str  # Name of weights preset (e.g., "behavior_heavy")

    # Traffic allocation
    traffic_percentage: float = 50.0  # Percentage of traffic to treatment (0-100)

    # Timing
    start_date: datetime = Field(default_factory=datetime.utcnow)
    end_date: Optional[datetime] = None

    # Status
    is_active: bool = True

    # Tracking
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ABTestMetrics(BaseModel):
    """
    Metrics for a single variant in an A/B test.
    """
    variant: str  # "control" or "treatment"
    weights_config: str

    # Volume
    total_recommendations: int = 0
    unique_customers: int = 0

    # Outcomes
    total_clicks: int = 0
    total_add_to_cart: int = 0
    total_add_to_wishlist: int = 0
    total_purchases: int = 0
    total_revenue: float = 0.0

    @property
    def click_through_rate(self) -> float:
        if self.total_recommendations == 0:
            return 0.0
        return self.total_clicks / self.total_recommendations

    @property
    def conversion_rate(self) -> float:
        if self.total_recommendations == 0:
            return 0.0
        return self.total_purchases / self.total_recommendations

    @property
    def cart_rate(self) -> float:
        if self.total_recommendations == 0:
            return 0.0
        return self.total_add_to_cart / self.total_recommendations

    @property
    def revenue_per_recommendation(self) -> float:
        if self.total_recommendations == 0:
            return 0.0
        return self.total_revenue / self.total_recommendations


class ABTestResults(BaseModel):
    """
    Results of an A/B test analysis with statistical significance.
    """
    test_id: str
    test_name: str
    tenant_id: str

    # Variant metrics
    control: ABTestMetrics
    treatment: ABTestMetrics

    # Statistical analysis
    lift: float  # (treatment_cvr - control_cvr) / control_cvr
    p_value: float
    is_significant: bool
    confidence_level: float  # 1 - p_value

    # Sample size
    total_samples: int
    has_enough_samples: bool
    min_samples_required: int

    # Recommendation
    recommended_action: str  # "promote_treatment", "keep_control", "continue_test"
    recommended_weights: Optional[str] = None  # Weights preset to promote

    # Test metadata
    start_date: datetime
    end_date: Optional[datetime] = None
    days_running: int = 0


class TenantWeights(BaseModel):
    """
    Current best weights for a tenant.

    Stored in TWCTENANT_WEIGHTS table. Updated when A/B tests
    promote a winner.
    """
    tenant_id: str
    weights_preset: str  # Name of the weights preset
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by: str = ""  # "auto" for auto-promotion, or user ID
    previous_preset: str = ""  # Previous weights for rollback


class TenantConfig(BaseModel):
    """
    Configuration for a tenant's A/B testing behavior.

    Stored in TWCTENANT_CONFIG table.
    """
    tenant_id: str
    auto_promote_enabled: bool = True
    auto_start_new_tests: bool = True
    min_samples_for_significance: int = 1000
    p_value_threshold: float = 0.05
    min_lift_for_promotion: float = 0.05
    new_test_traffic_percentage: int = 20


class WeightPreset(BaseModel):
    """
    A stored weight configuration preset.

    Built-in presets (default, preference_heavy, behavior_heavy, new_customer)
    are defined in config/weights.py. Custom presets are stored in
    TWCWEIGHT_PRESETS table for auto-generated variations.
    """
    preset_name: str
    tenant_id: str = "__global__"  # "__global__" for shared presets
    weights: RecommendationWeights
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = ""  # "auto" for auto-generated, or user ID
