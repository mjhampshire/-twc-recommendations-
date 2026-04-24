# Product Enrichment & New Arrival Alerts

## Overview

This document outlines the architecture for:
1. **Image-based product enrichment** - Async scanning of product images to detect patterns, styles, and attributes
2. **New arrival alerts** - Proactive notifications when new products match customer preferences
3. **Auto-inferred preferences** - System-detected preferences marked with source "auto"

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PRODUCT INGEST FLOW                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Shopify ──────▶ Product Sync ──────▶ TWCVARIANT ──────▶ Event Published   │
│  (webhook)       (existing)           (ClickHouse)       (new product)      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                                              │
                                                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        ASYNC ENRICHMENT PIPELINE                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐                │
│  │ Image        │     │ Attribute    │     │ New Arrival  │                │
│  │ Scanner      │────▶│ Writer       │────▶│ Matcher      │                │
│  │ (CLIP)       │     │ (ClickHouse) │     │              │                │
│  └──────────────┘     └──────────────┘     └──────────────┘                │
│         │                    │                    │                         │
│         ▼                    ▼                    ▼                         │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐                │
│  │ Detected:    │     │ TWCPRODUCT_  │     │ TWCNEW_      │                │
│  │ - pattern    │     │ ENRICHMENT   │     │ ARRIVAL_     │                │
│  │ - neckline   │     │ (new table)  │     │ ALERTS       │                │
│  │ - colors     │     │              │     │ (new table)  │                │
│  └──────────────┘     └──────────────┘     └──────────────┘                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component 1: Image Scanner Service

### Purpose
Asynchronously process product images to detect visual attributes not provided by Shopify.

### Detected Attributes

| Attribute | Values | Detection Method |
|-----------|--------|------------------|
| `pattern` | solid, striped, floral, checkered, polka_dot, animal_print, geometric, abstract | CLIP zero-shot |
| `dominant_colors` | Array of detected colors | CLIP + color extraction |
| `neckline` | crew, v_neck, scoop, off_shoulder, halter, collared, turtleneck | CLIP zero-shot |
| `sleeve_length` | sleeveless, short, three_quarter, long | CLIP zero-shot |
| `fit` | fitted, relaxed, oversized | CLIP zero-shot |
| `length` | cropped, regular, midi, maxi | CLIP zero-shot (for dresses/skirts) |

### Technology Choice: CLIP

**Why CLIP:**
- Zero-shot classification - no training data needed
- Natural language queries: "Is this a striped pattern?"
- Open source (MIT license)
- Runs locally or via Hugging Face Inference API
- Handles fashion domain well

**Alternative:** Fine-tuned ResNet on fashion dataset for higher accuracy on specific attributes, but requires labeled training data.

### Trigger Modes

1. **Event-driven (primary):**
   - New product published event → Queue message → Scanner processes
   - Latency: Minutes after product sync

2. **Batch backfill:**
   - One-time or scheduled job for existing products
   - Process products where `enrichment_status IS NULL`

3. **Manual re-scan:**
   - API endpoint to re-process specific products
   - Useful after model improvements

### Service Design

```python
class ImageScanner:
    """Scans product images for visual attributes using CLIP."""

    def __init__(self, model: str = "openai/clip-vit-base-patch32"):
        self.model = CLIPModel.from_pretrained(model)
        self.processor = CLIPProcessor.from_pretrained(model)

    def scan_product(self, image_url: str) -> ProductEnrichment:
        """
        Scan a product image and return detected attributes.

        Returns:
            ProductEnrichment with pattern, colors, neckline, etc.
        """
        image = self._load_image(image_url)

        return ProductEnrichment(
            pattern=self._detect_pattern(image),
            dominant_colors=self._extract_colors(image),
            neckline=self._detect_neckline(image),
            sleeve_length=self._detect_sleeve_length(image),
            fit=self._detect_fit(image),
            confidence_scores={...},
        )

    def _detect_pattern(self, image) -> str:
        """Zero-shot classification for pattern."""
        labels = ["solid color", "striped", "floral", "checkered",
                  "polka dot", "animal print", "geometric", "abstract"]
        return self._classify(image, labels)

    def _classify(self, image, labels: list[str]) -> str:
        """Run CLIP zero-shot classification."""
        inputs = self.processor(
            text=labels,
            images=image,
            return_tensors="pt",
            padding=True
        )
        outputs = self.model(**inputs)
        probs = outputs.logits_per_image.softmax(dim=1)
        return labels[probs.argmax()]
```

### Database Schema

```sql
-- New table for enriched product attributes
CREATE TABLE IF NOT EXISTS TWCPRODUCT_ENRICHMENT (
    tenantId String,
    productId String,
    variantId String,

    -- Detected attributes
    pattern String DEFAULT '',           -- 'striped', 'floral', 'solid', etc.
    dominantColors Array(String),         -- ['navy', 'white', 'gold']
    neckline String DEFAULT '',           -- 'v_neck', 'crew', etc.
    sleeveLength String DEFAULT '',       -- 'sleeveless', 'short', 'long'
    fit String DEFAULT '',                -- 'fitted', 'relaxed', 'oversized'
    length String DEFAULT '',             -- 'cropped', 'midi', 'maxi'

    -- Confidence scores (0-1)
    patternConfidence Float32 DEFAULT 0,

    -- Processing metadata
    imageUrl String,
    modelVersion String DEFAULT 'clip-vit-base-patch32',
    processedAt DateTime DEFAULT now(),
    processingStatus String DEFAULT 'pending',  -- 'pending', 'completed', 'failed'
    errorMessage String DEFAULT ''

) ENGINE = ReplacingMergeTree(processedAt)
ORDER BY (tenantId, productId, variantId);
```

---

## Component 2: New Arrival Matcher

### Purpose
When a new product arrives, find customers whose preferences match and create alerts for proactive outreach.

### Matching Logic

A product matches a customer if:
1. **Category match** - Product category in customer's preferred categories
2. **Brand match** - Product brand in customer's preferred brands
3. **Color match** - Product color(s) in customer's preferred colors
4. **Pattern match** - Product pattern in customer's preferred patterns (NEW)
5. **Style match** - Product style in customer's preferred styles
6. **NOT in dislikes** - No attributes match customer dislikes

### Match Scoring

```python
def calculate_match_score(product: Product, customer: Customer) -> float:
    """
    Calculate how well a product matches customer preferences.

    Returns score 0-1 where higher = better match.
    """
    score = 0.0
    max_score = 0.0

    # Category match (weight: 0.25)
    if product.category in customer.preferences.categories:
        score += 0.25
    max_score += 0.25

    # Brand match (weight: 0.20)
    if product.brand in customer.preferences.brands:
        score += 0.20
    max_score += 0.20

    # Color match (weight: 0.20)
    if any(c in customer.preferences.colors for c in product.colors):
        score += 0.20
    max_score += 0.20

    # Pattern match (weight: 0.15) - NEW
    if product.pattern in customer.preferences.patterns:
        score += 0.15
    max_score += 0.15

    # Style match (weight: 0.10)
    if product.style in customer.preferences.styles:
        score += 0.10
    max_score += 0.10

    # Size availability (weight: 0.10)
    if customer_size_available(product, customer):
        score += 0.10
    max_score += 0.10

    return score / max_score if max_score > 0 else 0
```

### Alert Generation

Only generate alerts when:
- Match score > threshold (e.g., 0.6)
- Customer has opted into alerts (or is VIP)
- Product is in stock
- Customer hasn't been alerted recently (cooldown period)

### Database Schema

```sql
-- New arrival alerts for proactive outreach
CREATE TABLE IF NOT EXISTS TWCNEW_ARRIVAL_ALERTS (
    alertId String,
    tenantId String,
    customerId String,
    productId String,

    -- Match details
    matchScore Float32,                    -- 0-1, how well product matches preferences
    matchReasons Array(String),            -- ['Matches floral preference', 'Favorite brand']

    -- Alert metadata
    collectionName String DEFAULT '',      -- 'Summer 2024', 'Resort Collection'
    alertType String DEFAULT 'new_arrival', -- 'new_arrival', 'back_in_stock', 'price_drop'

    -- Status tracking
    status String DEFAULT 'pending',       -- 'pending', 'sent', 'viewed', 'dismissed', 'converted'
    createdAt DateTime DEFAULT now(),
    sentAt Nullable(DateTime),
    viewedAt Nullable(DateTime),
    convertedAt Nullable(DateTime),

    -- Delivery channel
    channel String DEFAULT ''              -- 'app', 'email', 'sms', 'staff_app'

) ENGINE = ReplacingMergeTree(createdAt)
ORDER BY (tenantId, customerId, createdAt);

-- Index for fetching pending alerts per customer
ALTER TABLE TWCNEW_ARRIVAL_ALERTS ADD INDEX idx_pending (status) TYPE set(100) GRANULARITY 4;
```

### Alert Message Generation

```python
def generate_alert_message(
    customer: Customer,
    product: Product,
    match_reasons: list[str],
    tone: str = "friendly"
) -> str:
    """
    Generate personalized alert message.

    Examples:
    - "Hi Jane, this just arrived and we thought of you - a floral midi dress
       from Zimmermann, one of your favorite brands."
    - "Sarah, the Summer collection just dropped with some gorgeous striped
       pieces we know you'll love."
    """
    # Could use Claude for natural language generation
    # Or template-based for simpler implementation
    ...
```

---

## Component 3: Auto-Inferred Preferences

### Purpose
Track preferences that are system-detected (from behavior or image analysis) separately from explicit preferences added by staff or customers.

### Preference Sources

```python
class PreferenceSource(str, Enum):
    CUSTOMER = "customer"   # Customer explicitly stated
    STAFF = "staff"         # Staff added based on conversation
    AUTO = "auto"           # System inferred from behavior/analysis
```

### Auto-Inference Rules

| Source Data | Inferred Preference | Confidence Threshold |
|-------------|---------------------|---------------------|
| 3+ purchases in category | Category preference | High |
| 3+ purchases of pattern | Pattern preference | High |
| 5+ views of brand | Brand interest | Medium |
| Wishlist items | Strong interest in those attributes | High |
| Cart abandonment | Interest (but maybe price sensitive) | Medium |

### Key Principle: Auto Never Overwrites Explicit

```python
def maybe_add_preference(
    customer_id: str,
    preference_type: str,  # 'color', 'pattern', 'brand', etc.
    value: str,
    source: PreferenceSource,
) -> bool:
    """
    Add a preference only if it doesn't conflict with explicit preferences.

    Rules:
    - AUTO never overwrites CUSTOMER or STAFF
    - AUTO can add new preferences not explicitly set
    - If customer explicitly dislikes something, AUTO cannot like it
    """
    existing = get_preference(customer_id, preference_type, value)

    if existing:
        # Never overwrite explicit with auto
        if existing.source in (PreferenceSource.CUSTOMER, PreferenceSource.STAFF):
            return False
        # Can update auto with newer auto
        if source == PreferenceSource.AUTO:
            return update_preference(...)

    # Check if this conflicts with explicit dislikes
    if is_explicit_dislike(customer_id, preference_type, value):
        return False

    return add_preference(customer_id, preference_type, value, source)
```

### Source-Based Weighting

**Auto-inferred preferences carry less weight than explicit preferences.**

The scoring model applies a multiplier based on preference source:

```python
# In config/weights.py - source multipliers
class RecommendationWeights(BaseModel):
    # ... existing weights ...

    # Source multipliers (applied to preference match scores)
    customer_source_multiplier: float = 1.0   # Full weight - customer said it
    staff_source_multiplier: float = 1.0      # Full weight - staff confirmed
    auto_source_multiplier: float = 0.6       # Reduced weight - system inferred
```

**Example scoring impact:**

| Preference | Source | Base Score | Multiplier | Final Score |
|------------|--------|------------|------------|-------------|
| "Loves florals" | CUSTOMER | 0.12 | 1.0 | 0.12 |
| "Likes navy" | STAFF | 0.08 | 1.0 | 0.08 |
| "Interested in Zimmermann" | AUTO | 0.08 | 0.6 | 0.048 |

**Implementation in scorer.py:**

```python
def _score_preference_match(
    product: Product,
    preferences: CustomerPreferences,
    weights: RecommendationWeights,
) -> float:
    """Score based on preference matches, weighted by source."""
    score = 0.0

    # Category preference
    for pref in preferences.categories:
        if product.category.lower() == pref.value.lower():
            multiplier = _get_source_multiplier(pref.source, weights)
            score += weights.preference_category * multiplier

    # Pattern preference (NEW)
    for pref in preferences.patterns:
        if product.pattern.lower() == pref.value.lower():
            multiplier = _get_source_multiplier(pref.source, weights)
            score += weights.preference_pattern * multiplier

    # ... similar for colors, brands, styles ...

    return score


def _get_source_multiplier(
    source: PreferenceSource,
    weights: RecommendationWeights,
) -> float:
    """Get the weighting multiplier for a preference source."""
    if source == PreferenceSource.CUSTOMER:
        return weights.customer_source_multiplier
    elif source == PreferenceSource.STAFF:
        return weights.staff_source_multiplier
    elif source == PreferenceSource.AUTO:
        return weights.auto_source_multiplier
    return 1.0  # Default
```

**Rationale:**
- Customer explicitly stating "I love florals" is a strong signal (1.0x)
- Staff observing and adding "she prefers navy" is equally strong (1.0x)
- System inferring "seems to like Zimmermann" from 3 purchases is weaker (0.6x)

The 0.6x multiplier for AUTO is configurable. It should be:
- High enough that auto preferences contribute meaningfully
- Low enough that explicit preferences clearly win when in conflict

### UI Display

When showing preferences in staff app:
- **Customer-added:** "Jane told us she loves florals"
- **Staff-added:** "Added by Sarah on 15 Jan"
- **Auto-inferred:** "Based on purchase history" (with option to confirm/dismiss)

Staff can **confirm** an auto preference, which promotes it to STAFF source (full weight).
Staff can **dismiss** an auto preference, which removes it.

---

## Data Flow: End-to-End Example

### Scenario: New floral dress arrives

```
1. PRODUCT SYNC
   └── Shopify webhook → Product sync service → TWCVARIANT
       └── New product: "Floral Midi Dress" by Zimmermann
       └── Shopify attributes: category=Dresses, color=Multi

2. IMAGE ENRICHMENT (async, ~30 seconds later)
   └── Event: new_product_created
   └── Image Scanner downloads image, runs CLIP
   └── Detected: pattern=floral, neckline=v_neck, length=midi,
                 dominant_colors=[pink, green, white]
   └── Writes to TWCPRODUCT_ENRICHMENT

3. NEW ARRIVAL MATCHING (async, ~1 minute later)
   └── Event: product_enrichment_completed
   └── Query: Find customers where:
       - preferences.categories contains 'Dresses'
       - preferences.brands contains 'Zimmermann' OR
       - preferences.patterns contains 'floral'
       - NOT dislikes any of the above
   └── Found: 47 matching customers
   └── Create alerts for customers with match_score > 0.6
   └── Write to TWCNEW_ARRIVAL_ALERTS

4. ALERT DELIVERY
   └── Staff app: Shows "3 new arrivals for Jane" badge
   └── Or: Push notification / email (if enabled)

5. STAFF INTERACTION
   └── Staff views alert: "Floral Midi Dress matches Jane's love of
       florals and Zimmermann"
   └── Staff sends message to Jane
   └── Alert status → 'sent'

6. CONVERSION TRACKING
   └── Jane purchases the dress
   └── Alert status → 'converted'
   └── Metrics: new arrival alerts → conversions
```

---

## API Endpoints

### Image Scanner Service

```
POST /api/v1/enrichment/scan/{product_id}
  - Manually trigger scan for a product
  - Returns: enrichment results

POST /api/v1/enrichment/backfill
  - Body: { "tenant_id": "...", "limit": 1000 }
  - Triggers batch backfill job
  - Returns: job_id

GET /api/v1/enrichment/{product_id}
  - Get enrichment data for a product
```

### New Arrival Alerts

```
GET /api/v1/alerts/{retailer_id}/{customer_id}
  - Get pending alerts for a customer
  - Query params: status=pending, limit=10

POST /api/v1/alerts/{alert_id}/sent
  - Mark alert as sent

POST /api/v1/alerts/{alert_id}/dismissed
  - Customer/staff dismissed the alert

GET /api/v1/alerts/{retailer_id}/stats
  - Alert metrics: created, sent, viewed, converted
```

### Recommendation Engine Updates

```
GET /api/v1/recommendations/{retailer_id}/{customer_id}
  - (existing) Now includes enriched attributes in scoring

GET /api/v1/new-arrivals/{retailer_id}/{customer_id}
  - NEW: Get new arrivals that match customer preferences
  - Returns products from last N days with match scores
```

---

## Implementation Phases

### Phase 1: Image Enrichment (Foundation)
- [ ] Create TWCPRODUCT_ENRICHMENT table
- [ ] Build ImageScanner service with CLIP
- [ ] Event-driven processing for new products
- [ ] Backfill endpoint for existing catalog
- [ ] Add enriched attributes to product queries

### Phase 2: Preference Model Updates
- [ ] Add PreferenceSource.AUTO enum value
- [ ] Add `pattern` to CustomerPreferences
- [ ] Add `patterns` to CustomerDislikes
- [ ] Update scoring to include pattern matching
- [ ] Update matches_dislikes() for patterns

### Phase 3: New Arrival Matcher
- [ ] Create TWCNEW_ARRIVAL_ALERTS table
- [ ] Build NewArrivalMatcher service
- [ ] Alert generation logic with scoring
- [ ] Cooldown/deduplication logic
- [ ] API endpoints for alert management

### Phase 4: Integration & UI
- [ ] Staff app: Display alerts per customer
- [ ] Staff app: Show auto-inferred preferences differently
- [ ] Message templates for new arrival outreach
- [ ] Conversion tracking

---

## Configuration Options

```python
# Image enrichment
IMAGE_SCANNER_MODEL = "openai/clip-vit-base-patch32"
IMAGE_SCANNER_BATCH_SIZE = 100
IMAGE_SCANNER_MIN_CONFIDENCE = 0.7

# New arrival matching
NEW_ARRIVAL_MATCH_THRESHOLD = 0.6      # Minimum score to create alert
NEW_ARRIVAL_LOOKBACK_DAYS = 7          # Products added in last N days
NEW_ARRIVAL_COOLDOWN_HOURS = 72        # Min hours between alerts to same customer
NEW_ARRIVAL_MAX_ALERTS_PER_DAY = 3     # Max alerts per customer per day

# Auto preferences
AUTO_PREF_MIN_PURCHASES = 3            # Purchases to infer category preference
AUTO_PREF_MIN_VIEWS = 5                # Views to infer brand interest
AUTO_PREF_CONFIDENCE_THRESHOLD = 0.8   # Confidence to auto-add preference
```

---

## Decisions

| Question | Decision |
|----------|----------|
| **Alert delivery** | Staff app only (via existing product alerts). Push/email is future consideration. |
| **Collection grouping** | Per-product alerts for MVP. Grouped alerts ("3 new pieces...") is nice-to-have for later. |
| **Auto preference confirmation** | Not required. Display as "Auto generated" in FE; staff can optionally confirm but most won't. |
| **Auto preference weighting** | **Lower weight than explicit preferences.** Auto-inferred signals are weaker than customer/staff stated preferences. |

---

## Open Questions

1. **VIP prioritization:** Different thresholds for VIP vs. regular customers?
2. **Image scanner hosting:** Self-hosted GPU, or cloud inference API (Hugging Face/Replicate)?

---

## Dependencies

| Component | Dependency | Notes |
|-----------|------------|-------|
| Image Scanner | `transformers`, `torch`, `Pillow` | CLIP model |
| Image Scanner | GPU (optional) | CPU works but slower (~2s vs ~0.2s per image) |
| Event bus | SQS/SNS or Kafka | For async processing |
| Scheduler | K8s CronJob or similar | For batch backfill |
