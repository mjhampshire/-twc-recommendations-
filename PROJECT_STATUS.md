# TWC Recommendations - Project Status

**Last Updated:** February 2025
**Status:** MVP Complete - Ready for Data Integration

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
- **Dislikes filtering** - Hard filter for products matching customer dislikes (brand, color, style, etc.)
- **Preference source tracking** - Each preference records whether it was entered by staff or customer, with configurable score multipliers

### 2. Data Signals Supported

| Signal Type | Source | Examples |
|-------------|--------|----------|
| **Preferences** | Customer profile | Categories, colors, fabrics, styles, brands, sizes (with staff/customer source tracking) |
| **Dislikes** | Customer profile | Categories, colors, fabrics, styles, brands to avoid (hard filter) |
| **Purchase History** | Transaction data | Top categories, brands, colors purchased |
| **Wishlist** | Wishlist activity | Wishlisted categories, brands, colors |
| **Browsing Behavior** | Website events (DynamoDB) | Viewed categories, brands; cart items |
| **Product Performance** | Aggregated metrics | Popularity, trending score |

### 3. Sold-Out Alternatives
- Finds similar in-stock products for sold-out wishlist items
- Matches on: category, brand, style, color, fabric, price range

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
│   ├── api/              # FastAPI endpoints
│   │   ├── app.py
│   │   └── routes.py
│   ├── engine/           # Core recommendation logic
│   │   ├── scorer.py     # Product scoring algorithm
│   │   └── recommender.py
│   ├── data/             # Data access layer
│   │   └── repository.py # Currently mock data
│   ├── models/           # Pydantic models
│   │   ├── customer.py   # Customer, Preferences, History, Browsing
│   │   └── product.py    # Product, Attributes, Metrics
│   └── config/
│       └── weights.py    # Configurable weight presets
├── tests/
│   └── test_recommender.py  # 18 tests, all passing
├── requirements.txt
└── README.md
```

---

## Tech Stack

- **Language:** Python 3.13
- **Framework:** FastAPI
- **Validation:** Pydantic v2
- **Testing:** pytest

**Production Dependencies (not yet integrated):**
- AWS DynamoDB (customer profiles, browsing events)
- ClickHouse Cloud (analytics, aggregations)
- Shopify API (future: product catalog)

---

## What's Next (To-Do)

### Data Integration
- [ ] Connect `CustomerRepository` to DynamoDB for real customer profiles
- [ ] Connect `ProductRepository` to product catalog (DynamoDB or Shopify)
- [ ] Add ClickHouse queries for behavioral aggregations
- [ ] Implement browsing event ingestion
- [ ] Populate `inStock` field in TWCVARIANT (currently frontend handles stock filtering)

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

## Git History

```
7437ef9 Add browsing behavior signals and sold-out alternatives
eb35ad9 TWC Recommendations - Initial commit
```

---

## Key Files to Review When Resuming

1. **`src/config/weights.py`** - All the scoring weights (adjust these to tune recommendations)
2. **`src/engine/scorer.py`** - The scoring algorithm
3. **`src/data/repository.py`** - Where to add real database connections
4. **`src/models/customer.py`** - Data structures for customer profile
