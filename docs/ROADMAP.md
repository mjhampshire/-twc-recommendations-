# TWC Recommendations Roadmap

## Executive Summary

This roadmap consolidates all planned enhancements for the TWC recommendations platform. It prioritizes:

1. **Quick wins** - Immediate improvements with minimal effort
2. **Shopify integration** - Customer-requested, revenue-driving
3. **Product intelligence** - Better data = better recommendations
4. **Advanced features** - Purchase readiness, cross-retailer intelligence

**Timeline:** 3-6 months

---

## Current State (Completed)

| Component | Status | Notes |
|-----------|--------|-------|
| Core recommendation engine | ✅ Done | Rule-based scoring with configurable weights |
| A/B testing framework | ✅ Done | Variant assignment, statistical analysis, auto-promotion |
| Multi-armed bandit | ✅ Done | Thompson sampling for weight optimization |
| Recommendation logging | ✅ Done | ClickHouse tables for impressions, outcomes |
| Widget API endpoints | ✅ Done | Render, track, wishlist operations |
| TWC Core client | ✅ Done | OAuth2 authentication, wishlist CRUD |
| Widget tracking tables | ✅ Done | Impressions, events, daily metrics |
| Tags & collections support | ✅ Done | Scoring against customer preferences |
| Product description field | ✅ Done | Fetched and available (not yet used in scoring) |

---

## Phase 1: Quick Wins & Shopify (Weeks 1-4)

### 1.1 Recommendation Model Quick Wins

These improvements can be made immediately with existing data.

| Enhancement | Effort | Impact | Description |
|-------------|--------|--------|-------------|
| **Trending boost** | 1 day | High | Boost recently wishlisted/viewed products in recommendations |
| **Recency weighting** | 1 day | Medium | Weight recent purchases/views higher than older ones |
| **Price range matching** | 2 days | Medium | Match product price to customer's typical spend range |
| **Out-of-stock filtering** | 1 day | High | Hard filter out-of-stock products (requires inStock data) |
| **Wishlist deduplication** | 1 day | Medium | Don't recommend products already on customer's wishlist |

**Implementation priority:** Out-of-stock filtering → Wishlist dedup → Trending boost → Recency → Price range

### 1.2 Shopify App Blocks (Theme App Extension)

**Why now:** Customer demand, straightforward implementation, immediate revenue.

#### Deliverables

| Deliverable | Effort | Description |
|-------------|--------|-------------|
| Theme App Extension scaffold | 2 days | Basic extension structure, Shopify CLI setup |
| "For You" App Block | 3 days | Personalized recommendations widget |
| "Trending" App Block | 2 days | Products trending on wishlists |
| "Similar Products" App Block | 2 days | "You might also like" for PDP |
| Shopify Proxy endpoint | 1 day | Secure API proxy (hides secrets from JS) |
| Basic styling/theming | 2 days | CSS variables for merchant customization |

#### Technical Approach

```
Shopify Store
    │
    ├── Theme App Extension (our code in merchant's theme)
    │   ├── blocks/
    │   │   ├── for-you.liquid         # Personalized recs
    │   │   ├── trending.liquid        # Trending products
    │   │   └── similar.liquid         # Similar products
    │   ├── assets/
    │   │   └── twc-widget.js          # Shared JS (fetch, render, track)
    │   └── snippets/
    │       └── twc-product-card.liquid # Reusable product card
    │
    └── App Proxy (/apps/twc-recs/*)
        └── Routes to our Widget API (with tenant auth)
```

#### Success Criteria

- [ ] Merchant can add "For You" block to homepage via theme editor
- [ ] Widget loads recommendations in <500ms
- [ ] Clicks/adds tracked for attribution
- [ ] Works with Online Store 2.0 themes

### 1.3 Purchase Readiness Scoring (RFM-based)

**Why now:** Quick win, enables prioritized outreach, uses existing data.

| Task | Effort | Description |
|------|--------|-------------|
| Schema for readiness signals | 1 day | ClickHouse table for computed signals |
| Batch job to compute scores | 2 days | Daily aggregation of recency/frequency/intent |
| API endpoint | 1 day | GET /customers/ready-to-buy |
| Dashboard integration | 2 days | Surface in TWC admin |

**Formula (v1):**
```
Score =
    recency_score × 0.35 +      # Days since last visit (decay)
    frequency_score × 0.25 +    # Visit frequency trend
    intent_score × 0.25 +       # Cart adds, wishlist adds
    cycle_score × 0.15          # Within typical purchase window
```

---

## Phase 2: Shopify Polish & Web Components (Weeks 5-8)

### 2.1 Shopify Enhancements

| Enhancement | Effort | Description |
|-------------|--------|-------------|
| "Complete the Look" block | 3 days | Complementary products on PDP |
| "Recently Viewed" block | 2 days | Customer's browsing history |
| Wishlist integration | 2 days | Heart icon, add-to-wishlist from widget |
| Analytics dashboard | 3 days | Widget performance in Shopify admin |
| A/B test controls | 2 days | Enable/disable experiments from admin |

### 2.2 Web Components (Non-Shopify)

For retailers not on Shopify (custom sites, other platforms).

| Deliverable | Effort | Description |
|-------------|--------|-------------|
| `<twc-recommendations>` component | 3 days | Self-contained web component |
| `<twc-trending>` component | 2 days | Trending products widget |
| `<twc-similar>` component | 2 days | Similar products widget |
| Embed script & docs | 2 days | Single script tag integration |
| Styling API | 2 days | CSS custom properties for theming |

#### Usage Example
```html
<script src="https://widgets.thewishlist.io/v1/twc-widgets.js"
        data-tenant="retailer-id"></script>

<twc-recommendations
    type="for-you"
    customer-id="{{customer.id}}"
    limit="8"
    layout="carousel">
</twc-recommendations>
```

---

## Phase 3: Product Intelligence Pipeline (Weeks 9-12)

Better product data = better recommendations. Now that tags and descriptions are flowing, enhance how we use them.

### 3.1 Tag Processing

| Task | Effort | Description |
|------|--------|-------------|
| Tag taxonomy mapping | 3 days | Normalize tags to standard categories (style, occasion, etc.) |
| Tag weight learning | 2 days | Learn which tags predict purchases |
| Tag-based filtering | 1 day | "Show me only casual styles" |

### 3.2 Description Analysis

| Task | Effort | Description |
|------|--------|-------------|
| Keyword extraction | 2 days | Extract style/material/feature keywords |
| Description embeddings | 3 days | Generate embeddings for semantic search |
| Similar by description | 2 days | Find products with similar descriptions |

### 3.3 CLIP Integration (Visual Intelligence)

| Task | Effort | Description |
|------|--------|-------------|
| CLIP embedding pipeline | 1 week | Generate image+text embeddings |
| Visual similarity search | 3 days | "Find products that look like this" |
| Pattern/color extraction | 3 days | Identify patterns and colors from images |
| Style clustering | 1 week | Group products by visual style |

**Note:** CLIP is higher effort but high value for visual discovery.

---

## Phase 4: Advanced Features (Weeks 13-20)

### 4.1 Purchase Readiness v2 (ML-based)

| Task | Effort | Description |
|------|--------|-------------|
| Feature engineering | 1 week | Build training dataset from outcomes |
| Model training | 1 week | Logistic regression or XGBoost |
| A/B test vs RFM | 2 weeks | Measure lift over rule-based |
| Production deployment | 3 days | Real-time scoring |

### 4.2 Collaborative Filtering & Cross-Retailer Intelligence

These features share the same foundation: learning patterns across customers and retailers.

#### Item-Based CF (Within Retailer)

| Task | Effort | Description |
|------|--------|-------------|
| Item co-purchase tables | 3 days | "Bought together" patterns |
| "Complete the Look" from CF | 1 week | Complementary products from co-purchase |

#### Cross-Retailer Intelligence (Across Retailers)

| Task | Effort | Description |
|------|--------|-------------|
| Anonymization pipeline | 1 week | Hash customer IDs across retailers |
| Size co-occurrence tables | 3 days | Build size mapping from purchases |
| Size prediction API | 2 days | GET /size-prediction/{customer} |
| Brand affinity mapping | 1 week | Cross-retailer brand preferences |

**Start with:** Shoes sizes only (most standardized), top 5 retailers with overlap.

#### User-Based CF (If Needed)

| Task | Effort | Description |
|------|--------|-------------|
| User similarity | 1 week | For new customer bootstrap |
| Cold start recs | 3 days | Bootstrap from similar customers |

**Note:** Only pursue collaborative filtering if explicit preferences show diminishing returns. Cross-retailer intelligence is a unique competitive advantage worth investing in once core features are solid.

---

## Phase Summary

| Phase | Weeks | Focus | Key Deliverables |
|-------|-------|-------|------------------|
| **1** | 1-4 | Quick Wins + Shopify | Model improvements, Shopify App Blocks, Purchase readiness v1 |
| **2** | 5-8 | Polish + Expand | Shopify enhancements, Web Components |
| **3** | 9-12 | Product Intelligence | Tag processing, description analysis, CLIP |
| **4** | 13-20 | Advanced | ML readiness, CF + Cross-retailer intelligence |

---

## Quick Reference: What to Build When

### This Week (Quick Wins)
- [ ] Out-of-stock hard filter
- [ ] Wishlist deduplication
- [ ] Trending boost in scorer

### This Month (Shopify MVP)
- [ ] Theme App Extension scaffold
- [ ] "For You" App Block
- [ ] Shopify Proxy endpoint
- [ ] Purchase readiness v1

### This Quarter (Full Widget Suite)
- [ ] All Shopify blocks (Trending, Similar, Complete the Look)
- [ ] Web Components for non-Shopify
- [ ] Tag taxonomy and scoring improvements
- [ ] Product intelligence pipeline basics

---

## Success Metrics

| Metric | Current | Target (6 months) |
|--------|---------|-------------------|
| Widget CTR | - | >3% |
| Recommendation conversion | - | >2% |
| Attribution revenue | $0 | Track and grow |
| Size prediction accuracy | - | >80% |
| Purchase readiness lift | - | >20% vs random |
| Shopify merchants live | 0 | 10+ |

---

## Dependencies & Risks

| Risk | Mitigation |
|------|------------|
| inStock data not populated | Prioritize data pipeline fix before out-of-stock filtering |
| Shopify app approval delays | Start review process early, follow guidelines strictly |
| CLIP infrastructure cost | Start with batch processing, optimize later |
| Cross-retailer data privacy | Legal review before implementation |

---

## Next Steps

1. **Immediate:** Implement quick wins (out-of-stock filter, wishlist dedup, trending boost)
2. **This week:** Set up Shopify Theme App Extension scaffold
3. **This month:** Ship Shopify MVP with "For You" block
4. **Ongoing:** Track metrics, iterate based on data

---

*Last updated: May 2026*
