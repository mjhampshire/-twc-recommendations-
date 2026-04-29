# Recommendation Widget Architecture

## Overview

This document defines the architecture for embedding TWC recommendations into Shopify stores and general websites.

**Design Principles:**
1. **Self-serve installation** - No manual theme edits or support tickets
2. **Server-side intelligence** - Embed is dumb; all logic lives on our platform
3. **One codebase, multiple platforms** - Web Component works everywhere; Shopify wraps it
4. **Tracking from day one** - Can't iterate without measurement
5. **Intent recovery, not just AOV** - Differentiate from Rebuy/Nosto with wishlist + preferences + offline intelligence

---

## Widget Types

### MVP Widgets (Phase 1)

| Widget | Type ID | Placement | Personalized | Anonymous |
|--------|---------|-----------|--------------|-----------|
| Trending Wishlist Items | `trending_wishlist` | Homepage, collection, PLP | Segment-aware | Yes |
| Wishlist Recommendations | `wishlist_recs` | Wishlist page, account | Yes | Only with anon wishlist |
| Out-of-Stock Alternatives | `oos_alternatives` | PDP, wishlist | Contextual | Yes |
| Recommended for You | `for_you` | Homepage, account, empty states | Yes | Fallback only |
| Staff Picks for You | `staff_picks` | Account, post-consultation | Yes | No |

### Phase 2 Widgets

| Widget | Type ID | Placement | Notes |
|--------|---------|-----------|-------|
| New Arrivals for You | `new_arrivals` | Homepage, account | Uses product enrichment |
| Available in Your Size | `size_available` | Wishlist, PDP | High value for fashion |
| Popular in Your Store | `store_popular` | Homepage, collection | Uses offline sales |
| Complete the Look | `complete_the_look` | PDP, cart | Needs product relationships |
| Price Drops | `price_drop` | Account, sale page | Wishlist + browse + sale data |

### Phase 3 Widgets

| Widget | Type ID | Notes |
|--------|---------|-------|
| Frequently Bought Together | `frequently_bought` | Needs basket volume |
| Recently Viewed (Smart) | `recently_viewed` | Reranked by affinity/stock |
| Back in Stock | `back_in_stock` | Higher intent than generic |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SHOPIFY STORE                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Theme App Extension                                                  │   │
│  │                                                                      │   │
│  │  ┌──────────────┐    ┌──────────────────────────────────────────┐  │   │
│  │  │ App Embed    │    │ App Blocks                               │  │   │
│  │  │              │    │                                          │  │   │
│  │  │ • Loader     │    │ • Homepage: Trending, For You            │  │   │
│  │  │ • Identity   │    │ • PDP: OOS Alternatives, Complete Look   │  │   │
│  │  │ • Tracking   │    │ • Wishlist: Wishlist Recs                │  │   │
│  │  │ • CSS vars   │    │ • Account: For You, Staff Picks          │  │   │
│  │  └──────────────┘    └──────────────────────────────────────────┘  │   │
│  │         │                           │                              │   │
│  └─────────┼───────────────────────────┼──────────────────────────────┘   │
│            │                           │                                   │
│            ▼                           ▼                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ <twc-recommendations> Web Component                                 │   │
│  │ • Renders product cards                                             │   │
│  │ • Handles carousel/grid layout                                      │   │
│  │ • Fires tracking events                                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
└────────────────────────────────────┼────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              TWC PLATFORM                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  CDN (CloudFront / Fastly)                                                 │
│  ├── /widgets/v1/loader.js          (global loader)                        │
│  ├── /widgets/v1/twc-recommendations.js (web component)                    │
│  └── /widgets/v1/twc-recommendations.css                                   │
│                                                                             │
│  Widget API                                                                 │
│  ├── POST /v1/widgets/render         (get recommendations)                 │
│  ├── POST /v1/widgets/track          (track events)                        │
│  └── GET  /v1/widgets/config/{id}    (widget configuration)                │
│                                                                             │
│  Recommendation Engine                                                      │
│  ├── Identity resolution (anon → customer)                                 │
│  ├── Hard filters (stock, published, dislikes)                             │
│  ├── Widget-specific ranking                                               │
│  ├── Fallback strategies                                                   │
│  └── A/B test assignment                                                   │
│                                                                             │
│  Event Pipeline                                                             │
│  ├── Impressions, clicks, conversions                                      │
│  ├── Attribution to widget/request                                         │
│  └── Analytics aggregation                                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Embedding Approach

### Shopify: Theme App Extensions

Use Shopify's native app block system for self-serve installation.

| Mechanism | Purpose |
|-----------|---------|
| **App Embed Block** | Global loader, identity resolution, tracking, CSS variables |
| **App Blocks** | Visible recommendation widgets in theme sections |

Merchants add widgets through the theme editor without code changes.

### Non-Shopify: Web Component + CDN

Single script tag + declarative elements:

```html
<script
  async
  src="https://cdn.thewishlistco.com/widgets/v1/loader.js"
  data-tenant-id="viktoria-woods"
></script>

<twc-recommendations
  widget="trending_wishlist"
  title="Most wishlisted right now"
  limit="8"
  layout="carousel"
></twc-recommendations>
```

---

## API Contract

### POST /v1/widgets/render

Request recommendations for a widget placement.

#### Request

```json
{
  "tenant_id": "viktoria-woods",
  "widget_type": "oos_alternatives",
  "placement": "pdp",

  "identity": {
    "customer_id": "CUST001",
    "anonymous_id": "anon_abc123",
    "shopify_customer_id": "gid://shopify/Customer/123456789"
  },

  "context": {
    "product_id": "PROD001",
    "variant_id": "VAR001",
    "collection_id": "new-arrivals",
    "page_type": "product",
    "currency": "AUD",
    "locale": "en-AU",
    "store_id": "sydney-cbd"
  },

  "options": {
    "limit": 8,
    "include_reasons": true
  }
}
```

#### Response

```json
{
  "request_id": "req_01HV123ABC",
  "widget_id": "pdp_oos_alt_01",
  "widget_type": "oos_alternatives",
  "title": "Similar styles available now",

  "experiment": {
    "experiment_id": "exp_trending_v2",
    "variant": "treatment_a"
  },

  "strategy_used": "oos_alternatives",
  "fallback_used": false,

  "products": [
    {
      "product_id": "PROD002",
      "variant_id": "VAR002",
      "title": "Linen Midi Dress",
      "url": "/products/linen-midi-dress",
      "image_url": "https://cdn.shopify.com/...",
      "price": 390.00,
      "compare_at_price": null,
      "currency": "AUD",
      "available": true,
      "available_sizes": ["XS", "S", "M"],
      "badges": ["Available now"],
      "reasons": ["Similar style", "Available in your size"],
      "score": 0.82,
      "rank": 1
    }
  ],

  "tracking": {
    "impression_payload": {
      "request_id": "req_01HV123ABC",
      "widget_id": "pdp_oos_alt_01",
      "products": ["PROD002", "PROD003"]
    }
  },

  "meta": {
    "latency_ms": 45,
    "products_considered": 127,
    "products_filtered": 119
  }
}
```

### POST /v1/widgets/track

Track widget events.

```json
{
  "tenant_id": "viktoria-woods",
  "event_type": "product_clicked",
  "request_id": "req_01HV123ABC",
  "widget_id": "pdp_oos_alt_01",

  "identity": {
    "customer_id": "CUST001",
    "anonymous_id": "anon_abc123"
  },

  "event_data": {
    "product_id": "PROD002",
    "rank": 1,
    "timestamp": "2025-04-29T10:30:00Z"
  }
}
```

#### Event Types

| Event | When | Purpose |
|-------|------|---------|
| `widget_rendered` | Widget displays | Impression attribution |
| `product_impression` | Product enters viewport | Product-level exposure |
| `product_clicked` | User clicks product | CTR measurement |
| `wishlist_added` | User wishlists from widget | Intent tracking |
| `add_to_cart` | User adds to cart | Conversion proxy |
| `widget_empty` | No products returned | Quality monitoring |
| `fallback_used` | Fallback strategy applied | Algorithm monitoring |

---

## Hard Filters

Apply before ranking. Products failing any filter are excluded.

| Filter | Default | Notes |
|--------|---------|-------|
| Published to online channel | Required | |
| In stock | Required | Except back-in-stock widgets |
| Available in customer's size | Configurable | Strong signal for fashion |
| Not in cart | Required | For cart/PDP widgets |
| Not purchased recently | Required | Configurable window (30/60/90 days) |
| Not explicitly disliked | Required | Check customer dislikes |
| Not gift card | Required | |
| Not hidden by merchant | Required | Exclusion lists |
| In customer's store region | Configurable | For multi-region |

```python
class WidgetFilters:
    """Hard filters applied before ranking."""

    def apply_filters(
        self,
        products: list[Product],
        context: WidgetContext,
        customer: Optional[Customer],
    ) -> list[Product]:
        return [
            p for p in products
            if self._passes_all_filters(p, context, customer)
        ]

    def _passes_all_filters(
        self,
        product: Product,
        context: WidgetContext,
        customer: Optional[Customer],
    ) -> bool:
        # Must be published
        if not product.published:
            return False

        # Must be in stock (unless back-in-stock widget)
        if context.widget_type != 'back_in_stock' and not product.in_stock:
            return False

        # Must not be in cart
        if context.cart_product_ids and product.id in context.cart_product_ids:
            return False

        # Must not be recently purchased
        if customer and self._recently_purchased(customer, product):
            return False

        # Must not be disliked
        if customer and self._is_disliked(customer, product):
            return False

        # Must not be excluded by merchant
        if self._is_excluded(context.tenant_id, product):
            return False

        return True
```

---

## Ranking Algorithms

### Trending Wishlist

Multi-signal intent ranking with recency decay.

```python
def calculate_trending_score(
    product: Product,
    window_days: int = 7,
    context_collection: Optional[str] = None,
) -> float:
    """
    Calculate trending score for a product.

    Weights (configurable):
    - Wishlist adds: 0.35
    - Product views: 0.20
    - Add-to-cart: 0.15
    - Sales velocity: 0.15
    - Wishlist growth rate: 0.10
    - Newness boost: 0.05
    """
    # Get signals with recency decay
    wishlist_score = get_decayed_signal(
        product.id, 'wishlist_add', window_days, half_life=3
    )
    view_score = get_decayed_signal(
        product.id, 'view', window_days, half_life=2
    )
    cart_score = get_decayed_signal(
        product.id, 'add_to_cart', window_days, half_life=2
    )
    sales_score = get_decayed_signal(
        product.id, 'purchase', window_days, half_life=3
    )

    # Wishlist growth rate (acceleration)
    growth_rate = calculate_wishlist_growth_rate(product.id, window_days)

    # Newness boost for products added in last 14 days
    days_since_added = (now() - product.created_at).days
    newness = max(0, 1 - (days_since_added / 14))

    # Weighted sum
    score = (
        0.35 * wishlist_score +
        0.20 * view_score +
        0.15 * cart_score +
        0.15 * sales_score +
        0.10 * growth_rate +
        0.05 * newness
    )

    # Penalty for low stock
    if product.stock_level < 5:
        score *= 0.8

    return score


def get_decayed_signal(
    product_id: str,
    signal_type: str,
    window_days: int,
    half_life: float,
) -> float:
    """
    Get signal count with exponential recency decay.

    Events from yesterday count more than events from 6 days ago.
    """
    events = get_events(product_id, signal_type, window_days)

    total = 0.0
    for event in events:
        days_ago = (now() - event.timestamp).days
        decay = 0.5 ** (days_ago / half_life)
        total += decay

    return normalize(total)
```

### Out-of-Stock Alternatives

Find similar products that are in stock.

```python
def get_oos_alternatives(
    product: Product,
    customer: Optional[Customer],
    limit: int = 8,
) -> list[ScoredProduct]:
    """
    Find alternatives for out-of-stock product.

    Ranking factors:
    - Same category: 0.25
    - Similar style/pattern: 0.25
    - Similar price range: 0.15
    - Same brand (or similar brand): 0.15
    - Available in customer's size: 0.10
    - Color match: 0.10
    """
    candidates = get_products_in_category(product.category)
    candidates = [p for p in candidates if p.in_stock and p.id != product.id]

    scored = []
    for candidate in candidates:
        score = 0.0
        reasons = []

        # Category match (should always match)
        if candidate.category == product.category:
            score += 0.25

        # Style/pattern similarity
        style_sim = calculate_style_similarity(product, candidate)
        score += 0.25 * style_sim
        if style_sim > 0.7:
            reasons.append("Similar style")

        # Price range (within 30%)
        price_ratio = candidate.price / product.price
        if 0.7 <= price_ratio <= 1.3:
            score += 0.15
            if price_ratio < 1.0:
                reasons.append("Lower price")

        # Brand
        if candidate.brand == product.brand:
            score += 0.15
            reasons.append(f"Same brand")
        elif brands_similar(candidate.brand, product.brand):
            score += 0.10

        # Size availability
        if customer and customer.preferred_size:
            if customer.preferred_size in candidate.available_sizes:
                score += 0.10
                reasons.append("Available in your size")

        # Color match
        if any(c in product.colors for c in candidate.colors):
            score += 0.10
            reasons.append("Similar color")

        scored.append(ScoredProduct(
            product=candidate,
            score=score,
            reasons=reasons,
        ))

    # Sort by score, return top N
    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:limit]
```

### Wishlist Recommendations

Products similar to wishlisted items.

```python
def get_wishlist_recommendations(
    customer: Customer,
    wishlist_items: list[Product],
    limit: int = 8,
) -> list[ScoredProduct]:
    """
    Recommend products based on wishlist.

    Strategy:
    1. Extract common attributes from wishlist
    2. Find products matching those attributes
    3. Exclude wishlist items and purchases
    4. Score by attribute overlap
    """
    # Extract wishlist profile
    wishlist_brands = Counter(p.brand for p in wishlist_items)
    wishlist_categories = Counter(p.category for p in wishlist_items)
    wishlist_patterns = Counter(p.pattern for p in wishlist_items if p.pattern)
    wishlist_colors = Counter(c for p in wishlist_items for c in p.colors)

    # Get candidates
    candidates = get_candidate_products(
        brands=wishlist_brands.keys(),
        categories=wishlist_categories.keys(),
    )

    # Exclude wishlist items and recent purchases
    exclude_ids = {p.id for p in wishlist_items}
    exclude_ids.update(get_recent_purchases(customer.id))
    candidates = [p for p in candidates if p.id not in exclude_ids]

    # Score candidates
    scored = []
    for candidate in candidates:
        score = 0.0
        reasons = []

        # Brand match
        if candidate.brand in wishlist_brands:
            brand_weight = wishlist_brands[candidate.brand] / len(wishlist_items)
            score += 0.3 * brand_weight
            if brand_weight > 0.3:
                reasons.append(f"You like {candidate.brand}")

        # Category match
        if candidate.category in wishlist_categories:
            cat_weight = wishlist_categories[candidate.category] / len(wishlist_items)
            score += 0.25 * cat_weight

        # Pattern match
        if candidate.pattern and candidate.pattern in wishlist_patterns:
            score += 0.2
            reasons.append(f"Matches your {candidate.pattern} style")

        # Color match
        color_matches = sum(1 for c in candidate.colors if c in wishlist_colors)
        if color_matches:
            score += 0.15 * min(1, color_matches / 2)

        # Size availability
        if customer.preferred_size in candidate.available_sizes:
            score += 0.1
            reasons.append("Available in your size")

        scored.append(ScoredProduct(
            product=candidate,
            score=score,
            reasons=reasons[:2],  # Limit to 2 reasons
        ))

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:limit]
```

---

## Fallback Strategies

Never render an empty widget.

| Primary Widget | Fallback 1 | Fallback 2 |
|----------------|------------|------------|
| Recommended for You | Segment popular | Store best sellers |
| Wishlist Recommendations | Similar to wishlist category | Trending wishlist |
| OOS Alternatives | Same category/style | Same collection |
| New Arrivals for You | New in preferred categories | Latest arrivals |
| Trending Wishlist | Best sellers | New arrivals |
| Complete the Look | Same collection | Merchant curated |
| Staff Picks | Customer's usual categories | Trending |

```python
class FallbackChain:
    """Execute fallback strategies until products found."""

    FALLBACK_CHAINS = {
        'for_you': ['segment_popular', 'store_bestsellers', 'global_bestsellers'],
        'wishlist_recs': ['wishlist_category', 'trending_wishlist'],
        'oos_alternatives': ['same_category_style', 'same_collection'],
        'trending_wishlist': ['bestsellers', 'new_arrivals'],
        'new_arrivals': ['new_in_category', 'latest_arrivals'],
    }

    def get_products(
        self,
        widget_type: str,
        context: WidgetContext,
        limit: int,
    ) -> tuple[list[Product], str, bool]:
        """
        Get products using primary strategy, falling back as needed.

        Returns:
            (products, strategy_used, fallback_used)
        """
        # Try primary strategy
        products = self._execute_strategy(widget_type, context, limit)
        if products:
            return products, widget_type, False

        # Try fallbacks
        for fallback in self.FALLBACK_CHAINS.get(widget_type, []):
            products = self._execute_strategy(fallback, context, limit)
            if products:
                return products, fallback, True

        # Last resort: empty (tracked for monitoring)
        return [], 'empty', True
```

---

## Identity Resolution

The widget receives identity from the embed and passes it to TWC Core APIs.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          WEBSITE                                │
│                                                                 │
│  Widget Embed                                                   │
│  ├── Reads customer_id from page (if logged in)                │
│  ├── Generates/reads anonymous_id from localStorage            │
│  └── Passes both to Widget API                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     TWC PLATFORM                                │
│                                                                 │
│  Widget API (this service)                                      │
│  ├── Receives customer_id + anonymous_id                        │
│  ├── Calls TWC Core REST APIs for customer data                │
│  └── Returns recommendations                                    │
│                                                                 │
│  TWC Core REST APIs (existing)                                  │
│  ├── GET /customers/{id} → Customer profile from DynamoDB      │
│  ├── GET /wishlists/{customer_id} → Wishlist items             │
│  ├── POST /wishlists/{customer_id}/items → Add to wishlist     │
│  ├── POST /identity/merge → Merge anonymous to customer        │
│  └── etc.                                                       │
│                                                                 │
│  Storage                                                        │
│  ├── DynamoDB (customers, wishlists, preferences)              │
│  └── ClickHouse (analytics, behavior, recommendations)          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Widget Identity Flow

```python
class WidgetIdentityResolver:
    """
    Resolve identity for widget requests.

    This service does NOT manage customers or wishlists directly.
    All mutations go through TWC Core REST APIs.
    """

    def __init__(self, twc_core_client: TWCCoreClient):
        self.twc_core = twc_core_client

    async def resolve(
        self,
        tenant_id: str,
        customer_id: Optional[str],
        anonymous_id: Optional[str],
        shopify_customer_id: Optional[str],
    ) -> ResolvedIdentity:
        """
        Resolve identity from available signals.

        Priority:
        1. customer_id (TWC internal) → fetch from Core API
        2. shopify_customer_id → lookup via Core API
        3. anonymous_id only → limited recommendations (trending, etc.)
        """
        if customer_id:
            # Fetch full customer profile from TWC Core
            customer = await self.twc_core.get_customer(tenant_id, customer_id)
            return ResolvedIdentity(
                customer_id=customer_id,
                customer=customer,
                anonymous_id=anonymous_id,
                is_anonymous=False,
            )

        if shopify_customer_id:
            # Lookup TWC customer by Shopify ID via Core API
            customer = await self.twc_core.get_customer_by_shopify_id(
                tenant_id, shopify_customer_id
            )
            if customer:
                return ResolvedIdentity(
                    customer_id=customer.customer_id,
                    customer=customer,
                    anonymous_id=anonymous_id,
                    is_anonymous=False,
                )

        # Anonymous visitor - can still get trending, contextual recommendations
        return ResolvedIdentity(
            customer_id=None,
            customer=None,
            anonymous_id=anonymous_id,
            is_anonymous=True,
        )


class TWCCoreClient:
    """Client for TWC Core REST APIs."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key

    async def get_customer(
        self, tenant_id: str, customer_id: str
    ) -> Optional[Customer]:
        """Fetch customer profile from TWC Core."""
        response = await self._get(f"/customers/{tenant_id}/{customer_id}")
        if response:
            return Customer(**response)
        return None

    async def get_customer_by_shopify_id(
        self, tenant_id: str, shopify_customer_id: str
    ) -> Optional[Customer]:
        """Lookup customer by Shopify customer ID."""
        response = await self._get(
            f"/customers/{tenant_id}/by-shopify/{shopify_customer_id}"
        )
        if response:
            return Customer(**response)
        return None

    async def add_to_wishlist(
        self, tenant_id: str, customer_id: str, product_id: str
    ) -> bool:
        """Add item to wishlist via TWC Core API."""
        return await self._post(
            f"/wishlists/{tenant_id}/{customer_id}/items",
            {"product_id": product_id}
        )

    async def _get(self, path: str) -> Optional[dict]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
            if response.status_code == 200:
                return response.json()
            return None

    async def _post(self, path: str, data: dict) -> bool:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}{path}",
                json=data,
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
            return response.status_code in (200, 201)
```

### Wishlist Actions from Widgets

When a user clicks "Add to Wishlist" in a widget:

```javascript
// In Web Component
async addToWishlist(productId) {
  // Call TWC Core API directly (or via widget API proxy)
  const response = await fetch(`${this.config.coreApiBase}/wishlists/items`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${this.config.publicKey}`,
    },
    body: JSON.stringify({
      tenant_id: this.config.tenantId,
      customer_id: this.config.customerId,  // null if anonymous
      anonymous_id: this.getAnonymousId(),
      product_id: productId,
    }),
  });

  if (response.ok) {
    this.trackWishlistAdd(productId);
    // Update UI to show wishlisted state
  }
}
```

### Anonymous to Customer Merge

Identity merge on login is handled by TWC Core, not this service:

```
User logs in on Shopify
        │
        ▼
Shopify sends customer data to TWC Core
        │
        ▼
TWC Core merges anonymous_id data to customer
(anonymous wishlist → customer wishlist)
        │
        ▼
Next widget request with customer_id
gets merged data automatically
```

The widget just needs to pass the new `customer_id` once the user logs in.

---

## Tracking Schema

### ClickHouse Tables

```sql
-- Widget render events (impressions)
CREATE TABLE IF NOT EXISTS TWCWIDGET_IMPRESSIONS (
    tenantId String,
    requestId String,
    widgetId String,
    widgetType String,
    placement String,

    -- Identity
    customerId String DEFAULT '',
    anonymousId String DEFAULT '',

    -- Context
    pageType String DEFAULT '',
    contextProductId String DEFAULT '',
    contextCollectionId String DEFAULT '',

    -- Results
    productIds Array(String),
    strategyUsed String,
    fallbackUsed UInt8 DEFAULT 0,
    experimentId String DEFAULT '',
    experimentVariant String DEFAULT '',

    -- Performance
    latencyMs UInt32,
    productsConsidered UInt32,
    productsFiltered UInt32,

    createdAt DateTime DEFAULT now()

) ENGINE = MergeTree()
PARTITION BY toYYYYMM(createdAt)
ORDER BY (tenantId, createdAt, requestId);

-- Product-level events (clicks, cart adds, etc.)
CREATE TABLE IF NOT EXISTS TWCWIDGET_EVENTS (
    tenantId String,
    eventType String,            -- 'click', 'wishlist_add', 'add_to_cart', 'purchase'
    requestId String,
    widgetId String,

    -- Identity
    customerId String DEFAULT '',
    anonymousId String DEFAULT '',

    -- Event details
    productId String,
    variantId String DEFAULT '',
    rank UInt8,                  -- Position in widget (1-indexed)

    -- Attribution
    experimentId String DEFAULT '',
    experimentVariant String DEFAULT '',

    createdAt DateTime DEFAULT now()

) ENGINE = MergeTree()
PARTITION BY toYYYYMM(createdAt)
ORDER BY (tenantId, createdAt, eventType);

-- Aggregated metrics (materialized view or scheduled job)
CREATE TABLE IF NOT EXISTS TWCWIDGET_METRICS_DAILY (
    tenantId String,
    date Date,
    widgetType String,
    placement String,

    -- Counts
    impressions UInt64,
    clicks UInt64,
    wishlistAdds UInt64,
    cartAdds UInt64,
    purchases UInt64,

    -- Rates
    ctr Float32,                 -- clicks / impressions
    conversionRate Float32,      -- purchases / impressions

    -- Quality
    emptyWidgets UInt64,
    fallbacksUsed UInt64,
    avgLatencyMs Float32,

    -- Revenue (if attributable)
    attributedRevenue Float64

) ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (tenantId, date, widgetType, placement);
```

---

## Performance Requirements

| Metric | Target | Notes |
|--------|--------|-------|
| API P50 latency | < 50ms | With warm cache |
| API P99 latency | < 200ms | Cold cache acceptable |
| Time to first render | < 100ms | From script load |
| Widget JS bundle | < 30KB gzipped | Core + one widget type |
| Loader script | < 5KB gzipped | Just bootstrap |

### Caching Strategy

| Data | Cache Location | TTL | Invalidation |
|------|----------------|-----|--------------|
| Anonymous trending | CDN edge | 5 min | Time-based |
| Customer recommendations | API cache | 1 min | On activity |
| Product catalog | API cache | 10 min | On sync |
| Widget config | CDN edge | 1 hour | On update |

```python
class WidgetCache:
    """Caching layer for widget API."""

    def get_cache_key(self, request: WidgetRequest) -> str:
        """
        Generate cache key based on request.

        Anonymous requests: cacheable by widget + context
        Customer requests: not edge-cacheable (personalized)
        """
        if request.identity.is_anonymous:
            # Cacheable at edge
            return f"widget:{request.tenant_id}:{request.widget_type}:" \
                   f"{request.context.collection_id}:{request.context.product_id}"
        else:
            # Cache in API only, short TTL
            return f"customer:{request.identity.customer_id}:" \
                   f"{request.widget_type}:{hash(request.context)}"

    def get_cache_ttl(self, request: WidgetRequest) -> int:
        """Get TTL in seconds."""
        if request.identity.is_anonymous:
            return 300  # 5 minutes for anonymous
        else:
            return 60   # 1 minute for personalized
```

---

## Shopify Theme App Extension

### File Structure

```
extensions/
└── twc-recommendations/
    ├── assets/
    │   ├── twc-loader.js           # Global loader
    │   ├── twc-recommendations.js   # Web component
    │   └── twc-recommendations.css  # Styles
    ├── blocks/
    │   ├── recommendations.liquid   # Main app block
    │   └── trending.liquid          # Trending-specific block
    ├── snippets/
    │   └── twc-product-card.liquid  # Product card template
    └── locales/
        ├── en.default.json
        └── en.schema.json
```

### App Embed Block (Global Loader)

```liquid
<!-- extensions/twc-recommendations/blocks/app-embed.liquid -->
<script>
  window.TWC_CONFIG = {
    tenantId: "{{ shop.metafields.twc.tenant_id }}",
    publicKey: "{{ shop.metafields.twc.public_key }}",
    shopDomain: "{{ shop.permanent_domain }}",
    customerId: {% if customer %}"{{ customer.id }}"{% else %}null{% endif %},
    currency: "{{ cart.currency.iso_code }}",
    locale: "{{ request.locale.iso_code }}"
  };
</script>
<script
  async
  src="{{ 'twc-loader.js' | asset_url }}"
></script>

{% schema %}
{
  "name": "TWC Recommendations",
  "target": "body",
  "settings": []
}
{% endschema %}
```

### App Block (Recommendations Widget)

```liquid
<!-- extensions/twc-recommendations/blocks/recommendations.liquid -->
<div
  class="twc-recommendations-container"
  data-widget-type="{{ block.settings.widget_type }}"
  data-title="{{ block.settings.title }}"
  data-limit="{{ block.settings.limit }}"
  data-layout="{{ block.settings.layout }}"
  {% if product %}data-product-id="{{ product.id }}"{% endif %}
  {% if collection %}data-collection-id="{{ collection.id }}"{% endif %}
>
  <twc-recommendations
    widget="{{ block.settings.widget_type }}"
    title="{{ block.settings.title }}"
    limit="{{ block.settings.limit }}"
    layout="{{ block.settings.layout }}"
  ></twc-recommendations>
</div>

{% schema %}
{
  "name": "TWC Recommendations",
  "target": "section",
  "stylesheet": "twc-recommendations.css",
  "javascript": "twc-recommendations.js",
  "settings": [
    {
      "type": "select",
      "id": "widget_type",
      "label": "Widget type",
      "options": [
        { "value": "trending_wishlist", "label": "Trending Wishlist Items" },
        { "value": "for_you", "label": "Recommended for You" },
        { "value": "wishlist_recs", "label": "Wishlist Recommendations" },
        { "value": "oos_alternatives", "label": "Out-of-Stock Alternatives" },
        { "value": "new_arrivals", "label": "New Arrivals for You" },
        { "value": "complete_the_look", "label": "Complete the Look" },
        { "value": "staff_picks", "label": "Staff Picks for You" }
      ],
      "default": "trending_wishlist"
    },
    {
      "type": "text",
      "id": "title",
      "label": "Heading",
      "default": "Most wishlisted right now"
    },
    {
      "type": "range",
      "id": "limit",
      "label": "Number of products",
      "min": 4,
      "max": 12,
      "step": 1,
      "default": 8
    },
    {
      "type": "select",
      "id": "layout",
      "label": "Layout",
      "options": [
        { "value": "carousel", "label": "Carousel" },
        { "value": "grid", "label": "Grid" },
        { "value": "compact", "label": "Compact" }
      ],
      "default": "carousel"
    }
  ]
}
{% endschema %}
```

---

## Web Component

```javascript
// twc-recommendations.js

class TWCRecommendations extends HTMLElement {
  static get observedAttributes() {
    return ['widget', 'limit', 'layout', 'title'];
  }

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.products = [];
    this.loading = true;
    this.error = null;
    this.requestId = null;
  }

  connectedCallback() {
    this.render();
    this.fetchRecommendations();
  }

  async fetchRecommendations() {
    const config = window.TWC_CONFIG || {};

    try {
      const response = await fetch(`${config.apiBase}/v1/widgets/render`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tenant_id: config.tenantId,
          widget_type: this.getAttribute('widget'),
          placement: this.detectPlacement(),
          identity: {
            customer_id: config.customerId,
            anonymous_id: this.getAnonymousId(),
          },
          context: {
            product_id: this.getAttribute('context-product-id') || this.detectProductId(),
            collection_id: this.getAttribute('context-collection-id') || this.detectCollectionId(),
            currency: config.currency,
            locale: config.locale,
          },
          options: {
            limit: parseInt(this.getAttribute('limit')) || 8,
            include_reasons: true,
          },
        }),
      });

      const data = await response.json();

      this.requestId = data.request_id;
      this.products = data.products;
      this.title = data.title || this.getAttribute('title');
      this.loading = false;

      this.render();
      this.trackImpression(data);

    } catch (err) {
      this.error = err;
      this.loading = false;
      this.render();
    }
  }

  render() {
    const layout = this.getAttribute('layout') || 'carousel';

    this.shadowRoot.innerHTML = `
      <style>${this.getStyles()}</style>

      <div class="twc-widget twc-widget--${layout}">
        ${this.loading ? this.renderSkeleton() : ''}
        ${this.error ? this.renderError() : ''}
        ${!this.loading && !this.error ? this.renderProducts() : ''}
      </div>
    `;

    this.attachEventListeners();
  }

  renderProducts() {
    if (!this.products.length) {
      return ''; // Hide widget if no products
    }

    const layout = this.getAttribute('layout') || 'carousel';

    return `
      <h2 class="twc-widget__title">${this.title}</h2>
      <div class="twc-widget__products twc-widget__products--${layout}">
        ${this.products.map((product, index) => this.renderProductCard(product, index)).join('')}
      </div>
      ${layout === 'carousel' ? this.renderCarouselControls() : ''}
    `;
  }

  renderProductCard(product, index) {
    return `
      <div class="twc-product-card" data-product-id="${product.product_id}" data-rank="${index + 1}">
        <a href="${product.url}" class="twc-product-card__link">
          <div class="twc-product-card__image-container">
            <img
              src="${product.image_url}"
              alt="${product.title}"
              loading="${index < 4 ? 'eager' : 'lazy'}"
              class="twc-product-card__image"
            />
            ${product.badges?.length ? this.renderBadges(product.badges) : ''}
          </div>
          <div class="twc-product-card__details">
            <h3 class="twc-product-card__title">${product.title}</h3>
            <div class="twc-product-card__price">
              ${product.compare_at_price ? `<span class="twc-product-card__compare-price">${this.formatPrice(product.compare_at_price)}</span>` : ''}
              <span class="twc-product-card__current-price">${this.formatPrice(product.price)}</span>
            </div>
            ${product.reasons?.length ? this.renderReasons(product.reasons) : ''}
            ${product.available_sizes?.length ? this.renderSizes(product.available_sizes) : ''}
          </div>
        </a>
        <button class="twc-product-card__wishlist" aria-label="Add to wishlist">
          <svg><!-- heart icon --></svg>
        </button>
      </div>
    `;
  }

  renderReasons(reasons) {
    return `
      <div class="twc-product-card__reasons">
        ${reasons.slice(0, 1).map(r => `<span class="twc-product-card__reason">${r}</span>`).join('')}
      </div>
    `;
  }

  attachEventListeners() {
    // Track clicks
    this.shadowRoot.querySelectorAll('.twc-product-card__link').forEach(link => {
      link.addEventListener('click', (e) => {
        const card = e.target.closest('.twc-product-card');
        this.trackClick(card.dataset.productId, parseInt(card.dataset.rank));
      });
    });

    // Track wishlist adds
    this.shadowRoot.querySelectorAll('.twc-product-card__wishlist').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const card = e.target.closest('.twc-product-card');
        this.trackWishlistAdd(card.dataset.productId, parseInt(card.dataset.rank));
        // Trigger actual wishlist add via TWC API
        window.TWC?.addToWishlist(card.dataset.productId);
      });
    });
  }

  trackImpression(data) {
    window.TWC?.track('widget_rendered', {
      request_id: this.requestId,
      widget_id: data.widget_id,
      products: data.products.map(p => p.product_id),
    });
  }

  trackClick(productId, rank) {
    window.TWC?.track('product_clicked', {
      request_id: this.requestId,
      product_id: productId,
      rank: rank,
    });
  }

  trackWishlistAdd(productId, rank) {
    window.TWC?.track('wishlist_added', {
      request_id: this.requestId,
      product_id: productId,
      rank: rank,
    });
  }

  getAnonymousId() {
    let id = localStorage.getItem('twc_anonymous_id');
    if (!id) {
      id = 'anon_' + crypto.randomUUID();
      localStorage.setItem('twc_anonymous_id', id);
    }
    return id;
  }

  // ... additional helper methods
}

customElements.define('twc-recommendations', TWCRecommendations);
```

---

## Privacy & GDPR Considerations

| Concern | Mitigation |
|---------|------------|
| Tracking before consent | Respect cookie consent; don't track until accepted |
| Cross-site tracking | anonymous_id is first-party, per-site |
| Data retention | Define retention period (e.g., 90 days for anonymous) |
| Right to deletion | API to delete customer data on request |
| Transparency | Document what data is collected in privacy policy |

```python
class PrivacyManager:
    """Handle privacy-related concerns."""

    def should_track(self, consent_status: Optional[str]) -> bool:
        """Check if tracking is allowed based on consent."""
        if consent_status == 'granted':
            return True
        if consent_status == 'denied':
            return False
        # Default: check regional requirements
        return self.default_for_region()

    def delete_customer_data(self, tenant_id: str, customer_id: str):
        """Delete all data for a customer (GDPR right to deletion)."""
        self.delete_from_tables(tenant_id, customer_id, [
            'TWCWIDGET_IMPRESSIONS',
            'TWCWIDGET_EVENTS',
            'TWCINFERRED_PREFERENCES',
            # ... other tables
        ])
```

---

## Accessibility Requirements

| Requirement | Implementation |
|-------------|----------------|
| Keyboard navigation | Tab through products, Enter to select |
| Screen reader | ARIA labels on products, carousel controls |
| Focus management | Visible focus indicators |
| Reduced motion | Respect `prefers-reduced-motion` |
| Color contrast | WCAG AA minimum (4.5:1) |

```css
/* Accessibility styles */
.twc-product-card:focus-within {
  outline: 2px solid var(--twc-focus-color, #005fcc);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .twc-widget__products--carousel {
    scroll-behavior: auto;
  }
  .twc-product-card {
    transition: none;
  }
}
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| API timeout | Show skeleton, retry once, then hide widget |
| API error | Log error, hide widget (don't show broken state) |
| Empty results | Hide widget (unless configured to show fallback message) |
| Invalid config | Console warning, hide widget |
| Network offline | Use cached data if available, else hide |

```javascript
class TWCRecommendations extends HTMLElement {
  async fetchWithRetry(url, options, retries = 1) {
    for (let i = 0; i <= retries; i++) {
      try {
        const response = await fetch(url, {
          ...options,
          signal: AbortSignal.timeout(3000), // 3 second timeout
        });
        if (response.ok) return response.json();
      } catch (err) {
        if (i === retries) throw err;
        await new Promise(r => setTimeout(r, 1000)); // Wait 1s before retry
      }
    }
  }
}
```

---

## Implementation Phases

### Phase 1: Foundation
- [ ] Widget API contract (FastAPI endpoints)
- [ ] Tracking schema and endpoints
- [ ] Identity resolution service
- [ ] Hard filter framework

### Phase 2: Core Widgets
- [ ] Web Component (TypeScript)
- [ ] Trending Wishlist algorithm
- [ ] Wishlist Recommendations algorithm
- [ ] OOS Alternatives algorithm
- [ ] Recommended for You (wrapper on existing engine)

### Phase 3: Shopify Integration
- [ ] Theme App Extension structure
- [ ] App Embed block (loader)
- [ ] App Block (recommendations)
- [ ] Shopify app configuration

### Phase 4: Tracking & Analytics
- [ ] Event pipeline to ClickHouse
- [ ] Daily aggregation job
- [ ] Dashboard queries
- [ ] A/B test framework

### Phase 5: Merchant Configuration
- [ ] Widget config API
- [ ] Admin UI for widget settings
- [ ] Exclusion/boost rules
- [ ] Preview mode

---

## What Can Be Coded Now

| Component | Can Code | Notes |
|-----------|----------|-------|
| Widget API (FastAPI) | ✅ Full | Endpoints, models, filters, ranking |
| Tracking API | ✅ Full | Events, schema, aggregation |
| Identity resolution | ✅ Full | Logic and storage |
| Web Component (JS) | ✅ Full | Core component, styles, tracking |
| Shopify Extension files | ✅ Full | Liquid, schema, JS wrappers |
| Ranking algorithms | ✅ Full | Trending, OOS, Wishlist, etc. |
| ClickHouse migrations | ✅ Full | Tables, indexes |
| CDN/deployment | ❌ Manual | CloudFront/Fastly setup |
| Shopify Partner app | ❌ Manual | Partner dashboard, OAuth |
| Production deploy | ❌ Manual | Infrastructure |

**Estimate:** Phases 1-3 core code can be written. Phases 4-5 require manual infrastructure and UI work.
