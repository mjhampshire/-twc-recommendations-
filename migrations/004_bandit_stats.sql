-- Migration 004: Multi-Armed Bandit Stats
-- Tracks successes/failures per arm for Thompson Sampling

-- Bandit arm statistics per tenant
CREATE TABLE IF NOT EXISTS default.TWCBANDIT_STATS (
    tenantId String,
    arm String,  -- Weight preset name (e.g., 'default', 'preference_heavy')
    successes UInt64 DEFAULT 0,  -- Conversions (purchases)
    failures UInt64 DEFAULT 0,   -- Non-conversions (impressions - conversions)
    impressions UInt64 DEFAULT 0,
    lastUpdated DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(lastUpdated)
ORDER BY (tenantId, arm);

-- Add bandit configuration to tenant config defaults
INSERT INTO TWCTENANT_CONFIG (tenantId, key, value) VALUES
    ('__default__', 'BANDIT_ENABLED', 'false'),
    ('__default__', 'BANDIT_ARMS', 'default,preference_heavy,behavior_heavy'),
    ('__default__', 'BANDIT_EXPLORATION_BONUS', '1');  -- Prior strength for Thompson Sampling
