"""API routes for widget rendering and tracking."""

import os
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..models import Customer, ScoredProduct
from ..clients.twc_core import TWCCoreClient, TWCCoreError, TWCCoreAuthError
from ..engine import RecommendationEngine
from ..config import RecommendationWeights
from ..config.clickhouse import get_clickhouse_config
from ..data.clickhouse_repository import ClickHouseCustomerRepository, ClickHouseProductRepository

router = APIRouter(prefix="/api/v1/widgets", tags=["widgets"])

# Initialize repositories and engine
_clickhouse_config = get_clickhouse_config()
customer_repo = ClickHouseCustomerRepository(_clickhouse_config)
product_repo = ClickHouseProductRepository(_clickhouse_config)
engine = RecommendationEngine()

# TWC Core client cache per tenant
_twc_clients: dict[str, TWCCoreClient] = {}


def get_twc_client(tenant_id: str) -> TWCCoreClient:
    """Get or create TWC Core client for a tenant."""
    if tenant_id not in _twc_clients:
        # In production, get secret from secure config per tenant
        # For now, check env var pattern: TWC_SECRET_{TENANT_ID}
        env_key = f"TWC_SECRET_{tenant_id.upper().replace('-', '_')}"
        secret = os.getenv(env_key) or os.getenv("TWC_DEFAULT_SECRET")
        if not secret:
            raise HTTPException(
                status_code=503,
                detail=f"TWC Core not configured for tenant {tenant_id}"
            )
        _twc_clients[tenant_id] = TWCCoreClient(client_secret=secret)
    return _twc_clients[tenant_id]


# =============================================================================
# Request/Response Models
# =============================================================================

class WidgetRenderRequest(BaseModel):
    """Request to render a widget with recommendations."""
    widget_id: str
    widget_type: str  # 'trending_wishlist', 'for_you', 'recently_viewed', etc.
    placement: str  # 'homepage', 'pdp', 'wishlist', 'cart', etc.

    # Identity (at least one required)
    customer_id: Optional[str] = None  # TWC customer ID (logged in)
    online_session_id: Optional[str] = None  # Shopify session ID (anonymous)

    # Context
    page_type: Optional[str] = None  # 'home', 'product', 'collection', etc.
    context_product_id: Optional[str] = None  # Product ID if on PDP
    context_collection_id: Optional[str] = None

    # Options
    limit: int = Field(default=8, ge=1, le=20)
    exclude_product_ids: list[str] = []

    # A/B Testing
    experiment_id: Optional[str] = None
    experiment_variant: Optional[str] = None


class WidgetProduct(BaseModel):
    """Simplified product for widget display."""
    product_id: str
    variant_id: Optional[str] = None
    title: str
    price: float
    compare_at_price: Optional[float] = None
    image_url: Optional[str] = None
    url: Optional[str] = None
    in_stock: bool = True

    # Recommendation metadata
    score: float = 0.0
    rank: int = 0
    reason: Optional[str] = None  # "Matches your style", "Trending", etc.


class WidgetRenderResponse(BaseModel):
    """Response containing widget recommendations."""
    request_id: str  # Unique ID for attribution tracking
    widget_id: str
    widget_type: str
    products: list[WidgetProduct]
    strategy_used: str  # Actual strategy (may differ if fallback)
    fallback_used: bool = False
    latency_ms: int

    # For client-side tracking
    tracking_payload: dict  # Pre-built payload for track endpoint


class WidgetTrackRequest(BaseModel):
    """Request to track a widget event."""
    request_id: str  # From render response
    event_type: str  # 'impression', 'click', 'wishlist_add', 'cart_add', 'purchase'
    widget_id: str

    # Identity
    customer_id: Optional[str] = None
    online_session_id: Optional[str] = None

    # Event details
    product_id: Optional[str] = None  # For click/add events
    variant_id: Optional[str] = None
    rank: Optional[int] = None  # Position in widget (1-indexed)

    # For purchases
    order_id: Optional[str] = None
    order_total: Optional[float] = None
    quantity: int = 1

    # A/B Testing
    experiment_id: Optional[str] = None
    experiment_variant: Optional[str] = None


class WidgetTrackResponse(BaseModel):
    """Response after tracking an event."""
    success: bool
    event_id: str


class WishlistAddRequest(BaseModel):
    """Request to add product to wishlist via widget."""
    request_id: str  # From render response, for attribution
    widget_id: str

    # Identity
    customer_id: Optional[str] = None
    online_session_id: Optional[str] = None

    # Product
    product_id: str
    variant_id: Optional[str] = None
    rank: Optional[int] = None  # Position in widget

    # A/B Testing
    experiment_id: Optional[str] = None
    experiment_variant: Optional[str] = None


class WishlistAddResponse(BaseModel):
    """Response after adding to wishlist."""
    success: bool
    wishlist_id: str
    customer_id: str  # May be newly created for anonymous
    item_id: Optional[str] = None
    event_id: str  # For tracking


class WishlistRemoveRequest(BaseModel):
    """Request to remove product from wishlist via widget."""
    wishlist_id: str
    item_id: str


class WishlistRemoveResponse(BaseModel):
    """Response after removing from wishlist."""
    success: bool


class IdentityMergeRequest(BaseModel):
    """Request to merge anonymous wishlist on login."""
    online_session_id: str  # The anonymous session
    customer_email: str  # Logged-in customer's email
    customer_ref: Optional[str] = None  # Shopify customer ID
    wishlist_ref: Optional[str] = None  # Target wishlist ID
    wishlist_name: Optional[str] = None  # Name for new wishlist if created


class IdentityMergeResponse(BaseModel):
    """Response after merging wishlists."""
    success: bool
    customer_id: str
    wishlist_id: str
    items_merged: int


# =============================================================================
# Widget Tracking Repository
# =============================================================================

class WidgetTrackingRepository:
    """Repository for logging widget events to ClickHouse."""

    def __init__(self, config):
        import clickhouse_connect
        self.client = clickhouse_connect.get_client(
            host=config.host,
            port=config.port,
            username=config.username,
            password=config.password,
            database=config.database,
        )

    def log_impression(
        self,
        tenant_id: str,
        request_id: str,
        widget_id: str,
        widget_type: str,
        placement: str,
        customer_id: str,
        online_session_id: str,
        is_anonymous: bool,
        page_type: str,
        context_product_id: str,
        context_collection_id: str,
        product_ids: list[str],
        strategy_used: str,
        fallback_used: bool,
        latency_ms: int,
        products_considered: int,
        products_filtered: int,
        experiment_id: str,
        experiment_variant: str,
        user_agent: str = "",
        locale: str = "",
        currency: str = "",
    ) -> None:
        """Log widget impression."""
        self.client.insert(
            "TWCWIDGET_IMPRESSIONS",
            [[
                tenant_id,
                request_id,
                widget_id,
                widget_type,
                placement,
                customer_id,
                online_session_id,
                1 if is_anonymous else 0,
                page_type,
                context_product_id,
                context_collection_id,
                "",  # storeId
                product_ids,
                len(product_ids),
                strategy_used,
                1 if fallback_used else 0,
                experiment_id,
                experiment_variant,
                latency_ms,
                products_considered,
                products_filtered,
                datetime.now(),
                user_agent,
                locale,
                currency,
            ]],
            column_names=[
                "tenantId", "requestId", "widgetId", "widgetType", "placement",
                "customerId", "onlineSessionId", "isAnonymous", "pageType",
                "contextProductId", "contextCollectionId", "storeId",
                "productIds", "productCount", "strategyUsed", "fallbackUsed",
                "experimentId", "experimentVariant", "latencyMs",
                "productsConsidered", "productsFiltered", "createdAt",
                "userAgent", "locale", "currency",
            ],
        )

    def log_event(
        self,
        tenant_id: str,
        event_type: str,
        request_id: str,
        widget_id: str,
        customer_id: str,
        online_session_id: str,
        product_id: str,
        variant_id: str,
        rank: int,
        order_id: str = "",
        order_total: float = 0.0,
        quantity: int = 1,
        experiment_id: str = "",
        experiment_variant: str = "",
    ) -> str:
        """Log widget event and return event ID."""
        event_id = str(uuid.uuid4())
        self.client.insert(
            "TWCWIDGET_EVENTS",
            [[
                tenant_id,
                event_type,
                event_id,
                request_id,
                widget_id,
                customer_id,
                online_session_id,
                product_id,
                variant_id,
                rank,
                order_id,
                order_total,
                quantity,
                experiment_id,
                experiment_variant,
                datetime.now(),
            ]],
            column_names=[
                "tenantId", "eventType", "eventId", "requestId", "widgetId",
                "customerId", "onlineSessionId", "productId", "variantId",
                "rank", "orderId", "orderTotal", "quantity",
                "experimentId", "experimentVariant", "createdAt",
            ],
        )
        return event_id


# Lazy-initialized tracking repository
_tracking_repo: Optional[WidgetTrackingRepository] = None


def get_tracking_repo() -> Optional[WidgetTrackingRepository]:
    """Lazy initialization of tracking repository."""
    global _tracking_repo
    if _tracking_repo is None and os.getenv("CLICKHOUSE_HOST"):
        _tracking_repo = WidgetTrackingRepository(get_clickhouse_config())
    return _tracking_repo


# =============================================================================
# Widget Endpoints
# =============================================================================

@router.post("/render/{retailer_id}")
async def render_widget(
    retailer_id: str,
    request: WidgetRenderRequest,
) -> WidgetRenderResponse:
    """
    Get recommendations for a widget.

    This is the main endpoint for widget rendering. It:
    1. Resolves customer identity (customer_id or online_session_id)
    2. Generates recommendations based on widget type
    3. Logs the impression for tracking
    4. Returns products with tracking payload

    Widget types:
    - 'for_you': Personalized recommendations
    - 'trending_wishlist': Products trending on wishlists
    - 'recently_viewed': Customer's recently viewed products
    - 'similar': Similar to context_product_id
    - 'complete_look': Complementary products
    """
    import time
    start_time = time.time()

    # Validate identity
    if not request.customer_id and not request.online_session_id:
        raise HTTPException(
            status_code=400,
            detail="Either customer_id or online_session_id is required"
        )

    request_id = str(uuid.uuid4())
    is_anonymous = not request.customer_id
    products_considered = 0
    products_filtered = 0
    fallback_used = False
    strategy_used = request.widget_type

    # Fetch products for retailer
    all_products = product_repo.get_products_for_retailer(retailer_id)
    if not all_products:
        raise HTTPException(
            status_code=404,
            detail=f"No products found for retailer {retailer_id}"
        )

    products_considered = len(all_products)
    exclude_ids = set(request.exclude_product_ids)

    # Generate recommendations based on widget type
    widget_products: list[WidgetProduct] = []

    if request.widget_type == "for_you" and request.customer_id:
        # Personalized recommendations
        customer = customer_repo.get_customer(retailer_id, request.customer_id)
        if customer:
            recommendations = engine.recommend(
                customer=customer,
                products=all_products,
                n=request.limit,
                exclude_product_ids=exclude_ids,
                fill_with_popular=True,
            )
            widget_products = _to_widget_products(recommendations, "Picked for you")
        else:
            fallback_used = True
            strategy_used = "bestsellers"

    elif request.widget_type == "similar" and request.context_product_id:
        # Similar products
        source = product_repo.get_product(retailer_id, request.context_product_id)
        if source:
            # Simple similarity matching
            similar = []
            for p in all_products:
                if p.product_id in exclude_ids or p.product_id == request.context_product_id:
                    continue
                score = 0.0
                if p.attributes.category == source.attributes.category:
                    score += 0.4
                if p.attributes.brand == source.attributes.brand:
                    score += 0.3
                if p.attributes.style == source.attributes.style:
                    score += 0.2
                if score > 0:
                    similar.append((score, p))

            similar.sort(key=lambda x: x[0], reverse=True)
            widget_products = [
                WidgetProduct(
                    product_id=p.product_id,
                    title=p.name,
                    price=p.price,
                    compare_at_price=p.compare_at_price,
                    image_url=p.image_urls[0] if p.image_urls else None,
                    in_stock=p.in_stock,
                    score=score,
                    rank=i + 1,
                    reason="Similar style",
                )
                for i, (score, p) in enumerate(similar[:request.limit])
            ]
        else:
            fallback_used = True
            strategy_used = "bestsellers"

    # Fallback to bestsellers if no results
    if not widget_products:
        fallback_used = True
        strategy_used = "bestsellers"
        # Simple fallback: return first N products (in production, use actual bestseller data)
        for i, p in enumerate(all_products[:request.limit]):
            if p.product_id not in exclude_ids:
                widget_products.append(
                    WidgetProduct(
                        product_id=p.product_id,
                        title=p.name,
                        price=p.price,
                        compare_at_price=p.compare_at_price,
                        image_url=p.image_urls[0] if p.image_urls else None,
                        in_stock=p.in_stock,
                        score=0.0,
                        rank=len(widget_products) + 1,
                        reason="Bestseller",
                    )
                )

    products_filtered = products_considered - len(widget_products)
    latency_ms = int((time.time() - start_time) * 1000)

    # Log impression
    tracking_repo = get_tracking_repo()
    if tracking_repo:
        try:
            tracking_repo.log_impression(
                tenant_id=retailer_id,
                request_id=request_id,
                widget_id=request.widget_id,
                widget_type=request.widget_type,
                placement=request.placement,
                customer_id=request.customer_id or "",
                online_session_id=request.online_session_id or "",
                is_anonymous=is_anonymous,
                page_type=request.page_type or "",
                context_product_id=request.context_product_id or "",
                context_collection_id=request.context_collection_id or "",
                product_ids=[p.product_id for p in widget_products],
                strategy_used=strategy_used,
                fallback_used=fallback_used,
                latency_ms=latency_ms,
                products_considered=products_considered,
                products_filtered=products_filtered,
                experiment_id=request.experiment_id or "",
                experiment_variant=request.experiment_variant or "",
            )
        except Exception:
            pass  # Don't fail request if logging fails

    # Build tracking payload for client
    tracking_payload = {
        "request_id": request_id,
        "widget_id": request.widget_id,
        "customer_id": request.customer_id,
        "online_session_id": request.online_session_id,
        "experiment_id": request.experiment_id,
        "experiment_variant": request.experiment_variant,
    }

    return WidgetRenderResponse(
        request_id=request_id,
        widget_id=request.widget_id,
        widget_type=request.widget_type,
        products=widget_products,
        strategy_used=strategy_used,
        fallback_used=fallback_used,
        latency_ms=latency_ms,
        tracking_payload=tracking_payload,
    )


@router.post("/track/{retailer_id}")
async def track_widget_event(
    retailer_id: str,
    request: WidgetTrackRequest,
) -> WidgetTrackResponse:
    """
    Track a widget event.

    Event types:
    - 'impression': Widget was viewed (auto-logged by render, but can be explicit)
    - 'click': Product was clicked
    - 'wishlist_add': Product added to wishlist via widget
    - 'cart_add': Product added to cart
    - 'purchase': Product was purchased (for attribution)
    """
    tracking_repo = get_tracking_repo()
    if not tracking_repo:
        raise HTTPException(
            status_code=503,
            detail="Tracking service not available"
        )

    valid_event_types = ["impression", "click", "wishlist_add", "cart_add", "purchase"]
    if request.event_type not in valid_event_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event_type. Must be one of: {valid_event_types}"
        )

    try:
        event_id = tracking_repo.log_event(
            tenant_id=retailer_id,
            event_type=request.event_type,
            request_id=request.request_id,
            widget_id=request.widget_id,
            customer_id=request.customer_id or "",
            online_session_id=request.online_session_id or "",
            product_id=request.product_id or "",
            variant_id=request.variant_id or "",
            rank=request.rank or 0,
            order_id=request.order_id or "",
            order_total=request.order_total or 0.0,
            quantity=request.quantity,
            experiment_id=request.experiment_id or "",
            experiment_variant=request.experiment_variant or "",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to log event: {str(e)}"
        )

    return WidgetTrackResponse(success=True, event_id=event_id)


@router.post("/wishlist/add/{retailer_id}")
async def add_to_wishlist(
    retailer_id: str,
    request: WishlistAddRequest,
) -> WishlistAddResponse:
    """
    Add product to wishlist via widget.

    This endpoint:
    1. Gets or creates wishlist (anonymous or customer)
    2. Adds the product
    3. Logs the event for attribution tracking

    For anonymous users, creates an anonymous customer/wishlist if needed.
    """
    if not request.customer_id and not request.online_session_id:
        raise HTTPException(
            status_code=400,
            detail="Either customer_id or online_session_id is required"
        )

    twc_client = get_twc_client(retailer_id)

    try:
        if request.customer_id:
            # Logged-in user - get their wishlist
            wishlists = await twc_client.get_customer_wishlists(request.customer_id)
            if not wishlists:
                raise HTTPException(
                    status_code=404,
                    detail="No wishlist found for customer"
                )
            wishlist_id = wishlists[0].get("wishlistId") or wishlists[0].get("id")
            customer_id = request.customer_id
        else:
            # Anonymous user - get or create anonymous wishlist
            result = await twc_client.get_or_create_anonymous_wishlist(
                request.online_session_id
            )
            wishlist_id = result.get("wishlistId")
            customer_id = result.get("customerId")

        # Add product to wishlist
        item_result = await twc_client.add_to_wishlist(
            wishlist_id=wishlist_id,
            product_id=request.product_id,
            variant_id=request.variant_id,
        )
        item_id = item_result.get("id") if item_result else None

    except TWCCoreAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except TWCCoreError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=str(e))

    # Log wishlist_add event
    event_id = str(uuid.uuid4())
    tracking_repo = get_tracking_repo()
    if tracking_repo:
        try:
            event_id = tracking_repo.log_event(
                tenant_id=retailer_id,
                event_type="wishlist_add",
                request_id=request.request_id,
                widget_id=request.widget_id,
                customer_id=customer_id,
                online_session_id=request.online_session_id or "",
                product_id=request.product_id,
                variant_id=request.variant_id or "",
                rank=request.rank or 0,
                experiment_id=request.experiment_id or "",
                experiment_variant=request.experiment_variant or "",
            )
        except Exception:
            pass

    return WishlistAddResponse(
        success=True,
        wishlist_id=wishlist_id,
        customer_id=customer_id,
        item_id=item_id,
        event_id=event_id,
    )


@router.post("/wishlist/remove/{retailer_id}")
async def remove_from_wishlist(
    retailer_id: str,
    request: WishlistRemoveRequest,
) -> WishlistRemoveResponse:
    """
    Remove product from wishlist via widget.
    """
    twc_client = get_twc_client(retailer_id)

    try:
        await twc_client.remove_from_wishlist(
            wishlist_id=request.wishlist_id,
            item_id=request.item_id,
        )
    except TWCCoreAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except TWCCoreError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=str(e))

    return WishlistRemoveResponse(success=True)


@router.post("/identity/merge/{retailer_id}")
async def merge_identity(
    retailer_id: str,
    request: IdentityMergeRequest,
) -> IdentityMergeResponse:
    """
    Merge anonymous wishlist into customer wishlist on login.

    Call this when an anonymous user logs in to merge their
    anonymous wishlist items into their customer wishlist.

    The merge behavior depends on tenant configuration:
    - If maxWishlists=1: Items are added to the customer's single wishlist
    - If maxWishlists>1: Items are added to specified wishlist or a new one is created
    """
    twc_client = get_twc_client(retailer_id)

    try:
        # Get the anonymous wishlist
        anon_wishlist = await twc_client.get_anonymous_wishlist(
            request.online_session_id
        )
        if not anon_wishlist:
            # No anonymous wishlist to merge
            return IdentityMergeResponse(
                success=True,
                customer_id="",
                wishlist_id="",
                items_merged=0,
            )

        anonymous_wishlist_id = anon_wishlist.get("wishlistId")
        items = anon_wishlist.get("items", [])

        # Merge into customer wishlist
        result = await twc_client.merge_anonymous_wishlist(
            anonymous_wishlist_id=anonymous_wishlist_id,
            customer_email=request.customer_email,
            online_session_id=request.online_session_id,
            customer_ref=request.customer_ref,
            wishlist_ref=request.wishlist_ref,
            wishlist_name=request.wishlist_name,
        )

    except TWCCoreAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except TWCCoreError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=str(e))

    return IdentityMergeResponse(
        success=True,
        customer_id=result.get("customerId", ""),
        wishlist_id=result.get("wishlistId", ""),
        items_merged=len(items),
    )


# =============================================================================
# Helper Functions
# =============================================================================

def _to_widget_products(
    recommendations: list[ScoredProduct],
    default_reason: str,
) -> list[WidgetProduct]:
    """Convert ScoredProduct list to WidgetProduct list."""
    return [
        WidgetProduct(
            product_id=r.product.product_id,
            title=r.product.name,
            price=r.product.price,
            compare_at_price=r.product.compare_at_price,
            image_url=r.product.image_urls[0] if r.product.image_urls else None,
            in_stock=r.product.in_stock,
            score=r.score,
            rank=i + 1,
            reason=default_reason,
        )
        for i, r in enumerate(recommendations)
    ]
