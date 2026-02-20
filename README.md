# TWC Recommendations

Product recommendation engine for The Wishlist Company.

## Overview

This service provides personalized product recommendations based on:
- Customer preferences (categories, colors, fabrics, styles, brands)
- Purchase history
- Wishlist activity
- Product performance metrics

## Quick Start

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/ -v

# Start the API server
uvicorn src.api.app:app --reload --port 8000
```

## API Endpoints

### Get Recommendations
```
GET /api/v1/recommendations/{retailer_id}/{customer_id}?n=4
```

Returns top N personalized product recommendations for a customer.

**Example Response:**
```json
{
  "customer_id": "cust_001",
  "retailer_id": "retailer_luxe",
  "recommendations": [
    {
      "product": {
        "product_id": "prod_002",
        "name": "Zimmermann Floral Midi Dress",
        "price": 850
      },
      "score": 0.78,
      "reasons": [
        "Matches preferred category: Dresses",
        "Preferred brand: Zimmermann",
        "Matches preferred color: Navy"
      ]
    }
  ],
  "weights_used": "default"
}
```

### Custom Weights
```
POST /api/v1/recommendations/{retailer_id}/{customer_id}
```

Request body allows custom weight configuration:
```json
{
  "weights": {
    "preference_category": 0.25,
    "preference_brand": 0.20,
    "purchase_history_category": 0.15
  },
  "exclude_product_ids": ["prod_001"],
  "diversity_factor": 0.3
}
```

### Similar Products
```
GET /api/v1/similar/{retailer_id}/{product_id}?n=4
```

Returns products similar to a given product.

## Configuration

### Weight Presets

The engine supports different weighting strategies:

- **DEFAULT_WEIGHTS**: Balanced approach
- **PREFERENCE_HEAVY_WEIGHTS**: Prioritizes stated preferences
- **BEHAVIOR_HEAVY_WEIGHTS**: Prioritizes purchase/wishlist history
- **NEW_CUSTOMER_WEIGHTS**: For customers with limited data (auto-selected)

### Customizing Weights

```python
from src.config import RecommendationWeights

custom_weights = RecommendationWeights(
    preference_category=0.20,
    preference_brand=0.15,
    purchase_history_category=0.15,
    wishlist_similarity=0.15,
    # ... other weights
)
```

## Architecture

```
src/
├── api/            # FastAPI endpoints
│   ├── app.py      # Application setup
│   └── routes.py   # API routes
├── engine/         # Recommendation logic
│   ├── scorer.py   # Product scoring
│   └── recommender.py  # Main engine
├── data/           # Data access layer
│   └── repository.py   # Customer/Product repos
├── models/         # Pydantic models
│   ├── customer.py
│   └── product.py
└── config/         # Configuration
    └── weights.py  # Weight definitions
```

## Data Integration

The `repository.py` file contains mock data for development. For production:

1. **DynamoDB**: Customer profiles, preferences
2. **ClickHouse**: Purchase events, browsing behavior, aggregations
3. **Shopify**: Product catalog (future integration)

Replace the mock implementations in `CustomerRepository` and `ProductRepository` with actual database queries.

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

## Development Roadmap

- [ ] DynamoDB integration for customer data
- [ ] ClickHouse integration for behavioral data
- [ ] Real-time event ingestion
- [ ] "Complete the look" recommendations
- [ ] Collaborative filtering (customers also bought)
- [ ] A/B testing framework
- [ ] Caching layer for performance
