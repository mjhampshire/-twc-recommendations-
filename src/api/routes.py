"""API routes for the recommendation service."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..models import Customer, Product, ScoredProduct
from ..config import RecommendationWeights, DEFAULT_WEIGHTS
from ..engine import RecommendationEngine
from ..data.repository import CustomerRepository, ProductRepository


router = APIRouter(prefix="/api/v1", tags=["recommendations"])

# Initialize repositories and engine
customer_repo = CustomerRepository()
product_repo = ProductRepository()
engine = RecommendationEngine()


class RecommendationRequest(BaseModel):
    """Request body for custom recommendation parameters."""
    weights: Optional[RecommendationWeights] = None
    exclude_product_ids: list[str] = []
    diversity_factor: float = 0.3


class RecommendationResponse(BaseModel):
    """Response containing recommendations."""
    customer_id: str
    retailer_id: str
    recommendations: list[ScoredProduct]
    weights_used: str  # "default", "new_customer", "custom"


@router.get("/recommendations/{retailer_id}/{customer_id}")
async def get_recommendations(
    retailer_id: str,
    customer_id: str,
    n: int = Query(default=4, ge=1, le=20),
    exclude: Optional[str] = Query(default=None, description="Comma-separated product IDs to exclude"),
) -> RecommendationResponse:
    """
    Get product recommendations for a customer.

    This is the main endpoint for the "VIP walks in the door" use case.
    Returns top N personalized product recommendations.
    """
    # Fetch customer profile
    customer = await customer_repo.get_customer(retailer_id, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

    # Fetch product catalog for retailer
    products = await product_repo.get_products_for_retailer(retailer_id)
    if not products:
        raise HTTPException(status_code=404, detail=f"No products found for retailer {retailer_id}")

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

    return RecommendationResponse(
        customer_id=customer_id,
        retailer_id=retailer_id,
        recommendations=recommendations,
        weights_used=weights_used,
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
    customer = await customer_repo.get_customer(retailer_id, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

    # Fetch product catalog
    products = await product_repo.get_products_for_retailer(retailer_id)
    if not products:
        raise HTTPException(status_code=404, detail=f"No products found for retailer {retailer_id}")

    # Generate recommendations with custom weights
    recommendations = engine.recommend(
        customer=customer,
        products=products,
        n=n,
        weights=request.weights,
        exclude_product_ids=set(request.exclude_product_ids),
        diversity_factor=request.diversity_factor,
    )

    return RecommendationResponse(
        customer_id=customer_id,
        retailer_id=retailer_id,
        recommendations=recommendations,
        weights_used="custom" if request.weights else "default",
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
    source_product = await product_repo.get_product(retailer_id, product_id)
    if not source_product:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    # Fetch all products
    products = await product_repo.get_products_for_retailer(retailer_id)

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


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "twc-recommendations"}
