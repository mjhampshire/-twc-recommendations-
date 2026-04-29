-- Migration 005: Widget Tracking Tables
-- Creates tables for tracking widget impressions, events, and metrics

-- =============================================================================
-- WIDGET IMPRESSIONS
-- =============================================================================
-- Tracks each widget render (what recommendations were shown)

CREATE TABLE IF NOT EXISTS default.TWCWIDGET_IMPRESSIONS (
    -- Identifiers
    tenantId String,
    requestId String,                    -- Unique request ID for attribution
    widgetId String,                     -- Widget instance ID
    widgetType String,                   -- 'trending_wishlist', 'for_you', etc.
    placement String,                    -- 'homepage', 'pdp', 'wishlist', etc.

    -- Identity
    customerId String DEFAULT '',        -- TWC customer ID (if logged in)
    onlineSessionId String DEFAULT '',   -- Shopify session ID
    isAnonymous UInt8 DEFAULT 1,         -- 1 if anonymous, 0 if logged in

    -- Context
    pageType String DEFAULT '',          -- 'home', 'product', 'collection', etc.
    contextProductId String DEFAULT '',  -- Product ID if on PDP
    contextCollectionId String DEFAULT '',
    storeId String DEFAULT '',           -- Store ID if applicable

    -- Results
    productIds Array(String),            -- Products shown in widget
    productCount UInt8,                  -- Number of products returned
    strategyUsed String,                 -- Actual strategy used (may differ from widget type)
    fallbackUsed UInt8 DEFAULT 0,        -- 1 if fallback was used

    -- A/B Testing
    experimentId String DEFAULT '',
    experimentVariant String DEFAULT '',

    -- Performance
    latencyMs UInt32,                    -- API response time
    productsConsidered UInt32,           -- Products evaluated before filtering
    productsFiltered UInt32,             -- Products removed by filters

    -- Metadata
    createdAt DateTime DEFAULT now(),
    userAgent String DEFAULT '',
    locale String DEFAULT '',
    currency String DEFAULT ''

) ENGINE = MergeTree()
PARTITION BY toYYYYMM(createdAt)
ORDER BY (tenantId, createdAt, requestId)
TTL createdAt + INTERVAL 365 DAY;

-- Index for finding impressions by customer
ALTER TABLE TWCWIDGET_IMPRESSIONS
    ADD INDEX IF NOT EXISTS idx_customer (customerId) TYPE set(1000) GRANULARITY 4;

-- Index for finding impressions by session
ALTER TABLE TWCWIDGET_IMPRESSIONS
    ADD INDEX IF NOT EXISTS idx_session (onlineSessionId) TYPE set(1000) GRANULARITY 4;


-- =============================================================================
-- WIDGET EVENTS
-- =============================================================================
-- Tracks user interactions with widgets (clicks, wishlist adds, cart adds, purchases)

CREATE TABLE IF NOT EXISTS default.TWCWIDGET_EVENTS (
    -- Identifiers
    tenantId String,
    eventType String,                    -- 'click', 'wishlist_add', 'cart_add', 'purchase'
    eventId String DEFAULT generateUUIDv4(),
    requestId String,                    -- Links back to impression
    widgetId String,

    -- Identity
    customerId String DEFAULT '',
    onlineSessionId String DEFAULT '',

    -- Event details
    productId String,
    variantId String DEFAULT '',
    rank UInt8,                          -- Position in widget (1-indexed)

    -- For purchases
    orderId String DEFAULT '',
    orderTotal Float64 DEFAULT 0,
    quantity UInt16 DEFAULT 1,

    -- Attribution
    experimentId String DEFAULT '',
    experimentVariant String DEFAULT '',

    -- Metadata
    createdAt DateTime DEFAULT now()

) ENGINE = MergeTree()
PARTITION BY toYYYYMM(createdAt)
ORDER BY (tenantId, createdAt, eventType, requestId)
TTL createdAt + INTERVAL 365 DAY;

-- Index for finding events by product
ALTER TABLE TWCWIDGET_EVENTS
    ADD INDEX IF NOT EXISTS idx_product (productId) TYPE set(1000) GRANULARITY 4;


-- =============================================================================
-- WIDGET METRICS (Daily Aggregation)
-- =============================================================================
-- Pre-aggregated metrics for dashboards

CREATE TABLE IF NOT EXISTS default.TWCWIDGET_METRICS_DAILY (
    tenantId String,
    date Date,
    widgetType String,
    placement String,

    -- Counts
    impressions UInt64,
    uniqueVisitors UInt64,
    clicks UInt64,
    wishlistAdds UInt64,
    cartAdds UInt64,
    purchases UInt64,

    -- Rates (calculated fields, updated by aggregation job)
    ctr Float32,                         -- clicks / impressions
    wishlistRate Float32,                -- wishlistAdds / impressions
    cartRate Float32,                    -- cartAdds / impressions
    conversionRate Float32,              -- purchases / impressions

    -- Quality
    emptyWidgets UInt64,                 -- Widgets with 0 products
    fallbacksUsed UInt64,
    avgLatencyMs Float32,
    avgProductsShown Float32,

    -- Revenue
    attributedRevenue Float64,
    attributedOrders UInt64,

    -- Metadata
    updatedAt DateTime DEFAULT now()

) ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (tenantId, date, widgetType, placement);


-- =============================================================================
-- WIDGET CONFIGURATION
-- =============================================================================
-- Stores widget configuration per tenant (optional - can also use config files)

CREATE TABLE IF NOT EXISTS default.TWCWIDGET_CONFIG (
    tenantId String,
    widgetId String,
    widgetType String,

    -- Display settings
    title String DEFAULT '',
    placement String DEFAULT '',
    maxProducts UInt8 DEFAULT 8,
    layout String DEFAULT 'carousel',    -- 'carousel', 'grid', 'compact'

    -- Behavior
    showReasons UInt8 DEFAULT 1,         -- Show "why" badges
    showPrices UInt8 DEFAULT 1,
    showSizes UInt8 DEFAULT 1,

    -- Filters
    inStockOnly UInt8 DEFAULT 1,
    excludeCollections Array(String),
    excludeProducts Array(String),
    boostCollections Array(String),

    -- Fallback
    fallbackStrategy String DEFAULT 'bestsellers',

    -- Metadata
    isActive UInt8 DEFAULT 1,
    createdAt DateTime DEFAULT now(),
    updatedAt DateTime DEFAULT now()

) ENGINE = ReplacingMergeTree(updatedAt)
ORDER BY (tenantId, widgetId);


-- =============================================================================
-- TRENDING SIGNALS (for Trending Widget)
-- =============================================================================
-- Aggregated signals for trending calculation

CREATE TABLE IF NOT EXISTS default.TWCTRENDING_SIGNALS (
    tenantId String,
    productId String,
    signalDate Date,

    -- Signal counts
    wishlistAdds UInt32 DEFAULT 0,
    productViews UInt32 DEFAULT 0,
    cartAdds UInt32 DEFAULT 0,
    purchases UInt32 DEFAULT 0,

    -- Calculated score (updated by aggregation job)
    trendingScore Float32 DEFAULT 0,

    -- Metadata
    updatedAt DateTime DEFAULT now()

) ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(signalDate)
ORDER BY (tenantId, signalDate, productId);

-- Index for finding top trending products
ALTER TABLE TWCTRENDING_SIGNALS
    ADD INDEX IF NOT EXISTS idx_score (trendingScore) TYPE minmax GRANULARITY 4;


-- =============================================================================
-- Materialized View: Daily Impressions Summary
-- =============================================================================
-- Auto-aggregates impressions into daily metrics

CREATE MATERIALIZED VIEW IF NOT EXISTS default.TWCWIDGET_IMPRESSIONS_DAILY_MV
TO TWCWIDGET_METRICS_DAILY
AS SELECT
    tenantId,
    toDate(createdAt) as date,
    widgetType,
    placement,
    count() as impressions,
    uniqExact(coalesce(nullIf(customerId, ''), onlineSessionId)) as uniqueVisitors,
    0 as clicks,
    0 as wishlistAdds,
    0 as cartAdds,
    0 as purchases,
    0 as ctr,
    0 as wishlistRate,
    0 as cartRate,
    0 as conversionRate,
    countIf(productCount = 0) as emptyWidgets,
    countIf(fallbackUsed = 1) as fallbacksUsed,
    avg(latencyMs) as avgLatencyMs,
    avg(productCount) as avgProductsShown,
    0 as attributedRevenue,
    0 as attributedOrders,
    now() as updatedAt
FROM TWCWIDGET_IMPRESSIONS
GROUP BY tenantId, date, widgetType, placement;


-- =============================================================================
-- Sample Queries
-- =============================================================================

-- Widget performance by type (last 7 days)
-- SELECT
--     widgetType,
--     sum(impressions) as impressions,
--     sum(clicks) as clicks,
--     sum(purchases) as purchases,
--     sum(clicks) / sum(impressions) as ctr,
--     sum(purchases) / sum(impressions) as cvr
-- FROM TWCWIDGET_METRICS_DAILY
-- WHERE tenantId = 'viktoria-woods'
--   AND date >= today() - 7
-- GROUP BY widgetType
-- ORDER BY impressions DESC;

-- Attribution: purchases from widget recommendations
-- SELECT
--     wi.widgetType,
--     wi.placement,
--     count(DISTINCT we.orderId) as orders,
--     sum(we.orderTotal) as revenue
-- FROM TWCWIDGET_EVENTS we
-- JOIN TWCWIDGET_IMPRESSIONS wi ON we.requestId = wi.requestId
-- WHERE we.tenantId = 'viktoria-woods'
--   AND we.eventType = 'purchase'
--   AND we.createdAt >= now() - INTERVAL 30 DAY
-- GROUP BY wi.widgetType, wi.placement
-- ORDER BY revenue DESC;

-- Top trending products (last 7 days)
-- SELECT
--     productId,
--     sum(wishlistAdds) as wishlists,
--     sum(productViews) as views,
--     sum(purchases) as purchases,
--     sum(trendingScore) as score
-- FROM TWCTRENDING_SIGNALS
-- WHERE tenantId = 'viktoria-woods'
--   AND signalDate >= today() - 7
-- GROUP BY productId
-- ORDER BY score DESC
-- LIMIT 20;
