# Research log

What has been tested, and what it returned. Kept so nobody - human or AI -
re-runs a dead end believing it is new ground. Negative results are results.

Every number here is net of modelled costs (live MT5 spread + $7/lot round-turn
commission), entries filled at the next bar's open, and judged by a bootstrap
95% CI on expectancy. "Edge" means that interval sits entirely above zero.

## Verdict so far: no demonstrated edge. Nothing is Ready.

Six strategies, five mechanisms, ~37,000 simulated trades, 3-12.7 years of real
history per instrument. Not one produced an edge that survives retail costs.

## 2026-08-30 - The demo lab's first out-of-sample read on the backtests

739 closed demo trades (2026-07-16 to 08-30) are now the first live check on the
numbers below. They were produced by the real engine against the real broker, so
they carry execution the backtest only models. Comparison, all in R:

| Strategy | Backtest | n | Demo | n | Demo 95% CI | Delta |
|---|---|---|---|---|---|---|
| `ema_trend_v1` | ~0 | 61 | -0.286 | 10 | [-0.859, +0.376] | unjudgeable |
| `london_breakout_v1` | -0.088 | 1,148 | **+0.137** | 43 | [-0.216, +0.499] | +0.225 |
| `range_fade_v1` | -0.027 | 6,033 | -0.114 | 204 | [-0.272, +0.045] | -0.087 |
| `range_fade_h4_v1` | -0.042 | 5,715 | -0.090 | 49 | [-0.393, +0.216] | -0.048 |
| `donchian_breakout_v1` | -0.090 | 15,024 | **-0.376** | 261 | [-0.511, -0.236] | -0.286 |
| `donchian_trending_v1` | -0.122 | 8,856 | **-0.324** | 172 | [-0.486, -0.155] | -0.202 |

**The sign never flipped in the direction that matters.** Every strategy the
backtest called negative came back negative, and the two channel-momentum
strategies came back 2-4x worse than modelled, with demo CIs entirely below zero
and drawdowns (101.6R and 58.2R) many times the 15R demote threshold.

**Do not over-read the size of the deltas.** The demo window is **six weeks -
one regime**, against backtests spanning 3-12.7 years. A momentum-hostile six
weeks explains the donchian gap as well as any execution story does, and nothing
here separates the two. What the window *can* support is the sign, which agrees
with the backtest everywhere it has the sample to speak.

### `london_breakout_v1` is the only positive, and it is thin

Demo +0.137R over 43 trades, PF 1.285, max drawdown **3.45R** - by far the
best-behaved equity curve in the lab, and the reason it is the only strategy the
evaluator has ever rated `almost_ready`. Both halves are positive (+0.181R,
+0.095R). It is also, on the same data:

- **outlier-carried** - dropping its single best trade gives +0.090R, dropping
  the best three gives **-0.005R**. Three trades out of 43 is the whole result.
- **median-negative** (-0.108R): most of its trades lose.
- **contradicted by 27x more data.** The backtest said -0.088R over 1,148
  trades. A true value of -0.088 is comfortably inside the demo CI
  [-0.216, +0.499]. Nothing here is inconsistent with the backtest being right
  and this being a lucky run.

The honest reading is that it has not shown anything yet, which is exactly what
`almost_ready` means and why the 100-trade bar exists. At its observed ~1.16
trades/day it reaches 100 around **mid-October 2026**. There is no legitimate way
to shorten that: the FX strategies already run the full 16-symbol `UNIVERSE`, so
the data-rate lever used on `ema_trend_v1` has already been pulled.

### The AI shadow reviewer shows no skill, and cannot reach a verdict from here

`review_scoring.py` exists to answer one falsifiable question: does Claude's
approval predict outcome? Joining all 189 `ai_reviews` through
`signals` -> `trades.signal_id` to realised R:

| Arm | n | Expectancy | 95% CI | Win rate |
|---|---|---|---|---|
| Approved | 38 | -0.164R | [-0.502, +0.200] | 29% |
| Rejected | 17 | -0.197R | [-0.666, +0.350] | 18% |

**Difference +0.033R, 95% CI [-0.600, +0.631].** No skill demonstrated. Both arms
lose, and the gap between them is a rounding error inside an interval 1.2R wide.
Approval rate is 69%; mean confidence is *higher* when rejecting (0.63) than when
approving (0.58).

The correct reading is not "the reviewer is useless" but **"this cannot be
answered yet, and will not be soon."** The rejected arm has 17 trades against
`MIN_ARM_FOR_ESTIMATE = 30`, so by the module's own standard no estimate should
be quoted at all. Worse, the arithmetic of getting there is discouraging:

- Only 55 of 189 reviews (29%) ever joined a closed trade with usable risk.
- Reviews accrue at ~4/day, so scoreable *rejections* accrue at ~0.36/day. Thirty
  rejections is ~5 more weeks; detecting an effect the size of a real edge
  (~0.1R against a per-trade SD near 1R) needs several hundred per arm, which is
  years.
- **Retiring the two donchians on 2026-08-30 removes 33 of the 55 scored reviews'
  source (60%)**, cutting that rate further. That is a real cost of the
  retirement, recorded here rather than discovered later.

So the reviewer is not a near-term route to anything. Raising
`ai_review_sample_pct` (currently 10) would accelerate the record at the price of
Opus calls per signal; leaving it alone means the experiment runs indefinitely
without concluding. Either is defensible; pretending the current record says
something is not.

### Retired

`donchian_breakout_v1` and `donchian_trending_v1` were marked
`strategies.retired = true` on 2026-08-30. Both were negative in backtest before
this, `donchian_trending_v1` was already recorded here as falsified 0-for-8 out
of sample, and the demo run put both CIs entirely below zero over 261 and 172
trades. They were 59% of all lab trades and were no longer buying information.
Reversible in one field if that judgement is ever revisited.

## The strategies

| Strategy | Mechanism | Trades | Net expectancy | Verdict |
|---|---|---|---|---|
| `ema_trend_v1` | MA-crossover trend-following | 61 | ~0 | no edge (also far too rare to judge: ~19/yr) |
| `london_breakout_v1` | Compressed Asian range breaks at London open | 1,148 | −0.088R | **negative** |
| `range_fade_v1` | Mean reversion, ADX < 20 | 6,033 | −0.027R | zero |
| `donchian_breakout_v1` | 20-bar price-channel momentum, FX | 15,024 | −0.090R | **negative** |
| `donchian_trending_v1` | Same logic, trending assets | 8,856 | −0.122R | **negative** |
| `range_fade_h4_v1` | Same logic as `range_fade_v1`, at H4 | 5,715 | −0.042R | **negative** |

Six strategies, five mechanisms: `range_fade_h4_v1` and `donchian_trending_v1`
are not new ideas, they are the *same* mechanism aimed at unseen data - which is
the only kind of variant this log permits (see the standing rule at the bottom).

## The two findings that actually matter

### 1. Costs are the whole story, and they are not fixable

`range_fade_v1` produced **+263.91R gross** across 6,033 trades. Measured, not
inferred: **gross expectancy +0.044R/trade, bootstrap 95% CI [+0.013, +0.074] →
signal POSITIVE.** The strategy genuinely predicts price. Costs then took 456.67R
of it: **net -0.032R/trade, CI [-0.063, -0.001] → negative.** The inefficiency is
real and smaller than the toll to reach it. The gap is **0.029R**.

**Two caveats that cut against reading this as encouragement:**

- **It is not stable across time.** First half gross +0.031R, CI [-0.013,
  +0.075] - *not* significant. Second half +0.057R, CI [+0.013, +0.101] -
  significant. The full-sample result is carried by the recent half, so the edge
  may be regime-dependent or fading rather than a permanent feature.
- **Closing the gap barely helps.** Commission $7 → $4 (IBKR at 1 lot, or a
  volume tier) reaches roughly break-even, not profit. Futures-grade cost
  (~$2/round-turn ≈ 0.030R) would yield ~+0.014R/trade - but the edge was
  measured on FX, and there is no evidence it exists in the instruments where
  those costs live. Chasing it there is a new research project, not a port.

Per-symbol gross results are noise: USDCHF shows GROSS +0.140R, CI [+0.025,
+0.255] POSITIVE - 1 significant result in 16 tests, where chance alone yields
~0.8. Do not build on it.

This is not a bug to fix or a parameter to tune. It is the seat at the table.
Every strategy here shows the same shape: gross hovering around zero, net
pushed below it by costs.

### 2. The gold result was noise, and the arithmetic said so before the test did

`donchian_breakout_v1` on XAUUSD returned +0.089R with CI [+0.003, +0.176] -
the only positive across **3 strategies x 16 symbols = 48 tests**. At 95%
confidence, noise alone is expected to manufacture ~2.4 false positives. Finding
**one** is *fewer* than chance predicts.

Three independent checks then killed it:

- **The CI flipped on a spread snapshot.** Re-running the identical 1,043 trades
  minutes later moved it to [−0.003, +0.170] - not significant - purely because
  `resolve_costs()` sampled the live spread at a different instant. Any result
  whose significance depends on *what second you measured* is sitting on zero.
- **Neither half of its own sample cleared zero** (first: [−0.070, +0.174],
  second: [−0.011, +0.242]).
- **The out-of-sample test failed 0 for 8** (below).

## The out-of-sample test (the one that settled it)

The 48-test pattern - gold positive, 15 FX negative - suggested a *mechanism*
rather than a fluke: momentum works on assets that trend (persistent macro/supply
flows), and fails on FX majors (relative prices between similar economies, which
mean-revert). That explains every result at once **and predicts** momentum should
work on other trending assets.

`donchian_trending_v1` tested exactly that, on eight instruments never examined.
It **subclasses** `donchian_breakout_v1` so the logic is provably identical -
`evaluate()` is the same function object, zero new parameters, nothing tunable.
Deliberately excluded: XAUEUR/XAUGBP/XAUJPY/XAUCHF/XAUAUD/GCQ26, which look cheap
(~0.005R) but **are gold** in another currency - testing them would re-run the
same coin flip and call the echo confirmation.

| Symbol | Cost (median) | Expectancy | Verdict |
|---|---|---|---|
| XAGUSD | 0.186R | −0.153R | negative |
| XPTUSD | 0.315R | −0.411R | negative |
| XPDUSD | 0.357R | −0.599R | negative |
| MidDE50 | 0.148R | −0.214R | negative |
| MidDE60 | 0.220R | −0.163R | negative |
| XNGUSD | 0.070R | −0.030R | zero |
| **BTCUSD** | **0.023R** | −0.060R | zero |
| IT40 | 0.099R | −0.055R | zero |

**0 of 8 positive.** And it cannot be blamed on costs: BTCUSD (0.023R) and
XNGUSD (0.070R) are cheap, clean and large-sampled, and both fail. The
hypothesis died on its best ground. **Falsified.**

## The scale test: why the one real edge cannot be reached

`range_fade_v1` has a genuine gross edge (+0.044R/trade) that its 0.066R costs
consume. Cost-in-R is `commission / (stop x value)`, so it shrinks as the stop
grows: the identical signal on a bigger bar should carry less drag. That is
arithmetic, not a hope, and it makes a clean prediction - if the edge is
scale-invariant, H4 halves the cost and the net turns positive.

`range_fade_h4_v1` tested it. Identical logic (asserted: `evaluate()` is the same
function object), only the timeframes moved. **The prediction split in two:**

| | H1 | H4 |
|---|---|---|
| Cost / trade | 0.066R | **0.031R** - halved, exactly as predicted |
| **Gross / trade** | **+0.044R** | **-0.008R** - gone |

Net -0.042R, CI [-0.074, -0.010] → **negative**, over **12.7 years** (H4 history
reaches 2013 - a *longer* sample than the H1 run), across 5,715 trades.

An earlier version of this section claimed the H4 result was "negative in both
halves". **That was wrong**, and two independent re-runs say so: the first half
is negative (CI [-0.102, -0.009]) but the second half straddles zero (CI
[-0.072, +0.017]) - i.e. *not* distinguishable from zero, not negative. The
verdict is unchanged, because it never rested on the halves: the full-sample net
CI is entirely below zero and the full-sample **gross** CI [-0.039, +0.025]
contains zero, which is the actual finding. Corrected rather than quietly
dropped - a log that overstates in the pessimistic direction is still a log that
overstates.

**The cost model is trustworthy. Scale-invariance was wrong.** The edge lives at
one hour and is absent at four.

### The finding that matters

Mean reversion at H1 is a short-term order-flow imbalance correcting itself; by
H4 it has already played out. It is a *fast* effect - and fast effects are
exactly where costs dominate, because the same toll is charged against a much
smaller move.

> **The edge survives only at the timescale where it is too expensive to trade.**

That is not bad luck. It is *why it still exists*. An effect this cheap to
capture would have been arbitraged away long ago; the cost barrier is what
preserves it. Retail costs do not merely reduce this edge - they are the reason
there is anything left to find.

Do not read "there is a real gross edge" as encouragement. Read it as: the
market is efficient *net of costs*, which is the only sense in which efficiency
was ever claimed.

## Incidental findings worth not rediscovering

- **Some instruments are structurally untradeable, and only the broker says so.**
  Platinum/palladium: the broker minimum stop distance (XPTUSD: 14.92) *exceeds*
  typical ATR - 816 signals were unplaceable, so volatility-scaled stops cannot
  work there. MidDE50 (2026-07-17) hit the same wall twice: it first rejected the
  lab's hardcoded 0.01 lot (retcode 10014 - index CFDs carry a larger
  `volume_min`; fixed by sizing to the broker's minimum), and behind that
  rejected the ATR stop as too tight (retcode 10016) - the XPTUSD trap again. So
  `donchian_trending_v1` has never recorded a trade on any of its three index
  CFDs. That changes nothing about its verdict (already falsified, 0-for-8), but
  the **shape** matters: *a signal fires, the order silently cannot be placed,
  and no trade is ever recorded* - a strategy's real universe can be quietly
  smaller than its declared one. Note the asymmetry that hides it: the backtest
  floors out stops that could never have been placed, while the live engine
  attempts them, so this only ever surfaces as a failed order.
  **The subtle risk, for any future strategy:** an ATR stop falls below the
  broker minimum precisely when volatility is *low*. If an instrument's minimum
  always exceeds its ATR the instrument is simply absent (harmless). If it is
  *marginal*, only the high-volatility trades survive to be recorded - selection
  on a variable plausibly correlated with outcome, which is a real bias, not
  merely a smaller sample.
- **Trade frequency is a first-class design constraint.** `ema_trend_v1` trades
  ~19/yr on 4 symbols, so the lab's 100-trade bar sat ~5 years away and no
  verdict could ever arrive. A strategy that cannot be judged in a useful
  timeframe is unusable regardless of its merit. Widening to 16 symbols fixed
  the rate (327-4,650/yr); it did not create an edge.
- **Cost is a hyperbola in stop size.** `cost = commission / (risk x value)`, so
  as a stop shrinks the modelled cost explodes. Holiday sessions collapse ATR,
  ATR-multiple stops collapse with it, and a handful of sub-pip "trades" at tens
  of R each once made costs read 1.2R/trade (~20x reality). Fixed by flooring
  out stops that could never have been placed. Any future cost model must be
  checked at the *distribution*, not the average.

## What has NOT been tested

- **Slow momentum.** Time-series momentum has real academic support, but at
  1-12 **month** horizons in diversified futures portfolios - not H1 bars. That
  is a genuinely different claim. It is also nearly unvalidatable here: a few
  trades per year means decades to reach a judgeable sample.
- **Non-price edges** (carry, positioning, fundamentals). Different data, not a
  different indicator.

## The standing rule

Do not respond to these results by generating more strategy variants until one
passes. Across 48+ tests we found fewer "significant" results than chance
predicts; mining harder finds noise, and that false positive is the one that
would take real money. New tests need a *prior mechanism* and a prediction about
unseen data - the standard `donchian_trending_v1` met, and failed honestly.
