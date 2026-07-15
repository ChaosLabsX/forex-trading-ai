# Going live

Everything needed to trade the real IC Markets account is **built and tested**.
Nothing about it is half-finished. It is switched off on purpose.

This document is the whole procedure. It assumes no memory of the conversation
that produced it - if you are a future reader (human or AI) with no context,
this page plus `docs/safety-rails.md` is all you need.

## The one thing that has to happen first

**A strategy must reach `readiness = 'ready'`.** That is not a judgement call or
a config toggle - `engine/evaluator.py` grants it only when a bootstrap 95%
confidence interval on the strategy's expectancy sits **entirely above zero**
across at least `readiness_min_trades_ready` (100) closed demo trades, and it
survives the profit-factor and drawdown vetoes.

As of writing, **no strategy has ever been Ready**, and the reference strategy
`ema_trend_v1` showed no demonstrated edge in backtest. Expect this to take
months, and expect the honest answer to sometimes be "this strategy never earns
it." That is the system working. Do not route around it.

> None of this is financial advice. The code can tell you whether an edge is
> statistically demonstrated; it cannot tell you whether to risk your money.

## The four guards

All four are independent. Live orders require **all four** to be deliberately
undone - no single mistake, typo, or forgotten flag can start live trading.

| # | Guard | Where | Default |
|---|---|---|---|
| 1 | `LIVE_TRADING_ENABLED` master switch | `.env` / `Settings.live_trading_enabled` | `false` |
| 2 | `accounts.enabled` for `icmarkets-live` | Supabase | `false` |
| 3 | `strategy_accounts.enabled` per strategy on live | Supabase / dashboard toggle | `false` |
| 4 | `strategies.readiness == 'ready'` | Supabase, set only by the evaluator | `not_ready` |

Guard 1 deliberately does **not** mean "sizing is implemented". An earlier
version derived safety from sizing being missing, which is a trap: the safety
property silently disappears the moment the feature lands. This switch is
explicit and orthogonal.

**`TEST_MODE` is not a guard.** It selects sizing *style*: `true` = the demo
lab's fixed 0.01 micro lot, `false` = real risk-based sizing. On a live account
`TEST_MODE=true` is the *dangerous* setting - it would place real micro-lot
orders. `infra/run-live-engine.ps1` correctly sets it `false`.

## What sizing does (already built, `engine/sizing.py`)

Risk a % of equity per trade, derived from the distance to the stop:

```
budget       = equity × risk_pct / 100
loss_per_lot = |entry − stop| × value_per_price_per_lot   (from MT5 symbol_info)
lots         = floor(budget / loss_per_lot / volume_step) × volume_step
```

- **Always rounds down.** Rounding up would exceed the risk budget - the one
  direction it must never err in.
- **Refuses rather than guesses**: zero stop distance, sub-minimum lot size,
  unknown symbol, missing tick value, zero equity.
- **Clamped** to the broker's `volume_min` / `volume_max` / `volume_step`, read
  live from MT5 - never hardcoded, because contract specs are the broker's to
  change.
- **Margin-checked** afterwards: sizing bounds the *loss*, not the capital
  committed, so a correctly-sized trade can still be unaffordable. Refused if it
  exceeds `max_margin_use_pct` (25%) of free margin.

### What varies per strategy

Only one number: `strategy_accounts.risk_pct`. Everything else is either a
broker fact (lot step, tick value, margin) read at runtime, or the single shared
sizing function. `NULL` means "use `default_risk_pct`" (0.5%). A per-strategy
value can lower risk but is clamped to `max_risk_pct` (2%), so a bad row can
never become an outsized bet.

## The procedure

1. **Wait for `readiness = 'ready'`** on the dashboard. You'll get a Telegram
   promotion alert with the statistics behind it. Don't proceed without it.
2. **Install the live infrastructure** if you haven't: a *second* MT5 terminal
   logged into the real account, plus the second engine. See step 6 of
   [`infra/vps-setup.md`](../infra/vps-setup.md). Do this while still blocked -
   it proves the plumbing with nothing at stake.

   > **Pin both engines to their own terminal and account first.** If
   > `MT5_TERMINAL_PATH` is empty, `mt5.initialize()` attaches to whichever
   > terminal Windows offers - so the moment a second terminal exists, the
   > *demo* engine can attach to the *live* one and place `TEST_MODE=true`
   > micro-lot orders on real money while still calling itself the demo lab.
   > `run-live-engine.ps1` pins the live engine's path; the demo engine's `.env`
   > must pin its own. Set `MT5_LOGIN`/`MT5_PASSWORD` for both as well, or the
   > engine cannot verify - or recover - which account it is on. See
   > [`safety-rails.md`](safety-rails.md).
3. **Set the risk** for that strategy on the live account. Start at the smallest
   thing that can trade. In Supabase: `strategy_accounts.risk_pct` for
   (strategy, `icmarkets-live`).
4. **Undo the guards, in this order** (each step is verifiable before the next):
   - Guard 2: set `accounts.enabled = true` for `icmarkets-live`.
   - Guard 3: enable that one strategy on the live account (dashboard toggle).
   - Guard 1: add `LIVE_TRADING_ENABLED=true` to the live engine's environment
     (`infra/run-live-engine.ps1`), then restart `ForexAI-Engine-Live`.
   - Guard 4 needs nothing - the strategy is already Ready, which is the point.
5. **Verify on the first real trade.** Watch for the Telegram `OPENED · LIVE`
   alert. Check the lot size matches what you'd expect from
   `equity × risk_pct / (stop distance × tick value)`. Confirm the position in
   the terminal.
6. **Keep the demo lab running.** It never stops. It is what detects the
   strategy decaying - and if it does, the evaluator demotes it automatically
   and the live engine stops trading it without anyone intervening.

## Rolling back

Any one of these stops live trading immediately:

- Dashboard → toggle the strategy off on the live account.
- Dashboard → **Pause trading** on the live engine (stops new trades, leaves
  positions open; MT5 still enforces their stops).
- Dashboard → **Emergency close all** on the live engine (closes everything now).
- Set `LIVE_TRADING_ENABLED=false` and restart the live engine.

An automatic demotion (a Ready strategy decaying) does the first one for you and
sends a Telegram alert saying so.
