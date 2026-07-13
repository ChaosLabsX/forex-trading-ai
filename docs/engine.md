# Engine

The persistent Python process that does the actual work. Entry point:
`scripts/run_engine.py`, which builds the plugin composition (`engine.registry.build_engine`)
and hands it to `engine.loop.EngineLoop.run_forever()`.

## The loop (`engine/loop.py`)

A single `while True` loop, `POLL_INTERVAL_SECONDS = 2`:

1. **`_ensure_connected()`** - checks `broker.is_connected()`; if not, attempts
   `broker.connect()` with exponential-ish backoff (5s/10s/30s/60s, capped).
   Notifies (console + Telegram) on every connect/disconnect transition, not
   every tick.
2. **`_process_commands()`** - polls the `commands` table for `status=pending`
   rows, handles `pause`/`resume`/`emergency_close_all`, marks each row
   `processed`. Runs every tick (2s) once connected.
3. **`_send_heartbeat()`** - every 60s, inserts a row into `engine_heartbeats`
   (status, broker_connected). The dashboard's "Engine Health" card considers a
   heartbeat older than 3 minutes stale.
4. **`_refresh_market_data_and_evaluate()`** - every 60s: fetches H1/H4/D1
   candles for each configured instrument, upserts them to `candles`
   (idempotent on `symbol,timeframe,time`), then runs strategy evaluation.

### Why candles are trimmed before indicators ever see them

`MetaTrader5.copy_rates_from_pos(..., 0, ...)` includes the **currently
forming** bar. Indicators must never see it - a crossover reading would
flip-flop as price moves within the hour. `_closed_only()` drops the last
candle before anything touches it. Combined with a per-`(strategy, symbol)`
dedupe on the latest closed bar's timestamp, each closed bar gets evaluated
and logged exactly once, no matter how many 60s cycles pass before the next
bar closes.

### Strategy evaluation → risk → execution → AI review

For each configured `StrategyPlugin`, for each instrument in its
`.instruments`:

1. `strategy.evaluate(context)` → `StrategyEvaluation(signal, reason)`. Every
   evaluation gets logged to `signals` (fired or not, with why) -
   `_log_signal()` uses `SupabaseClient.insert(..., returning=True)` to get the
   new row's id back, since later steps need to link to it.
2. If a signal fired: `risk_engine.validate_signal(...)` → `RiskDecision`. If
   approved, `_open_trade()` calls `execution_engine.execute(order, broker)`,
   which places the order and inserts a `trades` row with `status=OPEN`.
3. Either way, `ai_provider.review_signal(signal, context)` runs (shadow mode -
   this happens regardless of the risk decision, so the `ai_reviews` table lets
   you compare "what the rules did" vs. "what Claude would have done" after the
   fact). Logged to `ai_reviews`, linked to the signal's id.

### Reconciling closed trades

Every refresh cycle, `_reconcile_closed_trades()` diffs `trades` rows with
`status=OPEN` against `broker.get_open_positions()`. Anything in the DB but no
longer open at the broker has closed (stop, target, or manual) -
`broker.get_closed_position_pnl()` fetches the real realized P&L from MT5's
deal history, the row gets updated to `CLOSED`, and a Telegram alert fires with
the actual number.

### Circuit breakers

`RiskEngine.validate_signal()` checks, in order: max concurrent open trades
(2), consecutive losing trades today (3), and max daily loss % (3%). The last
two are computed from **real** MT5 deal history
(`MT5BrokerAdapter._daily_stats()`), not estimated - this matters, since a
fake/stale number here would make the safety rail meaningless. See
[`docs/safety-rails.md`](safety-rails.md).

## The reference strategy (`engine/plugins/strategies/ema_trend_v1.py`)

Multi-timeframe trend-following - the first `StrategyPlugin` implementation,
used to build and verify the rest of the platform. Not what the engine is
designed around; a different strategy is a new file + a config change (see
`docs/plugin-system.md`).

- **Regime (H4):** EMA(50) vs EMA(200) sets allowed direction; ADX(14) < 20
  blocks entry (flat/choppy market - the classic trend-following failure mode).
- **Entry (H1):** EMA(20)/EMA(50) crossover in the regime's direction.
- **Stop/target:** ATR(14)-based, 1.5x/2.0x - risk scales per-instrument
  automatically instead of a fixed pip value.
- **Filters:** London/NY session overlap only (12:00-16:00 UTC); news blackout
  (currently always-empty via the `placeholder` `NewsProvider` - real calendar
  integration needs an API key, deferred).
- Configured instruments: `EURUSD`, `GBPUSD`, `USDJPY`, `XAUUSD`.

Sanity-checked via `scripts/backtest_ema_trend_v1.py`, which replays real
historical MT5 candles through the exact same logic and window sizes the live
loop uses, then simulates each signal forward to see whether the stop or
target would have hit first. This is a "logic isn't obviously broken" check,
not a statistically rigorous validation - sample sizes from a single backtest
run are small.

## Config and secrets

- `.env` (repo root, gitignored): all secrets - `TEST_MODE`, Supabase URL +
  service-role key, MT5 login (optional - see below), Telegram, Anthropic.
- `config/plugins.yaml` (committed, not secret): which plugin key backs each
  subsystem.
- MT5 credentials deliberately stay **out** of `.env` by default -
  `mt5.initialize()` attaches to an already-running, already-logged-in
  terminal with no login/password needed in code. Only fill in
  `MT5_LOGIN`/`MT5_PASSWORD` for unattended/headless startup (relevant once
  running as a Phase 6 service).

## Running it

```
python scripts/smoke_test_registry.py    # no external calls - just proves the registry wires up
python scripts/run_engine.py             # the real loop - needs MT5 terminal open + logged in
```

Locally, still run as a detached background process (`Start-Process`, not
tied to any shell session). On the VPS (Phase 6), it runs via a Task
Scheduler "at logon" trigger instead of a Windows service - MT5's Python
bridge needs an interactive desktop session, which a Session-0 service can't
provide; see `infra/vps-setup.md`. Either way, logs go to `logs/engine.log`
(rotating file handler, `scripts/run_engine.py`) - both Python's own logging
and every `NotificationProvider` event (`ConsoleNotifier` logs rather than
`print()`s, specifically so it's captured under Task Scheduler, which has no
attached console to redirect).
