# TWC Recommendations - ML Roadmap

## Vision

Transform the recommendation engine from a rule-based scoring system to a continuously improving ML-powered system that learns from customer interactions and optimizes for business outcomes.

---

## Current State: Phase 1 (Complete)

### Rule-Based Scoring
- ✅ Feature matching (preferences, purchase history, browsing, wishlist)
- ✅ Configurable weights for different customer types
- ✅ Dislike filtering (hard exclusions)
- ✅ Preference source weighting (customer > staff > inferred)
- ✅ Result diversification
- ✅ Sold-out alternative finder

### Data Infrastructure
- ✅ Anonymized customer model (no PII)
- ✅ ClickHouse repository layer
- ✅ Recommendation event logging (`TWCRECOMMENDATION_LOG`)
- ✅ Outcome tracking (`TWCRECOMMENDATION_OUTCOME`)
- ✅ Pre-aggregated materialized views for metrics

---

## Phase 2: Outcome Tracking & Baseline Metrics (Next)

### Objective
Establish a feedback loop by capturing what happens after recommendations are shown.

### Deliverables

1. **Frontend Integration**
   - Pass `event_id` to client applications
   - Track clicks on recommended products
   - Track add-to-cart events
   - Track purchases (with attribution window)

2. **Attribution Logic**
   - Link purchases to recommendations within N days
   - Handle multi-touch attribution
   - Track position bias (does position 1 always win?)

3. **Metrics Dashboard**
   - Click-through rate (CTR) by model version
   - Conversion rate (CVR) by model version
   - Revenue per recommendation
   - Position analysis

### Success Criteria
- CTR baseline established
- CVR baseline established
- 30 days of outcome data collected

### Estimated Effort: 3-4 weeks

---

## Phase 3: A/B Testing Framework

### Objective
Enable controlled experiments to validate improvements before full rollout.

### Deliverables

1. **Traffic Splitting**
   - Hash-based assignment (consistent per customer)
   - Configurable percentage splits
   - Multiple concurrent tests support

2. **Variant Management**
   - Control vs treatment configuration
   - Different weight presets
   - Different model versions
   - Feature flags

3. **Statistical Analysis**
   - Sample size calculator
   - Significance testing
   - Confidence intervals
   - Guardrail metrics (ensure no regression)

4. **Test Management UI**
   - Create/stop tests
   - View results
   - Winner declaration

### Success Criteria
- Run first A/B test comparing weight configurations
- Measure statistical significance
- Ship winning variant

### Estimated Effort: 4-5 weeks

---

## Phase 4: ML Model Training Pipeline

### Objective
Replace rule-based scoring with learned models that optimize for conversions.

### Deliverables

1. **Feature Store**
   - Customer features (purchase recency, frequency, monetary)
   - Product features (category embeddings, popularity scores)
   - Interaction features (view count, cart rate)
   - Real-time feature serving

2. **Training Pipeline**
   - Export training data from ClickHouse
   - Feature engineering pipeline
   - Model training (XGBoost/LightGBM for tabular)
   - Model versioning (MLflow)

3. **Model Types**
   - Pointwise ranking model (predict conversion probability)
   - Consider: Neural collaborative filtering
   - Consider: Transformer-based embeddings

4. **Inference Service**
   - Model serving (batch or real-time)
   - A/B test integration
   - Fallback to rule-based

### Architecture

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

### Success Criteria
- First ML model deployed
- ML model beats rule-based by >5% CVR in A/B test
- Training pipeline runs weekly

### Estimated Effort: 8-12 weeks

---

## Phase 5: Continuous Learning & Next Best Action

### Objective
Create a self-improving system that continuously learns and expands beyond product recommendations.

### Deliverables

1. **Online Learning**
   - Real-time model updates from new interactions
   - Bandit algorithms for exploration/exploitation
   - Cold-start handling for new products

2. **Next Best Action (NBA)**
   - Recommend actions to staff (call customer, send email, etc.)
   - Action outcome tracking
   - Action-specific models

3. **Personalized Outreach**
   - "Products You Might Like" emails
   - "Back in Stock" notifications
   - "Similar to Wishlist" alerts

4. **Advanced Features**
   - Contextual bandits (time of day, device, etc.)
   - Cross-retailer learning (with privacy)
   - Seasonal adaptation

### NBA Action Catalog

| Action | Trigger | Expected Outcome |
|--------|---------|------------------|
| Send styling suggestion | High-value customer inactive 30+ days | Re-engage, purchase |
| Notify wishlist back in stock | Item restocked | Purchase wishlist item |
| Invite to VIP event | Top 10% by spend | Brand loyalty, purchase |
| Offer personal shopping | Cart abandoned >$500 | Convert abandoned cart |
| Send size recommendation | Multiple returns for sizing | Reduce returns |

### Success Criteria
- Real-time model updates operational
- NBA deployed for at least 3 action types
- Measurable impact on customer lifetime value

### Estimated Effort: 12-16 weeks (ongoing)

---

## Technical Considerations

### Infrastructure Requirements

| Phase | Compute | Storage | New Services |
|-------|---------|---------|--------------|
| 2 | Minimal | +10GB/month logs | None |
| 3 | Minimal | +1GB for configs | None |
| 4 | GPU for training | +100GB for features | MLflow, Feature Store |
| 5 | Real-time inference | Streaming data | Kafka/Kinesis |

### Risk Mitigation

1. **Data Quality**
   - Validate click/purchase tracking before relying on it
   - Monitor for missing data
   - Handle attribution edge cases

2. **Model Degradation**
   - Continuous monitoring of model performance
   - Automatic fallback to rule-based
   - Drift detection

3. **Privacy**
   - All customer data remains anonymized
   - No PII in training data
   - Per-tenant model isolation

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
- **Customer lifetime value** (CLTV) impact
- **Return rate** for recommended products
- **Customer satisfaction** (NPS for recommendations)

### Model Metrics
- **NDCG** (Normalized Discounted Cumulative Gain)
- **MRR** (Mean Reciprocal Rank)
- **Coverage**: % of catalog recommended
- **Diversity**: Variety in recommendations

---

## Timeline Summary

| Phase | Duration | Key Milestone |
|-------|----------|---------------|
| 1 | Complete | Rule-based engine live |
| 2 | 3-4 weeks | Baseline metrics established |
| 3 | 4-5 weeks | First A/B test completed |
| 4 | 8-12 weeks | ML model beats rules |
| 5 | 12-16 weeks | Continuous learning operational |

**Total estimated time to Phase 5:** 6-9 months

---

## References

- [TWC Recommendations Architecture](./ARCHITECTURE.md)
- [ClickHouse Migration Scripts](../migrations/001_recommendation_logging.sql)
- [Model Code](../src/engine/recommender.py)
