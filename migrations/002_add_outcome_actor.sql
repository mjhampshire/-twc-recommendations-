-- Add actor field to TWCRECOMMENDATION_OUTCOME
-- Tracks whether the outcome was initiated by 'customer' or 'staff'
-- Staff-initiated outcomes should be excluded from recommendation success metrics

ALTER TABLE default.TWCRECOMMENDATION_OUTCOME
    ADD COLUMN IF NOT EXISTS `actor` String DEFAULT 'customer';

ALTER TABLE default.TWCRECOMMENDATION_OUTCOME
    ADD COLUMN IF NOT EXISTS `staffId` String DEFAULT '';
