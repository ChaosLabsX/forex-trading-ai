-- Repair trades wrongly closed by the OTHER account's engine.
--
-- Bug: _reconcile_closed_trades() selected `trades` by status only, never by
-- account_key. With a demo and a live engine both running, each one looked at
-- the other's OPEN trades, failed to find those tickets in its own terminal,
-- concluded the positions had closed, and wrote status=CLOSED with
-- realized_pnl=NULL ("no deal history found" in the Telegram alerts).
--
-- The damage is subtle rather than loud: the evaluator skips trades with no
-- P&L, so every affected trade vanishes from the statistics. The lab appears to
-- be running perfectly while collecting nothing - the worst kind of failure.
--
-- These rows cannot be repaired into real results. A trade closed at the wrong
-- moment by the wrong engine has no true exit price or P&L, and inventing one
-- would poison the very verdicts this system exists to produce. They are marked
-- as void instead, so they are visibly excluded rather than silently wrong.
--
-- Positions may still be OPEN in MT5 (the reconciler only wrote to the database;
-- it never sent a close order). Check the terminal - MT5 still enforces their
-- stops either way, so nothing is unprotected.

alter table public.trades
    add column if not exists void_reason text;

comment on column public.trades.void_reason is
    'Non-null means this trade is excluded from evaluation: its recorded outcome is not trustworthy. Set by repairs, never by the engine.';

update public.trades
set void_reason = 'closed by the other account''s engine before reconciliation filtered by account_key (migration 0013)'
where status = 'CLOSED'
  and realized_pnl is null
  and void_reason is null;
