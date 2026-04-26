"""API routes for the recommendation service."""
import os
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..models import Customer, Product, ScoredProduct
from ..models.logging import RecommendationEvent, RecommendationType, OutcomeType, OutcomeActor
from ..models.ab_test import ABTestConfig, ABTestResults, TenantConfig
from ..engine.logging_service import RecommendationLogger
from ..engine.ab_test_manager import ABTestManager
from ..engine.ab_test_analyzer import ABTestAnalyzer
from ..config import RecommendationWeights, DEFAULT_WEIGHTS
from ..config.clickhouse import get_clickhouse_config
from ..engine import RecommendationEngine
from ..data.clickhouse_repository import ClickHouseCustomerRepository, ClickHouseProductRepository
from ..data.logging_repository import RecommendationLogRepository
from ..data.ab_test_repository import ABTestRepository


router = APIRouter(prefix="/api/v1", tags=["recommendations"])

# Initialize repositories and engine
_clickhouse_config = get_clickhouse_config()
customer_repo = ClickHouseCustomerRepository(_clickhouse_config)
product_repo = ClickHouseProductRepository(_clickhouse_config)
engine = RecommendationEngine()

# Initialize logging repository (optional - only if ClickHouse is configured)
_log_repo: Optional[RecommendationLogRepository] = None
_logger: Optional[RecommendationLogger] = None
_ab_test_manager: Optional[ABTestManager] = None
_ab_test_analyzer: Optional[ABTestAnalyzer] = None
_ab_test_repo: Optional[ABTestRepository] = None

def get_log_repo() -> Optional[RecommendationLogRepository]:
    """Lazy initialization of logging repository."""
    global _log_repo
    if _log_repo is None and os.getenv("CLICKHOUSE_HOST"):
        _log_repo = RecommendationLogRepository(get_clickhouse_config())
    return _log_repo


def get_logger() -> Optional[RecommendationLogger]:
    """Lazy initialization of recommendation logger."""
    global _logger
    if _logger is None and os.getenv("CLICKHOUSE_HOST"):
        _logger = RecommendationLogger(get_clickhouse_config())
    return _logger


def get_ab_test_manager() -> Optional[ABTestManager]:
    """Lazy initialization of A/B test manager."""
    global _ab_test_manager
    if _ab_test_manager is None and os.getenv("CLICKHOUSE_HOST"):
        _ab_test_manager = ABTestManager(get_clickhouse_config())
    return _ab_test_manager


def get_ab_test_analyzer() -> Optional[ABTestAnalyzer]:
    """Lazy initialization of A/B test analyzer."""
    global _ab_test_analyzer
    if _ab_test_analyzer is None and os.getenv("CLICKHOUSE_HOST"):
        _ab_test_analyzer = ABTestAnalyzer(get_clickhouse_config())
    return _ab_test_analyzer


def get_ab_test_repo() -> Optional[ABTestRepository]:
    """Lazy initialization of A/B test repository."""
    global _ab_test_repo
    if _ab_test_repo is None and os.getenv("CLICKHOUSE_HOST"):
        _ab_test_repo = ABTestRepository(get_clickhouse_config())
    return _ab_test_repo


def build_context_features(customer: Customer) -> dict:
    """Build context features dict for logging."""
    return {
        "has_preferences": bool(customer.preferences.categories or customer.preferences.colors or customer.preferences.brands),
        "has_dislikes": bool(customer.dislikes.categories or customer.dislikes.colors or customer.dislikes.brands),
        "purchase_count": customer.purchase_history.total_purchases,
        "total_spend": customer.purchase_history.total_spend,
        "wishlist_count": customer.wishlist.total_wishlisted,
        "browsing_view_count": customer.browsing.view_count_last_30_days,
        "has_cart_items": bool(customer.browsing.cart_product_ids),
        "is_vip": customer.is_vip,
    }


class RecommendationRequest(BaseModel):
    """Request body for custom recommendation parameters."""
    weights: Optional[RecommendationWeights] = None
    exclude_product_ids: list[str] = []
    diversity_factor: float = 0.3
    fill_with_popular: bool = True  # Fill remaining slots with popular items if needed
    category: Optional[str] = None
    subcategory: Optional[str] = None
    collection: Optional[str] = None


class CategoryItem(BaseModel):
    """A category with its subcategories and product count."""
    name: str
    subcategories: list[str]
    product_count: int


class CategoriesResponse(BaseModel):
    """Response containing categories for a retailer."""
    retailer_id: str
    categories: list[CategoryItem]


class RecommendationResponse(BaseModel):
    """Response containing recommendations."""
    customer_id: str
    retailer_id: str
    recommendations: list[ScoredProduct]
    weights_used: str  # "default", "new_customer", "custom", or preset name
    event_id: Optional[str] = None  # Recommendation event ID for tracking
    ab_test_id: Optional[str] = None  # A/B test ID if in test
    ab_test_variant: Optional[str] = None  # "control" or "treatment"


class OutcomeRequest(BaseModel):
    """Request body for logging a recommendation outcome."""
    product_id: str  # The product that was interacted with
    position: int  # Position in the recommendation list (1-indexed)
    outcome_type: OutcomeType  # What happened: clicked, added_to_cart, added_to_wishlist, dismissed
    actor: OutcomeActor = OutcomeActor.CUSTOMER  # Who took the action
    staff_id: Optional[str] = None  # Required if actor is STAFF


class OutcomeResponse(BaseModel):
    """Response after logging an outcome."""
    success: bool
    outcome_event_id: str


@router.post("/outcomes/{retailer_id}/{customer_id}/{event_id}")
async def log_outcome(
    retailer_id: str,
    customer_id: str,
    event_id: str,
    request: OutcomeRequest,
) -> OutcomeResponse:
    """
    Log an outcome/interaction with a recommendation.

    Call this when a user interacts with a recommended product:
    - clicked: User clicked to view product details
    - added_to_cart: User added product to cart
    - added_to_wishlist: User added product to wishlist
    - dismissed: User explicitly dismissed/hid the recommendation

    For staff-initiated actions (e.g., staff adding to wishlist on behalf of customer),
    set actor to "staff" and provide the staff_id. Staff-initiated outcomes are logged
    but excluded from recommendation success metrics.

    The event_id should be the one returned from the original recommendation request.
    """
    logger = get_logger()
    if not logger:
        raise HTTPException(
            status_code=503,
            detail="Logging service not available"
        )

    # Map outcome type to logger method
    outcome_type = request.outcome_type
    try:
        if outcome_type == OutcomeType.CLICKED:
            logger.log_click(
                recommendation_event_id=event_id,
                tenant_id=retailer_id,
                customer_id=customer_id,
                product_id=request.product_id,
                position=request.position,
                actor=request.actor,
                staff_id=request.staff_id,
            )
        elif outcome_type == OutcomeType.ADDED_TO_CART:
            logger.log_add_to_cart(
                recommendation_event_id=event_id,
                tenant_id=retailer_id,
                customer_id=customer_id,
                product_id=request.product_id,
                position=request.position,
                actor=request.actor,
                staff_id=request.staff_id,
            )
        elif outcome_type == OutcomeType.ADDED_TO_WISHLIST:
            logger.log_add_to_wishlist(
                recommendation_event_id=event_id,
                tenant_id=retailer_id,
                customer_id=customer_id,
                product_id=request.product_id,
                position=request.position,
                actor=request.actor,
                staff_id=request.staff_id,
            )
        elif outcome_type == OutcomeType.DISMISSED:
            logger.log_dismissed(
                recommendation_event_id=event_id,
                tenant_id=retailer_id,
                customer_id=customer_id,
                product_id=request.product_id,
                position=request.position,
                actor=request.actor,
                staff_id=request.staff_id,
            )
        elif outcome_type == OutcomeType.VIEWED:
            logger.log_view(
                recommendation_event_id=event_id,
                tenant_id=retailer_id,
                customer_id=customer_id,
                product_id=request.product_id,
                position=request.position,
                actor=request.actor,
                staff_id=request.staff_id,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported outcome type: {outcome_type}. Use 'clicked', 'added_to_cart', 'added_to_wishlist', 'viewed', or 'dismissed'."
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to log outcome: {str(e)}"
        )

    return OutcomeResponse(
        success=True,
        outcome_event_id=event_id,
    )


@router.get("/categories/{retailer_id}")
async def get_categories(
    retailer_id: str,
) -> CategoriesResponse:
    """
    Get all categories for a retailer.

    Returns categories with their subcategories and product counts.
    Useful for populating category filter dropdowns in the UI.
    """
    categories = product_repo.get_categories_for_retailer(retailer_id)

    return CategoriesResponse(
        retailer_id=retailer_id,
        categories=[CategoryItem(**cat) for cat in categories],
    )


@router.get("/recommendations/{retailer_id}/{customer_id}")
async def get_recommendations(
    retailer_id: str,
    customer_id: str,
    n: int = Query(default=4, ge=1, le=20),
    exclude: Optional[str] = Query(default=None, description="Comma-separated product IDs to exclude"),
    category: Optional[str] = Query(default=None, description="Filter to specific category"),
    subcategory: Optional[str] = Query(default=None, description="Filter to specific subcategory"),
    collection: Optional[str] = Query(default=None, description="Filter to products in a specific collection"),
    fill_with_popular: bool = Query(default=True, description="Fill remaining slots with popular items if personalized recommendations are insufficient"),
) -> RecommendationResponse:
    """
    Get product recommendations for a customer.

    This is the main endpoint for the "VIP walks in the door" use case.
    Returns top N personalized product recommendations.

    If there's an active A/B test, the customer will be assigned to a variant
    and the appropriate weights will be used.
    """
    # Fetch customer profile
    customer = customer_repo.get_customer(retailer_id, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

    # Fetch product catalog for retailer (with optional filters pushed to DB)
    products = product_repo.get_products_for_retailer(
        retailer_id,
        category=category,
        subcategory=subcategory,
        collection=collection,
    )
    if not products:
        detail = f"No products found for retailer {retailer_id}"
        if category or subcategory or collection:
            detail = "No products found for the specified filters"
        raise HTTPException(status_code=404, detail=detail)

    # Parse exclusions
    exclude_ids = set(exclude.split(",")) if exclude else set()

    # Check for A/B test assignment or tenant's best weights
    ab_manager = get_ab_test_manager()
    ab_assignment = None
    weights = None
    weights_used = "default"
    ab_test_id = None
    ab_test_variant = None

    if ab_manager:
        try:
            # First, check for active A/B test
            ab_assignment = ab_manager.assign_variant(retailer_id, customer_id)
            if ab_assignment:
                weights = ab_assignment.weights
                weights_used = ab_assignment.weights_name
                ab_test_id = ab_assignment.test_id
                ab_test_variant = ab_assignment.variant
            else:
                # No active test - use tenant's best weights from previous A/B test winners
                tenant_weights_name, tenant_weights = ab_manager.get_tenant_default_weights(retailer_id)
                if tenant_weights_name != "default":
                    weights = tenant_weights
                    weights_used = tenant_weights_name
        except Exception:
            # Don't fail if A/B test/weights lookup fails
            pass

    # Override for new customers (no purchase history, no wishlist)
    if weights is None and customer.purchase_history.total_purchases == 0 and customer.wishlist.total_wishlisted == 0:
        weights_used = "new_customer"

    # Generate recommendations with determined weights
    recommendations = engine.recommend(
        customer=customer,
        products=products,
        n=n,
        weights=weights,
        exclude_product_ids=exclude_ids,
        fill_with_popular=fill_with_popular,
    )

    # Log recommendation event with A/B test info
    event_id = None
    log_repo = get_log_repo()
    if log_repo and recommendations:
        event = RecommendationEvent(
            tenant_id=retailer_id,
            customer_id=customer_id,
            recommendation_type=RecommendationType.PERSONALIZED,
            recommended_items=[r.product.product_id for r in recommendations],
            scores=[r.score for r in recommendations],
            positions=list(range(1, len(recommendations) + 1)),
            context_features=build_context_features(customer),
            model_version="rule-based-v1",
            weights_config=weights_used,
            ab_test_id=ab_test_id,
            ab_test_variant=ab_test_variant,
        )
        try:
            log_repo.log_recommendation(event)
            event_id = event.event_id
        except Exception:
            # Don't fail the request if logging fails
            pass

    return RecommendationResponse(
        customer_id=customer_id,
        retailer_id=retailer_id,
        recommendations=recommendations,
        weights_used=weights_used,
        event_id=event_id,
        ab_test_id=ab_test_id,
        ab_test_variant=ab_test_variant,
    )


@router.post("/recommendations/{retailer_id}/{customer_id}")
async def get_recommendations_custom(
    retailer_id: str,
    customer_id: str,
    request: RecommendationRequest,
    n: int = Query(default=4, ge=1, le=20),
) -> RecommendationResponse:
    """
    Get recommendations with custom weights.

    Use this endpoint when you want to override the default weighting strategy.
    """
    # Fetch customer profile
    customer = customer_repo.get_customer(retailer_id, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

    # Fetch product catalog (with optional filters pushed to DB)
    products = product_repo.get_products_for_retailer(
        retailer_id,
        category=request.category,
        subcategory=request.subcategory,
        collection=request.collection,
    )
    if not products:
        detail = f"No products found for retailer {retailer_id}"
        if request.category or request.subcategory or request.collection:
            detail = "No products found for the specified filters"
        raise HTTPException(status_code=404, detail=detail)

    # Generate recommendations with custom weights
    recommendations = engine.recommend(
        customer=customer,
        products=products,
        n=n,
        weights=request.weights,
        exclude_product_ids=set(request.exclude_product_ids),
        diversity_factor=request.diversity_factor,
        fill_with_popular=request.fill_with_popular,
    )

    weights_used = "custom" if request.weights else "default"

    # Log recommendation event
    event_id = None
    log_repo = get_log_repo()
    if log_repo and recommendations:
        event = RecommendationEvent(
            tenant_id=retailer_id,
            customer_id=customer_id,
            recommendation_type=RecommendationType.PERSONALIZED,
            recommended_items=[r.product.product_id for r in recommendations],
            scores=[r.score for r in recommendations],
            positions=list(range(1, len(recommendations) + 1)),
            context_features=build_context_features(customer),
            model_version="rule-based-v1",
            weights_config=weights_used,
        )
        try:
            log_repo.log_recommendation(event)
            event_id = event.event_id
        except Exception:
            # Don't fail the request if logging fails
            pass

    return RecommendationResponse(
        customer_id=customer_id,
        retailer_id=retailer_id,
        recommendations=recommendations,
        weights_used=weights_used,
        event_id=event_id,
        ab_test_id=None,  # Custom weights bypass A/B testing
        ab_test_variant=None,
    )


@router.get("/similar/{retailer_id}/{product_id}")
async def get_similar_products(
    retailer_id: str,
    product_id: str,
    n: int = Query(default=4, ge=1, le=20),
) -> list[Product]:
    """
    Get products similar to a given product.

    Useful for "you might also like" sections.
    """
    # Fetch the source product
    source_product = product_repo.get_product(retailer_id, product_id)
    if not source_product:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    # Fetch all products
    products = product_repo.get_products_for_retailer(retailer_id)

    # Simple similarity: same category or brand, excluding the source
    similar = []
    for p in products:
        if p.product_id == product_id:
            continue

        score = 0.0
        if (p.attributes.category and source_product.attributes.category and
            p.attributes.category.lower() == source_product.attributes.category.lower()):
            score += 0.4
        if (p.attributes.brand and source_product.attributes.brand and
            p.attributes.brand.lower() == source_product.attributes.brand.lower()):
            score += 0.3
        if (p.attributes.style and source_product.attributes.style and
            p.attributes.style.lower() == source_product.attributes.style.lower()):
            score += 0.2
        if (p.attributes.color and source_product.attributes.color and
            p.attributes.color.lower() == source_product.attributes.color.lower()):
            score += 0.1

        if score > 0:
            similar.append((score, p))

    # Sort by score and return top N
    similar.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in similar[:n]]


@router.get("/alternatives/{retailer_id}/{product_id}")
async def get_product_alternatives(
    retailer_id: str,
    product_id: str,
    n: int = Query(default=3, ge=1, le=10),
) -> list[ScoredProduct]:
    """
    Get in-stock alternatives for a sold-out product.

    Useful for wishlist items that are no longer available.
    Returns similar products based on category, brand, style, color, etc.
    """
    # Fetch the sold-out product
    sold_out_product = product_repo.get_product(retailer_id, product_id)
    if not sold_out_product:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    # Fetch all products
    products = product_repo.get_products_for_retailer(retailer_id)

    # Find alternatives
    alternatives = engine.find_alternatives(sold_out_product, products, n=n)

    return alternatives


class WishlistAlternativesResponse(BaseModel):
    """Response containing alternatives for sold-out wishlist items."""
    customer_id: str
    retailer_id: str
    alternatives: dict[str, list[ScoredProduct]]  # product_id -> alternatives
    sold_out_count: int


@router.get("/wishlist-alternatives/{retailer_id}/{customer_id}")
async def get_wishlist_alternatives(
    retailer_id: str,
    customer_id: str,
    n_per_item: int = Query(default=2, ge=1, le=5),
) -> WishlistAlternativesResponse:
    """
    Get alternatives for all sold-out items in a customer's wishlist.

    Returns a map of sold_out_product_id -> list of alternative products.
    Only includes wishlist items that are currently out of stock.
    """
    # Fetch customer profile
    customer = customer_repo.get_customer(retailer_id, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

    # Fetch product catalog
    products = product_repo.get_products_for_retailer(retailer_id)
    if not products:
        raise HTTPException(status_code=404, detail=f"No products found for retailer {retailer_id}")

    # Get alternatives for sold-out wishlist items
    alternatives = engine.get_wishlist_alternatives(
        customer=customer,
        products=products,
        n_per_item=n_per_item,
    )

    return WishlistAlternativesResponse(
        customer_id=customer_id,
        retailer_id=retailer_id,
        alternatives=alternatives,
        sold_out_count=len(alternatives),
    )


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "twc-recommendations"}


# ==================== A/B Test Management Endpoints ====================

class CreateABTestRequest(BaseModel):
    """Request body for creating an A/B test."""
    name: str
    description: str = ""
    control_weights: str = "default"  # Name of control weights preset
    treatment_weights: str  # Name of treatment weights preset
    traffic_percentage: float = Field(default=50.0, ge=0, le=100)


class UpdateABTestRequest(BaseModel):
    """Request body for updating an A/B test."""
    is_active: Optional[bool] = None
    traffic_percentage: Optional[float] = Field(default=None, ge=0, le=100)


class ABTestResponse(BaseModel):
    """Response containing A/B test details."""
    test_id: str
    tenant_id: str
    name: str
    description: str
    control_weights: str
    treatment_weights: str
    traffic_percentage: float
    is_active: bool
    start_date: datetime
    end_date: Optional[datetime] = None


class ABTestResultsResponse(BaseModel):
    """Response containing A/B test results with metrics."""
    test_id: str
    test_name: str
    tenant_id: str
    control_cvr: float
    treatment_cvr: float
    lift: float
    p_value: float
    is_significant: bool
    confidence_level: float
    total_samples: int
    has_enough_samples: bool
    min_samples_required: int
    recommended_action: str
    recommended_weights: Optional[str] = None
    days_running: int


class TenantConfigRequest(BaseModel):
    """Request body for updating tenant A/B test configuration."""
    auto_promote_enabled: Optional[bool] = None
    auto_start_new_tests: Optional[bool] = None
    min_samples_for_significance: Optional[int] = None
    p_value_threshold: Optional[float] = None
    min_lift_for_promotion: Optional[float] = None
    new_test_traffic_percentage: Optional[int] = None


@router.post("/ab-tests/{retailer_id}")
async def create_ab_test(
    retailer_id: str,
    request: CreateABTestRequest,
) -> ABTestResponse:
    """
    Create a new A/B test for a retailer.

    Only one A/B test can be active per retailer at a time.
    The control_weights and treatment_weights should be preset names
    (e.g., "default", "behavior_heavy", "preference_heavy").
    """
    repo = get_ab_test_repo()
    if not repo:
        raise HTTPException(
            status_code=503,
            detail="A/B test service not available"
        )

    # Check for existing active tests
    active_tests = repo.get_active_tests(retailer_id)
    if active_tests:
        raise HTTPException(
            status_code=409,
            detail=f"An active test already exists: {active_tests[0].name}. End it before creating a new one."
        )

    # Create the test
    config = ABTestConfig(
        tenant_id=retailer_id,
        name=request.name,
        description=request.description,
        control_weights=request.control_weights,
        treatment_weights=request.treatment_weights,
        traffic_percentage=request.traffic_percentage,
    )

    created = repo.create_test(config)

    return ABTestResponse(
        test_id=created.test_id,
        tenant_id=created.tenant_id,
        name=created.name,
        description=created.description,
        control_weights=created.control_weights,
        treatment_weights=created.treatment_weights,
        traffic_percentage=created.traffic_percentage,
        is_active=created.is_active,
        start_date=created.start_date,
        end_date=created.end_date,
    )


@router.get("/ab-tests/{retailer_id}")
async def list_ab_tests(
    retailer_id: str,
) -> list[ABTestResponse]:
    """
    List all active A/B tests for a retailer.
    """
    repo = get_ab_test_repo()
    if not repo:
        raise HTTPException(
            status_code=503,
            detail="A/B test service not available"
        )

    tests = repo.get_active_tests(retailer_id)

    return [
        ABTestResponse(
            test_id=t.test_id,
            tenant_id=t.tenant_id,
            name=t.name,
            description=t.description,
            control_weights=t.control_weights,
            treatment_weights=t.treatment_weights,
            traffic_percentage=t.traffic_percentage,
            is_active=t.is_active,
            start_date=t.start_date,
            end_date=t.end_date,
        )
        for t in tests
    ]


@router.get("/ab-tests/{retailer_id}/{test_id}")
async def get_ab_test(
    retailer_id: str,
    test_id: str,
) -> ABTestResultsResponse:
    """
    Get A/B test details with current results and statistical analysis.

    Returns metrics for both variants, lift, p-value, and recommended action.
    """
    analyzer = get_ab_test_analyzer()
    if not analyzer:
        raise HTTPException(
            status_code=503,
            detail="A/B test service not available"
        )

    try:
        results = analyzer.analyze_test(test_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Verify tenant ownership
    if results.tenant_id != retailer_id:
        raise HTTPException(status_code=404, detail="Test not found")

    return ABTestResultsResponse(
        test_id=results.test_id,
        test_name=results.test_name,
        tenant_id=results.tenant_id,
        control_cvr=results.control.conversion_rate,
        treatment_cvr=results.treatment.conversion_rate,
        lift=results.lift,
        p_value=results.p_value,
        is_significant=results.is_significant,
        confidence_level=results.confidence_level,
        total_samples=results.total_samples,
        has_enough_samples=results.has_enough_samples,
        min_samples_required=results.min_samples_required,
        recommended_action=results.recommended_action,
        recommended_weights=results.recommended_weights,
        days_running=results.days_running,
    )


@router.put("/ab-tests/{retailer_id}/{test_id}")
async def update_ab_test(
    retailer_id: str,
    test_id: str,
    request: UpdateABTestRequest,
) -> ABTestResponse:
    """
    Update an A/B test.

    Can be used to:
    - End a test by setting is_active to false
    - Adjust traffic percentage
    """
    repo = get_ab_test_repo()
    if not repo:
        raise HTTPException(
            status_code=503,
            detail="A/B test service not available"
        )

    # Verify test exists and belongs to tenant
    test = repo.get_test(test_id)
    if not test or test.tenant_id != retailer_id:
        raise HTTPException(status_code=404, detail="Test not found")

    # Apply updates
    updated = repo.update_test(
        test_id=test_id,
        is_active=request.is_active,
        traffic_percentage=request.traffic_percentage,
    )

    if not updated:
        raise HTTPException(status_code=404, detail="Test not found")

    return ABTestResponse(
        test_id=updated.test_id,
        tenant_id=updated.tenant_id,
        name=updated.name,
        description=updated.description,
        control_weights=updated.control_weights,
        treatment_weights=updated.treatment_weights,
        traffic_percentage=updated.traffic_percentage,
        is_active=updated.is_active,
        start_date=updated.start_date,
        end_date=updated.end_date,
    )


@router.delete("/ab-tests/{retailer_id}/{test_id}")
async def end_ab_test(
    retailer_id: str,
    test_id: str,
) -> dict:
    """
    End an A/B test.

    This marks the test as inactive and sets the end date.
    It does NOT auto-promote the winner - use the analyzer for that.
    """
    repo = get_ab_test_repo()
    if not repo:
        raise HTTPException(
            status_code=503,
            detail="A/B test service not available"
        )

    # Verify test exists and belongs to tenant
    test = repo.get_test(test_id)
    if not test or test.tenant_id != retailer_id:
        raise HTTPException(status_code=404, detail="Test not found")

    repo.end_test(test_id)

    return {"success": True, "test_id": test_id, "action": "ended"}


@router.get("/ab-tests/{retailer_id}/config")
async def get_tenant_ab_config(
    retailer_id: str,
) -> TenantConfig:
    """
    Get A/B testing configuration for a retailer.

    Returns settings like auto_promote_enabled, min_samples, etc.
    """
    repo = get_ab_test_repo()
    if not repo:
        raise HTTPException(
            status_code=503,
            detail="A/B test service not available"
        )

    return repo.get_tenant_config(retailer_id)


@router.put("/ab-tests/{retailer_id}/config")
async def update_tenant_ab_config(
    retailer_id: str,
    request: TenantConfigRequest,
) -> TenantConfig:
    """
    Update A/B testing configuration for a retailer.

    Use this to:
    - Disable auto-promotion: {"auto_promote_enabled": false}
    - Disable auto-starting new tests: {"auto_start_new_tests": false}
    - Adjust significance thresholds
    """
    repo = get_ab_test_repo()
    if not repo:
        raise HTTPException(
            status_code=503,
            detail="A/B test service not available"
        )

    # Update each provided config value
    if request.auto_promote_enabled is not None:
        repo.set_tenant_config(
            retailer_id, "AUTO_PROMOTE_ENABLED",
            "true" if request.auto_promote_enabled else "false"
        )

    if request.auto_start_new_tests is not None:
        repo.set_tenant_config(
            retailer_id, "AUTO_START_NEW_TESTS",
            "true" if request.auto_start_new_tests else "false"
        )

    if request.min_samples_for_significance is not None:
        repo.set_tenant_config(
            retailer_id, "MIN_SAMPLES_FOR_SIGNIFICANCE",
            str(request.min_samples_for_significance)
        )

    if request.p_value_threshold is not None:
        repo.set_tenant_config(
            retailer_id, "P_VALUE_THRESHOLD",
            str(request.p_value_threshold)
        )

    if request.min_lift_for_promotion is not None:
        repo.set_tenant_config(
            retailer_id, "MIN_LIFT_FOR_PROMOTION",
            str(request.min_lift_for_promotion)
        )

    if request.new_test_traffic_percentage is not None:
        repo.set_tenant_config(
            retailer_id, "NEW_TEST_TRAFFIC_PERCENTAGE",
            str(request.new_test_traffic_percentage)
        )

    return repo.get_tenant_config(retailer_id)
