-- A deliberate, one-shot "place a test trade" command.
--
-- Why this instead of a throwaway strategy: verifying the live path (sizing ->
-- order -> trades row -> Telegram -> close -> reconciliation -> Telegram) needs
-- a trade ON DEMAND. A real strategy fires roughly once a fortnight, so using
-- one as a test fixture means waiting weeks to learn whether the plumbing works.
-- A high-frequency throwaway strategy would work, but it would bleed spread and
-- commission continuously and pollute the lab's statistics with trades that were
-- never meant to have an edge.
--
-- This command still routes through the FULL risk engine: circuit breakers,
-- risk-based sizing, lot clamps and the margin check all apply. It bypasses only
-- the strategy eligibility gate (readiness/enabled), because it is an explicit
-- act by a signed-in human, not an automated strategy seeking an edge.
--
-- It does NOT bypass the account-level block: on a live account it is refused
-- unless LIVE_TRADING_ENABLED is on. Turning that on remains the money decision.

alter table public.commands drop constraint if exists commands_command_type_check;
alter table public.commands add constraint commands_command_type_check
    check (command_type in ('pause', 'resume', 'emergency_close_all', 'test_trade'));

-- Symbol / direction / risk for a test_trade; null for every other command.
alter table public.commands add column if not exists payload jsonb;

comment on column public.commands.payload is
    'test_trade only: {"symbol": "EURUSD", "direction": "LONG", "risk_pct": 0.5}. Ignored by other commands.';
