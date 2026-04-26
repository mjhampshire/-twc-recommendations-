# Weight Optimization Guide

This guide explains how to use A/B testing and multi-armed bandit to optimize recommendation weights for your tenants.

---

## Overview

The recommendation engine uses **weights** to score products for each customer. Different weight configurations prioritize different signals (preferences, purchase history, browsing, etc.).

You have three options for weight optimization:

| Mode | Description | Best For |
|------|-------------|----------|
| **Static** | Use default weights, no optimization | Baseline, testing |
| **A/B Testing** | Explicit experiments comparing two weight configs | Controlled experiments |
| **Multi-Armed Bandit** | Automatic optimization using Thompson Sampling | Continuous optimization |

---

## Quick Start

### 1. Run Without Optimization (Baseline)

By default, tenants use static `default` weights with no learning. This is useful for establishing a baseline before enabling optimization.

```bash
# Check current state - should show bandit disabled, no active tests
curl https://api.example.com/api/v1/bandit/viktoria-woods
curl https://api.example.com/api/v1/ab-tests/viktoria-woods
```

### 2. Enable Multi-Armed Bandit (Recommended)

The bandit automatically finds the best weights by tracking conversion rates.

```bash
# Enable bandit
curl -X POST https://api.example.com/api/v1/bandit/viktoria-woods/enable

# Optional: Sync historical data first (warm start)
curl -X POST "https://api.example.com/api/v1/bandit/viktoria-woods/sync?days_back=30"
```

### 3. Or Run an A/B Test

For controlled experiments comparing specific weight configurations.

```bash
curl -X POST https://api.example.com/api/v1/ab-tests/viktoria-woods \
  -H "Content-Type: application/json" \
  -d '{
    "name": "preference_vs_behavior",
    "control_weights": "default",
    "treatment_weights": "preference_heavy",
    "traffic_percentage": 50
  }'
```

---

## Multi-Armed Bandit

### How It Works

1. Each weight preset is an "arm" (e.g., `default`, `preference_heavy`, `behavior_heavy`)
2. The bandit tracks conversion rates for each arm
3. Uses **Thompson Sampling** to select arms:
   - Arms with good conversion rates are selected more often (exploitation)
   - Arms with uncertain data are occasionally tried (exploration)
4. Over time, traffic naturally shifts to the best-performing weights

### Configuration

```bash
# View current status
GET /api/v1/bandit/{retailer_id}

# Response:
{
  "tenant_id": "viktoria-woods",
  "enabled": true,
  "arms": [
    {"arm": "default", "successes": 45, "failures": 955, "impressions": 1000, "conversion_rate": 0.045},
    {"arm": "preference_heavy", "successes": 62, "failures": 938, "impressions": 1000, "conversion_rate": 0.062},
    {"arm": "behavior_heavy", "successes": 51, "failures": 949, "impressions": 1000, "conversion_rate": 0.051}
  ],
  "total_impressions": 3000,
  "best_arm": "preference_heavy",
  "best_conversion_rate": 0.062
}
```

### Enable/Disable

```bash
# Enable
POST /api/v1/bandit/{retailer_id}/enable

# Disable
POST /api/v1/bandit/{retailer_id}/disable
```

### Configure Arms

By default, the bandit uses: `default`, `preference_heavy`, `behavior_heavy`

To customize:

```bash
PUT /api/v1/bandit/{retailer_id}
Content-Type: application/json

{
  "arms": ["default", "preference_heavy", "behavior_heavy", "new_customer"]
}
```

### Sync Historical Data

Before enabling, you can warm-start the bandit with historical data:

```bash
# Sync last 30 days of data
POST /api/v1/bandit/{retailer_id}/sync?days_back=30
```

### Reset Statistics

To start fresh (e.g., after changing weight configurations):

```bash
# Reset all arms
POST /api/v1/bandit/{retailer_id}/reset

# Reset specific arm
POST /api/v1/bandit/{retailer_id}/reset?arm=preference_heavy
```

---

## A/B Testing

### How It Works

1. Create a test comparing two weight configurations
2. Customers are deterministically assigned to control or treatment
3. Track conversion rates for each variant
4. System calculates statistical significance
5. When significant, winner can be auto-promoted

### Create a Test

```bash
POST /api/v1/ab-tests/{retailer_id}
Content-Type: application/json

{
  "name": "test_name",
  "description": "Testing preference-heavy weights",
  "control_weights": "default",
  "treatment_weights": "preference_heavy",
  "traffic_percentage": 20
}
```

| Field | Description |
|-------|-------------|
| `name` | Unique test identifier |
| `control_weights` | Baseline weight preset |
| `treatment_weights` | Variant to test |
| `traffic_percentage` | % of traffic to treatment (rest goes to control) |

### View Test Results

```bash
GET /api/v1/ab-tests/{retailer_id}/{test_id}

# Response:
{
  "test_id": "abc123",
  "test_name": "test_name",
  "control": {
    "total_recommendations": 5000,
    "total_purchases": 225,
    "conversion_rate": 0.045
  },
  "treatment": {
    "total_recommendations": 1250,
    "total_purchases": 71,
    "conversion_rate": 0.057
  },
  "lift": 0.267,
  "p_value": 0.023,
  "is_significant": true,
  "recommended_action": "promote_treatment"
}
```

### End a Test

```bash
DELETE /api/v1/ab-tests/{retailer_id}/{test_id}
```

### Auto-Promotion

When a test reaches statistical significance:
1. Winner is saved to `TWCTENANT_WEIGHTS`
2. Test is ended
3. Optionally, a new test with a variation is started

Configure auto-promotion:

```bash
PUT /api/v1/ab-tests/{retailer_id}/config
Content-Type: application/json

{
  "auto_promote_enabled": true,
  "auto_start_new_tests": true,
  "min_samples_for_significance": 1000,
  "p_value_threshold": 0.05,
  "min_lift_for_promotion": 0.05
}
```

---

## Weight Presets

Built-in presets:

| Preset | Description |
|--------|-------------|
| `default` | Balanced weights across all signals |
| `preference_heavy` | Emphasizes stated preferences (likes/dislikes) |
| `behavior_heavy` | Emphasizes purchase history and browsing |
| `new_customer` | For customers with no history (uses popularity, browsing) |

Custom presets can be created via the `TWCWEIGHT_PRESETS` table.

---

## Priority Order

When a recommendation request comes in, weights are selected in this order:

1. **Active A/B Test** - If customer is in a test, use variant weights
2. **Bandit** - If enabled, use Thompson Sampling to select arm
3. **Promoted Weights** - If tenant has auto-promoted winner from past tests
4. **Default** - System default weights
5. **New Customer Override** - If customer has no purchase history

---

## Monitoring

### Check Recommendation Logs

The `weights_config` field in `TWCRECOMMENDATION_LOG` shows which weights were used:

```sql
SELECT
    weightsConfig,
    count(*) as recommendations,
    countIf(eventId IN (SELECT recommendationEventId FROM TWCRECOMMENDATION_OUTCOME WHERE outcomeType = 'purchased')) as conversions
FROM TWCRECOMMENDATION_LOG
WHERE tenantId = 'viktoria-woods'
  AND createdAt >= now() - INTERVAL 7 DAY
GROUP BY weightsConfig
```

### Bandit Arm Performance

```sql
SELECT arm, successes, failures, impressions,
       successes / impressions as conversion_rate
FROM TWCBANDIT_STATS FINAL
WHERE tenantId = 'viktoria-woods'
ORDER BY conversion_rate DESC
```

---

## Best Practices

1. **Start with baseline** - Run without optimization for 1-2 weeks to establish baseline conversion rates

2. **Sync before enabling bandit** - Use `/sync` to warm-start with historical data

3. **Don't run both simultaneously** - A/B tests override bandit. Use one or the other.

4. **Monitor regularly** - Check bandit stats weekly to ensure it's converging

5. **Reset after major changes** - If you significantly change weight presets, reset bandit stats

6. **Use A/B tests for big changes** - For major new weight configurations, use explicit A/B tests first

---

## Troubleshooting

### Bandit not selecting arms

Check if enabled:
```bash
curl https://api.example.com/api/v1/bandit/viktoria-woods
```

### A/B test not showing results

Ensure outcomes are being logged. Check for purchases in `TWCRECOMMENDATION_OUTCOME`:
```sql
SELECT count(*) FROM TWCRECOMMENDATION_OUTCOME
WHERE tenantId = 'viktoria-woods' AND outcomeType = 'purchased'
```

### Weights not being applied

Check the response `weights_used` field:
```bash
curl https://api.example.com/api/v1/recommendations/viktoria-woods/CUST001
# Check "weights_used" in response
```
