# Research log

What has been tested, and what it returned. Kept so nobody - human or AI -
re-runs a dead end believing it is new ground. Negative results are results.

Every number here is net of modelled costs (live MT5 spread + $7/lot round-turn
commission), entries filled at the next bar's open, and judged by a bootstrap
95% CI on expectancy. "Edge" means that interval sits entirely above zero.

## Verdict so far: no demonstrated edge. Nothing is Ready.

Six strategies, five mechanisms, ~37,000 simulated trades, 3-12.7 years of real
history per instrument. Not one produced an edge that survives retail costs.
The one funded on live, `london_breakout_v1`, has now been backtested exactly as
it trades, and its CI sits entirely below zero (2026-11-04, below).

A seventh strategy and sixth mechanism - slow trend-following on daily bars,
28 markets, `trend_daily_v1` - failed its pre-registered test on 2026-11-13:
-0.095R over 1,553 trades, CI [-0.161, -0.027], and a coin flip before costs
(next).

## 2026-11-13 - Pre-registered: `trend_daily_v1`, slow trend-following, tested once

Written before the backtest that tests it has been run on any symbol.

**Why this one.** It is the "slow momentum" this log has listed as untested
since the start, requested by the owner. It is a new claim, not a variant: every
strategy so far carried ~0.08R of cost because its stop was 10-20 pips, and its
signal was worth about zero before that cost. Here the stop is two DAILY ATRs -
100+ pips - so the same spread and commission come to about 0.01R. Cost cannot
be what decides this test. What is left is the question: does a price that
closes out of a multi-month range keep going?

**The rules, fixed now.** All from the published Turtle "System 2" (1983), none
fitted here.

| | |
|---|---|
| Signal | a closed daily bar closes above the high (long) or below the low (short) of the 55 daily bars before it |
| Stop | 2 x ATR(20, daily) from that close |
| Target | none |
| Exit | the engine's own stop management, unchanged: to entry at +1R, then trailing 1R behind price past +2R |
| When | once per closed day, at the close of the first H4 bar of the new day (04:00 broker time) - not at the daily close, which is the rollover minute the risk engine refuses |
| Positions | one per symbol; a new breakout while one is open is ignored |

**The 28 markets, chosen by rule before any result:** the lab's standing 16
(15 FX pairs and gold), plus every continuous, non-expiring market the broker
lists that is not an echo of one already in: silver, platinum, palladium; WTI
crude and natural gas (Brent is WTI's echo); bitcoin (other coins are its echo
at this horizon); and one stock index per region - US500, DE40, UK100, JP225,
AUS200, HK50. Dated futures (bonds, softs) are out: no continuous history.

**The test.** `scripts/backtest.py trend_daily_v1`, run once: 20,000 H4 bars a
symbol (~12.8 years where the broker has them), stops managed as the engine
manages them, net of spread, commission AND overnight financing.

**Pass criteria.** Over every trade together: net expectancy with a 95% CI
entirely above zero AND positive in both chronological halves. Anything less is
a fail, recorded and not adjusted - no other channel length, stop multiple,
exit or market list. Asset-class and long/short breakdowns are printed to be
read; a pass in a part ("indices only", "longs only") is NOT a pass.

**Prediction.** 1,500-2,500 trades. Spread and commission under 0.02R a trade
at the median; financing a further -0.02R to -0.08R a trade, heaviest on long
indices, gold and bitcoin. About half the trades full losses, a fifth scratched
at entry, the return in a minority of long runs. FX about zero. Indices, gold
and bitcoin positive long and negative short - 2014-2026 was a rising market in
all three, which is drift, not timing, and the long/short split is there to
show it. Whole test: between -0.05R and +0.15R net, more likely a fail than a
pass. If it passes on longs in rising markets alone, that is recorded as what
it is.

**What a pass would and would not mean.** A candidate for the demo lab, never
for live directly. Even then three things stand in the way, known now: the
lab's cap of 4 concurrent trades would cut a 28-market trend-follower short;
the AI reviewer's prompt assumes a target; and a two-daily-ATR stop costs
$10-$120 at the broker's minimum lot, so at 0.75% risk the live account (~$223)
could not size a single one of these trades.

**Three faults in the backtest itself, found while preparing this, fixed before
the run.** None is specific to this strategy; all change what re-runs of older
strategies would print.

1. **A look-ahead in every two-timeframe backtest.** Bars are stamped with their
   open time, and the slower timeframe was sliced as "every bar opened by now" -
   which includes the one still forming. An H4 bar opened at 08:00 was handed to
   an evaluation made at 10:00 carrying its high, low and close up to 12:00.
   The engine reads closed bars only and never sees this. It reached
   `ema_trend_v1`, `range_fade_v1` (H1 + an H4 regime filter, up to 3 hours
   ahead) and `range_fade_h4_v1` (H4 + D1, up to 20 hours). Their verdicts
   stand a fortiori - all lost even with the peek - but **`range_fade_v1`'s
   "real gross edge" (+0.044R, the finding this log calls the one that matters)
   was measured through a filter that could see the next few hours**, and a
   fade's worst trades are exactly the ones a peek at the coming range would
   remove. The demo, which cannot peek, returned -0.080R gross over 272. That
   made the edge suspect; **re-measured below, it stands.**
2. **No position was ever open.** Every strategy declines a symbol it already
   holds; the backtest showed it an empty book on every bar, so a signal that
   repeated during an open trade was counted again. Now one position per
   symbol, as traded.
3. **Commission was charged on markets that have none.** 2,060 of the demo
   account's own deals: $3.50 a lot a side on FX and metals; **zero on indices,
   energies and crypto** (XNGUSD, BTCUSD, IT40, MidDE50: $0.00 over 178 deals).
   The model charged $7 a lot on everything - on a small-contract index that is
   most of the risk. It explains the 4-43x gap between modelled and realised
   cost recorded on 2026-08-30 for IT40, MidDE50, BTCUSD and XNGUSD, and it
   means `donchian_trending_v1`'s backtest figures for those symbols carried a
   toll that does not exist. Its retirement rests on the demo result (-0.324R,
   CI below zero), which was charged real costs, and is unchanged.

Also new: overnight financing is charged per night held, from the broker's
swap quote (today's rates applied to every year - crude, and stated in the
output). A known simplification left as it is: a trade's first bar after entry
is not walked, so a stop touched inside it is seen one bar late.

**Amendment, still before the run: what history the broker actually has.**
Downloading the 28 markets' bars (bars only; no strategy was run on them)
showed two things the plan above did not know.

- **Before 2016-2018 the non-FX markets have one bar a day.** The broker serves
  its older years as a single daily bar on every intraday timeframe: gold,
  silver and the stock indices until 2016, platinum and palladium until 2017,
  bitcoin until 2018. A strategy clocked on H4 bars cannot be tested as it
  trades on a day that has one of them. So each market is tested from its first
  year of real intraday bars, found mechanically and without reference to
  prices (`first_intraday_index`: bars per calendar day at least two-thirds of
  the market's densest year). FX from 2014-01; gold, silver, US500, DE40,
  UK100, JP225, HK50 from 2016-01; WTI 2016-06; natural gas 2016-08; platinum,
  palladium 2017-01; bitcoin 2018-01.
- **Four markets have under two years of history on this server:** USDCAD,
  AUDJPY, CADJPY and AUS200 begin on 2025-01-02, and a clean re-download gives
  the same. They stay in the test and contribute what they have. This also
  means every earlier "16 symbols, 12.7 years" H4 backtest in this log
  (`range_fade_h4_v1`) very likely ran those three FX pairs on far less than
  12.7 years without saying so; the backtest now prints each symbol's span.

So the sample is smaller than predicted - nearer 10 years than 12.8 outside
FX - and the trade-count prediction is revised down to 1,000-1,800. Nothing
else in the pre-registration changes.

**Result (2026-11-13, run once, on the owner's machine; output kept in
`docs/backtest-output/2026-11-13-trend_daily_v1.txt`): FAIL.** 28 markets, 1,553 trades,
2014-03 to 2026-11 (122 a year), managed stops, net R:

| | Trades | Net | 95% CI | Halves | |
|---|---|---|---|---|---|
| every trade | 1,553 | **-0.095R** | **[-0.161, -0.027]** | -0.032 / -0.158 | fail |

| Per trade | |
|---|---|
| before any cost | +0.008R, CI [-0.057, +0.075] |
| spread + commission | -0.012R (median 0.005R) |
| overnight financing | -0.092R |

- **The question was answered, and the answer is no.** Cost was taken out of
  the way as designed - a hundredth of the risk - and what was left is a coin
  flip: +0.008R a trade before any cost. A daily close out of a 55-day range
  does not keep going, on these markets, over these years.
- **Financing is the toll at this horizon, and it is larger than spread ever
  was.** 142.5R of the 160.6R in costs. 104R of it fell on the six stock
  indices (US500 alone: -45R over 63 trades). Today's swap rates applied to
  every year overstate 2016-2021, when rates were near zero, and the dividend
  credit to longs is not modelled - but the indices made +0.5R over 300 trades
  before any cost, so at zero financing they are still nothing.
- **Read, not judged:**

  | Group | Trades | Net | 95% CI | Halves |
  |---|---|---|---|---|
  | FX (15 pairs) | 855 | -0.113R | [-0.199, -0.026] | -0.025 / -0.201 |
  | stock indices | 300 | -0.348R | [-0.479, -0.209] | -0.402 / -0.294 |
  | metals | 235 | +0.080R | [-0.090, +0.262] | +0.117 / +0.044 |
  | energies | 100 | +0.184R | [-0.201, +0.593] | +0.164 / +0.204 |
  | crypto | 63 | +0.266R | [-0.079, +0.638] | +0.500 / +0.040 |
  | long | 867 | -0.056R | [-0.148, +0.036] | -0.075 / -0.036 |
  | short | 686 | -0.144R | [-0.240, -0.042] | +0.018 / -0.306 |

  FX loses before costs too (-0.078R gross): breakouts in FX revert at this
  horizon as they did at H1.
- **The prediction, scored.** Trade count (revised) and cost held. Half the
  trades were full losses (784, 50.5%), as predicted. Financing came in a
  little worse than the range given (-0.092R against -0.02R to -0.08R). Two
  calls were wrong: FX is not "about zero" but negative, and the stock indices
  are not "positive long" but the worst group in the test. The whole landed
  below the predicted range, on the "more likely" side: a fail.
- Max drawdown 184.6R; 18 losses in a row. The "stops held fixed" block the
  backtest prints means nothing for a strategy with no target (unmanaged, a
  trade can only end in a full loss or the one-year limit) and is not a result.
- **What this does not license: "commodities and crypto only".** Gold (+0.418R
  over 59), bitcoin (+0.266R over 63) and oil (+0.248R over 50) are the
  positive names, and three positive groups of five, none with a CI above
  zero, picked after the result, is the gold finding of this log over again -
  the one that was noise, from the hypothesis that then failed 0 for 8. By the
  rule written above before the run, a pass in a part is not a pass.

`trend_daily_v1` is not promoted to the lab. It stays registered for
`scripts/backtest.py` and is not in `config/plugins.yaml`.

**`range_fade_v1`, re-measured on the corrected backtest (2026-11-14): its
gross edge stands, and the suspicion in fault 1 above was wrong.** No
look-ahead, one position per symbol, financing charged; output in
`docs/backtest-output/2026-11-14-range_fade_v1-corrected.txt`:

| | Trades | Gross | Gross CI | Net | Net CI |
|---|---|---|---|---|---|
| as recorded | 6,033 | +0.044R | [+0.013, +0.074] | -0.032R | [-0.063, -0.001] |
| corrected | 5,567 | **+0.041R** | **[+0.011, +0.071]** | -0.042R | [-0.072, -0.012] |

The look-ahead was real, but it did not make this result: with the filter
blind to the forming bar the signal is the same size. Halves as before - first
+0.025R (CI spans zero), second +0.057R (above it). So this log's central
finding is unchanged and now rests on a cleaner measurement: mean reversion at
H1 predicts price by about 0.04R a trade, and costs of about 0.07R a trade
exceed it. (Run on a Saturday, so the spread is the last quote; gross does not
depend on it.) The demo's -0.080R gross over 272 trades remains the open
disagreement with it, at under two standard errors.

## 2026-11-13 - Full audit: live is now net negative, and the cap did not bind on one bar

A whole-system audit against the accounts' own records. No strategy, threshold
or parameter was changed; nothing here is a variant.

| `london_breakout_v1` | Trades | Net | 95% CI | PF | Net P&L |
|---|---|---|---|---|---|
| live | 35 | **-0.132R** | [-0.503, +0.250] | 0.78 | **-$5.50** |
| demo (after the void below) | 91 | **-0.011R** | [-0.253, +0.235] | 0.98 | |
| backtest, as traded | 1,302 | -0.074R | [-0.135, -0.013] | 0.87 | |

- **The "+$2.30 over 27" has gone.** Eight more live trades took it to -$5.50.
  Live, demo and backtest now agree in sign, and both account intervals still
  contain -0.074R. Live gross is -0.045R a trade and commission a median 0.083R
  - the backtest's cost figure, measured on real fills.
- **Execution is not the problem.** Entry slippage: median +0.012R live (p90
  +0.087R), +0.007R demo. Stops return about -1.1R and targets +1.4R on both
  accounts. No heartbeat gap during market hours in the last 30 days. There is
  no execution fix that turns a gross of about zero into an edge.
- **The demo's one spurious trade was still being counted.** The 2026-09-09
  01:00 EURUSD +1.78R - recorded below as fired on a 7-hours-wrong clock, with
  the instruction to exclude it from the verdict - had never been voided. It is
  now (`void_reason`, trade 873). Without it the demo expectancy is negative and
  the verdict is `not_ready`, not `almost_ready`: that one trade was the whole
  of the strategy's standing in the lab.
- **`max_concurrent_trades` did not bind inside a pass** - a bug, fixed
  (`docs/safety-rails.md`, `scripts/test_concurrent_cap.py`). On 2026-11-10
  08:00 the live account, capped at 2, opened four correlated longs on one bar;
  all four stopped out, -4.4R and 2.6% of equity in an hour. With the cap
  working, two of them (-$3.27) are refused. This is a risk fix, not an edge:
  the same rule would have refused winners on another morning.
- **Sizing is at the broker's floor.** Live equity is ~$223 (it was ~$450 until
  early November), so 0.75% is ~$1.67 and most trades are the 0.01-lot minimum.
  Rounding down means the money at risk now varies from about 0.4% to 0.7% a trade,
  and a setup whose stop costs more than $1.67 at 0.01 lots is refused outright.

What the audit does NOT license, by the standing rule: dropping EURGBP (live
-0.56R over 11, demo -0.34R over 22) or any symbol by its results, another hour,
another exit. H2 already tested the cost mechanism behind EURGBP and failed.

## 2026-11-04 - `london_breakout_v1`, tested exactly as it trades: it loses after costs

The corrected re-run (VPS, `scripts/backtest.py london_breakout_v1`, output kept
there in `logs/backtest-lbo-corrected.txt`) is the first backtest of this
strategy on the right hours - each bar on the clock in force when it formed -
with the engine's own stop management. 16 symbols, **1,302 trades**, 2023-07-24
to 2026-11-03 (397 a year):

| Stops | Net | 95% CI | Halves | Gross |
|---|---|---|---|---|
| managed (as traded) | **-0.074R** | **[-0.135, -0.013]** | -0.080 / -0.068 | +0.009R, CI [-0.052, +0.070] |
| fixed | -0.077R | [-0.143, -0.010] | | +0.006R |

- **Before costs it is a coin flip; costs make it a loser.** Gross +0.009R a
  trade with a CI straddling zero: no signal. Spread and commission take 108R
  over the run - 0.083R a trade - and push the net CI entirely below zero.
  Profit factor 0.87, max drawdown 121R, and both halves lose by about the same.
- **Both pre-registered filters fail** (the 2026-11-03 pre-registration, below).
  Nothing inside the strategy rescues it.
- **The demo and live accounts agree with it, inside their noise.** Demo +0.098R
  over 81 trades (CI [-0.158, +0.362]); live +0.062R over 27 (CI [-0.377,
  +0.506]), +$2.30. Both intervals contain -0.074R. Four months above a 3.3-year
  average is what noise does at these sizes: for live results alone to show a
  -0.074R edge is not zero would take roughly 900 trades - over five years at
  the live pace.
- **No version of the clock gave it an edge.** The summer run said -0.060R over
  1,070, the void winter run -0.092R over 1,895; the right hours land between.

What this means for live is the owner's decision, recorded here when made. What
it does not license is trying other hours, thresholds or exits until some slice
would have worked. The 10:00 bar's +0.024R (174 trades, halves +0.147 / -0.098)
is exactly such a slice, and the standing rule exists because of them.

## 2026-11-03 - Every backtest so far ran part of each year an hour off

**What was wrong.** MT5 stamps every bar in the broker's server time, and the
code converted all of it to UTC with ONE offset - the one measured at run time.
This broker's server runs on the New York close: UTC+3 while New York is on
daylight time, UTC+2 otherwise. Its own deal records show it
(`scripts/diagnose_clock_history.py`): +3.00h every week from 2026-07-16 to
2026-10-26, +2.00h from 2026-11-02 - the US switch on 1 Nov, not Europe's on
25 Oct. So every conversion labelled the other season's bars an hour off.

**What it did.**
- **Every `london_breakout` backtest tested a partly different strategy.** Its
  rules ARE hours (Asian range 00:00-07:00, breakouts 07:00-10:00 UTC). The
  runs made in summer (2026-08-30: -0.088R; 2026-09-16: v1 -0.060R, crosses
  -0.132R, wide -0.052R) moved the winter months - about a third of the history
  - an hour early. The 2026-11-03 run, made in winter, moved the summer months -
  about two thirds - an hour late. That is why it found 1,895 trades where the
  September run found 1,070 on the same code. Strategies that read only bar
  sequences (EMAs, channels, ADX) are barely touched; session strategies are not.
- **The 2026-11-03 autopsy recompute measured the hour before each pre-switch
  trade.** The 13-Oct GBPJPY live short read "+3.1R best". On the real minute
  bars it peaked at +0.94R (bid) - under the +1R that moves a stop to entry, so
  the live engine was right to leave it, and the two demo trades on the same
  setup moved theirs only because their entries put +1R closer. No stop-
  management fault; a measurement one.
- **The live engine and the demo lab were never affected:** they convert recent
  bars with the offset measured now, which is right for recent bars, and every
  signal and trade timestamp comes from the VPS clock (within 0.4s of the
  database's).

**The fix.** `MarketDataProvider.get_history()` stamps each bar with the offset
in force when it formed (`mt5_time.server_epoch_to_utc_ny_close`), after
checking that the New-York-close rule agrees with the offset measured now -
refusing otherwise. The backtest, the engine's trade autopsy and the backfill
read history through it; the backtest stops before running if the rule and the
clock disagree. `scripts/test_clock_history.py` (17/17) replays the broker's 17
measured weeks, 2023-2027's switch dates, and the real 13-Oct GBPJPY bars.

**What it voids.** The 2026-11-03 filter test (below) and its -0.092R headline:
a broken measurement, not a result - the test is re-run ONCE on corrected
hours, same criteria. Every earlier london-breakout backtest figure in this log
was measured on partly shifted sessions and should be read as such until the
corrected re-run replaces it. The managed-vs-fixed stop comparison still stands:
it scores the same trades both ways. **Re-run 2026-11-04** (the entry above):
`london_breakout_v1` -0.074R over 1,302, both filters fail. The retired London
variants (crosses, wide) were not re-run; their figures stay shifted.

**The autopsy, recomputed 2026-11-04** on per-bar offsets: 950 demo and 27 live
trades. The 13-Oct GBPJPY live short now reads "full stop, best was +0.9R", and
the two demo trades on that setup "stop at entry, best +1.6R / +1.5R". Full
stops claiming a best beyond +1.2R - impossible when the stop moves at +1R -
are down to 10 of 702 stop and scratch exits, none since September: mostly
July-August, where minute history no longer reaches and 5-minute bars stand in.

## 2026-11-03 - Pre-registered: two filters for `london_breakout_v1`, tested once

Written before the backtest that tests them has been run.

**Where they come from.** Slicing the demo lab's london breakout trades
(`london_breakout_v1` plus `london_breakout_wide_v1`, one count per setup: 115
trades) and the live account's fee records turned up two patterns, each with a
mechanism behind it:

| Hypothesis | Demo evidence | Mechanism |
|---|---|---|
| **H1 - first London hour.** Breakouts on the bar that opens 07:00 UTC beat later ones | 07:00 +0.144R (51), 08:00 -0.130R (25), 09:00 -0.224R (22), 10:00 +0.045R (16) | the premise itself: the Asian coil releases at the open; a break hours later is more often a false one |
| **H2 - cheap trades.** Trades whose commission is under 8% of the risk beat the rest | < 0.08R +0.185R (38), 0.08-0.12R -0.319R (29), >= 0.12R -0.232R (22) | a fixed per-lot fee eats more of R when the stop is tight - EURGBP's ~4.6-pip stop is the extreme (-0.365R over 26) |

Slicing 115 trades five ways guarantees some slice looks good by chance, so these
are hypotheses, not findings. They get ONE test each, here, on data they did not
come from.

**The test.** `scripts/backtest.py london_breakout_v1`: 16 symbols, up to 12.7
years, stops managed as the engine manages them (the 2026-10-12 fix), run once.
The breakdowns it prints:
- H1: by the hour (UTC) the breakout bar opened - 07, 08, 09, 10.
- H2: by modelled commission ($7/lot round trip) as a share of the trade's risk -
  the same quantity the demo measured (spread excluded) - split at 0.08R.

**Pass criteria, fixed now.** A rule passes only if the trades it keeps have a net
expectancy whose 95% CI lies entirely above zero AND is positive in both
chronological halves. Judged three ways: H1 alone ("07:00 bar only"), H2 alone
("commission < 0.08R only"), and both together. Anything less is a fail, recorded
here and not adjusted: no other hour, no other threshold, no second look.

**What a pass would and would not mean.** A pass makes ONE rule a candidate for the
demo lab, not for live - the demo then has to confirm it on trades it has not
seen. A fail says the demo pattern was the noise five slices of 115 trades produce.

**Prediction.** H2's gradient is partly mechanical: net R is gross minus cost, so
cheaper trades net more by construction. Whether what survives is a positive
edge is the open question, and against a whole-strategy result of -0.060R
(gross +0.018R) I expect neither rule to clear the CI bar on its own. H1 is the
better bet, because it is the strategy's own premise rather than an accident of
cost.

**First run, 2026-11-03 - VOID: run on mislabelled hours (see the entry above).**
Kept for the record; NOT a verdict. 1,895 trades,
2023-07-07 to 2026-11-03, managed stops, net R:

| Rule | Trades | Net | 95% CI | Halves |
|---|---|---|---|---|
| H1: 07:00 bar only | 773 | -0.150R | [-0.227, -0.072] | -0.250 / -0.051 |
| H2: commission < 0.08R only | 1,331 | -0.039R | [-0.099, +0.022] | -0.085 / +0.007 |
| H1 + H2 | 519 | -0.109R | [-0.205, -0.010] | -0.256 / +0.038 |
| every trade | 1,895 | -0.092R | [-0.144, -0.041] | -0.123 / -0.060 |

By hour: 07:00 -0.150R (773), 08:00 -0.025R (512), 09:00 -0.128R (344), 10:00
-0.003R (266). By commission: < 0.08R -0.039R (1,331), 0.08-0.12R -0.221R (492),
>= 0.12R -0.179R (72). H1's premise is contradicted outright (the first hour is
the WORST); H2's gradient appears, as the cost model guarantees, and stops short
of an edge.

Why on hold rather than final: reading the same day's autopsy recompute exposed
that every bar time is converted to UTC with ONE offset - the one measured at
run time. If this broker's server clock switches between summer and winter
time, this run labelled one half of its history an hour off, which voids H1 and
shifts the London session the backtest simulated for those months. It also
fits an unexplained fact: this run produced 1,895 trades where the 2026-09-16
run (in summer) produced 1,070. `scripts/diagnose_clock_history.py` reads the
broker's offset history from its own deal records. If the offset never changed,
these results stand as recorded. If it did, the labels get fixed and the test is
run ONCE more with the same criteria - a repaired measurement, not a second
look. **It did** (+3h to 26 Oct, +2h from 2 Nov): void.

**Corrected run, 2026-11-04 - the verdict: all three FAIL.** Same code, same
criteria, each bar on the clock in force when it formed. 1,302 trades,
2023-07-24 to 2026-11-03, managed stops, net R:

| Rule | Trades | Net | 95% CI | Halves | |
|---|---|---|---|---|---|
| H1: 07:00 bar only | 584 | -0.084R | [-0.173, +0.006] | -0.137 / -0.031 | fail |
| H2: commission < 0.08R only | 966 | -0.036R | [-0.106, +0.034] | -0.055 / -0.017 | fail |
| H1 + H2 | 438 | -0.038R | [-0.142, +0.072] | -0.104 / +0.028 | fail |
| every trade | 1,302 | -0.074R | [-0.135, -0.013] | -0.080 / -0.068 | |

By hour: 07:00 -0.084R (584), 08:00 -0.109R (312), 09:00 -0.077R (232), 10:00
+0.024R (174, halves +0.147 / -0.098). By commission: < 0.08R -0.036R (966),
0.08-0.12R -0.198R (303), >= 0.12R -0.049R (33).

Against the prediction: neither rule cleared the bar, as expected, but H1 was
not the better bet. The first London hour does no better than the session as a
whole (-0.084R against -0.074R), so the premise H1 rested on is not in the data.
H2 came closer only for the reason the prediction gave - net is gross minus
cost, so the cheapest trades lose least - and even they lose. Recorded, not
adjusted: no other hour, no other threshold. The demo pattern was the noise
that five slices of 115 trades produce.

## 2026-11-03 - `london_breakout_wide_v1` retired

Its month-long demo test (2026-09-16 pre-registration, above) is over: **58
trades, -0.099R, CI [-0.395, +0.202]**, against `london_breakout_v1`'s +0.056R
over 78 on the same weeks. It did what its backtest said (-0.052R over 2,129):
about twice the trades, and the extra ones lose. Loosening the compression filter
buys frequency, not edge. Marked `retired = true` and removed from
`config/plugins.yaml`; still registered for backtests. Its open demo positions
close normally.

## 2026-10-12 - The backtest now manages stops like the engine. Prediction, before the run

Written before the corrected backtest has been run on real history.

**What was wrong.** The engine moves a stop to entry once a trade is +1R in
profit (`breakeven_at_r`), and trails it past +2R. `scripts/backtest.py` held
every stop fixed. So every backtest number in this log measured exits that no
live or demo trade has had. On demo, 9 of `london_breakout_v1`'s 63 trades (14%)
ended at a stop moved to entry - an outcome the backtest could not produce.
Found when a live CHFJPY short reached +1R, came back, and closed at entry.

**The fix.** `simulate_outcome()` now drives the engine's own
`DefaultExecutionEngine` bar by bar: the stop is managed once per H1 bar, after
the bar's worst price, and a bar that closes beyond the new stop exits there.
The fixed model is kept and printed beside it on the same signals, so the
results above stay comparable; it is identical to the old function on
20,000/20,000 random paths. `scripts/test_backtest_exits.py` pins both.

**This is a measurement fix, not a variant.** Nothing about any strategy or
the engine changes. It makes the screen describe what actually trades. Exit
variants (closing half at +1R, a stop at +0.5R, ...) are still barred by the
standing rule until a strategy passes its screen.

**What to expect from bar order alone.** On a no-edge random walk with a 1.5R
target, fixed scores -0.009R and managed -0.029R: the conservative bar order
(worst price first) costs the managed model ~0.02R by itself. In continuous
time a stop moved on a no-edge path changes nothing in expectation, so ~-0.02R
is the noise line. A gap far from it means the price paths after +1R are not
random.

**Prediction for `london_breakout_v1`** (last fixed run: -0.060R over 1,070):
- the same signals, so the same trade count under both models;
- 10-20% of trades end at the moved stop (demo 14%, random walk 19%);
- managed expectancy = fixed - 0.02R, within +/-0.03R;
- fewer full losses and a smaller max drawdown under managed;
- the verdict does not change: no edge, CI not above zero.

If managed comes in clearly above fixed - 0.02R, prices tend to fall back after
+1R and the move to entry is worth keeping. Clearly below, they tend to carry
on, and the move is costing winners. Either result is recorded here; neither
licenses tuning `breakeven_at_r` until the strategy itself passes.

**Result (run 2026-11-03 on the VPS, same signals both ways): every prediction
held.**

| Prediction | Result |
|---|---|
| same trade count under both models | 1,895 and 1,895 |
| 10-20% of trades end at the moved stop | 14.4% (272) |
| managed = fixed - 0.02R, +/- 0.03R | -0.092R vs -0.090R: **-0.002R** |
| fewer full losses, smaller max drawdown | 972 vs 1,134 losses; 200.4R vs 203.7R |
| no edge either way | net CI [-0.144, -0.041] managed, [-0.145, -0.035] fixed |

The move to entry at +1R neither helps nor hurts this strategy: it trades full
losses for scratches and some winners for scratches in roughly equal measure,
as a stop moved on a path with no memory should. Nothing to tune, and nothing
to remove. The managed model is now the headline for every backtest.

This comparison held whatever the clock turned out to be (the same trades are
scored both ways), and the corrected-hours re-run (2026-11-04) repeats it:
managed -0.074R vs fixed -0.077R (+0.003R), 202 of 1,302 trades (15.5%) at the
moved stop, 655 vs 778 full losses, drawdown 121.0R vs 128.6R.

## 2026-09-16 - Pre-registered: two `london_breakout_v1` extensions, demo only

Written before either strategy produced a single trade or a backtest.

**Why.** The owner wants `london_breakout_v1` to trade more often without
trading riskier. It averages ~1.1 trades a day and fired nothing from 09-14 to
09-16. Both extensions run on the demo lab only. Plugins load on both engines,
but a new strategy is linked to the live account with `enabled=false`, so guard
3 blocks them there. `london_breakout_v1` itself is unchanged: 0 differences in
226,573 evaluations on stored candles, before vs after the refactor that made
the limit overridable.

Each extension moves exactly one thing, so a result can be pinned on it.

| Strategy | Changes | Keeps |
|---|---|---|
| `london_breakout_crosses_v1` | pairs: EURCHF, GBPCHF, EURCAD, GBPCAD, CADCHF | everything, including 1.5x |
| `london_breakout_wide_v1` | compression limit 1.75x instead of 1.5x | the 16 symbols, everything else |

**What the choices were based on: frequency only, no outcomes.** Over 28 clean
demo days, the 1.5x check passed on 9.2% of symbol-days. EURGBP passed on 9 days,
GBPUSD 8, EURUSD 5, USDCAD 4 and USDCHF 3; AUDUSD, EURAUD, USDJPY and XAUUSD
never passed. So the crosses are the remaining pairs whose two currencies are
both quiet in Asia; no AUD, NZD or JPY pair qualifies. The limit 1.75x doubles
the pass rate to 19.4% (2.0x would give 31.7%, 2.5x 58.5%).

**Honest status against the standing rule.** The crosses test qualifies: it is
the same mechanism aimed at unseen data, with pairs picked by a rule. The wide
test does not fully qualify. It loosens the mechanism's own filter, which makes
it a parameter variant. It is run at the owner's request on that understanding,
and is allowed only because it is ONE value, declared here, and never tuned.

**Predictions.**
- `london_breakout_crosses_v1`: 0.5-0.8 trades a day. Backtest expectancy no
  better than v1's -0.088R. Realised cost at or above v1's +0.100R, because
  crosses have wider spreads.
- `london_breakout_wide_v1`: about twice v1's trades. A replay on stored candles
  gave 138 fires against v1's 73, and every v1 fire was also a wide fire.
  Per-trade expectancy will be BELOW v1's, in the backtest and on demo, because
  the added setups come from less-compressed nights. The informative sample is
  the trades v1 did not take; read those, not the headline.

**Stop rules, fixed now.**
- If a backtest comes in below v1's -0.088R, that extension has failed its
  screen. Record it here; do not adjust it.
- No second value of the limit (2.0x, 2.25x ...). No dropping individual pairs
  or symbols by their results. Either move turns a test into a search.
- The READY bar is unchanged: 30 trades for `almost_ready`, 100 for `ready`.

**What the planned one-month demo (to ~2026-10-16) can and cannot show.** It can
show real trade frequency, realised cost per trade, and that both run correctly.
At the predicted rates that is ~40 trades for wide and ~15 for crosses, which is
too few to read an edge from: v1's own CI was 1.24R wide at 50 trades. Any
decision about live rests on the backtest and a larger demo sample, not the
month alone.

**Backtest results (2026-09-16, run on the VPS the same day as the demo launch).**
v1 was re-run alongside the two extensions so all three share one spread snapshot.
Net of costs:

| Strategy | Trades | Expectancy | 95% CI | Gross | Median cost | Halves |
|---|---|---|---|---|---|---|
| `london_breakout_v1` (re-run) | 1,070 | -0.060R | [-0.133, +0.015] | +0.018R | 0.074R | -0.057 / -0.063 |
| `london_breakout_wide_v1` | 2,129 | -0.052R | [-0.104, +0.000] | +0.032R | 0.074R | -0.078 / -0.026 |
| `london_breakout_crosses_v1` | 1,171 | **-0.132R** | **[-0.202, -0.060]** | -0.031R | 0.095R | -0.076 / **-0.189** |

- **Crosses: FAILED its screen.** -0.132R is below both v1's recorded -0.088R and
  the same-day -0.060R. The CI sits entirely below zero, the second half is worse
  than the first, and even the gross signal is negative, so no cost assumption
  rescues it. Its predictions held: no better than v1, and a higher cost (0.095R
  against 0.074R). By the stop rule above, it is not to be adjusted. **Retired
  2026-09-16** at the owner's instruction, before it placed a single demo trade.
- **Wide: passed its screen, and its per-trade prediction was WRONG.** Trade count
  came in at 2.0x v1's, as predicted. The per-trade result was not lower: -0.052R
  against v1's -0.060R. The added setups alone come to roughly 1,059 trades at
  -0.044R net and +0.046R gross, which is no worse than v1's own trades. The gap
  is well inside the noise, though, and the conclusion that matters is unchanged:
  **neither version has an edge after costs.** Loosening did not damage the
  strategy, and it did not create an edge either. More trades of a
  slightly-negative strategy means proportionally more expected loss.

**Demo review** is due ~2026-10-16.

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

### Realised execution cost, measured without a cost model

`risk_amount` is `|entry - stop| x value_per_lot x lots` - the loss a stop-out
produces if it fills exactly at the stop and costs nothing. So a stopped-out trade
should return exactly **-1.000R**, and whatever sits below that is spread +
commission + slippage, in R, with no model in the way. Over 417 identified
stop-outs (-1.6R <= R <= -0.85R, a band narrow enough to exclude gaps):

**median +0.060R, mean +0.082R per trade.**

| Strategy | n | Median realised cost |
|---|---|---|
| `london_breakout_v1` | 22 | **+0.100R** |
| `range_fade_v1` | 111 | +0.098R |
| `donchian_breakout_v1` | 141 | +0.066R |
| `range_fade_h4_v1` | 30 | +0.046R |
| `ema_trend_v1` | 6 | +0.030R |
| `donchian_trending_v1` | 107 | +0.013R |

On FX majors this runs 0.05-0.10R, which sits comfortably around the 0.066R the
backtest models for `range_fade_v1` at H1. **On the non-FX symbols it does not:**

| Symbol | Realised | Modelled | Ratio |
|---|---|---|---|
| IT40 | +0.002R | 0.099R | 43x |
| XPTUSD | +0.012R | 0.315R | 27x |
| XPDUSD | +0.021R | 0.357R | 17x |
| XAGUSD | +0.014R | 0.186R | 13x |
| MidDE50 | +0.016R | 0.148R | 9x |
| BTCUSD | +0.004R | 0.023R | 6x |
| XNGUSD | +0.019R | 0.070R | 4x |

**Two readings, and this data cannot separate them.**

1. *The model overstates cost on wide-stop instruments.* Consistent with the
   hyperbola already recorded here (`cost = commission / (risk x value)` explodes
   as the stop shrinks) and with `diagnose_costs.py` existing at all. If so, the
   trending-asset verdicts were judged against an inflated toll.
2. *The demo account does not charge live commission.* Then this measures spread
   alone, live cost is higher by the commission term, and the FX agreement above
   is a coincidence of two errors.

**This does not reopen `donchian_trending_v1`.** Its realised cost was the lowest
in the lab (+0.013R) and its demo expectancy was still -0.324R with a CI entirely
below zero. Cheap execution did not save it; the signal is simply bad. The
retirement stands on live results, not on modelled costs.

**What it does change is how `london_breakout_v1` should be read.** It carries the
*highest* realised cost of any strategy at +0.100R, and its +0.137R demo
expectancy is already net of that - so its gross is ~+0.237R and costs eat 42% of
it. Adding a live commission term of ~0.05R would take it to ~+0.087R; a term
matching $7/lot round-turn on its typical stop would erase it. Which of those is
true is not knowable from demo fills, and is the single most useful thing a small
live account could measure.

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

Three more were retired on **2026-09-16**, and all five retired strategies were
removed from `config/plugins.yaml`. They are still in `engine/registry.py`, so
`scripts/backtest.py` can re-run any of them, and their trades stay in the
database. Neither position management nor reconciliation depends on that list,
so their open demo positions still close normally.

| Strategy | Demo at retirement | Backtest | Why |
|---|---|---|---|
| `range_fade_v1` | 271 trades, -0.144R, CI [-0.278, -0.008], drawdown 54.8R | net CI entirely below zero | both CIs below zero, the donchian standard |
| `range_fade_h4_v1` | 76 trades, -0.200R, CI [-0.432, +0.048], drawdown 21.5R | CI [-0.074, -0.010] over 5,715 trades | a 12.7-year negative backtest that 76 demo trades cannot overturn, and a demo drawdown past the 15R limit. Its demo CI does NOT yet sit entirely below zero, so this rests on the backtest |
| `london_breakout_crosses_v1` | 0 trades | -0.132R, CI [-0.202, -0.060] | failed its pre-registered screen |
| `london_breakout_wide_v1` (2026-11-03) | 58 trades, -0.099R, CI [-0.395, +0.202] | -0.052R over 2,129 | its month-long test ended as its backtest predicted: twice the trades, no edge |

`ema_trend_v1` was kept deliberately. It stands at -0.417R, but on 12 trades,
which is noise in either direction, and retiring on that would be judging a
coin by three flips. Retiring `range_fade_v1` also removes most of the AI
reviewer's remaining source of scoreable reviews (see above); that experiment
was already not converging.

## The strategies

| Strategy | Mechanism | Trades | Net expectancy | Verdict |
|---|---|---|---|---|
| `ema_trend_v1` | MA-crossover trend-following | 61 | ~0 | no edge (also far too rare to judge: ~19/yr) |
| `london_breakout_v1` | Compressed Asian range breaks at London open | 1,148 | −0.088R | **negative** |
| `range_fade_v1` | Mean reversion, ADX < 20 | 6,033 | −0.027R | zero (retired 2026-09-16: demo CI below zero) |
| `donchian_breakout_v1` | 20-bar price-channel momentum, FX | 15,024 | −0.090R | **negative** |
| `donchian_trending_v1` | Same logic, trending assets | 8,856 | −0.122R | **negative** |
| `range_fade_h4_v1` | Same logic as `range_fade_v1`, at H4 | 5,715 | −0.042R | **negative** (retired 2026-09-16) |
| `london_breakout_crosses_v1` | Same logic as `london_breakout_v1`, 5 EUR/GBP/CHF/CAD crosses | 1,171 | −0.132R | **negative** (CI entirely below zero; failed its pre-registered screen; retired 2026-09-16) |
| `london_breakout_wide_v1` | `london_breakout_v1` with a 1.75x compression limit | 2,129 | −0.052R | zero (v1 re-run same day: −0.060R over 1,070); retired 2026-11-03 after -0.099R over 58 demo trades |
| `trend_daily_v1` | Slow trend-following: daily close out of a 55-day range, 28 markets | 1,553 | −0.095R | **negative** (CI entirely below zero; gross +0.008R; failed its pre-registered test 2026-11-13; never in the lab) |

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
- **Execution cost is paid at ENTRY too, and the stop-out method cannot see it.**
  The realised-cost table above measures what a stop-out gives up beyond
  -1.000R. That captures the exit only. Comparing each fill against the price
  its own signal asked for (`signals.entry_price` vs `trades.entry_price`,
  scaled by intended risk) measures the entry, and the two disagree sharply:

  | Symbol | Entry slippage (median) | Stop-out cost | 
  |---|---|---|
  | XPDUSD | **+0.358R** | - |
  | XPTUSD | **+0.189R** | - |
  | MidDE50 | +0.128R | - |
  | IT40 | +0.074R | - |
  | FX majors | +0.000 to +0.023R | - |

  `donchian_trending_v1` was recorded above as having *the lowest* realised cost
  in the lab (+0.013R) and the note concluded "cheap execution did not save it".
  The premise was wrong: its execution was the most expensive, at a median
  +0.066R and mean +0.104R given up before the trade even started, on
  instruments where the entry alone can cost a third of the risk budget. The
  retirement verdict is unchanged - -0.324R with a CI entirely below zero is not
  rescued by any cost story - but **the cost table understates wide-stop
  instruments, and any future test on them must measure entry slippage too.**
  Fill latency is not the cause: median 0.4s from signal row to open position.

- **The broker's daily rollover is the single most expensive minute to trade.**
  Grouping every fill by the UTC hour of its signal, entries in the 21:00 block
  (00:00-00:01 *server* time, the day boundary) gave up a median **+0.709R** of
  intended risk, against **+0.015R** in every other hour - a 47x difference,
  n=5. Realised P&L over those five is noise and is not the argument; the cost
  is mechanical and certain, and it exceeds every edge in this log.
  **Fixed** in `DefaultRiskEngine`: entries are refused within 10 minutes of the
  broker's midnight, read from the broker's own clock rather than a fixed UTC
  hour, because rollover moves with DST. It applies to the demo lab as well as
  live - it is an execution-cost rule, not capital protection, and the criterion
  is the clock rather than the outcome, so it censors nothing.

- **A wrong clock is the quietest way to invalidate a result.** MT5 reports every
  timestamp in the broker's server time, and the engine measured the UTC offset
  as `last tick - now`. That is only the offset if the tick is *current*. The
  demo engine restarted on Sunday 2026-09-06, measured against a 31-hour-old
  tick, and spent three days stamping bars **31 hours** into the future - 7
  hours once reduced mod 24, which moved `london_breakout_v1`'s 07:00-11:00 UTC
  window to **00:00-04:00**, so the lab
  traded the *Asian session* while labelling it the London open. It also wrote
  future-dated rows into `candles`. Nothing errored; every log line looked
  ordinary. Found only by pairing the live engine's evaluations against the
  demo's and noticing they disagreed about what hour it was.
  **Affected data.** A day-level flag over the drifted days is too coarse: what
  matters is whether a trade opened inside the window its strategy declares.
  Checked that way - a bar labelled hour H closes at H+1, so `london_breakout_v1`'s
  bar hours 07-10 admit opens at 08:00-11:00 UTC - exactly **one** of its 51 demo
  trades is inadmissible: `2026-09-09 01:00 EURUSD, +1.78R`, fired while the demo
  believed 01:00 was the London open.

  One trade, but it was a large winner on a 51-trade sample: it moved the headline
  from **+0.1260R (n=50)** to **+0.1585R (n=51)** - **20% of the measured edge,
  from a setup the strategy would never have taken.** The live engine, whose clock
  was correct, declined the same signal at the same second: "outside the
  London-open trigger window (bar hour 00:00 UTC)". That pairing is what proves
  the trade was spurious rather than lucky. Exclude it from the 100-trade
  verdict. The live account was unaffected throughout.
  **Fixed** by establishing tick freshness before measuring, refusing rather
  than falling back to 0.0 (which was itself a 3-hour error), and re-measuring
  periodically; `scripts/check_engine_health.py` now reports drift directly.
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

## Candidates rejected before any code (2026-09-16)

Looking for a replacement for the retired strategies, the two best-documented
mechanisms not yet tried were checked against the literature first. Both failed
the check, so neither was built.

- **The overnight drift.** Boyarchenko, Larsen & Whelan (NY Fed Staff Report 917;
  RFS 2023) found that US equity index futures earned their largest returns
  between 2 and 3 a.m. ET, as European markets open: ~3.6% annualised over
  1998-2019, strongest after US-session selloffs, explained by dealer inventory
  risk. It was structural, specific and intraday (no swap). But the same authors'
  follow-up, "The Disappearing Overnight Drift" (Liberty Street Economics, July
  2026), reports that the window has **averaged close to zero since 2021**. Dead
  after publication.
- **Daily reversal in US equity indices** (the "buy the short-term dip" family,
  e.g. RSI(2)). arXiv 2606.29591 (2026) finds SPY's lag-1 autocorrelation (-0.081,
  z = -7.4) is **driven by magnitude, not direction**: the sign test gives p = 0.11,
  consistent with bid-ask bounce and stale constituent prices. That is a
  measurement artefact, not a tradeable direction, and a CFD priced off futures
  lacks the stale-constituent part entirely. Its one directional result (lag 3,
  p = 0.02) is a single test among many. Blog backtests showing high win rates on
  SPY do not survive that decomposition.

**The lesson for the next search:** a published anomaly is the most likely kind
to have been traded away. Before building one, look for the authors' own
follow-up and for a sign-versus-magnitude decomposition.

## Candidates rejected before any code (2026-11-14): information that is not price

The owner asked for one idea built on a different KIND of information than
price patterns, tested like `trend_daily_v1`. Four were weighed; none was built.

- **The pick: the turn-of-the-month effect in stock indices** - hold the last
  trading day of a month and the first three of the next. Chosen because the
  information is the calendar, the mechanism is real (month-end pension and
  salary flows), it needs no outside data, and index CFDs carry no commission.
  Rejected on the literature check this log requires, and on arithmetic:
  - Han, Han & Tian, "The disappearing turn-of-month effect" (*Finance Research
    Letters* 71, 2025): once highly significant, it disappears entirely after
    2001, which they put down to cheaper trading letting it be arbitraged. A
    2025 practitioner re-test on ~30 ETFs agrees for the classic window: no
    significant effect in US equities in recent data.
  - The test could not have seen it anyway. Real intraday index history here
    starts in 2016: ~131 month-ends, and the six indices move together, so that
    is ~131 observations, not 786. Against a same-length mid-month control, a
    difference under roughly 0.4% a month would not clear a 95% interval (my
    estimate, from ~1.8% for a four-day index move) - and this broker's
    financing takes ~0.13% of each five-night hold first.
- **Interest-rate differences (carry).** The broker keeps most of it: on today's
  swap table only the yen and franc pairs pay the holder more than ~1.5% a year
  (USDJPY, GBPJPY, AUDJPY, USDCHF), and GBPUSD and GBPAUD charge both sides. A
  test of "hold what pays" is therefore one or two bets - short the yen, short
  the franc - repeated monthly, and a bootstrap would read one macro regime as
  hundreds of independent trades. It also needs rate history from outside, and
  an engine that can hold and rebalance, which this one cannot.
- **Trader positioning (the weekly CFTC reports).** Two opposite readings are
  both defended - extremes reverse, extremes continue - so choosing one after
  seeing the data is the search this log forbids, and the thresholds are free
  knobs. Needs outside data and a new provider.
- **News surprises (result against forecast).** No usable history of forecasts
  is available to test on, and the trade is at the moment spreads are widest -
  the fast, expensive kind this log has already measured to lose.

**What this adds to the lesson above:** the binding limits here are not ideas
but (1) how few independent observations ten years of one broker's history
holds for anything slower than hourly, and (2) what the broker charges to hold
a position overnight. An idea has to clear both before it is worth code.

## What has NOT been tested

- **Slow momentum - now tested once (2026-11-13, `trend_daily_v1`): fail.**
  That was a 55-day breakout on this broker's CFDs. It is not the literature's
  12-month return-sign rule in futures, which stays untested here - and the
  financing this broker charges on a position held for weeks (0.09R a trade,
  most of it on stock indices) would be charged on that too.
- **Non-price edges** (carry, positioning, fundamentals). Different data, not a
  different indicator.

## The standing rule

Do not respond to these results by generating more strategy variants until one
passes. Across 48+ tests we found fewer "significant" results than chance
predicts; mining harder finds noise, and that false positive is the one that
would take real money. New tests need a *prior mechanism* and a prediction about
unseen data - the standard `donchian_trending_v1` met, and failed honestly.
