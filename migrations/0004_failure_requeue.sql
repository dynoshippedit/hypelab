-- 0004: failure-type requeue support (T-011 / hl-cycle-08).
-- Additive only: two nullable columns on jobs.
--   requeue_not_before: ISO timestamp; claim() skips jobs whose backoff has
--     not elapsed yet (transient-failure auto-requeue, T-011/D1).
--   review_reason: classification string set when a failure is routed to the
--     manual review pile (terminal failures, max attempts, publish or
--     owner-waiting exclusions). NULL = not in the review pile.
ALTER TABLE jobs ADD COLUMN requeue_not_before TEXT;
ALTER TABLE jobs ADD COLUMN review_reason TEXT;
