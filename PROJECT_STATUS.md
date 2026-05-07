# TWC Recommendations - Project Status

**Last Updated:** May 2025
**Status:** Data Integration Complete - Ready for Production Testing

---

## What It Does

A product recommendation engine for The Wishlist Company that provides personalized product suggestions for retail staff when VIP customers arrive.

**Primary Use Case:** Staff receives 3-4 personalized product recommendations when a VIP customer walks in the door.

---

## Current Features

### 1. Recommendation Engine
- Configurable scoring weights for each signal type
- Auto-detects new customers and adjusts strategy
- Diversity algorithm (avoids recommending 4 similar items)
- Human-readable explanations ("Matches preferred brand: Zimmermann")
- **Dislikes filtering** - Hard filter for products matching customer dislikes
- **Preference source tracking** - Staff vs customer-entered preferences with configurable multipliers
- **Recency weighting** - Recent purchases/views weighted higher

### 2. Data Signals Supported

| Signal Type | ClickHouse Table | Data Retrieved |
|-------------|------------------|----------------|
| **Preferences** | TWCPREFERENCES | Categories, colors, brands, styles, sizes, occasions |
| **Dislikes** | TWCPREFERENCES | Items marked with `dislike: true` |
| **Purchase History** | TWCALLORDERS, ORDERLINE | Top categories/brands/colors, recent purchases |
| **Wishlist** | TWCWISHLIST, WISHLISTITEM | Active items, categories, brands, colors |
| **Browsing** | TWCCLICKSTREAM | Viewed products, categories, brands, colors, cart items |
| **Products** | TWCVARIANT | Product catalog with attributes |

### 3. Sold-Out Alternatives
- Finds similar in-stock products for sold-out wishlist items
- Matches on: category, brand, style, color, fabric, price range

---

## Data Integration (Completed)

### ClickHouse Tables Used

| Table | Purpose |
|-------|---------|
| `TWCPREFERENCES` | Customer preferences JSON (retailer-specific schemas) |
| `TWCVARIANT` | Product catalog with category, brand, color |
| `TWCALLORDERS` | Order summary data |
| `ORDERLINE` | Order line items |
| `TWCWISHLIST` | Wishlist headers |
| `WISHLISTITEM` | Wishlist items |
| `TWCCLICKSTREAM` | Browsing events (views, cart adds) |

### Preference Schema Handling

The `_parse_preferences_json()` method uses pattern matching to handle different retailer schemas:

| Key Pattern | Maps To |
|-------------|---------|
| `*brand*` | `preferences.brands` |
| `*color*`, `*colour*` | `preferences.colors` |
| `*categor*`, `*clothing*`, `*footwear*` | `preferences.categories` |
| `*fit*`, `*style*`, `*cut*` | `preferences.styles` |
| `*occasion*` | `preferences.occasions` |
| `*fabric*`, `*material*` | `preferences.fabrics` |
| Garment keys (dresses, tops, etc.) | Size fields |

Supports single-brand retailers (e.g., `{"categories": [...]}`) and multi-brand retailers (e.g., `{"womens_brands": [...], "mens_clothing": [...]}`).

---

## API Endpoints

```
GET  /api/v1/recommendations/{retailer_id}/{customer_id}?n=4
POST /api/v1/recommendations/{retailer_id}/{customer_id}  (custom weights)
GET  /api/v1/similar/{retailer_id}/{product_id}
GET  /api/v1/alternatives/{retailer_id}/{product_id}
GET  /api/v1/wishlist-alternatives/{retailer_id}/{customer_id}
GET  /api/v1/health
```

---

## Project Structure

```
twc-recommendations/
├── src/
│   ├── api/
│   │   ├── app.py              # FastAPI application
│   │   └── routes.py           # API endpoints
│   ├── engine/
│   │   ├── scorer.py           # Product scoring algorithm
│   │   └── recommender.py      # Recommendation orchestration
│   ├── data/
│   │   ├── clickhouse_repository.py  # ClickHouse queries (production)
│   │   ├── repository.py             # Mock data (testing)
│   │   └── stock_client.py           # Stock status client
│   ├── models/
│   │   ├── customer.py         # Customer, Preferences, History, Browsing
│   │   └── product.py          # Product, Attributes, Metrics
│   └── config/
│       ├── weights.py          # Scoring weight presets
│       └── clickhouse.py       # ClickHouse connection config
├── tests/
│   └── test_recommender.py
├── requirements.txt
└── README.md
```

---

## Tech Stack

- **Language:** Python 3.13
- **Framework:** FastAPI
- **Validation:** Pydantic v2
- **Database:** ClickHouse Cloud
- **Testing:** pytest

---

## What's Next (To-Do)

### Stock Filtering
- [ ] Implement stock status check via DynamoDB API or Shopify directly
- [ ] Filter out-of-stock products from recommendations

### Scoring Enhancements
- [ ] **Product description matching** - Use description field for keyword/semantic matching (field is fetched but not yet used in scoring)
- [ ] **Fabric matching** - Add fabric preferences to scoring (model supports it, not yet implemented)

### Additional Use Cases
- [ ] **Complete the Look** - "You're trying on X, here's what pairs with it"
- [ ] **Real-time Fitting** - Incorporate "currently looking at" signal
- [ ] **Collaborative Filtering** - "Customers who bought X also bought Y"
- [ ] **Shopper-facing Widget** - Recommendations for website visitors

### Production Readiness
- [ ] Caching layer (Redis) for performance
- [ ] A/B testing framework
- [ ] Metrics/logging for recommendation quality
- [ ] Rate limiting

---

## Running Locally

```bash
cd twc-recommendations
source venv/bin/activate
pip install -r requirements.txt

# Run tests
PYTHONPATH=. pytest tests/ -v

# Start API server
uvicorn src.api.app:app --reload --port 8000

# Test endpoint
curl http://localhost:8000/api/v1/recommendations/retailer_luxe/cust_001
```

---

## Key Files to Review When Resuming

1. **`src/data/clickhouse_repository.py`** - All ClickHouse queries and preference parsing
2. **`src/config/weights.py`** - Scoring weights (adjust to tune recommendations)
3. **`src/engine/scorer.py`** - The scoring algorithm
4. **`src/models/customer.py`** - Customer profile data structures
