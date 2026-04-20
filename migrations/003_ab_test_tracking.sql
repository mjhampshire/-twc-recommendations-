-- Migration 003: A/B Test Tracking and Tenant Configuration
-- Adds columns for tracking A/B test assignments in recommendation logs
-- Creates tables for tenant weights management and configuration

-- Add A/B test tracking columns to recommendation log
ALTER TABLE TWCRECOMMENDATION_LOG
    ADD COLUMN IF NOT EXISTS abTestId String DEFAULT '';

ALTER TABLE TWCRECOMMENDATION_LOG
    ADD COLUMN IF NOT EXISTS abTestVariant String DEFAULT '';  -- 'control' or 'treatment'

-- Tenant's current best weights (auto-promoted from A/B tests)
CREATE TABLE IF NOT EXISTS default.TWCTENANT_WEIGHTS (
    tenantId String,
    weightsPreset String,
    updatedAt DateTime DEFAULT now(),
    updatedBy String DEFAULT '',  -- 'auto' for auto-promotion, or user ID
    previousPreset String DEFAULT ''
) ENGINE = ReplacingMergeTree(updatedAt)
ORDER BY tenantId;

-- Tenant configuration (A/B testing settings and safety switches)
CREATE TABLE IF NOT EXISTS default.TWCTENANT_CONFIG (
    tenantId String,
    key String,
    value String,
    updatedAt DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updatedAt)
ORDER BY (tenantId, key);

-- Custom weight presets (for auto-generated variations)
CREATE TABLE IF NOT EXISTS default.TWCWEIGHT_PRESETS (
    presetName String,
    tenantId String DEFAULT '__global__',  -- '__global__' for shared presets
    preferenceCategory Float32 DEFAULT 0.12,
    preferenceColor Float32 DEFAULT 0.08,
    preferenceFabric Float32 DEFAULT 0.04,
    preferenceStyle Float32 DEFAULT 0.08,
    preferenceBrand Float32 DEFAULT 0.08,
    purchaseHistoryCategory Float32 DEFAULT 0.08,
    purchaseHistoryBrand Float32 DEFAULT 0.06,
    purchaseHistoryColor Float32 DEFAULT 0.04,
    wishlistSimilarity Float32 DEFAULT 0.10,
    browsingViewedCategory Float32 DEFAULT 0.06,
    browsingViewedBrand Float32 DEFAULT 0.04,
    browsingCartSimilarity Float32 DEFAULT 0.12,
    productPopularity Float32 DEFAULT 0.04,
    newArrivalBoost Float32 DEFAULT 0.04,
    sizeMatchBoost Float32 DEFAULT 0.02,
    customerSourceMultiplier Float32 DEFAULT 1.0,
    staffSourceMultiplier Float32 DEFAULT 1.0,
    inStockRequirement UInt8 DEFAULT 0,
    createdAt DateTime DEFAULT now(),
    createdBy String DEFAULT ''
) ENGINE = ReplacingMergeTree(createdAt)
ORDER BY (tenantId, presetName);

-- Insert default configuration for all tenants
INSERT INTO TWCTENANT_CONFIG (tenantId, key, value) VALUES
    ('__default__', 'AUTO_PROMOTE_ENABLED', 'true'),
    ('__default__', 'AUTO_START_NEW_TESTS', 'true'),
    ('__default__', 'MIN_SAMPLES_FOR_SIGNIFICANCE', '1000'),
    ('__default__', 'P_VALUE_THRESHOLD', '0.05'),
    ('__default__', 'MIN_LIFT_FOR_PROMOTION', '0.05'),
    ('__default__', 'NEW_TEST_TRAFFIC_PERCENTAGE', '20');

-- Insert built-in weight presets
INSERT INTO TWCWEIGHT_PRESETS (presetName, tenantId) VALUES
    ('default', '__global__'),
    ('preference_heavy', '__global__'),
    ('behavior_heavy', '__global__'),
    ('new_customer', '__global__');

-- Update preference_heavy preset
ALTER TABLE TWCWEIGHT_PRESETS
    UPDATE preferenceCategory = 0.16,
           preferenceColor = 0.10,
           preferenceFabric = 0.06,
           preferenceStyle = 0.10,
           preferenceBrand = 0.10,
           purchaseHistoryCategory = 0.06,
           purchaseHistoryBrand = 0.04,
           purchaseHistoryColor = 0.02,
           browsingViewedCategory = 0.04,
           browsingViewedBrand = 0.02,
           browsingCartSimilarity = 0.08,
           productPopularity = 0.02
    WHERE presetName = 'preference_heavy' AND tenantId = '__global__';

-- Update behavior_heavy preset
ALTER TABLE TWCWEIGHT_PRESETS
    UPDATE preferenceCategory = 0.08,
           preferenceColor = 0.05,
           preferenceFabric = 0.02,
           preferenceStyle = 0.05,
           preferenceBrand = 0.05,
           purchaseHistoryCategory = 0.12,
           purchaseHistoryBrand = 0.10,
           purchaseHistoryColor = 0.06,
           wishlistSimilarity = 0.15,
           browsingViewedCategory = 0.08,
           browsingViewedBrand = 0.06,
           browsingCartSimilarity = 0.16,
           productPopularity = 0.02
    WHERE presetName = 'behavior_heavy' AND tenantId = '__global__';

-- Update new_customer preset
ALTER TABLE TWCWEIGHT_PRESETS
    UPDATE preferenceCategory = 0.10,
           preferenceColor = 0.08,
           preferenceFabric = 0.04,
           preferenceStyle = 0.08,
           preferenceBrand = 0.08,
           purchaseHistoryCategory = 0.02,
           purchaseHistoryBrand = 0.02,
           purchaseHistoryColor = 0.01,
           wishlistSimilarity = 0.05,
           browsingViewedCategory = 0.10,
           browsingViewedBrand = 0.08,
           browsingCartSimilarity = 0.14,
           productPopularity = 0.15,
           newArrivalBoost = 0.05
    WHERE presetName = 'new_customer' AND tenantId = '__global__';
