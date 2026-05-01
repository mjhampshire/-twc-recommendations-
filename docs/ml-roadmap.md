# TWC Recommendations - ML Roadmap

## Vision

Transform the recommendation engine from a rule-based scoring system to a continuously improving ML-powered system that learns from customer interactions and optimizes for business outcomes.

---

## Phase 1: Rule-Based Scoring ✅ Complete

### Deliverables

**Scoring Engine**
- ✅ Feature matching (preferences, purchase history, browsing, wishlist)
- ✅ Configurable weights for different customer types
- ✅ Dislike filtering (hard exclusions)
- ✅ Preference source weighting (customer > staff > inferred)
- ✅ Result diversification
- ✅ Sold-out alternative finder
- ✅ Tags and collections scoring
- ✅ Multi-collection support (comma-separated parsing)

**Data Infrastructure**
- ✅ Anonymized customer model (no PII)
- ✅ ClickHouse repository layer
- ✅ Product attributes (category, brand, color, style, tags, description)

---

## Phase 2: Outcome Tracking & Baseline Metrics ✅ Complete

### Deliverables

**Logging Infrastructure**
- ✅ `TWCRECOMMENDATION_LOG` - Recommendation events with context
- ✅ `TWCRECOMMENDATION_OUTCOME` - Click, cart, wishlist, purchase outcomes
- ✅ Pre-aggregated materialized views for metrics
- ✅ `RecommendationLogger` service with outcome methods

**API Endpoints**
- ✅ `POST /outcomes/{retailer_id}/{customer_id}/{event_id}` - Log outcomes
- ✅ Outcome types: clicked, added_to_cart, added_to_wishlist, dismissed, viewed
- ✅ Actor tracking (customer vs staff)
- ✅ Position tracking for bias analysis

**Attribution**
- ✅ Event ID links recommendations to outcomes
- ✅ A/B test variant tracking on outcomes

---

## Phase 3: A/B Testing Framework ✅ Complete

### Deliverables

**Traffic Splitting**
- ✅ Hash-based assignment (consistent per customer)
- ✅ Configurable percentage splits
- ✅ `ABTestManager` for variant assignment

**Variant Management**
- ✅ Control vs treatment configuration
- ✅ Different weight presets per variant
- ✅ `TWCAB_TEST` table for test configuration
- ✅ `TWCTENANT_WEIGHTS` for promoted winners

**Statistical Analysis**
- ✅ `ABTestAnalyzer` with chi-squared significance testing
- ✅ Confidence intervals and p-value calculation
- ✅ Sample size validation
- ✅ Recommended action generation

**Auto-Optimization**
- ✅ Multi-armed bandit (Thompson Sampling)
- ✅ `BanditManager` for arm selection
- ✅ Automatic weight variation generation
- ✅ Auto-promotion of winners

**API Endpoints**
- ✅ Full CRUD for A/B tests
- ✅ Tenant configuration management
- ✅ Bandit enable/disable/sync/reset

---

## Phase 4: ML Model Training Pipeline (Planned)

**Objective:** Replace rule-based scoring with learned models that optimize for conversions.

### 4.1 Feature Store

| Feature Category | Features | Source |
|------------------|----------|--------|
| **Customer (RFM)** | Recency, frequency, monetary value, days since last purchase | Orders, clickstream |
| **Customer (Behavioral)** | Browse patterns, cart rate, wishlist rate, return rate | Clickstream, orders |
| **Product (Popularity)** | View count, cart rate, conversion rate, trending score | Aggregated events |
| **Product (Attributes)** | Category embedding, brand embedding, price percentile | Product catalog |
| **Product (Visual)** | CLIP embeddings, style cluster, pattern/color vectors | Images + CLIP |
| **Product (Text)** | Description embeddings, tag embeddings | Descriptions, tags |
| **Interaction** | Customer-product affinity, category match, brand match | Computed |

### 4.2 Training Pipeline

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ ClickHouse  │────▶│   Feature    │────▶│   Model     │
│   (logs)    │     │   Pipeline   │     │  Training   │
└─────────────┘     └──────────────┘     └─────────────┘
                                               │
                                               ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Real-time  │◀────│   Feature    │◀────│   Model     │
│  Inference  │     │   Store      │     │  Registry   │
└─────────────┘     └──────────────┘     └─────────────┘
```

| Task | Effort | Description |
|------|--------|-------------|
| Export training data | 3 days | Labeled examples from ClickHouse outcomes |
| Feature engineering pipeline | 1 week | Transform raw data to ML features |
| Model training | 1 week | XGBoost/LightGBM for ranking |
| Model versioning | 2 days | MLflow for experiment tracking |
| Real-time feature serving | 1 week | Low-latency feature lookup |

### 4.3 Model Types

| Model | Use Case | Approach |
|-------|----------|----------|
| **Pointwise ranker** | Predict P(conversion) per product | XGBoost on customer×product features |
| **Embedding retrieval** | Find similar products | CLIP/text embeddings + ANN search |
| **Two-tower model** | Customer-product matching | Separate customer/product encoders |
| **Neural CF** | Collaborative signals | If explicit preferences plateau |

### 4.4 Inference Service

| Task | Effort | Description |
|------|--------|-------------|
| Batch inference | 3 days | Pre-compute scores for active customers |
| Real-time inference | 1 week | On-demand scoring API |
| Fallback logic | 2 days | Graceful degradation to rule-based |
| A/B test integration | 2 days | Route traffic between models |

### Success Criteria
- [ ] First ML model deployed
- [ ] ML model beats rule-based by >5% CVR in A/B test
- [ ] Training pipeline runs weekly
- [ ] <100ms inference latency

**Estimated Effort:** 8-12 weeks

---

## Phase 5: Continuous Learning & Next Best Action (Planned)

**Objective:** Create a self-improving system that continuously learns and expands beyond product recommendations.

### 5.1 Online Learning

| Task | Effort | Description |
|------|--------|-------------|
| Streaming feature updates | 2 weeks | Real-time feature refresh from events |
| Incremental model updates | 2 weeks | Update models without full retrain |
| Bandit exploration | 1 week | Contextual bandits for new products |
| Cold-start handling | 1 week | Bootstrap new products/customers |
| Drift detection | 1 week | Alert on model performance degradation |
| Seasonal adaptation | 1 week | Detect and adapt to seasonal shifts |

### 5.2 Next Best Action (NBA)

Recommend actions to staff, not just products.

| Task | Effort | Description |
|------|--------|-------------|
| Purchase readiness scoring | 2 weeks | ML-based propensity to buy |
| Action recommendation API | 1 week | GET /customers/{id}/next-action |
| Action outcome tracking | 3 days | Track which actions drive results |
| Action-specific models | 2 weeks | Optimize per action type |

**NBA Action Catalog:**

| Action | Trigger | Expected Outcome |
|--------|---------|------------------|
| Send styling suggestion | High-value customer inactive 30+ days | Re-engage, purchase |
| Notify wishlist back in stock | Item restocked | Purchase wishlist item |
| Invite to VIP event | Top 10% by spend | Brand loyalty, purchase |
| Offer personal shopping | Cart abandoned >$500 | Convert abandoned cart |
| Send size recommendation | Multiple returns for sizing | Reduce returns |
| Predict size at new retailer | First visit, has cross-retailer data | Reduce sizing friction |
| Suggest cross-retailer brands | New to retailer, has affinity data | Faster discovery |

### 5.3 Personalized Outreach

| Task | Effort | Description |
|------|--------|-------------|
| "Products You Might Like" emails | 2 weeks | Personalized email content |
| "Back in Stock" notifications | 1 week | Wishlist item alerts |
| "Similar to Wishlist" alerts | 1 week | New arrivals matching wishlist |
| Optimal send time | 1 week | Learn best time to contact each customer |

### 5.4 Cross-Retailer Intelligence

Leverage anonymized data across TWC retailers for unique insights.

| Task | Effort | Description |
|------|--------|-------------|
| Anonymization pipeline | 1 week | Hash(email + salt) → anon_id |
| Size co-occurrence tables | 3 days | Build size mappings from purchases |
| Size prediction API | 2 days | Predict size at new retailers |
| Brand affinity mapping | 1 week | Cross-retailer brand preferences |
| Cold-start from cross-retailer | 3 days | Bootstrap recs for new-to-retailer customers |

**Privacy Architecture:**
```
Retailer A                    Retailer B
    │                             │
    ▼                             ▼
┌─────────────────────────────────────┐
│   Anonymization Layer               │
│   hash(email + global_salt)         │
│                                     │
│   Stores ONLY:                      │
│   - Sizes purchased                 │
│   - Categories purchased            │
│   - Brands purchased                │
│   - Price ranges                    │
│                                     │
│   NEVER stores:                     │
│   - Email, name, address            │
│   - Any PII                         │
└─────────────────────────────────────┘
```

### Success Criteria
- [ ] Real-time model updates operational
- [ ] NBA deployed for at least 3 action types
- [ ] Cross-retailer size prediction >80% accuracy
- [ ] Measurable impact on customer lifetime value

**Estimated Effort:** 12-16 weeks (ongoing)

---

## Technical Considerations

### Infrastructure Requirements

| Phase | Compute | Storage | New Services |
|-------|---------|---------|--------------|
| 1-3 | Minimal | Existing ClickHouse | None |
| 4 | GPU for training | +100GB for features | MLflow, Feature Store |
| 5 | Real-time inference | Streaming data | Kafka/Kinesis (optional) |

### Risk Mitigation

**Data Quality**
- Validate click/purchase tracking before relying on it
- Monitor for missing data
- Handle attribution edge cases

**Model Degradation**
- Continuous monitoring of model performance
- Automatic fallback to rule-based
- Drift detection alerts

**Privacy**
- All customer data remains anonymized
- No PII in training data
- Per-tenant model isolation
- Cross-retailer data uses separate anon IDs

---

## Metrics to Track

### Engagement Metrics
- **CTR** (Click-through rate): % of recommendations clicked
- **View rate**: % of recommendations viewed in detail
- **Cart rate**: % of recommendations added to cart

### Conversion Metrics
- **CVR** (Conversion rate): % of recommendations purchased
- **Revenue per recommendation**: Total revenue / recommendation events
- **Incremental revenue**: Revenue from recommendations vs no recommendations

### Business Metrics
- Customer lifetime value (CLTV) impact
- Return rate for recommended products
- Customer satisfaction (NPS for recommendations)

### Model Metrics
- **NDCG** (Normalized Discounted Cumulative Gain)
- **MRR** (Mean Reciprocal Rank)
- **Coverage**: % of catalog recommended
- **Diversity**: Variety in recommendations

---

## Timeline Summary

| Phase | Status | Duration | Key Milestone |
|-------|--------|----------|---------------|
| 1 | ✅ Complete | - | Rule-based engine live |
| 2 | ✅ Complete | - | Outcome tracking operational |
| 3 | ✅ Complete | - | A/B testing + bandit live |
| 4 | Planned | 8-12 weeks | ML model beats rules |
| 5 | Planned | 12-16 weeks | Continuous learning + NBA operational |

**Time to Phase 5 completion:** 5-7 months from start of Phase 4

---

## References

- [ROADMAP.md](./ROADMAP.md) - Delivery roadmap (Shopify, widgets, quick wins)
- [future-enhancements.md](./future-enhancements.md) - Purchase readiness & cross-retailer details
- [collaborative-filtering-consideration.md](./collaborative-filtering-consideration.md) - CF analysis
- [widget-architecture.md](./widget-architecture.md) - Widget delivery architecture

---

*Last updated: May 2026*
