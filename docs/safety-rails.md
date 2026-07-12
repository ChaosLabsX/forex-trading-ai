# Safety rails

Everything in this doc exists to answer "is this safe to leave running?" -
consolidated in one place rather than scattered across commit messages.

## `TEST_MODE`

Single flag in `.env`, defaults to `true`. Read by `DefaultRiskEngine`
(`engine/plugins/risk/default_risk_engine.py`):

- `TEST_MODE=true`: every approved order uses a fixed micro lot
  (`TEST_MODE_LOT_SIZE = 0.01`), regardless of account size or signal
  confidence.
- `TEST_MODE=false`: **not implemented.** `validate_signal()` explicitly
  refuses to approve any order when `TEST_MODE` is off, rather than silently
  falling back to the demo sizing. Live position sizing (e.g. % equity risk
  derived from stop distance) is Phase 6 scope - don't build "live mode" by
  just flipping this flag without implementing real sizing first.

## Circuit breakers (`DefaultRiskEngine.validate_signal`)

Checked in this order, any failure blocks the trade:

1. **Max concurrent open trades** (`MAX_CONCURRENT_TRADES = 2`) - counts
   `Position.status == OPEN` across all instruments/strategies.
2. **Consecutive losing trades today** (`MAX_CONSECUTIVE_STOP_LOSSES = 3`) -
   from `AccountState.consecutive_stop_losses_today`, computed by
   `MT5BrokerAdapter._daily_stats()` from **real** MT5 closed-deal history
   (today's closing deals, counting backward from the most recent while
   `profit < 0`). Not an estimate or a placeholder.
3. **Max daily loss %** (`MAX_DAILY_LOSS_PCT = 3.0`) - from
   `AccountState.daily_pnl` (also real, same source) as a percentage of
   balance.

All three numbers are recomputed fresh from MT5 on every `get_account_state()`
call - there's no cached/stale risk state to go wrong here.

## AI review is shadow-mode only

`ClaudeAIProvider` (Phase 5) reviews every fired signal and logs a verdict to
`ai_reviews`, but **the verdict never gates execution**. A trade proceeds or
doesn't based purely on `RiskEngine`'s decision. This is deliberate per the
original plan (build a track record before trusting it to block trades) - if
this ever changes, it's a real architectural decision worth flagging clearly
before implementing, not a quiet default.

## RLS / dashboard security model

The dashboard is a public static site using the Supabase **anon** key - there
is no secret in the frontend bundle. Row-Level Security is the actual access
boundary:

| Table | `anon` | `authenticated` | `service_role` (engine) |
|---|---|---|---|
| `signals`, `trades`, `engine_heartbeats`, `candles`, `ai_reviews` | SELECT | SELECT | ALL |
| `commands` | none | SELECT + INSERT (own rows only, `auth.uid()=created_by`) | ALL |

**Real bug that shipped once:** migration `0005` granted the monitoring tables
to `anon` only. Signed-in users got 403s, because `supabase-js` sends the
user's session JWT once signed in - Postgres denies the request outright at
the grant level (before RLS policies are even evaluated) if the role has no
privilege on the table at all. Fixed in migration `0007`. **Lesson: any RLS
policy added for one role must be checked against every role that will
actually query the table** - test both signed-out and signed-in states, not
just whichever one you happened to be testing with.

Public sign-up is disabled on the Supabase Auth project - the only way to gain
control access is being the one invited account. Don't add a self-serve
sign-up flow without reconsidering this.

## Known, deliberate gaps (not bugs - documented so they aren't "discovered" again)

- **No breakeven/trailing stop management.** `DefaultExecutionEngine.manage_open_position()`
  is a no-op; MT5 enforces the stop/target natively once placed, so positions
  stay protected even if the engine process is down, but profit-locking
  strategies described in the original strategy spec aren't implemented.
- **No real news blackout.** `NullNewsProvider` (registered as `placeholder`)
  always returns zero events. A real economic calendar needs an API key from
  a provider (TradingEconomics/Finnhub/FMP etc.) - that's a manual account
  signup, deliberately not blocking the rest of the system.
- **No partial position closes.** The `trades` lifecycle is binary
  (`OPEN` → `CLOSED`); scaling out of a position isn't modeled.
- **Doesn't survive a reboot.** The engine runs as a detached background
  process, not a Windows service - Phase 6's NSSM wrapping is what adds
  auto-restart/boot-survival.
