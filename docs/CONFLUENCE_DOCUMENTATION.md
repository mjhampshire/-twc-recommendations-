# TWC Recommendations Engine

**Document Version:** 1.0
**Last Updated:** March 2026
**Status:** Phase 1 Complete (Rule-Based), Phase 2 In Planning

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
3. [Data Model](#data-model)
4. [Scoring Algorithm](#scoring-algorithm)
5. [API Reference](#api-reference)
6. [Database Schema](#database-schema)
7. [ML Roadmap](#ml-roadmap)
8. [Integration Guide](#integration-guide)
9. [Appendix](#appendix)

---

## Executive Summary

The TWC Recommendations Engine is a personalized product recommendation system for retail clienteling applications. It analyzes customer preferences, purchase history, browsing behavior, and wishlist data to generate relevant product suggestions.

### Key Features

| Feature | Status | Description |
|---------|--------|-------------|
| Personalized Recommendations | ✅ Live | 4 products based on customer profile |
| Dislike Filtering | ✅ Live | Hard exclude customer dislikes |
| Preference Source Weighting | ✅ Live | Customer > Staff > Inferred |
| Sold-Out Alternatives | ✅ Live | Find in-stock alternatives |
| Recommendation Logging | ✅ Live | Track recommendations for ML |
| Outcome Tracking | 🚧 Next | Track clicks, purchases |
| ML Model | 📋 Planned | Replace rules with learned model |

### Privacy

- **No PII stored** - Customer model is anonymized
- **Opaque identifiers** - customer_id maps to source system
- **Per-tenant isolation** - Data separated by retailer

---

## Architecture Overview

### System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Client Applications                             │
│                    (Styleboard, ClientApp, Staff Portal)                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FastAPI Service                                 │
│                         /api/recommendations                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    ▼                  ▼                  ▼
           ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
           │   Customer    │  │   Product     │  │  Logging      │
           │   Repository  │  │   Repository  │  │  Repository   │
           └───────────────┘  └───────────────┘  └───────────────┘
                    │                  │                  │
                    └──────────────────┼──────────────────┘
                                       ▼
                         ┌───────────────────────┐
                         │      ClickHouse       │
                         └───────────────────────┘
```

### Component Responsibilities

| Component | File | Purpose |
|-----------|------|---------|
| RecommendationEngine | `src/engine/recommender.py` | Orchestrates scoring, filtering, ranking |
| Scorer | `src/engine/scorer.py` | Calculates product scores |
| ClickHouseCustomerRepository | `src/data/clickhouse_repository.py` | Fetches customer data |
| ClickHouseProductRepository | `src/data/clickhouse_repository.py` | Fetches products |
| RecommendationLogger | `src/engine/logging_service.py` | Logs events for ML |
| RecommendationLogRepository | `src/data/logging_repository.py` | Persists logs |

### Technology Stack

- **Language:** Python 3.13
- **Framework:** FastAPI
- **Database:** ClickHouse
- **Validation:** Pydantic
- **Testing:** pytest

---

## Data Model

### Customer Model (Anonymized)

```python
class Customer:
    customer_id: str          # Opaque identifier (no PII)
    retailer_id: str          # Tenant ID (e.g., "camillaandmarc-au")
    is_vip: bool
    preferences: CustomerPreferences
    dislikes: CustomerDislikes
    purchase_history: PurchaseHistory
    wishlist: WishlistSummary
    browsing: BrowsingBehavior
```

### Customer Signals

| Signal | Source | Fields |
|--------|--------|--------|
| **Preferences** | PREFERENCES table | categories, colors, brands, sizes |
| **Dislikes** | PREFERENCES table (dislike=true) | categories, colors, brands |
| **Purchase History** | ALLORDERS + ORDERLINE | total_purchases, total_spend, top_categories |
| **Wishlist** | TWCWISHLIST + WISHLISTITEM | active_items, wishlist_categories |
| **Browsing** | TWCCLICKSTREAM | viewed_products, cart_items, session_count |

### Preference JSON Format

Preferences are stored as JSON in the PREFERENCES table:

```json
{
  "categories": [
    {"id": "evening", "value": "evening", "source": "staff"}
  ],
  "colours": [
    {"id": "black", "value": "black", "source": "customer"},
    {"id": "orange", "value": "orange", "source": "staff", "dislike": true}
  ],
  "dresses": [
    {"id": "size_8", "value": "8", "source": "staff"}
  ],
  "tops": [
    {"id": "size_s", "value": "S", "source": "customer"}
  ]
}
```

### Preference Sources

| Source | Description | Confidence Multiplier |
|--------|-------------|----------------------|
| `customer` | Customer entered directly | 1.0x |
| `staff` | Staff entered during clienteling | 0.8x |
| `inferred` | Derived from behavior | 0.6x |

---

## Scoring Algorithm

### Overview

Products are scored against customer profiles using weighted feature matching:

```
Score = Σ (feature_score × feature_weight × source_multiplier)
```

### Scoring Features

| Feature | Weight | Description |
|---------|--------|-------------|
| Preference Match | 0.30 | Category, color, brand preferences |
| Purchase Affinity | 0.25 | Similar to past purchases |
| Wishlist Affinity | 0.15 | Similar to wishlisted items |
| Browsing Affinity | 0.10 | Similar to recently viewed |
| Popularity | 0.10 | Product engagement metrics |
| Newness | 0.05 | Recently added products |
| Size Availability | 0.05 | Customer's size in stock |

### Weight Configurations

| Config | Use Case |
|--------|----------|
| `DEFAULT_WEIGHTS` | Standard balanced recommendations |
| `PREFERENCE_HEAVY_WEIGHTS` | New customers with limited behavior data |
| `BEHAVIOR_HEAVY_WEIGHTS` | High-data customers |
| `NEW_CUSTOMER_WEIGHTS` | Zero purchase history |

### Filtering Pipeline

Before scoring, products are filtered:

1. **Retailer Match** - Same tenant_id as customer
2. **Stock Filter** - Optionally exclude out-of-stock
3. **Dislike Filter** - Hard exclude disliked categories/colors/brands
4. **Recently Purchased** - Exclude recent purchases
5. **Explicit Exclusions** - Items in cart, etc.

### Diversification

After scoring, results are diversified:

| Similarity | Penalty |
|------------|---------|
| Same category | -30% |
| Same brand | -20% |
| Same color | -10% |

---

## API Reference

### Generate Recommendations

```http
POST /api/recommendations
```

**Request:**
```json
{
  "customer_id": "2905235947555",
  "tenant_id": "camillaandmarc-au",
  "n": 4,
  "exclude_product_ids": ["P123"],
  "weights_preset": "default"
}
```

**Response:**
```json
{
  "recommendations": [
    {
      "product_id": "VAR-001",
      "name": "Silk Evening Dress",
      "score": 0.85,
      "reasons": [
        "Matches your style preference: Evening",
        "Similar to your past purchases"
      ],
      "price": 650.00,
      "image_url": "https://..."
    }
  ],
  "event_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Find Alternatives

```http
POST /api/alternatives
```

**Request:**
```json
{
  "product_id": "SOLD-OUT-001",
  "tenant_id": "camillaandmarc-au",
  "n": 3
}
```

### Log Outcome

```http
POST /api/outcomes
```

**Request:**
```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "outcome_type": "clicked",
  "product_id": "VAR-001",
  "position": 1
}
```

---

## Database Schema

### Source Tables

| Table | Purpose |
|-------|---------|
| PREFERENCES | Customer preferences (JSON) |
| ALLORDERS | Order headers |
| ORDERLINE | Order line items |
| TWCVARIANT | Product catalog |
| TWCWISHLIST | Wishlist headers |
| WISHLISTITEM | Wishlist items |
| TWCCLICKSTREAM | Browsing events |

### Logging Tables (New)

#### TWCRECOMMENDATION_LOG

Captures every recommendation event.

```sql
CREATE TABLE default.TWCRECOMMENDATION_LOG
(
    `eventId` String,
    `tenantId` String,
    `customerId` String,
    `staffId` String DEFAULT '',
    `sessionId` String DEFAULT '',
    `recommendationType` String,
    `recommendedItems` Array(String),
    `scores` Array(Float32),
    `positions` Array(UInt8),
    `contextFeatures` String DEFAULT '{}',
    `modelVersion` String DEFAULT 'rule-based-v1',
    `weightsConfig` String DEFAULT '',
    `recommendedAt` DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(recommendedAt)
ORDER BY (tenantId, customerId, recommendedAt)
TTL recommendedAt + INTERVAL 2 YEAR;
```

#### TWCRECOMMENDATION_OUTCOME

Captures interactions with recommendations.

```sql
CREATE TABLE default.TWCRECOMMENDATION_OUTCOME
(
    `eventId` String,
    `recommendationEventId` String,
    `tenantId` String,
    `customerId` String,
    `outcomeType` String,
    `itemId` String,
    `position` UInt8,
    `purchaseValue` Nullable(Float32),
    `daysToConversion` Nullable(Int32),
    `occurredAt` DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(occurredAt)
ORDER BY (tenantId, recommendationEventId, occurredAt)
TTL occurredAt + INTERVAL 2 YEAR;
```

See `migrations/001_recommendation_logging.sql` for full DDL including indexes and materialized views.

---

## ML Roadmap

### Phase Overview

| Phase | Status | Description |
|-------|--------|-------------|
| **1. Rule-Based Engine** | ✅ Complete | Feature matching with configurable weights |
| **2. Outcome Tracking** | 🚧 Next | Capture clicks, purchases, build baseline metrics |
| **3. A/B Testing** | 📋 Planned | Controlled experiments, traffic splitting |
| **4. ML Models** | 📋 Planned | Train models on outcome data |
| **5. Continuous Learning** | 📋 Planned | Online learning, Next Best Action |

### Phase 2: Outcome Tracking (Next)

**Objective:** Establish a feedback loop by capturing what happens after recommendations are shown.

**Deliverables:**
- Frontend integration to pass event_id
- Click tracking
- Purchase attribution (N-day window)
- Metrics dashboard (CTR, CVR, revenue)

**Duration:** 3-4 weeks

### Phase 3: A/B Testing

**Objective:** Enable controlled experiments to validate improvements.

**Deliverables:**
- Hash-based traffic splitting
- Variant management (different weights/models)
- Statistical significance testing
- Test management UI

**Duration:** 4-5 weeks

### Phase 4: ML Model Training

**Objective:** Replace rule-based scoring with learned models.

**Deliverables:**
- Feature store (customer, product, interaction features)
- Training pipeline (XGBoost/LightGBM)
- Model versioning (MLflow)
- Inference service with A/B integration

**Duration:** 8-12 weeks

### Phase 5: Continuous Learning & NBA

**Objective:** Self-improving system with Next Best Action.

**Deliverables:**
- Online learning from new interactions
- Next Best Action recommendations for staff
- Personalized outreach triggers
- Contextual bandits

**Duration:** 12-16 weeks (ongoing)

### Metrics to Track

| Category | Metrics |
|----------|---------|
| Engagement | CTR, View Rate, Cart Rate |
| Conversion | CVR, Revenue/Recommendation |
| Business | CLTV Impact, Return Rate |
| Model | NDCG, MRR, Coverage, Diversity |

---

## Integration Guide

### Prerequisites

- Python 3.13+
- ClickHouse access
- Environment variables configured

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| CLICKHOUSE_HOST | Server hostname | localhost |
| CLICKHOUSE_PORT | HTTP port | 8443 |
| CLICKHOUSE_USER | Username | default |
| CLICKHOUSE_PASSWORD | Password | (empty) |
| CLICKHOUSE_DATABASE | Database | default |
| CLICKHOUSE_SECURE | Use HTTPS | true |

### Usage Example

```python
from src.engine import RecommendationEngine, RecommendationLogger
from src.data import ClickHouseCustomerRepository, ClickHouseProductRepository
from src.config import get_clickhouse_config

# Initialize
config = get_clickhouse_config()
customer_repo = ClickHouseCustomerRepository(config)
product_repo = ClickHouseProductRepository(config)
engine = RecommendationEngine()
logger = RecommendationLogger(config)

# Fetch data
customer = customer_repo.get_customer("camillaandmarc-au", "2905235947555")
products = product_repo.get_products_for_retailer("camillaandmarc-au")

# Generate recommendations
recommendations = engine.recommend(customer, products, n=4)

# Log for ML (returns event_id for tracking outcomes)
event_id = logger.log_recommendations(
    customer=customer,
    recommendations=recommendations,
    staff_id="STAFF-001",
)

# Return event_id to frontend for outcome tracking
return {
    "recommendations": recommendations,
    "event_id": event_id
}
```

### Tracking Outcomes

```python
# When customer clicks a recommendation
logger.log_click(
    recommendation_event_id=event_id,
    tenant_id="camillaandmarc-au",
    customer_id="2905235947555",
    product_id="VAR-001",
    position=1,
)

# When customer purchases
logger.log_purchase(
    recommendation_event_id=event_id,
    tenant_id="camillaandmarc-au",
    customer_id="2905235947555",
    product_id="VAR-001",
    position=1,
    purchase_value=650.00,
    order_id="ORD-12345",
)
```

### Running Tests

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ --cov=src --cov-report=html
```

---

## Appendix

### File Structure

```
twc-recommendations/
├── src/
│   ├── api/
│   │   └── app.py                    # FastAPI endpoints
│   ├── config/
│   │   ├── __init__.py
│   │   ├── clickhouse.py             # ClickHouse config
│   │   └── weights.py                # Weight configurations
│   ├── data/
│   │   ├── __init__.py
│   │   ├── repository.py             # Mock repositories
│   │   ├── clickhouse_repository.py  # ClickHouse repositories
│   │   └── logging_repository.py     # Logging repository
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── recommender.py            # Main engine
│   │   ├── scorer.py                 # Scoring logic
│   │   └── logging_service.py        # Logging service
│   └── models/
│       ├── __init__.py
│       ├── customer.py               # Customer models
│       ├── product.py                # Product models
│       └── logging.py                # Logging models
├── tests/
│   └── test_recommender.py           # 18 tests
├── migrations/
│   └── 001_recommendation_logging.sql
├── docs/
│   ├── ARCHITECTURE.md
│   ├── ML_ROADMAP.md
│   └── CONFLUENCE_DOCUMENTATION.md
└── requirements.txt
```

### Glossary

| Term | Definition |
|------|------------|
| **CTR** | Click-Through Rate |
| **CVR** | Conversion Rate |
| **NBA** | Next Best Action |
| **NDCG** | Normalized Discounted Cumulative Gain |
| **MRR** | Mean Reciprocal Rank |
| **PII** | Personally Identifiable Information |

### References

- [ClickHouse Documentation](https://clickhouse.com/docs)
- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [Pydantic Documentation](https://docs.pydantic.dev)
