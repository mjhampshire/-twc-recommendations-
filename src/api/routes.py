"""API routes for the recommendation service."""
import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..models import Customer, Product, ScoredProduct
from ..models.logging import RecommendationEvent, RecommendationType
from ..config import RecommendationWeights, DEFAULT_WEIGHTS
from ..config.clickhouse import get_clickhouse_config
from ..engine import RecommendationEngine
from ..data.clickhouse_repository import ClickHouseCustomerRepository, ClickHouseProductRepository
from ..data.logging_repository import RecommendationLogRepository


router = APIRouter(prefix="/api/v1", tags=["recommendations"])

# Initialize repositories and engine
_clickhouse_config = get_clickhouse_config()
customer_repo = ClickHouseCustomerRepository(_clickhouse_config)
product_repo = ClickHouseProductRepository(_clickhouse_config)
engine = RecommendationEngine()

# Initialize logging repository (optional - only if ClickHouse is configured)
_log_repo: Optional[RecommendationLogRepository] = None

def get_log_repo() -> Optional[RecommendationLogRepository]:
    """Lazy initialization of logging repository."""
    global _log_repo
    if _log_repo is None and os.getenv("CLICKHOUSE_HOST"):
        _log_repo = RecommendationLogRepository(get_clickhouse_config())
    return _log_repo


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
    category: Optional[str] = None
    subcategory: Optional[str] = None
    collection: Optional[str] = None


class RecommendationResponse(BaseModel):
    """Response containing recommendations."""
    customer_id: str
    retailer_id: str
    recommendations: list[ScoredProduct]
    weights_used: str  # "default", "new_customer", "custom"
    event_id: Optional[str] = None  # Recommendation event ID for tracking


@router.get("/recommendations/{retailer_id}/{customer_id}")
async def get_recommendations(
    retailer_id: str,
    customer_id: str,
    n: int = Query(default=4, ge=1, le=20),
    exclude: Optional[str] = Query(default=None, description="Comma-separated product IDs to exclude"),
    category: Optional[str] = Query(default=None, description="Filter to specific category"),
    subcategory: Optional[str] = Query(default=None, description="Filter to specific subcategory"),
    collection: Optional[str] = Query(default=None, description="Filter to products in a specific collection"),
) -> RecommendationResponse:
    """
    Get product recommendations for a customer.

    This is the main endpoint for the "VIP walks in the door" use case.
    Returns top N personalized product recommendations.
    """
    # Fetch customer profile
    customer = customer_repo.get_customer(retailer_id, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

    # Fetch product catalog for retailer
    products = product_repo.get_products_for_retailer(retailer_id)
    if not products:
        raise HTTPException(status_code=404, detail=f"No products found for retailer {retailer_id}")

    # Filter by category/subcategory/collection if specified
    if category:
        products = [p for p in products if p.attributes.category and p.attributes.category.lower() == category.lower()]
    if subcategory:
        products = [p for p in products if p.attributes.subcategory and p.attributes.subcategory.lower() == subcategory.lower()]
    if collection:
        # Collection is a comma-separated string, check if requested collection is in the list
        collection_lower = collection.lower()
        products = [p for p in products if p.attributes.collection and collection_lower in p.attributes.collection.lower()]

    if not products:
        raise HTTPException(status_code=404, detail=f"No products found for the specified filters")

    # Parse exclusions
    exclude_ids = set(exclude.split(",")) if exclude else set()

    # Generate recommendations
    recommendations = engine.recommend(
        customer=customer,
        products=products,
        n=n,
        exclude_product_ids=exclude_ids,
    )

    # Determine which weights were used
    weights_used = "default"
    if customer.purchase_history.total_purchases == 0 and customer.wishlist.total_wishlisted == 0:
        weights_used = "new_customer"

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

    # Fetch product catalog
    products = product_repo.get_products_for_retailer(retailer_id)
    if not products:
        raise HTTPException(status_code=404, detail=f"No products found for retailer {retailer_id}")

    # Filter by category/subcategory/collection if specified
    if request.category:
        products = [p for p in products if p.attributes.category and p.attributes.category.lower() == request.category.lower()]
    if request.subcategory:
        products = [p for p in products if p.attributes.subcategory and p.attributes.subcategory.lower() == request.subcategory.lower()]
    if request.collection:
        collection_lower = request.collection.lower()
        products = [p for p in products if p.attributes.collection and collection_lower in p.attributes.collection.lower()]

    if not products:
        raise HTTPException(status_code=404, detail=f"No products found for the specified filters")

    # Generate recommendations with custom weights
    recommendations = engine.recommend(
        customer=customer,
        products=products,
        n=n,
        weights=request.weights,
        exclude_product_ids=set(request.exclude_product_ids),
        diversity_factor=request.diversity_factor,
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
