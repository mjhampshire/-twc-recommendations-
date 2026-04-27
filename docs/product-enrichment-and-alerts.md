# Product Enrichment & New Arrival Alerts

## Overview

This document outlines the architecture for:
1. **Product intelligence pipeline** - Multi-signal enrichment combining retailer tags, descriptions, and image analysis
2. **New arrival alerts** - Proactive notifications when new products match customer preferences
3. **Auto-inferred preferences** - System-detected preferences marked with source "auto"

**Key design principle:** CLIP image analysis is ONE signal among many, not the primary driver. The pipeline combines:
- Retailer/Shopify product tags (primary - already accurate)
- Product title/description parsing
- Image enrichment (supplementary, for attributes not in tags)
- Purchase/wishlist behaviour signals

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
│                     PRODUCT INTELLIGENCE PIPELINE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ Tag          │  │ Description  │  │ Image        │  │ Behavior     │   │
│  │ Processor    │  │ Parser       │  │ Scanner      │  │ Signals      │   │
│  │ (retailer    │  │ (HTML→text)  │  │ (CLIP)       │  │ (purchases)  │   │
│  │ tags)        │  │              │  │              │  │              │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘   │
│         │                 │                 │                 │            │
│         ▼                 ▼                 ▼                 ▼            │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                     TWCPRODUCT_ENRICHMENT                           │  │
│  │  Unified product attributes from all sources                        │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                    │                                       │
│                                    ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                     New Arrival Matcher                             │  │
│  │  Query TWCCUSTOMER_PREFERENCE_INDEX for matching customers          │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                    │                                       │
│                                    ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                     TWCNEW_ARRIVAL_ALERTS                           │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component 1: Product Tag Processing

### Purpose
Retailer tags from Shopify are the most reliable source of product attributes. These should be the primary signal.

### Tag Sources

| Source | Examples | Reliability |
|--------|----------|-------------|
| Shopify product tags | `floral`, `midi-dress`, `summer-2024` | High |
| Shopify product type | `Dresses`, `Tops` | High |
| Shopify vendor | `Zimmermann`, `Aje` | High |
| Shopify metafields | Custom retailer fields | High |
| Collection membership | `New Arrivals`, `Sale` | High |

### Schema for Tags

```sql
-- Add tags column to TWCVARIANT if not present
ALTER TABLE TWCVARIANT
    ADD COLUMN IF NOT EXISTS tags Array(String) DEFAULT [];

-- Or store in enrichment table for unified access
```

### Tag Normalization

```python
class TagProcessor:
    """Normalizes and categorizes retailer tags."""

    TAG_MAPPINGS = {
        # Pattern tags
        'floral': ('pattern', 'floral'),
        'florals': ('pattern', 'floral'),
        'stripe': ('pattern', 'striped'),
        'striped': ('pattern', 'striped'),
        'check': ('pattern', 'checkered'),
        'polka': ('pattern', 'polka_dot'),

        # Color tags
        'navy': ('color', 'navy'),
        'black': ('color', 'black'),
        'white': ('color', 'white'),

        # Style tags
        'midi': ('length', 'midi'),
        'maxi': ('length', 'maxi'),
        'mini': ('length', 'mini'),
    }

    def process_tags(self, tags: list[str]) -> dict[str, list[str]]:
        """Convert raw tags to categorized attributes."""
        result = defaultdict(list)

        for tag in tags:
            normalized = tag.lower().strip().replace('-', '_')
            if normalized in self.TAG_MAPPINGS:
                category, value = self.TAG_MAPPINGS[normalized]
                result[category].append(value)
            else:
                # Keep unmapped tags for future analysis
                result['other'].append(normalized)

        return dict(result)
```

---

## Component 2: Description Parsing

### Purpose
Product descriptions contain valuable attribute information. Parse HTML descriptions to extract searchable text and attributes.

### Challenge
Descriptions are often long HTML strings with:
- Marketing copy
- Care instructions
- Fit information
- Material details

### Schema for Descriptions

```sql
-- Store parsed description text (not raw HTML)
ALTER TABLE TWCVARIANT
    ADD COLUMN IF NOT EXISTS descriptionText String DEFAULT '',
    ADD COLUMN IF NOT EXISTS descriptionKeywords Array(String) DEFAULT [];

-- Or in enrichment table
```

### Description Parser

```python
class DescriptionParser:
    """Parses product descriptions to extract text and keywords."""

    def parse(self, html_description: str) -> ParsedDescription:
        """
        Parse HTML description to extract:
        - Clean text (for search/matching)
        - Keywords (for attribute inference)
        """
        # Strip HTML
        text = self._strip_html(html_description)

        # Extract keywords
        keywords = self._extract_keywords(text)

        # Extract specific attributes
        attributes = self._extract_attributes(text)

        return ParsedDescription(
            text=text,
            keywords=keywords,
            fit=attributes.get('fit'),
            fabric=attributes.get('fabric'),
            occasion=attributes.get('occasion'),
        )

    def _strip_html(self, html: str) -> str:
        """Remove HTML tags, decode entities."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        return soup.get_text(separator=' ', strip=True)

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract significant keywords from description."""
        # Common fashion keywords to look for
        FASHION_KEYWORDS = {
            # Fit
            'fitted', 'relaxed', 'oversized', 'tailored', 'slim',
            # Fabric
            'silk', 'cotton', 'linen', 'wool', 'cashmere', 'viscose',
            # Occasion
            'casual', 'formal', 'evening', 'workwear', 'wedding',
            # Style
            'bohemian', 'minimalist', 'classic', 'romantic',
        }

        words = text.lower().split()
        return [w for w in words if w in FASHION_KEYWORDS]

    def _extract_attributes(self, text: str) -> dict[str, str]:
        """Extract structured attributes from description text."""
        attributes = {}

        # Fit detection
        if any(w in text.lower() for w in ['fitted', 'figure-hugging', 'body-con']):
            attributes['fit'] = 'fitted'
        elif any(w in text.lower() for w in ['relaxed', 'loose', 'easy']):
            attributes['fit'] = 'relaxed'
        elif any(w in text.lower() for w in ['oversized', 'boxy']):
            attributes['fit'] = 'oversized'

        return attributes
```

### Use in Recommendations

Parsed description text enables:
1. **Keyword matching** - "Bohemian floral dress" matches customer interest in bohemian style
2. **Fabric preferences** - Customer prefers silk → prioritize silk products
3. **Occasion matching** - Customer shopping for wedding → surface "wedding guest" products

---

## Component 3: Image Scanner Service

### Purpose
Asynchronously process product images to detect visual attributes NOT already available from tags or descriptions. Image analysis supplements existing data.

### CLIP Accuracy Expectations

**Realistic assessment:** CLIP zero-shot is useful for prototyping but has limitations for production fashion attributes.

| Attribute | CLIP Accuracy | Notes |
|-----------|---------------|-------|
| Pattern | Medium-High | Florals, stripes, solids work well |
| Dominant colors | Medium-High | Broad colors reliable |
| Neckline | Low-Medium | Pose, layering, crop affect results |
| Sleeve length | Low-Medium | Photography angle matters |
| Fit | Low | Very hard from single image |
| Length | Low-Medium | Model pose affects detection |

**MVP Scope:** For Phase 1, only use CLIP for **pattern** and **dominant colors** where confidence is high. Store but don't act on other attributes until validated.

### Detected Attributes (MVP)

| Attribute | Values | Detection Method | MVP Use |
|-----------|--------|------------------|---------|
| `pattern` | solid, striped, floral, checkered, polka_dot, animal_print | CLIP zero-shot | ✅ Active |
| `dominant_colors` | Array of detected colors | CLIP + color extraction | ✅ Active |
| `neckline` | crew, v_neck, scoop, off_shoulder, halter, collared | CLIP zero-shot | ⏸️ Store only |
| `sleeve_length` | sleeveless, short, three_quarter, long | CLIP zero-shot | ⏸️ Store only |
| `fit` | fitted, relaxed, oversized | CLIP zero-shot | ⏸️ Store only |
| `length` | cropped, regular, midi, maxi | CLIP zero-shot | ⏸️ Store only |

### Technology Choice: CLIP

**Why CLIP:**
- Zero-shot classification - no training data needed
- Natural language queries: "Is this a striped pattern?"
- Open source (MIT license)
- Runs locally or via Hugging Face Inference API

**Limitations:**
- Photography style, pose, layering affect results
- Nuanced fashion attributes (fit, neckline) are unreliable
- Use as candidate enrichment, not truth

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
-- Unified product enrichment table (all signal sources)
CREATE TABLE IF NOT EXISTS TWCPRODUCT_ENRICHMENT (
    tenantId String,
    productId String,
    variantId String,

    -- Source signals
    sourceType String DEFAULT 'image',    -- 'tag', 'description', 'image', 'manual'

    -- Detected attributes (MVP: pattern + colors active, others stored only)
    pattern String DEFAULT '',            -- 'striped', 'floral', 'solid', etc.
    dominantColors Array(String),         -- ['navy', 'white', 'gold']
    neckline String DEFAULT '',           -- 'v_neck', 'crew', etc. (store only for MVP)
    sleeveLength String DEFAULT '',       -- 'sleeveless', 'short', 'long' (store only)
    fit String DEFAULT '',                -- 'fitted', 'relaxed', 'oversized' (store only)
    length String DEFAULT '',             -- 'cropped', 'midi', 'maxi' (store only)

    -- From tags/description parsing
    retailerTags Array(String),           -- Original tags from Shopify
    parsedKeywords Array(String),         -- Keywords from description
    fabric String DEFAULT '',             -- Extracted from description
    occasion String DEFAULT '',           -- Extracted from description

    -- Confidence scores (per attribute)
    confidenceScores Map(String, Float32), -- {'pattern': 0.92, 'color': 0.87, ...}

    -- Model/version tracking (critical for re-processing)
    modelVersion String DEFAULT 'clip-vit-base-patch32',
    attributeVersion String DEFAULT 'v1',  -- Schema version for attributes
    rawModelOutput String DEFAULT '',      -- JSON of raw model response (for debugging)
    sourceImageHash String DEFAULT '',     -- Hash of processed image (detect changes)

    -- Processing metadata
    imageUrl String,
    processedAt DateTime DEFAULT now(),
    processingStatus String DEFAULT 'pending',  -- 'pending', 'completed', 'failed'
    errorMessage String DEFAULT ''

) ENGINE = ReplacingMergeTree(processedAt)
ORDER BY (tenantId, productId, variantId, sourceType);
```

**Schema notes:**
- `attributeVersion` - Track which schema version attributes use; enables re-processing when model changes
- `confidenceScores` - Map allows per-attribute confidence without column explosion
- `sourceImageHash` - Detect when image changed and re-enrichment needed
- `rawModelOutput` - Debug what the model actually returned
- `sourceType` - Single table for all enrichment sources (tags, description, image)

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

### Customer Preference Index

Matching products to customers at scale requires an inverted index. Scanning all customers for each product is expensive.

```sql
-- Inverted index: lookup customers by preference
CREATE TABLE IF NOT EXISTS TWCCUSTOMER_PREFERENCE_INDEX (
    tenantId String,
    preferenceType String,               -- 'brand', 'pattern', 'color', 'category'
    preferenceValue String,              -- 'Zimmermann', 'floral', 'navy', 'Dresses'
    customerId String,
    source String,                       -- 'explicit', 'auto'
    confidence Float32 DEFAULT 1.0,      -- 1.0 for explicit, lower for auto
    createdAt DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(createdAt)
ORDER BY (tenantId, preferenceType, preferenceValue, customerId);
```

**Usage:** When a floral Zimmermann dress arrives:

```sql
-- Find customers who like florals OR Zimmermann
SELECT DISTINCT customerId
FROM TWCCUSTOMER_PREFERENCE_INDEX
WHERE tenantId = 'viktoria-woods'
  AND (
    (preferenceType = 'pattern' AND preferenceValue = 'floral')
    OR (preferenceType = 'brand' AND preferenceValue = 'Zimmermann')
    OR (preferenceType = 'category' AND preferenceValue = 'Dresses')
  )
```

Then for each customer, calculate detailed match score.

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

**Score threshold alone is not enough.** A score over 0.6 may be too permissive if a product only matches broad attributes like category + color. This creates staff fatigue.

**Alert creation requires BOTH:**
1. Score >= threshold (0.6)
2. At least one **strong signal**:

| Strong Signal | Example |
|---------------|---------|
| Explicit brand match | Customer explicitly likes Zimmermann, product is Zimmermann |
| Explicit category + pattern | Customer likes Dresses AND florals, product is floral dress |
| Wishlist-derived | Product matches wishlist item attributes |
| VIP + strong product match | VIP customer with score >= 0.75 |

```python
def should_create_alert(
    match_score: float,
    match_details: MatchDetails,
    customer: Customer,
) -> bool:
    """Determine if alert should be created."""
    if match_score < 0.6:
        return False

    # Must have at least one strong signal
    has_strong_signal = any([
        match_details.has_explicit_brand_match,
        match_details.has_explicit_category_and_pattern_match,
        match_details.has_wishlist_signal,
        customer.is_vip and match_score >= 0.75,
    ])

    if not has_strong_signal:
        return False

    return True
```

### Alert Suppression Rules

Do **NOT** create alert if:

| Rule | Reason |
|------|--------|
| Same product already alerted | Dedupe |
| Same brand/category alerted within 48h | Prevent spam |
| Customer dismissed recent alerts (3+) | Fatigue signal |
| Product low stock or unavailable in customer size | Frustration |
| Customer in cooldown period | Rate limiting |

```python
def check_suppression(
    tenant_id: str,
    customer_id: str,
    product_id: str,
) -> Optional[str]:
    """Return suppression reason or None if alert is allowed."""

    # Same product already alerted
    if alert_exists(tenant_id, customer_id, product_id):
        return "duplicate_product"

    # Same brand/category recently
    recent_alerts = get_recent_alerts(tenant_id, customer_id, hours=48)
    product = get_product(tenant_id, product_id)
    for alert in recent_alerts:
        if alert.product_brand == product.brand and alert.product_category == product.category:
            return "recent_similar"

    # Customer dismissing alerts
    dismissed_count = count_dismissed_alerts(tenant_id, customer_id, days=14)
    if dismissed_count >= 3:
        return "customer_fatigue"

    # Size availability
    if not size_available_for_customer(product, customer_id):
        return "size_unavailable"

    # Cooldown
    last_alert = get_last_alert(tenant_id, customer_id)
    if last_alert and last_alert.created_at > now() - timedelta(hours=72):
        return "cooldown"

    return None
```

### Basic Requirements (still apply)

- Customer has opted into alerts (or is VIP)
- Product is in stock

### Database Schema

```sql
-- New arrival alerts for proactive outreach
CREATE TABLE IF NOT EXISTS TWCNEW_ARRIVAL_ALERTS (
    alertId String,
    tenantId String,
    customerId String,
    productId String,

    -- Dedupe key (critical for preventing duplicates)
    dedupeKey String,                      -- tenantId + customerId + productId + alertType

    -- Match details
    matchScore Float32,                    -- 0-1, how well product matches preferences
    matchReasons Array(String),            -- ['Matches floral preference', 'Favorite brand']
    strongSignals Array(String),           -- ['explicit_brand', 'wishlist'] - why alert was allowed
    priority Float32 DEFAULT 0.5,          -- 0-1, for sorting alerts by importance

    -- Alert metadata
    collectionName String DEFAULT '',      -- 'Summer 2024', 'Resort Collection'
    alertType String DEFAULT 'new_arrival', -- 'new_arrival', 'back_in_stock', 'price_drop'
    expiresAt DateTime DEFAULT now() + INTERVAL 14 DAY,  -- Auto-expire old alerts

    -- Status tracking
    status String DEFAULT 'pending',       -- 'pending', 'sent', 'viewed', 'dismissed', 'converted', 'expired'
    createdAt DateTime DEFAULT now(),
    sentAt Nullable(DateTime),
    viewedAt Nullable(DateTime),
    convertedAt Nullable(DateTime),
    suppressionReason String DEFAULT '',   -- If suppressed, why

    -- Store assignment
    assignedStore String DEFAULT '',       -- Store responsible for outreach
    assignedStaffId String DEFAULT '',     -- Specific staff member (optional)

    -- Delivery channel
    channel String DEFAULT 'staff_app'     -- 'app', 'email', 'sms', 'staff_app'

) ENGINE = ReplacingMergeTree(createdAt)
ORDER BY (tenantId, dedupeKey);

-- Indexes
ALTER TABLE TWCNEW_ARRIVAL_ALERTS ADD INDEX idx_pending (status) TYPE set(100) GRANULARITY 4;
ALTER TABLE TWCNEW_ARRIVAL_ALERTS ADD INDEX idx_store (assignedStore) TYPE set(100) GRANULARITY 4;
ALTER TABLE TWCNEW_ARRIVAL_ALERTS ADD INDEX idx_expires (expiresAt) TYPE minmax GRANULARITY 4;
```

**Schema notes:**
- `dedupeKey` - Prevents duplicate alerts from retries or catch-up jobs
- `expiresAt` - Auto-expire alerts after 14 days; scheduled job marks them `expired`
- `priority` - Sort alerts by importance (VIP, high match score)
- `assignedStore` / `assignedStaffId` - For store-level task assignment
- `strongSignals` - Track why alert passed the strong signal requirement

### Workflow State Consideration

ClickHouse is optimized for analytics, not transactional workflow state. For MVP, `ReplacingMergeTree` works if:
- UI tolerates eventual consistency on status changes
- High-volume status updates are acceptable

For production scale, consider:
| Option | Use Case |
|--------|----------|
| Keep in ClickHouse | MVP, low volume, analytics-first |
| DynamoDB/Postgres for state | High-volume workflow with reliable state |
| Event sourcing | Write events to ClickHouse, materialize state elsewhere |

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

### Phase 1: Product Intelligence Foundation
- [ ] Add `tags` and `descriptionText` columns to TWCVARIANT
- [ ] Create TWCPRODUCT_ENRICHMENT table (unified schema)
- [ ] Build TagProcessor for retailer tag normalization
- [ ] Build DescriptionParser for HTML → text extraction
- [ ] Store model version and confidence scores from day one

### Phase 2: Image Enrichment (MVP: Pattern + Colors Only)
- [ ] Build ImageScanner service with CLIP
- [ ] Detect pattern and dominant colors only (high confidence)
- [ ] Store but don't act on other attributes (neckline, fit, etc.)
- [ ] Event-driven processing + catch-up job
- [ ] Backfill endpoint for existing catalog

### Phase 3: Customer Preference Index
- [ ] Create TWCCUSTOMER_PREFERENCE_INDEX table
- [ ] Populate from explicit preferences
- [ ] Populate from inferred preferences (active, high confidence)
- [ ] Scheduled job to sync index

### Phase 4: New Arrival Matcher
- [ ] Create TWCNEW_ARRIVAL_ALERTS table (with dedupe, expiry)
- [ ] Build NewArrivalMatcher with strong signal requirements
- [ ] Implement suppression rules
- [ ] Store-level task assignment
- [ ] API endpoints for alert management

### Phase 5: Inferred Preferences
- [ ] Create TWCINFERRED_PREFERENCES table
- [ ] Build PreferenceInferrer from purchase history
- [ ] Implement decay scoring (scheduled job)
- [ ] Implement negative feedback from dismissed alerts
- [ ] Staff confirm/dismiss workflow

### Phase 6: Integration & UI
- [ ] Staff app: Display alerts per store
- [ ] Staff app: Show auto-inferred preferences with different styling
- [ ] Message templates for new arrival outreach
- [ ] Conversion tracking
- [ ] Alert expiry job

---

## Configuration Options

```python
# Image enrichment
IMAGE_SCANNER_MODEL = "openai/clip-vit-base-patch32"
IMAGE_SCANNER_BATCH_SIZE = 100
IMAGE_SCANNER_MIN_CONFIDENCE = 0.7
IMAGE_SCANNER_ACTIVE_ATTRIBUTES = ['pattern', 'dominant_colors']  # MVP subset

# New arrival matching
NEW_ARRIVAL_MATCH_THRESHOLD = 0.6      # Minimum score to create alert
NEW_ARRIVAL_REQUIRE_STRONG_SIGNAL = True  # Must have brand/pattern/wishlist match
NEW_ARRIVAL_LOOKBACK_DAYS = 7          # Products added in last N days
NEW_ARRIVAL_COOLDOWN_HOURS = 72        # Min hours between alerts to same customer
NEW_ARRIVAL_MAX_ALERTS_PER_DAY = 3     # Max alerts per customer per day
NEW_ARRIVAL_EXPIRY_DAYS = 14           # Auto-expire old alerts
NEW_ARRIVAL_SIMILAR_COOLDOWN_HOURS = 48  # Min hours between similar alerts

# Alert suppression
ALERT_MAX_DISMISSED_BEFORE_FATIGUE = 3  # Stop alerting after 3 dismissals
ALERT_REQUIRE_SIZE_AVAILABLE = True     # Only alert if customer's size in stock

# Auto preferences
AUTO_PREF_MIN_PURCHASES = 3            # Purchases to infer category preference
AUTO_PREF_MIN_VIEWS = 5                # Views to infer brand interest
AUTO_PREF_CONFIDENCE_THRESHOLD = 0.8   # Confidence to auto-add preference
AUTO_PREF_DECAY_HALF_LIFE_DAYS = 180   # 6 months for preferences to halve
AUTO_PREF_MIN_CONFIDENCE_TO_USE = 0.2  # Below this, don't use preference
```

---

## Decisions

| Question | Decision |
|----------|----------|
| **Primary enrichment source** | **Retailer tags and descriptions first.** CLIP is supplementary for attributes not in tags. |
| **CLIP MVP scope** | **Pattern and colors only.** Other attributes (fit, neckline) stored but not used until validated. |
| **Alert creation** | **Require strong signal, not just score.** Score >= 0.6 AND (brand match OR category+pattern OR wishlist OR VIP). |
| **Alert spam prevention** | **Dedupe + suppression from day one.** Same product, similar alerts, customer fatigue, size availability. |
| **Alert delivery** | Staff app only (via existing product alerts). Push/email is future consideration. |
| **Collection grouping** | Per-product alerts for MVP. Grouped alerts ("3 new pieces...") is nice-to-have for later. |
| **Auto preference confirmation** | Not required. Display as "Auto generated" in FE; staff can optionally confirm but most won't. |
| **Auto preference weighting** | **Lower weight than explicit preferences.** Auto-inferred signals are weaker than customer/staff stated preferences. |
| **Preference decay** | **180-day half-life.** Preferences decay over time; ignore if too old. |
| **Workflow state storage** | **ClickHouse for MVP.** Consider operational store (DynamoDB/Postgres) if workflow reliability issues arise. |

---

## Store-Level Outreach Tasks

### Purpose
Staff at a store should see alerts for customers whose `usualStore` or `preferredStore` matches their store. These appear as "outreach tasks" in the staff app.

### Schema Update

```sql
-- Add store fields to alerts for filtering
ALTER TABLE TWCNEW_ARRIVAL_ALERTS
    ADD COLUMN IF NOT EXISTS customerUsualStore String DEFAULT '',
    ADD COLUMN IF NOT EXISTS customerPreferredStore String DEFAULT '';

-- Index for store-level queries
ALTER TABLE TWCNEW_ARRIVAL_ALERTS
    ADD INDEX idx_usual_store (customerUsualStore) TYPE set(100) GRANULARITY 4;
ALTER TABLE TWCNEW_ARRIVAL_ALERTS
    ADD INDEX idx_preferred_store (customerPreferredStore) TYPE set(100) GRANULARITY 4;
```

### API Endpoint for Store Staff

```
GET /api/v1/alerts/{retailer_id}/store/{store_id}
  - Returns pending alerts for customers at this store
  - Filters: customerUsualStore = store_id OR customerPreferredStore = store_id
  - Query params: status=pending, limit=50, sort=match_score_desc

Response:
{
  "store_id": "sydney-cbd",
  "pending_tasks": 12,
  "alerts": [
    {
      "alert_id": "...",
      "customer_id": "CUST001",
      "customer_name": "Jane Smith",
      "product_name": "Floral Midi Dress",
      "match_score": 0.85,
      "match_reasons": ["Loves florals", "Zimmermann fan"],
      "customer_usual_store": "sydney-cbd",
      "created_at": "2025-04-26T10:00:00Z"
    }
  ]
}
```

### Workflow
1. Alert is created with `customerUsualStore` and `customerPreferredStore` populated from customer profile
2. Store staff opens "Outreach Tasks" in staff app
3. Staff app calls `/api/v1/alerts/{retailer_id}/store/{current_store}`
4. Staff sees list of customers to reach out to
5. Staff marks alerts as `sent`, `dismissed`, or waits for `converted`

---

## CLIP Enrichment Trigger

### How New Products Get Scanned

Products are pushed to CLIP based on the `createdAt` timestamp in `TWCVARIANT`:

```
┌─────────────────────────────────────────────────────────────────┐
│                   ENRICHMENT TRIGGER OPTIONS                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Option A: Event-Driven (Recommended)                           │
│  ────────────────────────────────────                           │
│  1. Product sync writes to TWCVARIANT                           │
│  2. Product sync publishes event: "product.created"             │
│  3. Image Scanner subscribes to event                           │
│  4. Scanner fetches product, downloads image, runs CLIP         │
│  5. Results written to TWCPRODUCT_ENRICHMENT                    │
│                                                                 │
│  Option B: Polling (Simpler, less real-time)                    │
│  ────────────────────────────────────────────                   │
│  1. Scheduled job runs every 5 minutes                          │
│  2. Query: SELECT * FROM TWCVARIANT                             │
│            WHERE createdAt > last_processed_timestamp           │
│            AND variantId NOT IN (SELECT variantId FROM          │
│                                  TWCPRODUCT_ENRICHMENT)         │
│  3. Process each new product through CLIP                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Recommended: Hybrid Approach

```python
class EnrichmentTrigger:
    """Handles triggering CLIP enrichment for products."""

    def __init__(self, config: ClickHouseConfig):
        self.client = get_clickhouse_client(config)
        self.scanner = ImageScanner()

    # Primary: Event-driven for new products
    async def on_product_created(self, event: ProductCreatedEvent):
        """Handle new product event from product sync service."""
        await self.enrich_product(event.tenant_id, event.variant_id)

    # Fallback: Catch-up job for missed events
    def run_catchup_job(self, lookback_hours: int = 24):
        """
        Scan products created recently that weren't enriched.
        Run as scheduled job (e.g., hourly).
        """
        unenriched = self.client.query("""
            SELECT v.tenantId, v.variantId, v.imageUrl
            FROM TWCVARIANT v
            LEFT JOIN TWCPRODUCT_ENRICHMENT e
              ON v.tenantId = e.tenantId AND v.variantId = e.variantId
            WHERE v.createdAt >= now() - INTERVAL {hours:UInt32} HOUR
              AND e.variantId IS NULL
              AND v.imageUrl != ''
        """, parameters={"hours": lookback_hours})

        for row in unenriched.result_rows:
            self.enrich_product(row[0], row[1])

    # Backfill: One-time for existing catalog
    def run_backfill(self, tenant_id: str, batch_size: int = 1000):
        """
        Backfill enrichment for existing products.
        Run as one-time migration or when model is updated.
        """
        unenriched = self.client.query("""
            SELECT v.variantId, v.imageUrl
            FROM TWCVARIANT v
            LEFT JOIN TWCPRODUCT_ENRICHMENT e
              ON v.tenantId = e.tenantId AND v.variantId = e.variantId
            WHERE v.tenantId = {tenant_id:String}
              AND e.variantId IS NULL
              AND v.imageUrl != ''
            LIMIT {limit:UInt32}
        """, parameters={"tenant_id": tenant_id, "limit": batch_size})

        # Process in batches...
```

---

## Auto-Inferred Preferences: Storage Strategy

### The Challenge

The retailer's `TWCPREFERENCES` structure is complex and retailer-defined:
- Categories, subcategories, specific fields (bra_size, bra_brands, etc.)
- Display logic, regional visibility, external system sync
- Shown in customer/staff-facing preference screens

Auto-inferred preferences are different:
- Simple attributes: "likes florals", "prefers navy", "interested in Zimmermann"
- Detected from behavior (purchases, browsing) or CLIP image analysis
- Should NOT appear in FE preference screens by default
- Should be available for recommendations and reporting

### Recommended: Separate Table for Inferred Preferences

```sql
-- Separate table for auto-inferred preferences
-- NOT shown in FE preference screens, but used for recommendations/reports
CREATE TABLE IF NOT EXISTS TWCINFERRED_PREFERENCES (
    tenantId String,
    customerId String,

    -- Preference details
    preferenceType String,      -- 'pattern', 'color', 'brand', 'category', 'style'
    preferenceValue String,     -- 'floral', 'navy', 'Zimmermann', 'Dresses'
    isLike UInt8 DEFAULT 1,     -- 1 = like, 0 = dislike

    -- Inference source and evidence
    inferenceSource String,     -- 'purchase_history', 'browsing', 'wishlist', 'clip_analysis'
    confidence Float32,         -- 0-1 base confidence score
    evidenceCount UInt32,       -- Number of supporting data points (e.g., 5 purchases)
    evidenceRefs Array(String), -- ['order:123', 'order:456'] - for explainability
    lastEvidenceAt DateTime,    -- When last evidence occurred (for decay)

    -- Decay tracking
    decayScore Float32 DEFAULT 1.0,  -- Decayed confidence (recalculated periodically)

    -- Metadata
    firstInferredAt DateTime DEFAULT now(),
    lastUpdatedAt DateTime DEFAULT now(),
    isActive UInt8 DEFAULT 1,   -- Can be disabled without deleting

    -- Staff interaction
    staffConfirmed UInt8 DEFAULT 0,   -- Staff promoted to explicit preference
    staffDismissed UInt8 DEFAULT 0,   -- Staff rejected this inference
    staffActionBy String DEFAULT '',
    staffActionAt Nullable(DateTime)

) ENGINE = ReplacingMergeTree(lastUpdatedAt)
ORDER BY (tenantId, customerId, preferenceType, preferenceValue);
```

**Schema notes:**
- `evidenceRefs` - Array of references for explainability ("Why do we think she likes florals?")
- `lastEvidenceAt` - When the last supporting evidence occurred; drives decay
- `decayScore` - Pre-calculated decayed confidence; updated by scheduled job

### Why Separate Table?

| Concern | TWCPREFERENCES | TWCINFERRED_PREFERENCES |
|---------|----------------|-------------------------|
| **Structure** | Complex retailer-defined JSON | Simple flat structure |
| **Source** | Customer/Staff explicit | System-detected |
| **FE visibility** | Shown in preference screens | Hidden by default |
| **Sync to external** | Yes (Shopify, etc.) | No |
| **Reports/filtering** | ✅ | ✅ |
| **Recommendations** | ✅ | ✅ (lower weight) |

### Recommendations Engine: Query Both Tables

```python
def get_customer_preferences(tenant_id: str, customer_id: str) -> CustomerPreferences:
    """
    Get combined preferences from both explicit and inferred sources.
    """
    # 1. Get explicit preferences from TWCPREFERENCES
    explicit = query_explicit_preferences(tenant_id, customer_id)

    # 2. Get inferred preferences (active, not dismissed)
    inferred = query_inferred_preferences(tenant_id, customer_id)

    # 3. Merge, with explicit taking precedence
    return merge_preferences(explicit, inferred)


def merge_preferences(
    explicit: ExplicitPreferences,
    inferred: list[InferredPreference],
) -> CustomerPreferences:
    """
    Merge explicit and inferred preferences.

    Rules:
    - Explicit preferences always included
    - Inferred added only if not conflicting with explicit
    - Inferred marked with source='auto' for lower weighting
    """
    result = CustomerPreferences()

    # Add all explicit preferences (source: customer or staff)
    for pref in explicit.all_preferences():
        result.add(pref.type, pref.value, source=pref.source)

    # Add inferred preferences if not conflicting
    for inf in inferred:
        if not inf.staff_dismissed and inf.is_active:
            # Don't add if explicit dislike exists
            if not explicit.has_dislike(inf.preference_type, inf.preference_value):
                # Don't add if explicit like already exists (no need to duplicate)
                if not explicit.has_like(inf.preference_type, inf.preference_value):
                    result.add(
                        inf.preference_type,
                        inf.preference_value,
                        source=PreferenceSource.AUTO,
                        confidence=inf.confidence,
                    )

    return result
```

### FE Visibility: Configuration Option

If a retailer DOES want to show auto-inferred preferences in the FE (with different styling), add a config flag:

```json
{
  "tenant_id": "viktoria-woods",
  "preference_display_config": {
    "show_inferred_in_staff_app": true,
    "show_inferred_in_customer_app": false,
    "inferred_display_style": "subtle",
    "allow_staff_confirm_dismiss": true
  }
}
```

### Preference Decay and Negative Feedback

Inferred preferences should decay if they become stale. Someone who bought florals 18 months ago may not still want floral alerts.

#### Time Decay

```python
def calculate_decay_score(
    base_confidence: float,
    last_evidence_at: datetime,
    half_life_days: int = 180,
) -> float:
    """
    Apply exponential decay to confidence based on time since last evidence.

    Half-life of 180 days means:
    - 6 months old: 50% of original confidence
    - 12 months old: 25% of original confidence
    - 18 months old: 12.5% of original confidence
    """
    days_since = (datetime.now() - last_evidence_at).days
    decay_factor = 0.5 ** (days_since / half_life_days)
    return base_confidence * decay_factor


# Scheduled job to update decay scores
def update_decay_scores():
    """Run daily to recalculate decayed confidence."""
    client.command("""
        ALTER TABLE TWCINFERRED_PREFERENCES
        UPDATE decayScore = confidence * pow(0.5, dateDiff('day', lastEvidenceAt, now()) / 180)
        WHERE isActive = 1 AND staffConfirmed = 0
    """)
```

#### Negative Feedback

Treat dismissed/ignored alerts as feedback against the inferred preference:

```python
def apply_negative_feedback(
    tenant_id: str,
    customer_id: str,
    product_attributes: dict,
    feedback_type: str,  # 'dismissed', 'ignored'
):
    """
    Reduce confidence in inferred preferences when customer ignores alerts.

    Rules:
    - Alert dismissed: reduce matching preference confidence by 20%
    - 3+ ignored alerts for same attribute: reduce by 30%
    - Staff dismisses auto preference: deactivate entirely
    """
    penalty = 0.2 if feedback_type == 'dismissed' else 0.1

    for attr_type, attr_value in product_attributes.items():
        pref = get_inferred_preference(tenant_id, customer_id, attr_type, attr_value)
        if pref and not pref.staff_confirmed:
            new_confidence = max(0.1, pref.confidence * (1 - penalty))
            update_preference_confidence(pref.id, new_confidence)

            # Deactivate if confidence drops too low
            if new_confidence < 0.2:
                deactivate_preference(pref.id)


# Track ignored alerts
def count_ignored_for_attribute(
    tenant_id: str,
    customer_id: str,
    attr_type: str,
    attr_value: str,
    days: int = 30,
) -> int:
    """Count how many alerts matching this attribute were ignored."""
    return client.query("""
        SELECT count(*)
        FROM TWCNEW_ARRIVAL_ALERTS
        WHERE tenantId = {tenant_id:String}
          AND customerId = {customer_id:String}
          AND status IN ('expired', 'dismissed')
          AND has(matchReasons, {reason:String})
          AND createdAt >= now() - INTERVAL {days:UInt32} DAY
    """, parameters={
        'tenant_id': tenant_id,
        'customer_id': customer_id,
        'reason': f'{attr_type}:{attr_value}',
        'days': days,
    }).first_row[0]
```

### Populating Inferred Preferences

```python
class PreferenceInferrer:
    """Infers preferences from customer behavior."""

    def infer_from_purchases(self, tenant_id: str, customer_id: str):
        """
        Analyze purchase history to infer preferences.
        Run periodically or after purchases.
        """
        # Count purchases by attribute
        stats = self.client.query("""
            SELECT
                v.category,
                v.brand,
                e.pattern,  -- From TWCPRODUCT_ENRICHMENT
                count(*) as cnt
            FROM ORDERLINE ol
            JOIN TWCVARIANT v ON ol.variantRef = v.variantRef
            LEFT JOIN TWCPRODUCT_ENRICHMENT e ON v.variantId = e.variantId
            WHERE ol.tenantId = {tenant_id:String}
              AND ol.customerRef = {customer_id:String}
            GROUP BY v.category, v.brand, e.pattern
            HAVING cnt >= 3
        """, ...)

        # Create inferred preferences for frequently purchased attributes
        for row in stats.result_rows:
            category, brand, pattern, count = row

            if category and count >= 3:
                self.add_inferred('category', category, 'purchase_history', count)

            if brand and count >= 3:
                self.add_inferred('brand', brand, 'purchase_history', count)

            if pattern and count >= 2:  # Lower threshold for patterns
                self.add_inferred('pattern', pattern, 'purchase_history', count)
```

---

## Design Review Feedback (Incorporated)

Following feedback was incorporated into this design:

| Concern | Resolution |
|---------|------------|
| **CLIP accuracy for fashion attributes** | Narrowed MVP to pattern + colors only; store but don't act on fit, neckline, length |
| **Product tags underutilized** | Added Tag Processor as primary signal; CLIP supplements missing attributes |
| **Descriptions not captured** | Added Description Parser; store parsed text in TWCVARIANT |
| **Alert spam risk** | Added strong signal requirement + suppression rules + dedupe keys |
| **ClickHouse for workflow state** | Acknowledged limitation; documented options for production scale |
| **Matching query scale** | Added TWCCUSTOMER_PREFERENCE_INDEX inverted index |
| **Preference decay** | Added decayScore with 180-day half-life; scheduled job to update |
| **Negative feedback** | Reduce confidence when alerts dismissed/ignored |
| **Schema versioning** | Added attributeVersion, rawModelOutput, sourceImageHash to enrichment |
| **Alert deduplication** | Added dedupeKey, expiresAt, strongSignals to alerts |
| **Evidence tracking** | Added evidenceRefs, lastEvidenceAt to inferred preferences |

---

## Open Questions

1. **VIP prioritization:** Different thresholds for VIP vs. regular customers?
2. **Image scanner hosting:** Self-hosted GPU, or cloud inference API (Hugging Face/Replicate)?
3. **Description HTML complexity:** How complex are the HTML descriptions? May need robust parsing.

---

## Dependencies

| Component | Dependency | Notes |
|-----------|------------|-------|
| Description Parser | `beautifulsoup4`, `lxml` | HTML parsing |
| Image Scanner | `transformers`, `torch`, `Pillow` | CLIP model |
| Image Scanner | GPU (optional) | CPU works but slower (~2s vs ~0.2s per image) |
| Event bus | SQS/SNS or Kafka | For async processing |
| Scheduler | K8s CronJob or similar | For batch backfill, decay updates, expiry |
