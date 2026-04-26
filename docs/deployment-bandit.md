# Deployment Guide: Multi-Armed Bandit & A/B Testing

This guide covers the steps to deploy the weight optimization features.

---

## Prerequisites

- Access to ClickHouse database
- Deployed recommendation service
- API access to the service

---

## Step 1: Run Database Migrations

Apply the new migrations to create the required tables.

### Migration 003: A/B Test Tracking (if not already applied)

```bash
clickhouse-client --host your-clickhouse-host \
  --user your-user \
  --password your-password \
  --database default \
  --multiquery < migrations/003_ab_test_tracking.sql
```

This creates:
- `TWCTENANT_WEIGHTS` - Stores promoted winning weights per tenant
- `TWCTENANT_CONFIG` - Tenant configuration (A/B test settings)
- `TWCWEIGHT_PRESETS` - Custom weight presets
- Adds `abTestId`, `abTestVariant` columns to `TWCRECOMMENDATION_LOG`

### Migration 004: Bandit Stats

```bash
clickhouse-client --host your-clickhouse-host \
  --user your-user \
  --password your-password \
  --database default \
  --multiquery < migrations/004_bandit_stats.sql
```

This creates:
- `TWCBANDIT_STATS` - Tracks successes/failures per arm per tenant
- Adds bandit config defaults to `TWCTENANT_CONFIG`

---

## Step 2: Verify Tables

```sql
-- Check tables exist
SHOW TABLES LIKE 'TWC%';

-- Verify bandit stats table
DESCRIBE TWCBANDIT_STATS;

-- Verify tenant config has bandit defaults
SELECT * FROM TWCTENANT_CONFIG FINAL WHERE key LIKE 'BANDIT%';
```

Expected output:
```
┌─tenantId────┬─key───────────────────────┬─value──────────────────────────────────┐
│ __default__ │ BANDIT_ENABLED            │ false                                  │
│ __default__ │ BANDIT_ARMS               │ default,preference_heavy,behavior_heavy│
│ __default__ │ BANDIT_EXPLORATION_BONUS  │ 1                                      │
└─────────────┴───────────────────────────┴────────────────────────────────────────┘
```

---

## Step 3: Update Dependencies

If deploying a new version of the service:

```bash
pip install -r requirements.txt
```

New dependency: `numpy>=1.24.0` (for Thompson Sampling)

---

## Step 4: Deploy Service

Deploy the updated recommendation service using your standard deployment process.

### Docker

```bash
docker build -t twc-recommendations:latest .
docker push your-registry/twc-recommendations:latest
```

### Kubernetes

```bash
kubectl set image deployment/twc-recommendations \
  twc-recommendations=your-registry/twc-recommendations:latest \
  -n recommendations
```

---

## Step 5: Verify Deployment

### Health Check

```bash
curl https://api.example.com/health
```

### Check Bandit Endpoint

```bash
curl https://api.example.com/api/v1/bandit/viktoria-woods
```

Expected response (bandit disabled by default):
```json
{
  "tenant_id": "viktoria-woods",
  "enabled": false,
  "arms": [],
  "total_impressions": 0,
  "best_arm": null,
  "best_conversion_rate": 0.0
}
```

### Check A/B Test Endpoint

```bash
curl https://api.example.com/api/v1/ab-tests/viktoria-woods
```

---

## Step 6: Enable for a Tenant (Optional)

### Option A: Enable Bandit

```bash
# Sync historical data first (recommended)
curl -X POST "https://api.example.com/api/v1/bandit/viktoria-woods/sync?days_back=30"

# Enable bandit
curl -X POST https://api.example.com/api/v1/bandit/viktoria-woods/enable

# Verify
curl https://api.example.com/api/v1/bandit/viktoria-woods
```

### Option B: Create A/B Test

```bash
curl -X POST https://api.example.com/api/v1/ab-tests/viktoria-woods \
  -H "Content-Type: application/json" \
  -d '{
    "name": "initial_test",
    "control_weights": "default",
    "treatment_weights": "preference_heavy",
    "traffic_percentage": 20
  }'
```

---

## Rollback

If issues occur, you can disable optimization without rolling back the deployment:

### Disable Bandit

```bash
curl -X POST https://api.example.com/api/v1/bandit/viktoria-woods/disable
```

### End A/B Test

```bash
curl -X DELETE https://api.example.com/api/v1/ab-tests/viktoria-woods/{test_id}
```

The service will fall back to default weights.

---

## Monitoring

### Key Metrics to Watch

1. **Recommendation latency** - Should not increase significantly
2. **Conversion rates** - Track via `TWCRECOMMENDATION_OUTCOME`
3. **Bandit arm distribution** - Check arms are being explored

### Dashboard Queries

```sql
-- Recommendations by weight config (last 24h)
SELECT
    weightsConfig,
    count(*) as recommendations
FROM TWCRECOMMENDATION_LOG
WHERE createdAt >= now() - INTERVAL 1 DAY
GROUP BY weightsConfig
ORDER BY recommendations DESC;

-- Bandit arm performance
SELECT
    tenantId,
    arm,
    successes,
    failures,
    impressions,
    round(successes / impressions, 4) as cvr
FROM TWCBANDIT_STATS FINAL
ORDER BY tenantId, cvr DESC;
```

---

## Configuration Reference

### Bandit Settings (TWCTENANT_CONFIG)

| Key | Default | Description |
|-----|---------|-------------|
| `BANDIT_ENABLED` | `false` | Enable/disable bandit |
| `BANDIT_ARMS` | `default,preference_heavy,behavior_heavy` | Arms to use |
| `BANDIT_EXPLORATION_BONUS` | `1` | Prior strength (higher = more exploration) |

### A/B Test Settings (TWCTENANT_CONFIG)

| Key | Default | Description |
|-----|---------|-------------|
| `AUTO_PROMOTE_ENABLED` | `true` | Auto-promote winners |
| `AUTO_START_NEW_TESTS` | `true` | Auto-start new tests after promotion |
| `MIN_SAMPLES_FOR_SIGNIFICANCE` | `1000` | Min samples before checking significance |
| `P_VALUE_THRESHOLD` | `0.05` | Statistical significance threshold |
| `MIN_LIFT_FOR_PROMOTION` | `0.05` | Min lift (5%) required to promote |
| `NEW_TEST_TRAFFIC_PERCENTAGE` | `20` | Traffic % for auto-generated tests |

---

## Checklist

- [ ] Migration 003 applied (if not already)
- [ ] Migration 004 applied
- [ ] Dependencies updated (`numpy`)
- [ ] Service deployed
- [ ] Health check passing
- [ ] Bandit endpoint responding
- [ ] A/B test endpoint responding
- [ ] (Optional) Bandit enabled for test tenant
- [ ] (Optional) Monitoring dashboards updated
