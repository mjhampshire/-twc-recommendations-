# TWC Recommendations Engine - Technical Documentation

## Overview

The TWC Recommendations Engine is a personalized product recommendation system designed for retail clienteling applications. It generates product recommendations based on customer preferences, purchase history, browsing behavior, and wishlist data.

**Current Status:** Rule-based scoring system (Phase 1)
**Target:** ML-powered recommendations with continuous learning (Phase 5)

---

## Architecture

### High-Level Architecture

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
                         │                       │
                         │  • PREFERENCES        │
                         │  • ALLORDERS          │
                         │  • ORDERLINE          │
                         │  • TWCWISHLIST        │
                         │  • TWCVARIANT         │
                         │  • TWCCLICKSTREAM     │
                         │  • TWCRECOMMENDATION_ │
                         │    LOG                │
                         │  • TWCRECOMMENDATION_ │
                         │    OUTCOME            │
                         └───────────────────────┘
```

### Component Responsibilities

| Component | Responsibility |
|-----------|---------------|
| **RecommendationEngine** | Orchestrates scoring, filtering, and ranking |
| **Scorer** | Calculates product scores against customer profile |
| **ClickHouseCustomerRepository** | Fetches and transforms customer data |
| **ClickHouseProductRepository** | Fetches product catalog |
| **RecommendationLogger** | Logs recommendation events and outcomes |
| **RecommendationLogRepository** | Persists logs and queries metrics |

---

## Data Model

### Customer Profile (Anonymized)

The customer model is intentionally anonymized. No PII (name, email, phone) is stored in the recommendation engine.

```python
class Customer:
    customer_id: str          # Opaque identifier (maps to source system)
    retailer_id: str          # Tenant ID (e.g., "camillaandmarc-au")
    is_vip: bool
    preferences: CustomerPreferences
    dislikes: CustomerDislikes
    purchase_history: PurchaseHistory
    wishlist: WishlistSummary
    browsing: BrowsingBehavior
```

### Customer Signals

| Signal | Source Table | Description |
|--------|-------------|-------------|
| **Preferences** | PREFERENCES | Category, color, brand, size preferences (staff or customer entered) |
| **Dislikes** | PREFERENCES | Items marked with `dislike: true` |
| **Purchase History** | ALLORDERS + ORDERLINE | Order count, spend, top categories/brands/colors |
| **Wishlist** | TWCWISHLIST + WISHLISTITEM | Active wishlist items, wishlisted categories |
| **Browsing** | TWCCLICKSTREAM | Viewed products, cart events, session data |

### Preference Sources

Preferences can come from different sources with different confidence levels:

| Source | Confidence | Multiplier |
|--------|-----------|------------|
| **CUSTOMER** | High - customer entered directly | 1.0x |
| **STAFF** | Medium - staff entered during clienteling | 0.8x |
| **INFERRED** | Low - derived from behavior | 0.6x |

---

## Scoring Algorithm

### Current Implementation: Rule-Based Scoring

Products are scored against customer profiles using weighted feature matching:

```
Final Score = Σ (feature_score × feature_weight × source_multiplier)
```

### Scoring Features

| Feature | Description | Default Weight |
|---------|-------------|----------------|
| **Preference Match** | Category, color, brand preferences | 0.30 |
| **Purchase Affinity** | Similar to past purchases | 0.25 |
| **Wishlist Affinity** | Similar to wishlisted items | 0.15 |
| **Browsing Affinity** | Similar to recently viewed | 0.10 |
| **Popularity** | Product engagement metrics | 0.10 |
| **Newness** | Recently added products | 0.05 |
| **Size Availability** | Customer's size in stock | 0.05 |

### Weight Configurations

| Config | Use Case | Key Differences |
|--------|----------|-----------------|
| **DEFAULT_WEIGHTS** | Standard recommendations | Balanced across all signals |
| **PREFERENCE_HEAVY_WEIGHTS** | New/low-data customers | 70% preference, 30% behavior |
| **BEHAVIOR_HEAVY_WEIGHTS** | High-data customers | 30% preference, 70% behavior |
| **NEW_CUSTOMER_WEIGHTS** | Zero purchase history | Popularity + preferences only |

### Filtering Rules

Before scoring, products are filtered:

1. **Retailer match** - Same tenant_id as customer
2. **Stock filter** - Optionally exclude out-of-stock items
3. **Dislike filter** - Hard exclude disliked categories/colors/brands
4. **Recently purchased** - Exclude items purchased in last N days
5. **Explicit exclusions** - Items already in cart, etc.

### Diversification

After scoring, results are diversified to avoid showing 4 similar items:

- Same category penalty: 30%
- Same brand penalty: 20%
- Same color penalty: 10%

---

## API Endpoints

### Generate Recommendations

```http
POST /api/recommendations
Content-Type: application/json

{
  "customer_id": "2905235947555",
  "tenant_id": "camillaandmarc-au",
  "n": 4,
  "exclude_product_ids": ["P123", "P456"],
  "weights_preset": "default"
}
```

**Response:**
```json
{
  "recommendations": [
    {
      "product_id": "VAR-001",
      "score": 0.85,
      "reasons": [
        "Matches your style preference: Evening",
        "Similar to your past purchases"
      ]
    }
  ],
  "event_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Find Alternatives (for sold-out wishlist items)

```http
POST /api/alternatives
Content-Type: application/json

{
  "product_id": "SOLD-OUT-001",
  "tenant_id": "camillaandmarc-au",
  "n": 3
}
```

---

## ClickHouse Tables

### Source Data Tables

| Table | Purpose | Key Fields |
|-------|---------|------------|
| **PREFERENCES** | Customer preferences JSON | tenantId, customerId, preferences |
| **ALLORDERS** | Order headers | tenantId, customerRef, amount, orderDate |
| **ORDERLINE** | Order line items | tenantId, variantRef, customerRef |
| **TWCVARIANT** | Product catalog | tenantId, variantRef, category, brand, color |
| **TWCWISHLIST** | Wishlist headers | tenantId, customerId, wishlistId |
| **WISHLISTITEM** | Wishlist items | wishlistId, productRef, category |
| **TWCCLICKSTREAM** | Browsing events | tenantId, customerRef, productRef, eventType |

### Logging Tables (New)

| Table | Purpose |
|-------|---------|
| **TWCRECOMMENDATION_LOG** | Logs every recommendation event |
| **TWCRECOMMENDATION_OUTCOME** | Logs interactions (clicks, purchases) |
| **TWCAB_TEST** | A/B test configurations |

See `migrations/001_recommendation_logging.sql` for full schemas.

---

## Usage Example

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

# Log the event (for ML training data)
event_id = logger.log_recommendations(
    customer=customer,
    recommendations=recommendations,
    staff_id="STAFF-001",
)

# Later, log outcomes as they occur
logger.log_click(event_id, "camillaandmarc-au", customer.customer_id, "VAR-001", 1)
logger.log_purchase(event_id, "camillaandmarc-au", customer.customer_id, "VAR-001", 1, 450.00)
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CLICKHOUSE_HOST` | ClickHouse server hostname | localhost |
| `CLICKHOUSE_PORT` | ClickHouse HTTP port | 8443 |
| `CLICKHOUSE_USER` | ClickHouse username | default |
| `CLICKHOUSE_PASSWORD` | ClickHouse password | (empty) |
| `CLICKHOUSE_DATABASE` | Database name | default |
| `CLICKHOUSE_SECURE` | Use HTTPS | true |

---

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=src --cov-report=html
```

Current test coverage: 18 tests passing
