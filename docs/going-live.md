# Going live

**Live trading is ON, for exactly one strategy, on a funded account.** Read the
current state below before touching anything.

This document is the whole procedure. It assumes no memory of the conversation
that produced it - if you are a future reader (human or AI) with no context, this
page plus [`safety-rails.md`](safety-rails.md) is all you need.

> None of this is financial advice. The code can tell you whether an edge is
> statistically demonstrated; it cannot tell you whether to risk your money.

## Current state (2026-09-05)

| | |
|---|---|
| Account | `icmarkets-live`, IC Markets, MT5 **#8050468** |
| Funded | **$200** |
| Trading | `london_breakout_v1` **only** - every other strategy is `enabled=false` on live |
| Risk | `strategy_accounts.risk_pct = 0.75` (~$1.50 a trade) |
| Guard 4 | satisfied by `live_override=true`, **not** by a READY verdict |

**Nothing has ever been READY.** `london_breakout_v1` is `almost_ready`: +0.126R
over 50 demo trades, against a spread of 1.24R. Proving that edge is real would
take roughly 369 trades - about 18 months. This is a deliberate bet taken with
the owner's eyes open, and the $200 is sized as tuition. Do not let anything you
write imply the edge is settled.

The demo lab keeps running regardless, and remains the only thing that can
produce a real READY verdict.

## The four guards

All four are independent. A live order requires **all four** to be open, so no
single mistake, typo or forgotten flag can start live trading.

| # | Guard | Where | Current |
|---|---|---|---|
| 1 | `LIVE_TRADING_ENABLED` master switch | `.env.live` → `Settings.live_trading_enabled` | **on** |
| 2 | `accounts.enabled` for `icmarkets-live` | Supabase | **true** |
| 3 | `strategy_accounts.enabled` per strategy on live | Supabase / dashboard toggle | **true for `london_breakout_v1` only** |
| 4 | `strategies.readiness == 'ready'`, **or** `strategy_accounts.live_override` | Supabase; readiness set only by the evaluator | **override** |

Guard 1 is account-wide and needs no database change, which makes it the fastest
way to disarm everything: set `LIVE_TRADING_ENABLED=false` in `.env.live` and
restart the live engine.

Guard 4's override exists so a human can consciously accept an unproven strategy.
It is the one guard that can be opened without evidence, so treat any request to
set it as a decision, not a config change.

The dashboard shows guard 1's real state on the live account's card, read from
the engine's own heartbeat rather than assumed - `Real orders are armed.` means
the running process has it on.

**`TEST_MODE` is not a guard.** It selects sizing *style*: `true` = the broker's
minimum volume (the lab), `false` = real risk-based sizing. On a live account
`TEST_MODE=true` is the *dangerous* setting - real orders at broker minimum,
ignoring `risk_pct`. The engine refuses to start that way
(`engine/loop.py:run_forever`).

## Sizing (`engine/sizing.py`)

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
  committed, so a correctly-sized trade can still be unaffordable. Refused above
  `max_margin_use_pct` (25%) of free margin.

Only one number varies per strategy: `strategy_accounts.risk_pct`. `NULL` means
`default_risk_pct` (0.5%). It is clamped to `max_risk_pct` (2%), so a bad row can
never become an outsized bet.

## Adding another strategy to live

1. **Prefer waiting for `readiness = 'ready'`.** You get a Telegram promotion
   alert with the statistics behind it. Anything else is an override, and the
   research log records that mining for variants has produced fewer significant
   results than chance predicts.
2. **Set its risk**: `strategy_accounts.risk_pct` for (strategy,
   `icmarkets-live`). Start at the smallest thing that can trade.
3. **Open guard 3** for that one strategy - the dashboard toggle.
4. **Verify on its first real trade.** Watch for the Telegram `OPENED · LIVE`
   alert, check the lot size against `equity × risk_pct / (stop distance × tick
   value)`, and confirm `risk_reason` shows risk-based sizing rather than
   `TEST_MODE`.

## Rolling back

Any one of these stops live trading immediately:

- Dashboard → toggle the strategy off on the live account (guard 3).
- Dashboard → **Pause trading** on the live engine - stops new trades, leaves
  open positions alone; MT5 still enforces their stops server-side.
- Dashboard → **Emergency close all** on the live engine - closes everything now.
- `LIVE_TRADING_ENABLED=false` in `.env.live`, then restart the live engine
  (guard 1, account-wide).

An automatic demotion - a READY strategy decaying - does the first one for you
and sends a Telegram alert saying so. That only applies to strategies that earned
READY; one running on `live_override` is not demoted, because the override says a
human decided to ignore the verdict.

## Running the live engine

See [`../infra/vps-setup.md`](../infra/vps-setup.md). In short: the live task
executes python directly with its own env file, so it restarts like the demo lab:

```powershell
Stop-ScheduledTask -TaskName "ForexAI-Engine-Live"; Start-ScheduledTask -TaskName "ForexAI-Engine-Live"
```

`.env.live` is what makes that process the live engine - account key, its own MT5
terminal, live credentials, `TEST_MODE=false`, and guard 1. It layers over `.env`
rather than replacing it, so Supabase, Telegram and Anthropic keys keep coming
from `.env`. See `.env.live.example`.

The engine refuses to start if the live account is not fully pinned (terminal
path, login, password, server) - `mt5.initialize()` attaches to whatever terminal
it is pointed at, so an unpinned engine would trade whatever account that
terminal happens to be showing while labelling everything `icmarkets-live`.
