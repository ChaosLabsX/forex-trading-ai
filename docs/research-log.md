# Research log

What has been tested, and what it returned. Kept so nobody - human or AI -
re-runs a dead end believing it is new ground. Negative results are results.

Every number here is net of modelled costs (live MT5 spread + $7/lot round-turn
commission), entries filled at the next bar's open, and judged by a bootstrap
95% CI on expectancy. "Edge" means that interval sits entirely above zero.

## Verdict so far: no demonstrated edge. Nothing is Ready.

Five strategies, five mechanisms, ~31,000 simulated trades, 3-7 years of real
history per instrument. Not one produced an edge that survives retail costs.

## The strategies

| Strategy | Mechanism | Trades | Net expectancy | Verdict |
|---|---|---|---|---|
| `ema_trend_v1` | MA-crossover trend-following | 61 | ~0 | no edge (also far too rare to judge: ~19/yr) |
| `london_breakout_v1` | Compressed Asian range breaks at London open | 1,148 | −0.088R | **negative** |
| `range_fade_v1` | Mean reversion, ADX < 20 | 6,033 | −0.027R | zero |
| `donchian_breakout_v1` | 20-bar price-channel momentum, FX | 15,024 | −0.090R | **negative** |
| `donchian_trending_v1` | Same logic, trending assets | 8,856 | −0.122R | **negative** |

## The two findings that actually matter

### 1. Costs are the whole story, and they are not fixable

`range_fade_v1` produced **+264.78R gross** across 6,033 trades - a real,
measurable inefficiency. Costs then took **425.55R** of it, landing at −160.77R
net. The signal has genuine predictive value and is too small to be worth a
retail spread and commission.

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

## Incidental findings worth not rediscovering

- **Platinum/palladium are structurally untradeable with ATR stops.** Their
  broker minimum stop distance (XPTUSD: 14.92) *exceeds* typical ATR - 816
  XPTUSD signals were unplaceable. Volatility-scaled stops cannot work there.
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
