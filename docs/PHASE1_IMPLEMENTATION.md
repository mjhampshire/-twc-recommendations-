# TWC Recommendations - Phase 1 Implementation Guide

## Overview

This document covers the setup requirements for Phase 1 of the TWC Recommendations Engine:
1. ClickHouse base table definitions
2. API reference
3. Jira stories for implementation

---

## 1. ClickHouse Base Table Definitions

These are the **source tables** that the recommendation engine reads from. Most already exist in your ClickHouse instance - verify and create any missing tables.

### 1.1 PREFERENCES

Stores customer preferences entered by staff or customers.

```sql
CREATE TABLE IF NOT EXISTS default.PREFERENCES
(
    `id` String,
    `tenantId` String,
    `customerId` String,
    `preferences` String,  -- JSON containing categories, colours, sizes, etc.
    `rangeName` Nullable(String),
    `isPrimary` UInt8 DEFAULT 0,
    `deleted` String DEFAULT '0',
    `createdAt` DateTime DEFAULT now(),
    `updatedAt` DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(updatedAt)
ORDER BY (tenantId, customerId, updatedAt)
SETTINGS index_granularity = 8192;
```

**Preferences JSON Structure:**
```json
{
  "categories": [
    {"id": "evening", "value": "evening", "source": "staff"},
    {"id": "casual", "value": "casual", "source": "customer", "dislike": true}
  ],
  "colours": [
    {"id": "black", "value": "black", "source": "customer"},
    {"id": "orange", "value": "orange", "source": "staff", "dislike": true}
  ],
  "dresses": [{"id": "size_8", "value": "8", "source": "staff"}],
  "tops": [{"id": "size_s", "value": "S", "source": "customer"}],
  "bottoms": [{"id": "size_10", "value": "10", "source": "staff"}],
  "footwear": [{"id": "size_38", "value": "38", "source": "customer"}]
}
```

---

### 1.2 ALLORDERS

Order header information.

```sql
CREATE TABLE IF NOT EXISTS default.ALLORDERS
(
    `orderId` String,
    `tenantId` String,
    `orderRef` String,
    `orderDate` DateTime,
    `customerRef` String,
    `customerEmail` Nullable(String),
    `amount` Float32,
    `storeRef` Nullable(String),
    `storeName` Nullable(String),
    `staffRef` Nullable(String),
    `staffName` Nullable(String),
    `firstName` Nullable(String),
    `lastName` Nullable(String),
    `phone` Nullable(String),
    `eventType` String DEFAULT 'INSERT',
    `converted` String DEFAULT '0',
    `totalItems` UInt32 DEFAULT 0,
    `updatedAt` DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(orderDate)
ORDER BY (tenantId, customerRef, orderDate)
SETTINGS index_granularity = 8192;
```

---

### 1.3 ORDERLINE

Individual line items within orders.

```sql
CREATE TABLE IF NOT EXISTS default.ORDERLINE
(
    `orderLineId` String,
    `tenantId` String,
    `orderId` String,
    `variantRef` String,
    `customerRef` String,
    `quantity` UInt32 DEFAULT 1,
    `unitPrice` Float32,
    `totalPrice` Float32,
    `orderLineDate` DateTime,
    `updatedAt` DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(orderLineDate)
ORDER BY (tenantId, customerRef, orderLineDate)
SETTINGS index_granularity = 8192;
```

---

### 1.4 TWCVARIANT

Product catalog with variant-level detail.

```sql
CREATE TABLE default.TWCVARIANT
(
    `variantId` String,
    `productId` String,
    `tenantId` String,
    `productRef` String,
    `variantRef` String,
    `productName` String,
    `variantName` Nullable(String),
    `brand` Nullable(String),
    `category` Nullable(String),
    `subCategory` Nullable(String),
    `collection` Nullable(String),
    `color` Nullable(String),
    `size` Nullable(String),
    `sizeType` Nullable(String),
    `price` Float32,
    `tags` Nullable(String),
    `imageUrl` Nullable(String),
    `url` Nullable(String),
    `inStock` UInt8 DEFAULT 1,
    `status` String,                    -- Variant status (e.g., "in_stock", "out_of_stock")
    `deleted` UInt8 DEFAULT 1,
    `createdAt` DateTime DEFAULT now(),
    `updatedAt` DateTime DEFAULT now()
)
ENGINE = SharedReplacingMergeTree('/clickhouse/tables/{uuid}/{shard}', '{replica}', updatedAt)
ORDER BY (tenantId, variantRef)
SETTINGS index_granularity = 8192;
```

**Key Fields:**
- `status` - Variant availability status (used for frontend filtering)
- `collection` - Fashion collection (e.g., "Summer 2025")
- `subCategory` - Product subcategory
- `sizeType` - Size system (e.g., "AU", "US", "EU")
- `tags` - Searchable tags

---

### 1.5 TWCWISHLIST

Wishlist headers.

```sql
CREATE TABLE IF NOT EXISTS default.TWCWISHLIST
(
    `wishlistId` String,
    `tenantId` String,
    `customerId` String,
    `name` Nullable(String),
    `deleted` String DEFAULT '0',
    `createdAt` DateTime DEFAULT now(),
    `updatedAt` DateTime DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY (tenantId, customerId, wishlistId)
SETTINGS index_granularity = 8192;
```

---

### 1.6 WISHLISTITEM

Individual wishlist items.

```sql
CREATE TABLE IF NOT EXISTS default.WISHLISTITEM
(
    `itemId` String,
    `tenantId` String,
    `wishlistId` String,
    `productRef` String,
    `variantRef` Nullable(String),
    `category` Nullable(String),
    `brandId` Nullable(String),
    `deleted` String DEFAULT '0',
    `purchased` String DEFAULT '0',
    `createdAt` DateTime DEFAULT now(),
    `updatedAt` DateTime DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY (tenantId, wishlistId, productRef)
SETTINGS index_granularity = 8192;
```

---

### 1.7 TWCCLICKSTREAM

Customer browsing behavior.

```sql
CREATE TABLE IF NOT EXISTS default.TWCCLICKSTREAM
(
    `eventId` String,
    `tenantId` String,
    `customerRef` String,
    `sessionId` Nullable(String),
    `productRef` Nullable(String),
    `variantRef` Nullable(String),
    `productType` Nullable(String),  -- category
    `brand` Nullable(String),
    `eventType` String,  -- 'view', 'add_to_cart', 'remove_from_cart', etc.
    `pageUrl` Nullable(String),
    `timeStamp` DateTime,
    `updatedAt` DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timeStamp)
ORDER BY (tenantId, customerRef, timeStamp)
TTL timeStamp + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;
```

---

### 1.8 Logging Tables (New for Recommendations)

See `migrations/001_recommendation_logging.sql` for:
- `TWCRECOMMENDATION_LOG` - Recommendation events
- `TWCRECOMMENDATION_OUTCOME` - Interaction outcomes
- `TWCAB_TEST` - A/B test configurations

---

## 2. API Reference

Base URL: `/api/v1`

### 2.1 Get Recommendations

**Endpoint:** `GET /recommendations/{retailer_id}/{customer_id}`

Generate personalized product recommendations for a customer.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `retailer_id` | path | Yes | Tenant ID (e.g., "camillaandmarc-au") |
| `customer_id` | path | Yes | Customer ID |
| `n` | query | No | Number of recommendations (1-20, default: 4) |
| `exclude` | query | No | Comma-separated product IDs to exclude |

**Response:**
```json
{
  "customer_id": "2905235947555",
  "retailer_id": "camillaandmarc-au",
  "recommendations": [
    {
      "product": {
        "product_id": "VAR-001",
        "name": "Silk Evening Dress",
        "price": 650.00,
        "image_url": "https://...",
        "attributes": {
          "category": "Dresses",
          "brand": "Camilla and Marc",
          "color": "Black"
        }
      },
      "score": 0.85,
      "score_breakdown": {
        "preference_match": 0.30,
        "purchase_affinity": 0.25,
        "wishlist_affinity": 0.15
      },
      "reasons": [
        "Matches your style preference: Evening",
        "Similar to your past purchases",
        "Available in your size"
      ]
    }
  ],
  "weights_used": "default"
}
```

---

### 2.2 Get Recommendations (Custom Weights)

**Endpoint:** `POST /recommendations/{retailer_id}/{customer_id}`

Generate recommendations with custom weight configuration.

**Request Body:**
```json
{
  "weights": {
    "preference_match": 0.40,
    "purchase_affinity": 0.20,
    "wishlist_affinity": 0.20,
    "browsing_affinity": 0.10,
    "popularity": 0.05,
    "newness": 0.05
  },
  "exclude_product_ids": ["P123", "P456"],
  "diversity_factor": 0.3
}
```

---

### 2.3 Get Similar Products

**Endpoint:** `GET /similar/{retailer_id}/{product_id}`

Find products similar to a given product.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `retailer_id` | path | Yes | Tenant ID |
| `product_id` | path | Yes | Source product ID |
| `n` | query | No | Number of results (1-20, default: 4) |

**Response:** Array of `Product` objects.

---

### 2.4 Get Product Alternatives

**Endpoint:** `GET /alternatives/{retailer_id}/{product_id}`

Find in-stock alternatives for a sold-out product.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `retailer_id` | path | Yes | Tenant ID |
| `product_id` | path | Yes | Sold-out product ID |
| `n` | query | No | Number of alternatives (1-10, default: 3) |

**Response:** Array of `ScoredProduct` objects with similarity scores.

---

### 2.5 Get Wishlist Alternatives

**Endpoint:** `GET /wishlist-alternatives/{retailer_id}/{customer_id}`

Find alternatives for all sold-out items in a customer's wishlist.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `retailer_id` | path | Yes | Tenant ID |
| `customer_id` | path | Yes | Customer ID |
| `n_per_item` | query | No | Alternatives per item (1-5, default: 2) |

**Response:**
```json
{
  "customer_id": "2905235947555",
  "retailer_id": "camillaandmarc-au",
  "alternatives": {
    "SOLD-OUT-001": [
      {"product": {...}, "score": 0.85, "reasons": ["Same category", "Same brand"]},
      {"product": {...}, "score": 0.72, "reasons": ["Same category", "Similar price"]}
    ]
  },
  "sold_out_count": 1
}
```

---

### 2.6 Health Check

**Endpoint:** `GET /health`

**Response:**
```json
{
  "status": "healthy",
  "service": "twc-recommendations"
}
```

---

## 3. Jira Stories for Phase 1

### Epic: TWC-REC - Recommendation Engine Phase 1

---

#### TWC-REC-001: Set up ClickHouse base tables
**Type:** Task
**Points:** 3
**Description:**
Verify existing tables and create any missing base tables in ClickHouse for the recommendation engine.

**Acceptance Criteria:**
- [ ] PREFERENCES table exists with correct schema
- [ ] ALLORDERS table exists with correct schema
- [ ] ORDERLINE table exists with correct schema
- [ ] TWCVARIANT table exists with correct schema
- [ ] TWCWISHLIST table exists with correct schema
- [ ] WISHLISTITEM table exists with correct schema
- [ ] TWCCLICKSTREAM table exists with correct schema
- [ ] All tables have appropriate indexes

---

#### TWC-REC-002: Create recommendation logging tables
**Type:** Task
**Points:** 2
**Description:**
Execute the migration script to create recommendation logging tables for ML training data.

**Acceptance Criteria:**
- [ ] TWCRECOMMENDATION_LOG table created
- [ ] TWCRECOMMENDATION_OUTCOME table created
- [ ] TWCAB_TEST table created
- [ ] Materialized views created for metrics aggregation

---

#### TWC-REC-003: Deploy recommendation API to staging
**Type:** Task
**Points:** 5
**Description:**
Deploy the TWC Recommendations FastAPI service to the staging environment.

**Acceptance Criteria:**
- [ ] Docker image built and pushed to registry
- [ ] Service deployed to staging Kubernetes cluster
- [ ] Environment variables configured (CLICKHOUSE_*)
- [ ] Health check endpoint responding
- [ ] API documentation accessible at /docs

---

#### TWC-REC-004: Configure ClickHouse connectivity
**Type:** Task
**Points:** 2
**Description:**
Configure the recommendation service to connect to the production ClickHouse cluster.

**Acceptance Criteria:**
- [ ] Secure connection established (TLS)
- [ ] Read-only credentials configured
- [ ] Connection pooling verified
- [ ] Query timeouts configured

---

#### TWC-REC-005: Validate customer data pipeline
**Type:** Task
**Points:** 3
**Description:**
Verify that customer data flows correctly from source systems to ClickHouse and is readable by the recommendation engine.

**Acceptance Criteria:**
- [ ] PREFERENCES data syncing from DynamoDB
- [ ] ALLORDERS data syncing correctly
- [ ] ORDERLINE data syncing correctly
- [ ] Customer profile assembles correctly via API
- [ ] Test with 5 real customer IDs

---

#### TWC-REC-006: Validate product catalog pipeline
**Type:** Task
**Points:** 2
**Description:**
Verify that product catalog data is available and correctly formatted in TWCVARIANT.

**Acceptance Criteria:**
- [ ] TWCVARIANT populated with current products
- [ ] All required fields present (category, brand, color, price, inStock)
- [ ] Product images accessible via imageUrl
- [ ] Stock status reflects reality

---

#### TWC-REC-007: Integrate recommendations API with Styleboard
**Type:** Story
**Points:** 5
**Description:**
Integrate the recommendation API with the Styleboard application to display personalized product suggestions.

**Acceptance Criteria:**
- [ ] Styleboard calls GET /recommendations/{retailer}/{customer}
- [ ] Recommendations displayed in dedicated panel
- [ ] Score reasons shown as tooltips
- [ ] Drag-and-drop from recommendations to canvas works
- [ ] Loading and error states handled

---

#### TWC-REC-008: Integrate recommendations API with ClientApp
**Type:** Story
**Points:** 5
**Description:**
Integrate the recommendation API with the ClientApp (customer-facing) to show personalized suggestions.

**Acceptance Criteria:**
- [ ] ClientApp calls recommendations API on customer login
- [ ] "Recommended for You" section displays products
- [ ] Click tracking implemented (for Phase 2)
- [ ] Fallback to popular items if no recommendations

---

#### TWC-REC-009: Implement sold-out alternatives in Wishlist
**Type:** Story
**Points:** 3
**Description:**
Show in-stock alternatives for sold-out wishlist items using the alternatives API.

**Acceptance Criteria:**
- [ ] Wishlist page calls /wishlist-alternatives endpoint
- [ ] Sold-out items show "Similar items available" badge
- [ ] Clicking shows alternative product cards
- [ ] Alternatives can be added to wishlist

---

#### TWC-REC-010: Add recommendation event logging
**Type:** Task
**Points:** 3
**Description:**
Integrate RecommendationLogger into the API to log all recommendation events.

**Acceptance Criteria:**
- [ ] Every recommendation request logged to TWCRECOMMENDATION_LOG
- [ ] Event ID returned in API response
- [ ] Context features captured (purchase count, preferences, etc.)
- [ ] Model version logged correctly

---

#### TWC-REC-011: Create monitoring dashboard
**Type:** Task
**Points:** 3
**Description:**
Create a Grafana dashboard to monitor recommendation service health and performance.

**Acceptance Criteria:**
- [ ] Request rate and latency charts
- [ ] Error rate monitoring
- [ ] ClickHouse query performance
- [ ] Recommendations per customer distribution
- [ ] Alerts configured for high error rates

---

#### TWC-REC-012: Load testing and performance tuning
**Type:** Task
**Points:** 3
**Description:**
Perform load testing and optimize query performance for production traffic.

**Acceptance Criteria:**
- [ ] Load test with expected peak traffic (X req/s)
- [ ] P95 latency < 500ms
- [ ] No memory leaks under sustained load
- [ ] ClickHouse queries optimized
- [ ] Connection pool sized correctly

---

#### TWC-REC-013: Write API documentation
**Type:** Task
**Points:** 2
**Description:**
Create comprehensive API documentation for consumers.

**Acceptance Criteria:**
- [ ] OpenAPI spec complete and accurate
- [ ] Example requests/responses documented
- [ ] Error codes and handling documented
- [ ] Authentication requirements documented
- [ ] Rate limits documented

---

#### TWC-REC-014: Deploy to production
**Type:** Task
**Points:** 3
**Description:**
Deploy the recommendation service to production with feature flag for gradual rollout.

**Acceptance Criteria:**
- [ ] Service deployed to production cluster
- [ ] Feature flag controls which tenants have access
- [ ] Rollout to 1 pilot tenant initially
- [ ] Monitoring confirms stable performance
- [ ] Runbook created for on-call

---

### Phase 1 Summary

| Story ID | Title | Points |
|----------|-------|--------|
| TWC-REC-001 | Set up ClickHouse base tables | 3 |
| TWC-REC-002 | Create recommendation logging tables | 2 |
| TWC-REC-003 | Deploy recommendation API to staging | 5 |
| TWC-REC-004 | Configure ClickHouse connectivity | 2 |
| TWC-REC-005 | Validate customer data pipeline | 3 |
| TWC-REC-006 | Validate product catalog pipeline | 2 |
| TWC-REC-007 | Integrate with Styleboard | 5 |
| TWC-REC-008 | Integrate with ClientApp | 5 |
| TWC-REC-009 | Implement sold-out alternatives | 3 |
| TWC-REC-010 | Add recommendation event logging | 3 |
| TWC-REC-011 | Create monitoring dashboard | 3 |
| TWC-REC-012 | Load testing and tuning | 3 |
| TWC-REC-013 | Write API documentation | 2 |
| TWC-REC-014 | Deploy to production | 3 |

**Total Points:** 44

**Suggested Sprint Breakdown:**
- **Sprint 1 (Infrastructure):** TWC-REC-001, 002, 003, 004 (12 pts)
- **Sprint 2 (Validation):** TWC-REC-005, 006, 010, 013 (10 pts)
- **Sprint 3 (Integration):** TWC-REC-007, 008, 009 (13 pts)
- **Sprint 4 (Production):** TWC-REC-011, 012, 014 (9 pts)
