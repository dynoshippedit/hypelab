-- 0005: remove the custom money pipeline (D2, owner decision 2026-09-29).
--
-- The cost ledger (cost_ledger table) is KEPT — it tracks spend and the
-- failure-requeue path writes per-attempt rows via log_cost(). Everything
-- else money-shaped goes: posts.payout_usd (always NULL; the rate-basis
-- fill was never implemented) and the campaign money-model columns
-- (rate_per_1k_usd, rate_basis, budget_total_usd, budget_seen_usd,
-- budget_checked, budget_provenance), which existed only to feed the
-- removed payout computation. Money returns later via a hosted processor,
-- not custom charge/payout code.
--
-- The removed code is preserved on the local archive branch
-- archive/money-pipeline-2026-09-29 (no push).

ALTER TABLE posts DROP COLUMN payout_usd;
ALTER TABLE campaigns DROP COLUMN rate_per_1k_usd;
ALTER TABLE campaigns DROP COLUMN rate_basis;
ALTER TABLE campaigns DROP COLUMN budget_total_usd;
ALTER TABLE campaigns DROP COLUMN budget_seen_usd;
ALTER TABLE campaigns DROP COLUMN budget_checked;
ALTER TABLE campaigns DROP COLUMN budget_provenance;
