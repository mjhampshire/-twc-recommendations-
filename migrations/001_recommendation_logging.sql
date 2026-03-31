-- Recommendation Logging Tables for TWC
-- These tables capture recommendation events and outcomes for:
-- - Model performance measurement
-- - A/B testing
-- - ML training data generation

-- =============================================================================
-- TWCRECOMMENDATION_LOG
-- Captures every recommendation event (when recommendations are shown to a user)
-- =============================================================================
CREATE TABLE IF NOT EXISTS default.TWCRECOMMENDATION_LOG
(
    `eventId` String,
    `tenantId` String,
    `customerId` String,
    `staffId` String DEFAULT '',
    `sessionId` String DEFAULT '',
    `recommendationType` String,  -- 'personalized', 'alternatives', 'similar', etc.
    `recommendedItems` Array(String),  -- Product IDs in order shown
    `scores` Array(Float32),  -- Corresponding scores
    `positions` Array(UInt8),  -- Display positions (1-indexed)
    `contextFeatures` String DEFAULT '{}',  -- JSON with ML features
    `modelVersion` String DEFAULT 'rule-based-v1',
    `weightsConfig` String DEFAULT '',  -- Name of weights preset used
    `recommendedAt` DateTime DEFAULT now(),
    `updatedAt` DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(recommendedAt)
ORDER BY (tenantId, customerId, recommendedAt)
TTL recommendedAt + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;

-- Indexes for common queries
ALTER TABLE default.TWCRECOMMENDATION_LOG ADD INDEX idx_event_id eventId TYPE bloom_filter GRANULARITY 1;
ALTER TABLE default.TWCRECOMMENDATION_LOG ADD INDEX idx_model_version modelVersion TYPE bloom_filter GRANULARITY 1;


-- =============================================================================
-- TWCRECOMMENDATION_OUTCOME
-- Captures interactions with recommendations (views, clicks, purchases, etc.)
-- =============================================================================
CREATE TABLE IF NOT EXISTS default.TWCRECOMMENDATION_OUTCOME
(
    `eventId` String,
    `recommendationEventId` String,  -- Links to TWCRECOMMENDATION_LOG.eventId
    `tenantId` String,
    `customerId` String,
    `outcomeType` String,  -- 'viewed', 'clicked', 'added_to_cart', 'purchased', etc.
    `itemId` String,  -- Which product was interacted with
    `position` UInt8,  -- Position in the recommendation list
    `purchaseValue` Nullable(Float32),  -- If purchased
    `purchaseOrderId` String DEFAULT '',
    `daysToConversion` Nullable(Int32),  -- Days from recommendation to outcome
    `occurredAt` DateTime DEFAULT now(),
    `updatedAt` DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(occurredAt)
ORDER BY (tenantId, recommendationEventId, occurredAt)
TTL occurredAt + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;

-- Indexes for joining with log table and filtering
ALTER TABLE default.TWCRECOMMENDATION_OUTCOME ADD INDEX idx_rec_event_id recommendationEventId TYPE bloom_filter GRANULARITY 1;
ALTER TABLE default.TWCRECOMMENDATION_OUTCOME ADD INDEX idx_outcome_type outcomeType TYPE bloom_filter GRANULARITY 1;


-- =============================================================================
-- TWCAB_TEST
-- Configuration for A/B tests comparing recommendation approaches
-- =============================================================================
CREATE TABLE IF NOT EXISTS default.TWCAB_TEST
(
    `testId` String,
    `tenantId` String,
    `name` String,
    `description` String DEFAULT '',
    `controlModelVersion` String,
    `controlWeights` String DEFAULT '',
    `treatmentModelVersion` String,
    `treatmentWeights` String DEFAULT '',
    `trafficPercentage` Float32 DEFAULT 50.0,  -- % to treatment
    `startDate` DateTime,
    `endDate` Nullable(DateTime),
    `isActive` UInt8 DEFAULT 1,
    `createdAt` DateTime DEFAULT now(),
    `updatedAt` DateTime DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY (tenantId, testId)
SETTINGS index_granularity = 8192;


-- =============================================================================
-- Materialized View: Hourly Metrics
-- Pre-aggregates metrics for dashboard performance
-- =============================================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS default.TWCRECOMMENDATION_METRICS_HOURLY
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(hour)
ORDER BY (tenantId, modelVersion, weightsConfig, hour)
AS
SELECT
    tenantId,
    modelVersion,
    weightsConfig,
    toStartOfHour(recommendedAt) as hour,
    count() as recommendation_count,
    uniq(customerId) as unique_customers,
    sum(length(recommendedItems)) as total_items_recommended
FROM default.TWCRECOMMENDATION_LOG
GROUP BY tenantId, modelVersion, weightsConfig, hour;


-- =============================================================================
-- Materialized View: Outcome Aggregates
-- Pre-aggregates outcome counts for efficient analytics
-- =============================================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS default.TWCRECOMMENDATION_OUTCOMES_DAILY
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(day)
ORDER BY (tenantId, modelVersion, outcomeType, day)
AS
SELECT
    l.tenantId AS tenantId,
    l.modelVersion AS modelVersion,
    l.weightsConfig AS weightsConfig,
    o.outcomeType AS outcomeType,
    toDate(o.occurredAt) AS day,
    count() AS outcome_count,
    sum(o.purchaseValue) AS total_revenue,
    uniq(o.recommendationEventId) AS unique_recommendations
FROM default.TWCRECOMMENDATION_OUTCOME o
JOIN default.TWCRECOMMENDATION_LOG l ON o.recommendationEventId = l.eventId
GROUP BY tenantId, modelVersion, weightsConfig, outcomeType, day;
