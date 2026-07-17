# Safety rails

Everything in this doc exists to answer "is this safe to leave running?" -
consolidated in one place rather than scattered across commit messages.

## `TEST_MODE`

Single flag in `.env`, defaults to `true`. Read by `DefaultRiskEngine`
(`engine/plugins/risk/default_risk_engine.py`). It selects sizing **style** and
is **not a safety guard** - on a live account `TEST_MODE=true` is the
*dangerous* setting. See "Live trading is off behind four independent guards".

- `TEST_MODE=true` (the demo lab): each order uses **the broker's minimum
  volume for that symbol**, read from `symbol_info` at runtime. Deliberately
  ignores equity - the lab measures edge in R, and R = `realized_pnl /
  risk_amount` is invariant to lot size, so the size need only be *placeable*.
  Per-symbol, **not** a fixed 0.01: that is an FX convention, and index CFDs
  carry a larger `volume_min` and reject 0.01 outright (retcode 10014
  INVALID_VOLUME). Found live on MidDE50, 2026-07-17 - the lab had been
  ignoring contract specs the live path always respected.
- `TEST_MODE=false` (live): risk-based sizing from stop distance
  (`engine/sizing.py`), clamped to the broker's `volume_min`/`volume_max`/
  `volume_step` and checked against free margin. **It is implemented and
  tested.** An earlier version of this section claimed it was "not
  implemented", which was false and contradicted this same document's guards
  section - live trading is off because no strategy has earned it, not because
  anything is missing.

## Circuit breakers (`DefaultRiskEngine.validate_signal`)

| Rail | Scope | Runs on |
|---|---|---|
| Max concurrent open trades (`Settings.max_concurrent_trades`, 4) | **per strategy** - each sees only its own positions (`strategy-lab.md`) | both accounts |
| Consecutive losing trades today (`MAX_CONSECUTIVE_STOP_LOSSES = 3`) | account-wide | **live only** |
| Max daily loss % (`MAX_DAILY_LOSS_PCT = 3.0`) | account-wide | **live only** |

The two LOSS breakers are gated on `Settings.live_trading_enabled` - the
explicit real-money switch - and deliberately **not** on `TEST_MODE`, which is
not a safety signal: a live account left on `TEST_MODE=true` must keep its
breakers, and does.

**Why they must not run on the demo lab.** They exist to protect real capital;
the lab has none. Worse, they corrupt the data the lab exists to produce. A
blocked signal is never recorded as a trade, and these breakers block
*precisely during losing streaks* - censoring losers, biasing measured
expectancy **upward**, and freezing account-wide accumulation toward the
100-trade bar (one strategy's bad day throttling every other strategy's data,
re-contaminating the isolation that ownership exists to provide). The
concurrency cap has no such problem: it is not outcome-correlated, so it
applies on both accounts.

The loss figures are recomputed fresh from **real** MT5 closed-deal history on
every `get_account_state()` (`MT5BrokerAdapter._daily_stats()`, counting
backward from the most recent close while `profit < 0`) - never cached or
estimated.

## AI review is shadow-mode only - and live-only

`ClaudeAIProvider` reviews a fired signal and logs a verdict to `ai_reviews`,
but **the verdict never gates execution**: the trade proceeds or doesn't purely
on `RiskEngine`'s decision, which has already run by the time the review fires.
Deliberate - build a track record before trusting it to block trades. If that
ever changes it is a real architectural decision worth flagging loudly, not a
quiet default.

It also runs **only when `live_trading_enabled`** (`EngineLoop._review_with_ai`).
Each review costs an Opus API call per fired signal, which only earns its keep
where a track record against real-money outcomes could one day justify letting
it gate trades; on the demo lab it billed continuously for opinions nothing
consumes. Nothing reads `ai_reviews` except the dashboard's display column -
not the evaluator, not the risk engine, not any strategy - so skipping it on
demo changes no trade and no readiness verdict. It resumes by itself when live
is enabled.

## RLS / dashboard security model

The dashboard is a public static site using the Supabase **anon** key - there
is no secret in the frontend bundle. Row-Level Security is the actual access
boundary. Since migration `0008` the whole dashboard sits behind a login gate,
and anon's read access was revoked to match (a UI-only gate would have left
the data publicly queryable via the REST API):

| Table | `anon` | `authenticated` | `service_role` (engine) |
|---|---|---|---|
| `signals`, `trades`, `engine_heartbeats`, `candles`, `ai_reviews` | none (revoked in `0008`) | SELECT | ALL |
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

## MT5 timestamps are server time, not UTC

Real bug, found and fixed in live Phase 3 testing: `symbol_info_tick()`,
`copy_rates_from_pos()`, and `history_deals_get()` all report timestamps in
the broker's **server time** (measured live on this IC Markets account: ~3
hours ahead of UTC, consistent with EEST), not UTC - despite the raw value
being a plain Unix epoch, which makes it easy to assume it's already UTC.
Code that did `datetime.fromtimestamp(x, tz=timezone.utc)` directly on these
values was silently 3 hours off. This mattered concretely: the session-time
filter (`ema_trend_v1`'s London/NY 12:00-16:00 UTC window) was gating trades
against the wrong 3-hour window, and `_daily_stats()`'s "today" boundary for
the circuit breakers was similarly skewed.

Fixed via `engine/plugins/brokers/mt5_time.py`: the offset is *measured* at
runtime (compare a live tick's `.time` against the local system clock's true
UTC), not hardcoded - a hardcoded value would silently break across DST
transitions. `MT5BrokerAdapter` remeasures on every `connect()`;
`MT5MarketDataProvider` measures once lazily and caches it (it has no
`connect()` lifecycle of its own). `_daily_stats()` no longer trusts
`history_deals_get()`'s query-bound timezone semantics (undocumented) -
it queries a generously wide window and filters deals precisely using each
deal's own corrected UTC time instead.

**If you ever add code that reads an MT5 timestamp field directly, route it
through `server_epoch_to_utc()` - never `datetime.fromtimestamp(x, tz=timezone.utc)`
on a raw MT5 value.**

## A client-side order error doesn't mean the order failed

Also found live: `place_order()` raised `MT5ConnectionError` with MT5 retcode
10012 (TIMEOUT) - the client gave up waiting for a response - but the order
had actually filled on the broker's side. The original code treated any
exception from `execute()` as "nothing happened," which meant this specific
position existed as a real open trade with **no corresponding `trades` row** -
invisible to `_reconcile_closed_trades()` forever, since that logic only
checks positions it already knows about.

Fixed in `EngineLoop._open_trade()`: on an execution exception, it now
snapshots open positions before the attempt and checks for a new, matching
position (same symbol/direction/lot size) after a failure before giving up -
recovering and logging it as a `trade_recovered` event instead of silently
losing track of it. This is a heuristic match, not a guarantee - if you ever
run multiple concurrent strategies capable of placing the *same* symbol +
direction + lot size at the *same* moment, this could misattribute which
signal a recovered position belongs to. Not a concern at today's scale (one
strategy, sequential evaluation), worth revisiting if that changes.

## "Connected" meant "MT5.exe is running" - and the engine never checked which account it was on

Found live on **2026-07-15**: 31 orders in a row refused by MT5 with retcode
**10019 (NO_MONEY)** on a demo account holding **$10,000,046 in free margin**,
placing 0.01 lots needing ~$18. NO_MONEY was not a lie about the balance - MT5
was simply not looking at the account we thought it was.

Two independent defects combined:

1. **`is_connected()` returned `mt5.terminal_info() is not None`.**
   `terminal_info()` returns a struct whenever the terminal *process* is
   reachable; its `.connected` field is what reports the trade-server link, and
   the check ignored it. Every heartbeat therefore recorded
   `broker_connected: true` throughout the outage. The health signal could not
   observe the thing it claimed to observe.
2. **Nothing verified the terminal's account.** `connect()` calls
   `mt5.initialize(login=...)` **once**; afterwards the IPC bridge silently
   follows the terminal wherever it is pointed. With `MT5_LOGIN` empty (the
   documented attach-to-open-terminal mode) it never logs in at all - it
   inherits whatever account the terminal happens to be on, and cannot log back
   in, because it has no credentials.

The engine was paused 15:07-16:47 UTC, which only *hid* the onset - a paused
engine sends no orders. Failures began 7 seconds after the resume and continued
for two hours until the process died; the restart re-attached and "fixed" it.
Nothing alerted, because by every check the engine had, it was healthy.

**Fixed in `MT5BrokerAdapter`:**

- `is_connected()` now requires `terminal_info().connected` **and** that the
  terminal is still on the bound account.
- `connect()` reads `account_info()` and calls `_bind_account()`, which pins the
  adapter to one account: `MT5_LOGIN` when set, otherwise the account seen on
  the first connect. Any later move raises rather than trading on.

Returning `False` is also the repair: `EngineLoop._ensure_connected()` already
alerts and calls `connect()`, which re-runs `initialize(login=...)`. That path
existed the whole time and never fired because nothing could detect the fault.

**This only fully works if `MT5_LOGIN`/`MT5_PASSWORD` are set.** Without them the
adapter can detect drift and refuse, but cannot log back in - it will alert and
stay down until a human fixes the terminal. That is the correct failure, not a
good one.

## ...and then `connect()` crashed on its own log line, undoing all of it

Found 2026-07-17, and it had been live since the fix above was written.
`mt5_broker.py` referenced `logger` on two lines but never imported `logging`
or defined it, so `connect()` raised `NameError: name 'logger' is not defined`
at the `attached: account ...` line - which sits **after** `mt5.initialize()`
and `account_info()` succeed, but **before** `_verify_server()`,
`_bind_account()`, and the server-time offset measurement.

The loop caught it as a connect failure and retried. On the next tick
`is_connected()` returned `True` - it returns `True` while `_bound_login is
None` ("never connected yet - nothing to compare against") - so the engine
**limped onward and traded** with three properties silently off:

- the wrong-server refusal never ran;
- the account was never pinned, so `is_connected()` could never detect drift -
  the exact protection the section above exists to provide;
- `_server_utc_offset_seconds` stayed at its `0.0` default, reintroducing the
  ~3h server-time-as-UTC error and skewing the circuit breakers' "today".

Two lessons worth more than the fix:

- **A green compile is not a green run.** `py_compile` passes on this - a
  NameError is a runtime fault. This is the same trap as the deleted file that
  compiled clean (see `CLAUDE.md` rule 6).
- **Tail the startup, not just recent activity.** It was invisible for days
  because every check looked at the *latest* log lines, where a limping engine
  and a healthy one are indistinguishable. The failure only appears in the
  first two seconds after a restart.

## The watchdog: silence is not health

A dead lab and a lab with nothing to report both produce **silence**, so "no
READY alert yet" and "the engine died three days ago" were indistinguishable
from a phone. The engine cannot announce its own death: a crash, a logged-out
terminal, or a hung loop all just stop.

`infra/watchdog.ps1` is a scheduled task (every 5 min, as SYSTEM - no
interactive session needed, so it survives logoff) that reads the newest
heartbeat per **enabled** account straight from Supabase and alerts on Telegram
when one goes stale: one alert on silence, an hourly reminder while it
persists, one all-clear on recovery. If it cannot reach Supabase it alerts
about **that** - blind is not all-clear.

It shares nothing with the engine but `.env`: no Python, no venv, no MT5, and
it delivers Telegram itself rather than through the engine's notifier - a
watchdog routed through the thing it watches is not a watchdog. Watching
*enabled* accounts means it covers the live account automatically the day
`accounts.enabled` flips, with nothing to remember.

Heartbeats are only sent while `self._connected`, so a broker that never
connects reads as silence - which is correct, and is exactly what the section
above would have surfaced in five minutes instead of days.

**Read this before installing the live terminal.** `MT5_TERMINAL_PATH` is also
empty for the demo engine, so a bare `mt5.initialize()` attaches to whichever
terminal Windows offers. `infra/run-live-engine.ps1` pins the path for the
*live* engine, but the *demo* engine has no such pin - so once a second terminal
exists, the demo engine can attach to the **live** terminal. Its `ACCOUNT_KEY`
would still say `icmarkets-demo`, so `gating.py` would clear it as the demo
account and place `TEST_MODE=true` micro-lot orders on real money. Pin
`MT5_TERMINAL_PATH` for both engines before step 2 of `going-live.md`.

## TLS is verified against the OS trust store, not OpenSSL's bundle

Found live during Phase 6 VPS bring-up: the engine ran fine, MT5 connected,
and Supabase writes succeeded, but every Telegram notification failed with
`ssl.SSLCertVerificationError: ... self-signed certificate in certificate
chain` from `urllib.request.urlopen()` in `telegram_notifier.py`.

It was not a code bug and not a proxy - `telegram_notifier.py` and
`supabase_client.py` use the identical bare `urllib.request` pattern, and
Supabase worked. The difference was purely the destination host's chain:
Windows' own verifier trusted `api.telegram.org` (confirmed via a .NET
`SslStream` probe returning zero policy errors), but Python's bundled OpenSSL
couldn't build the same path - Windows does alternate-chain building / AIA
fetching that OpenSSL doesn't, so OpenSSL dead-ended at a self-signed cert in
the presented chain.

Fixed by adding `truststore` (a dependency) and calling
`truststore.inject_into_ssl()` once at the top of `scripts/run_engine.py`,
before anything opens a socket. This delegates certificate verification to the
OS verifier (Windows CryptoAPI) - **verification stays fully on**, it's just
sourced from the store that already trusts the chain, and it also tracks any
future root changes Windows makes. It's a no-op wherever OpenSSL already
succeeds (Supabase, the Anthropic API). **Don't "fix" a TLS error here by
setting `verify_mode = CERT_NONE` or an unverified context in the plugins -
route trust through the OS store instead.**

## Breakeven / trailing stop management

`DefaultExecutionEngine.manage_open_position()` ratchets the stop toward profit
while a position is open, called every `MANAGE_INTERVAL_SECONDS` (5s) by the
loop's `_manage_open_positions()`:

- at `breakeven_at_r` (default 1.0R) profit, the stop moves to entry - the trade
  can no longer become a loss;
- past `trail_start_r` (default 2.0R), the stop trails `trail_distance_r`
  (default 1.0R) behind price.

Thresholds are in R (the trade's initial risk), so they scale per instrument
without a fixed pip value; all four knobs live on `Settings`
(`trail_enabled` off reverts to the old leave-it-alone behaviour). Two safety
properties worth stating explicitly:

- **The stop is only ever moved in the profit-locking direction, never
  loosened.** A modify is sent only when the new stop improves on the current
  one by at least `MIN_STEP_R` (0.25R) - which also throttles broker calls and
  notification spam.
- **A mid-trade engine restart is safe, not optimal.** The initial-risk cache
  is in-memory; after a restart it's re-derived from the *current* stop. If that
  stop was already at breakeven the derived risk is ~0 and management stops for
  that trade - it stays protected by the breakeven stop but won't trail further.
  Never unsafe (the stop is still never loosened), just occasionally leaves gain
  on the table. MT5 continues enforcing whatever stop is set even while the
  engine is down.

## Two terminals: pin each engine, and verify where it landed

With a demo and a live MT5 terminal installed on the same box, **an empty
`MT5_TERMINAL_PATH` is dangerous**. `mt5.initialize()` with no path attaches to
whichever terminal Windows offers - harmless with one installed, a live-money
incident with two.

The failure it enables: the **demo** engine runs `TEST_MODE=true`, which places
real 0.01-lot orders. Attached to the **live** terminal it would trade real money
while tagging every alert `DEMO`. And `_bind_account()` would not save you -
with `MT5_LOGIN` empty, the first account it attaches to becomes "correct" by
definition.

Two things prevent it:

1. **Pin `MT5_TERMINAL_PATH`** in each engine's environment. The live engine
   already does this (`infra/run-live-engine.ps1`); the demo engine's `.env`
   must too.
2. **`MT5BrokerAdapter._verify_server()`** refuses to trade when
   `account_info().server` doesn't match `MT5_SERVER`. The servers differ
   (`ICMarketsSC-Demo` vs `ICMarketsSC-MT5-3`), so a mix-up raises instead of
   trading. Every connect also logs the terminal path and account, so which
   account an engine is on is never invisible again.

Setting `MT5_LOGIN`/`MT5_PASSWORD` for both is stronger still: without
credentials the adapter cannot log back in, so a terminal that drifts to another
account can only be refused, not repaired.

**Stopping a live engine:** `Stop-ScheduledTask` kills the `powershell.exe`
wrapper but **not the `python.exe` it spawned**. Check for orphans with
`Get-Process python` and confirm the log has stopped growing - a disabled task
whose log is still being written is an orphaned engine, not a stopped one.

## Live trading is off behind four independent guards

Risk-based position sizing **is implemented and tested** (`engine/sizing.py`);
live trading is off because no strategy has earned it, not because anything is
missing. Full procedure in [`going-live.md`](going-live.md). The guards:

1. **`Settings.live_trading_enabled` (`LIVE_TRADING_ENABLED`, default false)** -
   `engine/gating.py` blocks every strategy account-wide on a live account while
   it is off.
2. **`accounts.enabled = false`** on `icmarkets-live` (migration `0010`).
3. **`strategy_accounts.enabled = false`** for every strategy on live - so
   promoting a strategy to READY never silently starts it live.
4. **`strategies.readiness == 'ready'`** is required on live, and only
   `engine/evaluator.py` ever grants it.

**An earlier version made guard 1 mean "sizing isn't implemented yet". That was
a trap**: a safety property derived from a feature being missing evaporates the
instant the feature lands - implementing sizing would have silently disarmed it.
The guard is now an explicit switch that says nothing about what is built.

**`TEST_MODE` is not a guard.** It selects sizing *style*: `true` = the demo
lab's fixed 0.01 micro lot, `false` = real risk-based sizing. On a live account
`TEST_MODE=true` is the *dangerous* setting - it would place real micro-lot
orders sized for a demo.

## Readiness verdicts are statistical, not opinions

`engine/evaluator.py` grades each strategy from its real closed trades. READY
requires a bootstrap 95% CI on expectancy sitting **entirely above zero** over
at least `readiness_min_trades_ready` (100) trades, plus profit-factor and
drawdown vetoes. Verdicts always derive from the **demo** account - grading a
strategy on the account it was already allowed onto would be circular - and are
recomputed every `evaluation_interval_minutes`, so a decayed strategy is
demoted automatically and loses live eligibility without anyone intervening.

R-multiples are the unit throughout, which is why `trades.risk_amount` and
`trades.initial_stop_loss` are captured at open: trailing-stop management
rewrites `trades.stop_loss`, so the original risk distance is gone by the time
a trade closes. Trades without `risk_amount` (anything opened before this) are
excluded from R statistics rather than guessed at.

## Known, deliberate gaps (not bugs - documented so they aren't "discovered" again)

- **News blackout is a best-effort filter, not a guarantee.**
  `ForexFactoryNewsProvider` (registered as `forexfactory`) pulls the free
  ForexFactory weekly economic calendar - no API key. The strategy blacks out
  entries within 30 min of a high-impact event in a traded currency. It's a
  free community mirror with no SLA, so the provider **fails open**: any
  fetch/parse error keeps the last good cache or, failing that, applies no
  blackout (same as the old placeholder) and logs a warning - it never crashes
  or stalls the loop. So a feed outage silently degrades to "no news filter",
  which is why the blackout sits on top of the session filter and circuit
  breakers rather than being relied on alone. (Finnhub's economic calendar,
  the original plan, turned out to be premium-only; the free ForexFactory feed
  covers this need without a paid plan. Swapping to a paid/official source is a
  new plugin + a one-line `plugins.yaml` change.)
- **No partial position closes.** The `trades` lifecycle is binary
  (`OPEN` → `CLOSED`); scaling out of a position isn't modeled.
- **Doesn't survive a reboot locally.** On this dev machine the engine runs
  as a detached background process with nothing to bring it back after a
  restart. On the VPS (Phase 6), Windows auto-login + a Task Scheduler "at
  logon" trigger (not a Windows service - see below) provide that.

## Why the VPS uses Task Scheduler, not a Windows service (NSSM)

The original plan called for wrapping the engine as an NSSM Windows service.
Corrected during Phase 6: MT5's Python bridge (`mt5.initialize()`) requires
running in the **same interactive desktop session** as the MT5 terminal GUI.
Windows services run in Session 0, which is isolated from any desktop session
by design - an NSSM-wrapped engine would never be able to see MT5, no matter
how correctly everything else was configured. The fix: Windows auto-login
brings up a real desktop session on boot, and a Task Scheduler "at logon"
trigger starts both the MT5 terminal and the engine into that same session.
Task Scheduler's own restart-on-failure settings (`infra/setup-scheduled-tasks.ps1`)
replace what NSSM would have provided. See `infra/vps-setup.md`.
