# Automated A/B Testing for Weight Optimization

## Overview

The TWC Recommendations service includes an automated A/B testing system that continuously optimizes recommendation weights to improve conversion rates. The system assigns customers to test variants, tracks outcomes, analyzes results for statistical significance, and automatically promotes winning configurations.

This enables data-driven optimization of the recommendation algorithm without manual intervention, ensuring the system continuously improves based on actual customer behavior.

---

## Business Value

### Why A/B Test Recommendation Weights?

The recommendation engine uses configurable weights to balance different signals when scoring products:

- **Stated preferences** (colors, styles, categories the customer said they like)
- **Purchase history** (what they've actually bought)
- **Browsing behavior** (what they've viewed, added to cart)
- **Wishlist data** (what they want to buy)
- **Product popularity** (what's trending)

Different weight configurations work better for different retailers and customer segments. A/B testing allows us to:

1. **Validate hypotheses** - Test whether emphasizing behavior over stated preferences improves conversions
2. **Optimize continuously** - Automatically find better configurations over time
3. **Reduce risk** - Test changes on a subset of traffic before full rollout
4. **Measure impact** - Quantify the business value of algorithm changes

### Key Metrics Tracked

| Metric | Description |
|--------|-------------|
| Conversion Rate | % of recommendations that lead to purchases |
| Click-Through Rate | % of recommendations that are clicked |
| Cart Rate | % of recommendations added to cart |
| Revenue per Recommendation | Average revenue generated per recommendation event |

### Expected Outcomes

- **Improved conversion rates** through continuous optimization
- **Reduced manual tuning** with automated promotion of winners
- **Faster iteration** with auto-generated test variations
- **Data-driven decisions** backed by statistical significance

---

## How It Works

### Test Lifecycle

```
┌─────────────────────────────────────────────────────────────────────┐
│                         A/B TEST LIFECYCLE                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. CREATE TEST                                                     │
│     ├── Define control weights (baseline)                           │
│     ├── Define treatment weights (challenger)                       │
│     └── Set traffic allocation (e.g., 20% to treatment)            │
│                                                                     │
│  2. ASSIGN CUSTOMERS                                                │
│     ├── Deterministic assignment via hash(customer_id + test_id)   │
│     ├── Same customer always sees same variant                      │
│     └── Assignment logged with each recommendation                  │
│                                                                     │
│  3. COLLECT DATA                                                    │
│     ├── Track recommendations per variant                           │
│     ├── Track outcomes (clicks, cart adds, purchases)              │
│     └── Wait for minimum sample size (default: 1,000)              │
│                                                                     │
│  4. ANALYZE RESULTS                                                 │
│     ├── Calculate conversion rates per variant                      │
│     ├── Chi-squared test for statistical significance              │
│     └── Determine if lift exceeds threshold (default: 5%)          │
│                                                                     │
│  5. AUTO-PROMOTE (if enabled)                                       │
│     ├── Promote winner as new default weights                       │
│     ├── End current test                                            │
│     └── Start new test with variation of winner                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Variant Assignment

Customers are assigned to variants using a deterministic hash:

```
hash(customer_id + test_id) % 100 < traffic_percentage → treatment
                                                       → control
```

This ensures:
- **Consistency** - The same customer always sees the same variant during a test
- **Even distribution** - Traffic is split according to the configured percentage
- **No session dependency** - Works across devices and sessions

### Statistical Analysis

Results are analyzed using the **chi-squared test** for comparing conversion rates:

- **Null hypothesis**: There is no difference between control and treatment
- **Alternative hypothesis**: Treatment performs differently than control
- **Significance threshold**: p-value < 0.05 (95% confidence)
- **Minimum lift required**: 5% improvement to promote treatment

### Auto-Promotion Flow

When a test reaches statistical significance:

1. **Identify winner** - Treatment (if lift > 5%) or Control (if lift < -5%)
2. **Update tenant defaults** - Set winner as the new default weights
3. **End test** - Mark test as complete with end date
4. **Generate variation** - Create new weights by perturbing winner by ±10-20%
5. **Start new test** - Begin testing winner vs. variation

This creates a continuous optimization loop that gradually improves performance.

---

## Configuration Options

### Per-Tenant Settings

Each retailer can customize A/B testing behavior:

| Setting | Default | Description |
|---------|---------|-------------|
| `AUTO_PROMOTE_ENABLED` | true | Automatically promote winning variants |
| `AUTO_START_NEW_TESTS` | true | Auto-start new tests after promotion |
| `MIN_SAMPLES_FOR_SIGNIFICANCE` | 1000 | Minimum recommendations before checking significance |
| `P_VALUE_THRESHOLD` | 0.05 | Statistical significance level (95% confidence) |
| `MIN_LIFT_FOR_PROMOTION` | 0.05 | 5% improvement required to promote |
| `NEW_TEST_TRAFFIC_PERCENTAGE` | 20 | Traffic % for auto-generated tests |

### Safety Controls

To disable automatic test iteration (e.g., during peak periods):

```bash
# Disable auto-starting new tests
PUT /api/v1/ab-tests/{retailer_id}/config
{"auto_start_new_tests": false}

# Disable all auto-promotion
PUT /api/v1/ab-tests/{retailer_id}/config
{"auto_promote_enabled": false}
```

When `AUTO_START_NEW_TESTS = false`:
- Winners are still promoted as new defaults
- Tests end and results are logged
- No new test is automatically created
- Manual intervention required to start next test

---

## API Reference

### Create a Test

```bash
POST /api/v1/ab-tests/{retailer_id}

{
  "name": "behavior_vs_preference",
  "description": "Test if behavioral signals outperform stated preferences",
  "control_weights": "default",
  "treatment_weights": "behavior_heavy",
  "traffic_percentage": 20
}
```

**Response:**
```json
{
  "test_id": "550e8400-e29b-41d4-a716-446655440000",
  "tenant_id": "viktoria-woods",
  "name": "behavior_vs_preference",
  "control_weights": "default",
  "treatment_weights": "behavior_heavy",
  "traffic_percentage": 20,
  "is_active": true,
  "start_date": "2024-01-15T10:30:00Z"
}
```

### Get Test Results

```bash
GET /api/v1/ab-tests/{retailer_id}/{test_id}
```

**Response:**
```json
{
  "test_id": "550e8400-e29b-41d4-a716-446655440000",
  "test_name": "behavior_vs_preference",
  "control_cvr": 0.032,
  "treatment_cvr": 0.038,
  "lift": 0.1875,
  "p_value": 0.023,
  "is_significant": true,
  "confidence_level": 0.977,
  "total_samples": 2450,
  "has_enough_samples": true,
  "recommended_action": "promote_treatment",
  "recommended_weights": "behavior_heavy",
  "days_running": 7
}
```

### List Active Tests

```bash
GET /api/v1/ab-tests/{retailer_id}
```

### Update Test

```bash
PUT /api/v1/ab-tests/{retailer_id}/{test_id}

{
  "traffic_percentage": 50
}
```

### End Test

```bash
DELETE /api/v1/ab-tests/{retailer_id}/{test_id}
```

### Get/Update Configuration

```bash
GET /api/v1/ab-tests/{retailer_id}/config

PUT /api/v1/ab-tests/{retailer_id}/config
{
  "auto_start_new_tests": false,
  "min_samples_for_significance": 2000
}
```

---

## Built-in Weight Presets

| Preset | Description |
|--------|-------------|
| `default` | Balanced approach giving equal weight to preferences and behavior |
| `preference_heavy` | Prioritizes stated preferences (colors, styles, categories) |
| `behavior_heavy` | Prioritizes actual behavior (purchases, browsing, cart) |
| `new_customer` | For customers with minimal history; emphasizes popularity |

Custom presets are automatically generated during the auto-iteration process and stored in the database.

---

## Technical Architecture

### Components

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  API Request    │────▶│  ABTestManager   │────▶│  Weight Config  │
│  /recommend     │     │  assign_variant  │     │  for scoring    │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │  Log event with  │
                        │  ab_test_id &    │
                        │  variant name    │
                        └──────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │  Outcomes logged │
                        │  (existing flow) │
                        └──────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │  ABTestAnalyzer  │
                        │  (scheduled job) │
                        │  - Compare rates │
                        │  - Significance  │
                        │  - Auto-promote  │
                        └──────────────────┘
```

### Database Tables

| Table | Purpose |
|-------|---------|
| `TWCAB_TEST` | A/B test configurations |
| `TWCTENANT_WEIGHTS` | Current best weights per tenant |
| `TWCTENANT_CONFIG` | A/B testing settings per tenant |
| `TWCWEIGHT_PRESETS` | Custom weight presets (auto-generated variations) |
| `TWCRECOMMENDATION_LOG` | Extended with `abTestId` and `abTestVariant` columns |

### Files

| File | Purpose |
|------|---------|
| `src/models/ab_test.py` | Data models for tests, assignments, and results |
| `src/data/ab_test_repository.py` | Database operations for A/B test data |
| `src/engine/ab_test_manager.py` | Variant assignment logic |
| `src/engine/ab_test_analyzer.py` | Statistical analysis and auto-promotion |
| `src/jobs/ab_test_promoter.py` | Scheduled job entry point |
| `src/api/routes.py` | API endpoints for test management |

### Scheduled Job

The auto-promoter runs hourly via Kubernetes CronJob:

```yaml
# k8s/cronjob-ab-promoter.yaml
schedule: "0 * * * *"  # Every hour at minute 0
```

To run manually:
```bash
python -m src.jobs.ab_test_promoter
```

---

## Monitoring & Observability

### Recommendation Response

Every recommendation response includes A/B test information:

```json
{
  "customer_id": "cust_123",
  "recommendations": [...],
  "weights_used": "behavior_heavy",
  "event_id": "evt_456",
  "ab_test_id": "test_789",
  "ab_test_variant": "treatment"
}
```

### Job Output

The promoter job outputs JSON for monitoring:

```json
{
  "start_time": "2024-01-15T10:00:00Z",
  "end_time": "2024-01-15T10:00:02Z",
  "duration_seconds": 2.3,
  "actions": [
    {
      "test_id": "test_789",
      "tenant_id": "viktoria-woods",
      "action": "promote_treatment",
      "winner_weights": "behavior_heavy",
      "lift": 0.18,
      "p_value": 0.02,
      "new_test_id": "test_790",
      "new_treatment_weights": "behavior_heavy_var_a1b2c3"
    }
  ],
  "action_count": 1
}
```

---

## Getting Started

### 1. Run the Migration

```bash
clickhouse-client --query "$(cat migrations/003_ab_test_tracking.sql)"
```

### 2. Create Your First Test

```bash
curl -X POST https://api.example.com/api/v1/ab-tests/viktoria-woods \
  -H "Content-Type: application/json" \
  -d '{
    "name": "q1_2024_optimization",
    "description": "Test behavior-heavy weights",
    "control_weights": "default",
    "treatment_weights": "behavior_heavy",
    "traffic_percentage": 20
  }'
```

### 3. Monitor Results

```bash
curl https://api.example.com/api/v1/ab-tests/viktoria-woods/{test_id}
```

### 4. Deploy the Promoter Job

```bash
kubectl apply -f k8s/cronjob-ab-promoter.yaml
```

---

## Best Practices

1. **Start conservative** - Begin with 10-20% traffic to treatment
2. **Run tests long enough** - Wait for minimum samples and business cycles
3. **One test at a time** - Only one active test per retailer to avoid interaction effects
4. **Monitor closely** - Watch for unexpected negative impacts
5. **Document hypotheses** - Use meaningful test names and descriptions
6. **Review auto-promotions** - Periodically audit the auto-generated variations

---

## Design Decisions

This section documents the key architectural and implementation choices made, along with alternatives considered and rationale for decisions.

### 1. Variant Assignment Strategy

**Chosen:** Deterministic hashing using `SHA256(customer_id + test_id) % 100`

**Alternatives considered:**
| Approach | Pros | Cons |
|----------|------|------|
| Random assignment | Simple | Inconsistent experience across sessions |
| Cookie/session-based | Works for anonymous users | Doesn't persist across devices |
| Database lookup | Explicit control | Extra latency, storage overhead |
| **Deterministic hash** | Consistent, no storage, fast | Requires customer ID |

**Rationale:** Since our use case involves known customers (VIP clienteling), we always have a customer ID. Hashing provides consistency without database lookups or session state.

**Future consideration:** For anonymous browsing recommendations, we may need session-based assignment with eventual reconciliation when customers identify themselves.

---

### 2. Statistical Test Method

**Chosen:** Chi-squared test for comparing conversion rates

**Alternatives considered:**
| Method | Pros | Cons |
|--------|------|------|
| **Chi-squared test** | Standard, well-understood | Requires sufficient sample size |
| Z-test for proportions | Similar to chi-squared | Less robust for small samples |
| Bayesian A/B testing | No fixed sample size needed | More complex to implement |
| Sequential testing | Can stop early | Risk of false positives |

**Rationale:** Chi-squared is the industry standard for conversion rate comparisons, well-supported by scipy, and easy to interpret. The minimum sample size requirement (default 1,000) mitigates small-sample issues.

**Future consideration:** Bayesian methods would allow for more nuanced probability statements ("90% chance treatment is better") and could enable adaptive traffic allocation.

---

### 3. Traffic Allocation

**Chosen:** Fixed percentage allocation (configurable per test)

**Alternatives considered:**
| Approach | Pros | Cons |
|----------|------|------|
| **Fixed allocation** | Simple, predictable | May waste traffic on losing variant |
| Multi-armed bandit | Minimizes regret | Harder to reach significance |
| Thompson sampling | Probabilistic, adaptive | Complex implementation |
| Epsilon-greedy | Simple adaptive | Suboptimal exploration |

**Rationale:** Fixed allocation is simpler to implement, easier to explain to stakeholders, and provides clean statistical interpretation. The auto-iteration loop compensates by quickly moving to new tests.

**Future consideration:** Thompson sampling could reduce the "cost" of testing by automatically shifting traffic toward better-performing variants while still exploring.

---

### 4. One Test Per Tenant

**Chosen:** Enforce single active test per retailer

**Alternatives considered:**
| Approach | Pros | Cons |
|----------|------|------|
| **Single test** | Clean measurement, no interaction | Slower iteration |
| Multiple tests | Faster iteration | Interaction effects, complex analysis |
| Factorial design | Test combinations | Requires much more traffic |
| Layered experiments | Independent tests | Complex infrastructure |

**Rationale:** With our traffic volumes, running multiple simultaneous tests would make it difficult to reach statistical significance and could introduce confounding effects between tests.

**Future consideration:** As traffic grows, a layered experimentation platform (like Google's Overlapping Experiment Infrastructure) could enable multiple independent tests.

---

### 5. Auto-Promotion Criteria

**Chosen:** Promote when p < 0.05 AND lift > 5%

**Alternatives considered:**
| Approach | Pros | Cons |
|----------|------|------|
| Significance only | Simpler rule | May promote tiny improvements |
| **Significance + min lift** | Ensures meaningful impact | May miss small but real effects |
| Confidence intervals | More nuanced | Harder to automate |
| Expected value | Accounts for uncertainty | Requires Bayesian framework |

**Rationale:** Requiring both statistical significance AND a minimum lift threshold (5%) ensures we only promote changes that are both real and meaningful. This prevents churn from promoting insignificant improvements.

**Future consideration:** Expected value calculations could account for uncertainty - a highly uncertain 10% lift might be worth less than a certain 6% lift.

---

### 6. Weight Variation Generation

**Chosen:** Random perturbation of 2-3 dimensions by ±10-20%

**Alternatives considered:**
| Approach | Pros | Cons |
|----------|------|------|
| **Random perturbation** | Simple, explores space | May miss optimal region |
| Gradient-based | Directed search | Requires differentiable objective |
| Genetic algorithms | Global optimization | Complex, slow |
| Bayesian optimization | Efficient search | Requires surrogate model |

**Rationale:** Random perturbation is simple to implement and provides reasonable exploration of the weight space. The continuous iteration loop means suboptimal steps are quickly corrected.

**Future consideration:** Bayesian optimization with Gaussian processes could more efficiently navigate the weight space by building a model of which regions are promising.

---

### 7. Primary Metric

**Chosen:** Conversion rate (purchases / recommendations)

**Alternatives considered:**
| Metric | Pros | Cons |
|--------|------|------|
| **Conversion rate** | Clear business value | Ignores purchase value |
| Revenue per recommendation | Accounts for AOV | Higher variance |
| Click-through rate | Fast feedback | Doesn't measure business value |
| Composite score | Balanced | Arbitrary weighting |

**Rationale:** Conversion rate is the clearest measure of recommendation effectiveness and has lower variance than revenue metrics, enabling faster statistical significance.

**Future consideration:** Multi-objective optimization could balance conversion rate with average order value, or use revenue per recommendation with variance reduction techniques.

---

### 8. Data Storage

**Chosen:** ClickHouse with ReplacingMergeTree tables

**Alternatives considered:**
| Storage | Pros | Cons |
|---------|------|------|
| **ClickHouse** | Already used, fast analytics | Eventual consistency |
| PostgreSQL | ACID, familiar | Slower for analytics |
| Redis | Fast reads | Not suitable for analytics |
| Dedicated A/B platform | Purpose-built | Additional infrastructure |

**Rationale:** Leveraging existing ClickHouse infrastructure minimizes operational complexity. ReplacingMergeTree handles updates cleanly for tenant weights and config.

**Future consideration:** Integration with a dedicated experimentation platform (Statsig, LaunchDarkly, Eppo) could provide richer features but adds infrastructure complexity.

---

### 9. Job Scheduling

**Chosen:** Hourly Kubernetes CronJob

**Alternatives considered:**
| Approach | Pros | Cons |
|----------|------|------|
| Real-time (on each request) | Immediate promotion | Performance overhead |
| **Hourly batch** | Simple, efficient | Up to 1 hour delay |
| Daily batch | Minimal overhead | Slow feedback |
| Event-driven | Responsive | Complex infrastructure |

**Rationale:** Hourly processing balances responsiveness with simplicity. Tests run for days/weeks, so a 1-hour delay in promotion is negligible.

**Future consideration:** Event-driven processing could enable faster response to dramatic differences, though the business value is limited.

---

## Limitations

- **One active test per tenant** - Multiple simultaneous tests could confound results
- **Conversion-focused** - Currently optimizes for purchase conversion rate only
- **Staff actions excluded** - Only customer-initiated outcomes count toward metrics
- **No multi-armed bandit** - Uses fixed traffic allocation, not adaptive
- **No segment targeting** - Cannot run different tests for VIP vs. regular customers
- **Single metric optimization** - Doesn't balance multiple business objectives

---

## Future Enhancements

### Near-term
- **Revenue optimization** - Option to optimize for revenue per recommendation instead of conversion rate
- **Segment-specific tests** - Different tests for VIP customers, new customers, etc.
- **Manual promotion override** - API to manually promote a variant without waiting for significance
- **Test scheduling** - Schedule tests to start/end at specific times

### Medium-term
- **Multi-metric dashboards** - Track secondary metrics (CTR, cart rate, revenue) alongside primary
- **Bayesian analysis** - Probability-based reporting ("85% chance treatment is better")
- **Adaptive allocation** - Thompson sampling to minimize regret during testing
- **Guardrail metrics** - Automatically pause tests if key metrics degrade

### Long-term
- **Multi-armed bandit mode** - Continuous optimization without fixed test periods
- **Contextual bandits** - Different weights for different customer contexts
- **Automated feature testing** - Beyond weights to other algorithm parameters
- **External platform integration** - Statsig, LaunchDarkly, or similar for enterprise features
