# Future Enhancements: Purchase Readiness & Cross-Retailer Intelligence

## Overview

This document outlines two significant enhancements to the TWC platform:

1. **Purchase Readiness Scoring** - Predict which customers are most likely to purchase soon
2. **Cross-Retailer Intelligence** - Leverage anonymized data across retailers for size prediction and preferences

---

## 1. Purchase Readiness Scoring

### Problem Statement

Not all customers are equally ready to buy. A customer who visited yesterday, added items to cart, and is within their typical purchase cycle is more valuable to contact than one who hasn't visited in months.

**Use Cases:**
- Prioritize VIP outreach (staff calls customers most likely to convert)
- Trigger automated campaigns (email/SMS to high-intent customers)
- Allocate limited inventory (show scarce items to ready buyers)
- Optimize ad spend (retarget high-propensity customers)

### Key Signals

| Signal Category | Signals | Weight Rationale |
|-----------------|---------|------------------|
| **Recency** | Days since last visit, last purchase, last wishlist add | Most predictive - recent activity = active intent |
| **Frequency** | Visit frequency trend (increasing/decreasing), sessions per week | Rising frequency signals building intent |
| **Engagement Depth** | Products viewed per session, time on site, pages per session | Deep engagement = serious consideration |
| **Intent Actions** | Wishlist adds, cart adds, cart abandonment | Explicit purchase intent signals |
| **Purchase Cycle** | Days since last purchase vs. average cycle, seasonal patterns | Predicts when next purchase is "due" |
| **Lifecycle Stage** | New/returning/VIP/lapsing, lifetime value | Context for interpreting other signals |

### Implementation Options

#### Option A: RFM-Based Scoring (Simplest)

Classic Recency-Frequency-Monetary model with extensions.

```
Purchase Readiness Score =
    recency_score × 0.35 +
    frequency_score × 0.25 +
    engagement_score × 0.20 +
    intent_score × 0.15 +
    cycle_score × 0.05

Where:
- recency_score: Decay function based on days since last activity
- frequency_score: Normalized visit frequency (sessions/week)
- engagement_score: Avg products viewed, time on site
- intent_score: Recent cart adds, wishlist adds
- cycle_score: 1.0 if within typical purchase window, decays outside
```

**Pros:** Simple, interpretable, no ML infrastructure needed
**Cons:** Linear assumptions, may miss complex patterns

#### Option B: Logistic Regression (Balanced)

Train a model to predict P(purchase in next N days).

```python
Features:
- days_since_last_visit
- days_since_last_purchase
- visits_last_7_days, visits_last_30_days
- products_viewed_last_session
- wishlist_adds_last_7_days
- cart_adds_last_7_days
- cart_abandonment_count
- avg_days_between_purchases
- days_until_predicted_purchase (based on cycle)
- is_sale_period
- has_items_in_cart
- has_items_on_wishlist

Target: purchased_within_7_days (binary)
```

**Pros:** Learns optimal weights from data, handles feature interactions
**Cons:** Requires labeled training data, periodic retraining

#### Option C: Gradient Boosting / XGBoost (Most Accurate)

Non-linear model that captures complex patterns.

**Additional features:**
- Browsing sequences (category flow patterns)
- Price sensitivity indicators
- Response to past campaigns
- Seasonal purchase patterns
- Day-of-week patterns

**Pros:** Handles non-linear relationships, feature interactions
**Cons:** More complex, requires ML infrastructure, less interpretable

#### Option D: Survival Analysis (Time-to-Event)

Predict *when* a customer will purchase, not just *if*.

```
Model: Cox Proportional Hazards or Accelerated Failure Time

Output: Expected days until next purchase, with confidence interval
```

**Pros:** Directly models timing, handles censored data (customers who haven't purchased yet)
**Cons:** More complex to implement and interpret

### Recommended Approach

**Phase 1: Rule-based RFM+ (Option A)**
- Quick to implement
- Provides immediate value
- Establishes baseline metrics

**Phase 2: Logistic Regression (Option B)**
- Once we have 3-6 months of labeled outcomes
- A/B test against rule-based
- Measure lift in conversion rates

**Phase 3: Advanced Models (Options C/D)**
- If Phase 2 shows ML provides significant lift
- Requires dedicated ML infrastructure

### Data Requirements

```sql
-- Purchase readiness signals table
CREATE TABLE IF NOT EXISTS TWCCUSTOMER_READINESS (
    tenantId String,
    customerId String,

    -- Recency signals
    daysSinceLastVisit UInt16,
    daysSinceLastPurchase UInt16,
    daysSinceLastWishlistAdd UInt16,
    daysSinceLastCartAdd UInt16,

    -- Frequency signals
    visitsLast7Days UInt8,
    visitsLast30Days UInt16,
    sessionsPerWeekAvg Float32,
    frequencyTrend String,  -- 'increasing', 'stable', 'decreasing'

    -- Engagement signals
    avgProductsPerSession Float32,
    avgSessionDurationSec UInt32,

    -- Intent signals
    wishlistItemsActive UInt16,
    cartItemsActive UInt8,
    cartAbandonmentsLast30Days UInt8,

    -- Purchase cycle
    avgDaysBetweenPurchases Float32,
    daysUntilPredictedPurchase Int16,  -- Negative if overdue

    -- Computed scores
    readinessScore Float32,
    readinessTier String,  -- 'hot', 'warm', 'cool', 'cold'

    -- Metadata
    computedAt DateTime DEFAULT now()

) ENGINE = ReplacingMergeTree(computedAt)
ORDER BY (tenantId, customerId);
```

### API Design

```
GET /api/v1/customers/{retailer_id}/ready-to-buy
    ?min_score=0.7
    &tier=hot,warm
    &limit=50
    &sort=score_desc

Response:
{
    "customers": [
        {
            "customer_id": "cust_123",
            "readiness_score": 0.87,
            "tier": "hot",
            "signals": {
                "last_visit": "2 hours ago",
                "items_in_cart": 3,
                "within_purchase_cycle": true
            },
            "recommended_action": "High-priority outreach"
        }
    ]
}
```

---

## 2. Cross-Retailer Intelligence

### Problem Statement

TWC has a unique advantage: visibility across multiple retailers. A customer's behavior at Retailer A provides valuable signals for Retailer B, particularly for:

1. **Size prediction** - Predict sizes at new retailers based on purchases elsewhere
2. **Brand/style affinity** - Predict preferences based on cross-retailer patterns
3. **Cold start** - Bootstrap recommendations for customers new to a retailer

### Privacy Architecture

**Critical Requirement:** Customer identity must remain anonymous across retailers.

```
┌─────────────────────────────────────────────────────────────────┐
│                    TWC Cross-Retailer System                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Retailer A          Anonymization Layer         Retailer B     │
│  ┌─────────┐         ┌───────────────┐          ┌─────────┐    │
│  │email:   │         │               │          │email:   │    │
│  │jane@... │ ──────▶ │ twc_anon_id:  │ ◀─────── │jane@... │    │
│  │         │         │ hash(email+   │          │         │    │
│  │size: 10 │         │ global_salt)  │          │size: ?  │    │
│  └─────────┘         │               │          └─────────┘    │
│                      │ Only stores:  │                          │
│                      │ - Sizes       │                          │
│                      │ - Categories  │                          │
│                      │ - Brands      │                          │
│                      │ No PII ever   │                          │
│                      └───────────────┘                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Anonymization approach:**
- Hash customer email with global salt → `twc_anon_id`
- Store only behavioral data (sizes, categories, brands purchased)
- Never store or transmit PII across retailer boundaries
- Individual retailers only see predictions, not source data

### Use Case 1: Size Prediction

#### The Problem

Customer buys size 46 shoes at Retailers X and Y. First time shopping at Retailer Z.
Based on other customers who are size 46 at X & Y, we can predict their size at Z.

#### Approach: Size Mapping via Collaborative Filtering

**Step 1: Build Size Co-occurrence Matrix**

```sql
-- Cross-retailer size purchases (anonymized)
CREATE TABLE IF NOT EXISTS TWCGLOBAL_SIZE_PURCHASES (
    anonCustomerId String,  -- hash(email + salt)
    tenantId String,
    category String,        -- 'shoes', 'dresses', 'tops'
    brandOrRetailer String, -- Brand or retailer name
    sizeValue String,       -- '46', 'M', '10', etc.
    purchaseCount UInt32,
    lastPurchaseDate Date,

    -- Never stored: email, name, address, etc.

) ENGINE = SummingMergeTree()
ORDER BY (anonCustomerId, tenantId, category, brandOrRetailer, sizeValue);
```

**Step 2: Calculate Size Correlations**

```python
def calculate_size_mapping(
    category: str,
    source_retailer: str,
    source_size: str,
    target_retailer: str,
) -> dict:
    """
    Find the most common size at target_retailer for customers
    who are source_size at source_retailer.
    """
    query = """
        WITH source_customers AS (
            SELECT DISTINCT anonCustomerId
            FROM TWCGLOBAL_SIZE_PURCHASES
            WHERE category = {category:String}
              AND brandOrRetailer = {source:String}
              AND sizeValue = {source_size:String}
        )
        SELECT
            sizeValue,
            count(*) as customer_count,
            customer_count / sum(customer_count) OVER () as probability
        FROM TWCGLOBAL_SIZE_PURCHASES
        WHERE anonCustomerId IN source_customers
          AND category = {category:String}
          AND brandOrRetailer = {target:String}
        GROUP BY sizeValue
        ORDER BY customer_count DESC
    """

    results = client.query(query, parameters={...})

    return {
        "predicted_size": results[0].sizeValue,
        "confidence": results[0].probability,
        "alternatives": [
            {"size": r.sizeValue, "probability": r.probability}
            for r in results[:3]
        ],
        "sample_size": sum(r.customer_count for r in results),
    }
```

**Step 3: Pre-compute Size Mapping Tables**

```sql
-- Pre-computed size mappings (updated daily)
CREATE TABLE IF NOT EXISTS TWCGLOBAL_SIZE_MAPPINGS (
    category String,
    sourceRetailer String,
    sourceSize String,
    targetRetailer String,

    -- Predictions
    predictedSize String,
    confidence Float32,
    alternativeSizes Array(Tuple(size String, probability Float32)),

    -- Metadata
    sampleSize UInt32,
    updatedAt DateTime DEFAULT now()

) ENGINE = ReplacingMergeTree(updatedAt)
ORDER BY (category, sourceRetailer, sourceSize, targetRetailer);
```

#### API Design

```
GET /api/v1/size-prediction/{retailer_id}/{customer_id}
    ?category=shoes

Response:
{
    "customer_id": "cust_456",
    "retailer_id": "retailer-z",
    "predictions": [
        {
            "category": "shoes",
            "predicted_size": "46",
            "confidence": 0.89,
            "based_on": "purchases at 2 other retailers",
            "alternatives": [
                {"size": "45", "probability": 0.08},
                {"size": "47", "probability": 0.03}
            ]
        },
        {
            "category": "dresses",
            "predicted_size": "12",
            "confidence": 0.72,
            "based_on": "purchases at 1 other retailer",
            "alternatives": [...]
        }
    ]
}
```

### Use Case 2: Brand/Style Affinity (Cross-Retailer CF)

This extends beyond sizes to predict brand preferences.

**Example:**
- Customers who buy Adidas at Retailers X & Y often buy Nike at Retailer Z
- Customer B buys Adidas at X & Y → suggest Nike at Z

#### Approach: Item-Based Collaborative Filtering Across Retailers

```sql
-- Cross-retailer brand co-purchases
CREATE TABLE IF NOT EXISTS TWCGLOBAL_BRAND_COPURCHASE (
    category String,
    brand1 String,
    retailer1 String,
    brand2 String,
    retailer2 String,

    -- Metrics
    coPurchaseCount UInt32,
    confidence Float32,
    lift Float32,

    updatedAt DateTime DEFAULT now()

) ENGINE = ReplacingMergeTree(updatedAt)
ORDER BY (category, brand1, retailer1, brand2, retailer2);
```

```python
def get_brand_recommendations(
    customer_brands: list[tuple[str, str]],  # [(brand, retailer), ...]
    target_retailer: str,
    category: str,
) -> list[dict]:
    """
    Predict brands customer might like at target_retailer
    based on their purchases at other retailers.
    """
    # Find brands with high co-purchase lift
    query = """
        SELECT
            brand2 as recommended_brand,
            avg(lift) as avg_lift,
            sum(coPurchaseCount) as support
        FROM TWCGLOBAL_BRAND_COPURCHASE
        WHERE category = {category:String}
          AND retailer2 = {target:String}
          AND (brand1, retailer1) IN {customer_brands:Array(Tuple(String, String))}
        GROUP BY brand2
        HAVING support >= 10
        ORDER BY avg_lift DESC
        LIMIT 5
    """

    return [
        {
            "brand": r.recommended_brand,
            "affinity_score": r.avg_lift,
            "reason": f"Customers with similar taste at other retailers love this brand"
        }
        for r in client.query(query, parameters={...}).result_rows
    ]
```

### Use Case 3: Cold Start Recommendations

For customers new to a retailer, bootstrap recommendations from their cross-retailer profile.

```python
def get_cold_start_recommendations(
    anon_customer_id: str,
    target_retailer: str,
) -> dict:
    """
    Generate recommendations for a customer new to this retailer
    using their anonymized cross-retailer profile.
    """
    # Get their profile from other retailers
    profile = get_cross_retailer_profile(anon_customer_id)

    return {
        "predicted_sizes": profile.sizes,
        "preferred_categories": profile.top_categories,
        "preferred_brands": get_brand_recommendations(
            profile.brand_purchases,
            target_retailer
        ),
        "style_affinity": profile.style_signals,
        "price_range": profile.typical_price_range,
    }
```

### Implementation Phases

#### Phase 1: Size Prediction (MVP)

**Scope:**
- Shoe sizes only (most standardized)
- Top 5 retailers with most cross-shopper overlap
- Simple co-occurrence model

**Deliverables:**
- Anonymization pipeline
- Size mapping batch job
- API endpoint for size prediction
- Dashboard showing prediction accuracy

**Validation:**
- Hold out 20% of known size purchases
- Measure prediction accuracy
- Target: >80% accuracy for top prediction

#### Phase 2: Expand Size Categories

**Scope:**
- Add dress sizes, top sizes, bottom sizes
- Handle size notation variations (S/M/L vs 8/10/12 vs 36/38/40)
- Build size normalization layer

**Challenges:**
- Size notation varies wildly across brands
- Need mapping tables: "Zimmermann 1" = "AU 8" = "US 4"

#### Phase 3: Brand/Style Affinity

**Scope:**
- Cross-retailer brand co-purchase analysis
- Style cluster identification
- Cold start recommendations

**This is collaborative filtering**, but across retailers rather than within one catalog.

### Privacy & Compliance

| Requirement | Implementation |
|-------------|----------------|
| No PII in cross-retailer data | Hash email with secure salt, never store raw email |
| No reverse identification | Salt rotated periodically, mappings not stored |
| Data minimization | Only store: sizes, categories, brands, prices |
| Tenant isolation | Each retailer only sees predictions, not source data |
| Consent | Customers opt-in to cross-retailer features |
| Right to deletion | Anon ID can be deleted across all tables |
| Audit trail | Log all cross-retailer data access |

### Metrics & Monitoring

| Metric | Target | Description |
|--------|--------|-------------|
| Size prediction accuracy | >80% | Top-1 prediction matches actual purchase |
| Size prediction coverage | >50% | % of customers where we can make a prediction |
| Brand recommendation CTR | >5% | Clicks on cross-retailer brand suggestions |
| Cold start conversion | >baseline | New customers with cross-retailer data convert better |

---

## Summary & Roadmap

| Enhancement | Phase | Priority | Complexity | Value |
|-------------|-------|----------|------------|-------|
| Purchase Readiness (RFM) | 1 | High | Low | High |
| Purchase Readiness (ML) | 2 | Medium | Medium | High |
| Size Prediction (Shoes) | 1 | High | Medium | High |
| Size Prediction (All) | 2 | Medium | High | High |
| Brand Affinity | 3 | Medium | High | Medium |
| Cold Start Recs | 3 | Low | Medium | Medium |

### Recommended Sequence

1. **Now:** Purchase Readiness (RFM-based) - quick win, immediate value
2. **Next Quarter:** Size Prediction (Shoes MVP) - unique competitive advantage
3. **Following Quarter:** Expand both based on learnings

---

## Technical Dependencies

| Enhancement | Dependencies |
|-------------|--------------|
| Purchase Readiness | Clickstream data in ClickHouse, customer purchase history |
| Size Prediction | Cross-retailer customer matching (anonymized), size normalization |
| Brand Affinity | Purchase data across retailers, brand catalog |

## Questions to Resolve

1. **Purchase Readiness:** What's the target outcome? Purchase within 7 days? 30 days?
2. **Size Prediction:** What's the minimum sample size for confident predictions?
3. **Privacy:** Legal review of anonymization approach for cross-retailer data?
4. **Size Normalization:** Build our own mapping or use existing standards?
