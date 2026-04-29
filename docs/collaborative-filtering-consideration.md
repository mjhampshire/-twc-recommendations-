# Collaborative Filtering: Consideration for Future Implementation

## Overview

This document evaluates whether collaborative filtering (CF) should be added to the TWC recommendations engine, and outlines a lightweight approach if we decide to proceed.

**Current Approach:** Content-based + behavioral scoring using:
- Explicit preferences (customer/staff stated likes/dislikes)
- Purchase history and browsing behavior
- Product attributes (category, brand, color, pattern)
- Weight optimization via A/B testing and multi-armed bandit

**Collaborative Filtering:** Recommends based on patterns across users:
- "Customers who bought X also bought Y"
- "Customers similar to you liked Z"

---

## How Collaborative Filtering Works

### User-Based CF
Find customers similar to the target customer, recommend what they bought.

```
Customer A: bought [Dress1, Bag2, Shoes3]
Customer B: bought [Dress1, Bag2, Earrings4]
Customer C: bought [Dress1, Bag2, Scarf5]

Target customer bought [Dress1, Bag2]
→ Recommend: Shoes3, Earrings4, Scarf5 (items similar customers bought)
```

### Item-Based CF
Find products frequently purchased together, recommend companions.

```
Dress1 is often bought with: Bag2 (80%), Belt3 (60%), Earrings4 (40%)

Customer bought Dress1
→ Recommend: Bag2, Belt3, Earrings4
```

### Matrix Factorization
Decompose the user-item purchase matrix to find latent factors (hidden patterns).

```
Customer-Item Matrix → [User Factors] × [Item Factors]

Latent factors might represent: "bohemian style", "minimalist", "occasion wear"
```

---

## Pros and Cons for TWC

### Potential Benefits

| Benefit | Description | Value for TWC |
|---------|-------------|---------------|
| **Cross-category discovery** | Surface accessories, shoes, bags that complement purchases | High - drives basket size |
| **Non-obvious relationships** | Find products that appeal to similar tastes but don't share attributes | Medium - may find hidden gems |
| **New customer bootstrap** | Recommend based on similar customers when no history | Medium - helps onboarding |
| **Complete the look** | Outfit suggestions from co-purchase patterns | High - natural for fashion |
| **Tacit preferences** | Capture preferences customers haven't explicitly stated | Medium - supplements explicit |

### Concerns and Limitations

| Concern | Description | Severity for TWC |
|---------|-------------|------------------|
| **Data sparsity** | Fashion retail has sparse purchase matrices - each customer buys few items, many products have few purchases | High |
| **Strong explicit signals** | Staff/customer preference capture provides higher quality signals than CF inference | High |
| **Fashion is personal** | Body type, lifestyle, occasions vary - "similar customers" may not apply | Medium |
| **Seasonal drift** | Co-purchase patterns from last season may mislead current recommendations | Medium |
| **New product cold start** | CF can't recommend new arrivals until they have purchase data | High |
| **Popularity bias** | CF tends to over-recommend bestsellers | Medium |
| **Privacy perception** | "Other customers" messaging may feel less personal for boutique positioning | Low |
| **Computational cost** | Matrix operations at scale require infrastructure | Low (manageable) |

### Assessment

| Factor | Score | Notes |
|--------|-------|-------|
| Data availability | ⚠️ | Likely sparse for CF to work well |
| Incremental value | ⚠️ | Strong explicit preferences may already capture most signal |
| Implementation cost | ✅ | Lightweight approach is feasible |
| Risk | ✅ | Low risk if used as supplementary signal |

**Recommendation:** Lower priority than current roadmap. Consider for Phase 2+ as a supplementary signal, not primary driver.

---

## Where CF Could Add Value

If implemented, focus on narrow, high-value use cases:

### 1. Complete the Look (Item-Based CF)
**Use case:** After purchase or on product page, suggest complementary items.

```
Customer views/buys: Navy Midi Dress
CF suggests: Gold hoop earrings, Nude heels, Clutch bag
(Based on what other customers bought with similar dresses)
```

**Why it works:** Co-purchase within short window is strong signal for styling combinations.

### 2. New Customer Bootstrap (User-Based CF)
**Use case:** For customers with < 3 purchases and no stated preferences.

```
New customer profile:
- Age: 35-45, Location: Sydney, First purchase: Zimmermann dress

Similar customers tend to like: Aje, Camilla, Rebecca Vallance
→ Surface these brands in recommendations
```

**Why it works:** Provides starting point until explicit preferences captured.

### 3. Hybrid Scoring Signal
**Use case:** Add CF score as low-weight signal in existing scoring model.

```
Final Score =
    content_score × 0.7 +      # Preferences, attributes
    behavior_score × 0.2 +     # Purchase/browse history
    cf_score × 0.1             # Collaborative signal
```

**Why it works:** CF catches patterns missed by content-based, without dominating.

---

## Lightweight Implementation Approach

### Phase 1: Item Co-Purchase (Simplest)

Build an item-item similarity matrix based on co-purchases.

#### Schema

```sql
-- Co-purchase pairs with strength
CREATE TABLE IF NOT EXISTS TWCITEM_COPURCHASE (
    tenantId String,
    productId1 String,
    productId2 String,

    -- Co-purchase metrics
    coPurchaseCount UInt32,        -- Times bought together
    product1Purchases UInt32,      -- Total purchases of product1
    product2Purchases UInt32,      -- Total purchases of product2
    confidence Float32,            -- coPurchaseCount / product1Purchases
    lift Float32,                  -- Observed / Expected co-occurrence

    -- Metadata
    windowDays UInt16 DEFAULT 7,   -- Co-purchase window (same order or within N days)
    lastUpdated DateTime DEFAULT now()

) ENGINE = ReplacingMergeTree(lastUpdated)
ORDER BY (tenantId, productId1, productId2);

-- Index for lookup
ALTER TABLE TWCITEM_COPURCHASE
    ADD INDEX idx_product1 (productId1) TYPE set(1000) GRANULARITY 4;
```

#### Batch Job: Calculate Co-Purchases

```python
def calculate_copurchases(tenant_id: str, window_days: int = 7):
    """
    Calculate item co-purchase pairs.
    Run daily or weekly as batch job.
    """
    # Find orders within window that share customers
    copurchases = client.query("""
        WITH customer_purchases AS (
            SELECT
                customerRef,
                variantRef,
                orderDate
            FROM ORDERLINE
            WHERE tenantId = {tenant_id:String}
              AND orderDate >= now() - INTERVAL 180 DAY
        )
        SELECT
            p1.variantRef as product1,
            p2.variantRef as product2,
            count(DISTINCT p1.customerRef) as co_purchase_count
        FROM customer_purchases p1
        JOIN customer_purchases p2
            ON p1.customerRef = p2.customerRef
            AND p1.variantRef < p2.variantRef  -- Avoid duplicates
            AND abs(dateDiff('day', p1.orderDate, p2.orderDate)) <= {window:UInt16}
        GROUP BY p1.variantRef, p2.variantRef
        HAVING co_purchase_count >= 3  -- Minimum support
    """, parameters={'tenant_id': tenant_id, 'window': window_days})

    # Calculate confidence and lift
    for row in copurchases.result_rows:
        product1, product2, count = row

        p1_total = get_purchase_count(tenant_id, product1)
        p2_total = get_purchase_count(tenant_id, product2)
        total_customers = get_total_customers(tenant_id)

        confidence = count / p1_total if p1_total > 0 else 0
        expected = (p1_total * p2_total) / total_customers
        lift = count / expected if expected > 0 else 0

        upsert_copurchase(tenant_id, product1, product2, count,
                          p1_total, p2_total, confidence, lift)
```

#### API: Get Complementary Products

```python
@router.get("/api/v1/complementary/{retailer_id}/{product_id}")
async def get_complementary_products(
    retailer_id: str,
    product_id: str,
    limit: int = 5,
    min_confidence: float = 0.1,
    min_lift: float = 1.5,
):
    """
    Get products frequently purchased with this product.
    Use for "Complete the Look" or "Customers Also Bought".
    """
    results = client.query("""
        SELECT
            productId2 as product_id,
            coPurchaseCount,
            confidence,
            lift
        FROM TWCITEM_COPURCHASE FINAL
        WHERE tenantId = {tenant_id:String}
          AND productId1 = {product_id:String}
          AND confidence >= {min_conf:Float32}
          AND lift >= {min_lift:Float32}
        ORDER BY lift DESC, coPurchaseCount DESC
        LIMIT {limit:UInt32}
    """, parameters={
        'tenant_id': retailer_id,
        'product_id': product_id,
        'min_conf': min_confidence,
        'min_lift': min_lift,
        'limit': limit,
    })

    return {
        "product_id": product_id,
        "complementary": [
            {
                "product_id": row[0],
                "co_purchase_count": row[1],
                "confidence": row[2],
                "lift": row[3],
            }
            for row in results.result_rows
        ]
    }
```

### Phase 2: User Similarity (If Needed)

For new customer bootstrap, calculate user similarity based on purchase overlap.

#### Schema

```sql
-- Customer similarity scores
CREATE TABLE IF NOT EXISTS TWCCUSTOMER_SIMILARITY (
    tenantId String,
    customerId1 String,
    customerId2 String,

    -- Similarity metrics
    sharedPurchases UInt32,        -- Products both bought
    jaccardSimilarity Float32,     -- Intersection / Union
    cosineSimilarity Float32,      -- Cosine of purchase vectors

    lastUpdated DateTime DEFAULT now()

) ENGINE = ReplacingMergeTree(lastUpdated)
ORDER BY (tenantId, customerId1, jaccardSimilarity DESC);
```

#### Usage: New Customer Recommendations

```python
def get_recommendations_for_new_customer(
    tenant_id: str,
    customer_id: str,
    limit: int = 10,
) -> list[str]:
    """
    For customers with minimal history, find similar customers
    and recommend what they bought.
    """
    # Find similar customers
    similar = client.query("""
        SELECT customerId2, jaccardSimilarity
        FROM TWCCUSTOMER_SIMILARITY FINAL
        WHERE tenantId = {tenant_id:String}
          AND customerId1 = {customer_id:String}
        ORDER BY jaccardSimilarity DESC
        LIMIT 10
    """, parameters={'tenant_id': tenant_id, 'customer_id': customer_id})

    if not similar.result_rows:
        return []  # Fall back to popularity or other method

    similar_ids = [row[0] for row in similar.result_rows]

    # Get products those customers bought that target hasn't
    already_bought = get_customer_purchases(tenant_id, customer_id)

    recommendations = client.query("""
        SELECT variantRef, count(*) as cnt
        FROM ORDERLINE
        WHERE tenantId = {tenant_id:String}
          AND customerRef IN {similar_ids:Array(String)}
          AND variantRef NOT IN {exclude:Array(String)}
        GROUP BY variantRef
        ORDER BY cnt DESC
        LIMIT {limit:UInt32}
    """, parameters={
        'tenant_id': tenant_id,
        'similar_ids': similar_ids,
        'exclude': already_bought,
        'limit': limit,
    })

    return [row[0] for row in recommendations.result_rows]
```

### Phase 3: Hybrid Scoring Integration

Add CF as a weighted signal in the main recommendation scorer.

```python
# In scorer.py

def calculate_cf_score(
    tenant_id: str,
    customer_id: str,
    product_id: str,
) -> float:
    """
    Calculate collaborative filtering score for a product.
    Based on: similar customers bought it, or it complements recent purchases.
    """
    score = 0.0

    # 1. Item-based: Does this complement recent purchases?
    recent_purchases = get_recent_purchases(tenant_id, customer_id, days=90)
    for purchase in recent_purchases:
        copurchase = get_copurchase_strength(tenant_id, purchase, product_id)
        if copurchase and copurchase.lift > 1.5:
            score += min(0.3, copurchase.confidence)  # Cap contribution

    # 2. User-based: Did similar customers buy this?
    similar_customers = get_similar_customers(tenant_id, customer_id, limit=5)
    for sim_customer, similarity in similar_customers:
        if has_purchased(tenant_id, sim_customer, product_id):
            score += similarity * 0.2  # Weight by similarity

    return min(1.0, score)  # Cap at 1.0


# In main scoring function
def score_product(customer, product, weights) -> float:
    content_score = calculate_content_score(customer, product, weights)
    behavior_score = calculate_behavior_score(customer, product, weights)
    cf_score = calculate_cf_score(customer.tenant_id, customer.id, product.id)

    # CF is low weight - supplementary signal
    return (
        content_score * weights.content_weight +      # e.g., 0.7
        behavior_score * weights.behavior_weight +    # e.g., 0.2
        cf_score * weights.cf_weight                  # e.g., 0.1
    )
```

---

## When to Implement

### Prerequisites
- [ ] At least 6-12 months of purchase data
- [ ] Sufficient purchase volume (rough guide: 1000+ orders)
- [ ] Current content-based approach showing diminishing returns
- [ ] Specific use case identified (e.g., "complete the look" feature request)

### Signals That CF Would Help
- Staff feedback: "Customers often buy X with Y but we don't suggest it"
- Cross-category conversion is low
- New customers have poor early experience
- Explicit preference capture rate is low

### Signals That CF Won't Help Much
- Strong explicit preference capture already
- Small, curated catalog where staff know the combinations
- Very sparse purchase data
- Highly seasonal with little repeat patterns

---

## Metrics to Track (If Implemented)

| Metric | Description | Target |
|--------|-------------|--------|
| CF coverage | % of recommendations where CF contributed | 20-40% |
| CF-driven conversions | Purchases where CF signal was top contributor | Monitor |
| Cross-category rate | % of orders with items from 2+ categories | Increase |
| New customer conversion | Purchase rate in first 30 days | Improve |
| A/B test lift | CF-enabled vs. CF-disabled | > 5% lift |

---

## Summary

| Aspect | Assessment |
|--------|------------|
| **Priority** | Lower - current approach has strong signals |
| **Best use case** | "Complete the look" / complementary items |
| **Implementation** | Start with item co-purchase (simplest) |
| **Risk** | Low if used as supplementary signal |
| **When to revisit** | After product enrichment and alerts are live |

---

## References

- [Amazon Item-to-Item CF](https://www.cs.umd.edu/~samir/498/Amazon-Recommendations.pdf) - Original paper on item-based CF
- [Netflix Prize](https://en.wikipedia.org/wiki/Netflix_Prize) - Matrix factorization approaches
- [Implicit Feedback CF](https://ieeexplore.ieee.org/document/4781121) - Handling sparse data
