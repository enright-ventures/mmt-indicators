## Delta Heat: real-time current candle (2026-10-22)

The live ladder was rebuilt only at each minute close from MMT's one-minute snapshots, so the current candle lagged by up to a minute and appeared up to a minute after loading. MMT has no forming volume profile, so the minute in progress now comes from live trades (history 0s, Binance/Bybit/OKX or the chart venue), bucketed on the ladder's row grid, kept for the two most recent minutes and dropped once that minute's snapshot exists, so no minute is counted twice. Redraws happen on trades, at most once a second, and at each minute close.

Live MMT (BTC/USD 30m): the test copy drew 8 s after being added and redrew about once a second. On a settled tab, over two bars, every completed minute's snapshot was found plus the live minute ("live ladder in real time"). An earlier run on a tab that had just been reloaded several times found minutes 1-8 of the bar missing; a probe later found all 1,440 one-minute snapshots of the preceding 24 hours present, including those minutes. So MMT's one-minute history can arrive a few minutes short of the live stream right after a reload and does not refill in that session; the title reports the shortfall until the bar closes. Filling it would mean loading recent trade history again, which was not done. Three tests cover the live minute, the snapshot handover without double counting, and the once-a-second limit.

## Offside: volume profiles instead of trades (2026-10-22)

Offside loaded 12 hours of individual trades (about 1 million on BTC across three perps) to measure a few dozen 5m bars a day; cold starts took 6 to 14 minutes and coincided with MMT's script-memory errors. A cold-load test showed the time is the first download of trade history: a different size minimum loaded in 15 s once the trades were cached, so raising the minimum would not have helped. Trades of $5,000+ were 96% of Binance's loaded volume, 93% of OKX's and 86% of Bybit's.

A probe of MMT's 5m volume profiles on BTC (Binance + Bybit + OKX, combined by MMT) found 4,761 snapshots (about 16.5 days), every one aligned with its 5m bar, no gaps, $2.50 price bins, and profile volume equal to the venues' summed candle volume (ratio 1.0001). Offside now measures pressed, average fill and reclaim volume from these profiles, cut at the level with `from`/`to`; the trade subscriptions, size and dollar minimums, per-venue coverage reconciliation and the large-print share are removed. On the live chart the profile version reached the live bar in 8 seconds with the same traps as the trade version, and measured a trap from 18 October that was outside the old 12-hour trade window. Tests: 50 pass; trade-only tests (coverage, minimums, venue reconciliation) were removed with the code they covered, and new tests cover a missing or misaligned profile and volume at the level's own price.

PR #5 review follow-up: the first version bounded each profile read by the chart venue's candle (p5 low/high) and averaged bucket midpoints. Pooled venues can trade outside the chart candle (review case: 101 pressed reported as 1), and a bucket midpoint can sit on the wrong side of the level (review case: support 100.5, all selling at 100, reported average 101.25). Offside now reads the native profile levels (`levels()`), classifies each by its own price against the level with no outer bound, and weights the average by those prices. Three new tests (pooled volume outside the chart candle, both directions; a level inside a $2.50 bin) fail on 3ddea1c and pass now; the harness stub implements `bucketsByStep` as documented (range selection, then a whole-multiple grid) so the old code could be exercised. 53 tests pass.

## Other indicators review fixes (2026-10-21)

A second review of 8940957 covered the other indicators. Each fix has a test in `tests/test_other_indicators.py`, which runs the production blocks through a generic Node harness (`tests/m5_script_harness.cjs`) with stubbed feeds; all six tests fail on the old scripts (the two Rolling VWAP tests because their helpers are new):

- Calendar VWAP picked the live bar's periods from `chart.time` (the last confirmed bar), so at Monday 00:00 UTC the new week's first forming candle was added to the old week (the review's case: mean 150 instead of 100). The live bar now uses the forming candle's time; the forming candle counts only inside [start, end) of the period; and at the live edge a venue whose forming candle is missing or stale withholds the developing period instead of showing the old accumulator.
- Rolling VWAP counted candles, not time: 335 hourly candles passed as a 7-day window. Each venue now tracks its run of consecutive candles; a window shows only once the run covers it, the live forming candle must follow the last closed one, and pooled venues must end on the same candle. After a real exchange gap a line stays hidden until a full gap-free window has built up.
- Delta Heat's live ladder stopped at the first missing minute snapshot and drew only the later minutes. Missing minutes are now skipped, earlier minutes kept, and the title shows the shortfall ("live ladder: 28 of 30 minutes").
- Bar Stats' live alignment is fixed in the Offside review fixes below.
- Calendar VWAP's +/-1 standard deviation bands are renamed from VAH/VAL to +1SD/-1SD (ASCII in the scripts; the guide writes ±1σ), as are Offside's optional VWAP trap levels, so they are not confused with Composites' TPO value areas.
- The older stand-alone scripts (Positioning NL/NS, OI Delta, Value Area Levels, Delta Footprint) are removed from the repo: they are not on the Swordfish v2 workspace and their roles are covered by Bar Stats, MMT's Open Interest pane, Composites/Calendar VWAP and Delta Heat. Their review findings were therefore not fixed.

PR #4 review follow-up: continuity alone let a feed that stopped advancing, or both venues together, pass (a Bybit pair 150 minutes behind still pooled; frozen venues still plotted 7D). Calendar and Rolling VWAP now subscribe to a live one-minute clock; on the live bar every selected venue's forming candle must be the source candle containing now (the later of the clock and the chart's forming bar). Four new tests (lagging venue, frozen single venue, jointly frozen venues, stale single venue) fail on a53b547 and pass now. Limitation: if the chart's own market also stops updating, there is no independent clock to compare against.

Full suite: 67 passed. MMT `script_check` passes for Calendar VWAP, Rolling VWAP, Delta Heat and Offside.

## Offside review fixes (2026-10-21)

A review of commit 8940957 reproduced five issues; each now has a production-harness regression test that fails on the old code (the live-export readiness check did not exist before):

1. Live flow exports and Bar Stats summed venues without checking that each forming candle and the open interest were on the current bar. Both now require every selected, listed venue and OI on the bar, plot or show nothing otherwise, and gate liquidations separately. Bar Stats' shading scale learns only from complete bars.
2. A missing 5m bar compressed the reclaim deadline and the hold. A gap now drops any break or hold in progress and ends tracked traps; no break is read on the first bar after it. The Python reference engine applies the same rule (two new tests).
3. The 1% pooled allowance could exceed a small venue's whole volume, so an absent venue passed. A venue or side with candle volume must now have supplied trades, and its allowance is capped at half its own volume.
4. A row's buys and sells were placed by their combined average price, so opposite-side aggression could move trades across the level (the review's case: 101 reported pressed, 1 actual). Each side is now placed by its own average price; only same-side trades within one 0.01% row of the level remain ambiguous.
5. The +L/+S flow-weighted prices carried weights across data gaps although the docs said they reset. A missing chart bar or an unready bar now resets them.

Also: prices in Offside's table, corner panel, captions and flow-price labels use decimals for their size (low-priced coins read 0 before), coverage shows one decimal, and an unknown liquidation total shows as n/a. Full suite: 56 passed. MMT `script_check` passes for Offside and Bar Stats. The review's interpretation points stand: traps are a price-pattern hypothesis with measured aggression, not identified trapped inventory, and the recorded backtest covers the price pattern only, not the trade features.

## Offside trade-layer review fixes (2026-10-15)

Price tracking now ends only on price invalidation or the tracking deadline. Counterflow is displayed in coins as a proxy and cannot identify an unwind. Pressed volume covers broken bars through the reclaim close; reclaim volume starts at the successful reclaim and continues through its hold. Failed reclaim attempts reset reclaim volume.

Trade readings require unfiltered buy and sell totals to reconcile separately against every selected, listed venue's aligned 5m candle, within one part per million or 1e-8 coins. Partial starts, missing venues, side mismatches, bucket overflow and discarded late prints withhold the entire trap's trade readings. The most recent measurement survives a trade-bar rollover before the candle-close handler.

- Full regression suite: **39 passed**, including the calendar test and 21 new Offside cases. Run `uv run --with pytest --with numpy --with polars pytest -q` with Python 3.11+ and Node.js 18+.
- The new Node harness translates the production M5 tape helpers and 5m close handler into their shared JavaScript subset and supplies synthetic feeds. Cases cover both directions, failed reclaim attempts, hold accounting, complete selected venues, missing or misaligned coverage, pooled totals hiding per-venue errors, rollover, overflow, counterflow with zero/nonzero break proxies, and price/time termination.
- `git diff --check` passes. MMT `script_check`, live feed scheduling, trade/candle unit compatibility, chart rendering, and cold-start performance have **not** been verified for this revision. The harness is not an M5 compiler or an MMT runtime.
- Follow-up after a live MMT run (BTC/USD, 24h, 5.97M trades, cold load about 6.5 min): per-venue exact matching passed only 151 of 292 bars. Pooled over four venues, trades were at least 99.9% of candle volume on 175 bars, 98-99.9% on 64, 95-98% on 29, and below 95% on 24 (mostly bars missing a measurement). Bybit's trade feed ran about 95% of its candle and Hyperliquid failed most often. Coverage now allows 10% per venue (setting) or 1% of pooled volume, reports the trap's covered share, and Hyperliquid was removed (Binance, Bybit, OKX). 43 tests pass, including tolerance and small-venue cases; MMT `script_check` passes.
- All prints are now requested to make volume reconciliation possible. The earlier filtered-tape loading times and example trap measurements do not validate this revision. A feed mismatch conservatively withholds readings; this change does not retry completed bars when trades arrive late. No exchange backtest was rerun.

> Review correction (2026-10-15): the results below are historical records, not validation of the revised indicators. The 21-month swing study used two-sided levels and excluded reclaim-bar flow; the current detector uses fixed-side swings and includes that bar. Run offside_traps_htf.py for the separately labelled current fixed-side report, using the same engine as offside_traps_mmt_replica.py. NL/NS, entry and unwind terminology in old records refers to flow proxies, not measured positions. Weekly calendar keys now start Monday. Rolling windows now include the forming candle within (not beyond) the stated candle count, so the old rolling comparison must be rerun.

## Review-fix verification (2026-10-15)

- 18 regression tests pass: quote mapping, empty/partial/failed watchlist replacement and recovery snapshots, retained markets, fixed-side traps, reclaim-bar flow, missing flow, invalidation/expiry, and Monday week boundaries.
- MMT `script_check` returned `{"status":"ok","errors":[]}` for the changed indicators: Offside, Bar Stats, Positioning NL/NS (since removed from the repo), Rolling VWAP and Delta Heat.
- Changed Python files compile; `git diff --check` passes. Basedpyright on the new engine, importer and tests reports zero errors and 176 warnings, chiefly dynamic/untyped JSON and legacy helper interfaces; this is not a clean type-check gate.
- Runtime charts were not updated. Compiler checks do not establish live feed synchronization, subscription performance or visual rendering. Watchlist tests use a stateful fake service and do not mutate a real watchlist. Rolling exchange comparisons have not been rerun for the revised window.

Run regression checks from the repository root:

```sh
uv run --with pytest --with numpy --with polars pytest -q
```

### Corrected fixed-side swing run

Ran the current `offside_fixed.find_traps` engine using the cached 187,488 Binance BTCUSDT 5m bars, 4h swings (three bars on each side), 14-day expiry and default MMT pattern settings. The report contains 266 events. The split remains 2025-12-01.

| Pattern | Events | 1R mean, all | First half | Second half | 2h mean return (bp), all |
|---|---:|---:|---:|---:|---:|
| Failed breakdown | 138 | +0.06 | +0.02 (71) | +0.11 (67) | +8.0 |
| Failed breakout | 128 | +0.09 | +0.07 (64) | +0.11 (64) | +4.0 |

These are gross simulated outcomes using the existing stop/target evaluator, without fees or slippage. They are not measured participant positions and do not establish a tradable edge. Raw exchange candles can differ from MMT. The full optional-level comparison was not rerun. To reproduce the current swing section with data under `validation/data/offside/`, run `python validation/offside_traps_htf.py`; it labels the fixed-side report separately from legacy two-sided comparisons.

# Swordfish wrun ports: validation record (2026-10-07)

Market: Binance Futures ETHUSDT. Reference data: Binance USD-M klines (`python3 composites_ref.py fetch`, `python3 vwap_ref.py fetch`).

## Composites (`wrun/swordfish-composites.ts`)

| Check | Result |
| --- | --- |
| Native 30m candles vs the kScript's paired 15m brackets | 5,759 brackets, 0 high/low differences; Daily composites identical |
| kScript method vs trading-suite/swordfish engine (`resolve_tpo_distribution`, `value_area_overlap_ratio`, ingest state machine) | every closed period's POC/VAH/VAL identical; composite runs identical (Daily and Weekly, floor and nearest binning) |
| wrun port vs Python port of the kScript, Daily rolling 30d | 7 of 7 composites identical (dates, members, VAH, POC, VAL) |
| wrun port vs Python port of the kScript, Weekly rolling 13w | 3 of 3 composites identical |
| wrun port vs the running kScript (hover tooltips, same chart) | 3D 04/10-06/10 VAH 2717 / POC 2696; 8D 24/09-01/10 POC 2687: identical |

Known difference from the swordfish engine (not from the kScript): the kScript and the port bin prices into
floor rows (`[r*step, (r+1)*step)`); the swordfish engine rounds to the nearest row (`ROUND_HALF_UP`). With 0.05% rows
on ETHUSDT this changes the daily composite count (7 floor vs 6 nearest over the same 30 days). The port's
"Price to row" setting selects either. Per the trading-suite records the method was never confirmed against a
reference chart (C2M level ground truth: 0 of 80 levels matched); "authenticated" there refers to the course text.

## Calendar VWAP (`wrun/swordfish-calendar-vwap.ts`)

| Check | Result |
| --- | --- |
| wrun port vs Python (Binance REST), 30m-sourced periods | pW, pM, 3 older weeks, Aug: identical to 6 significant digits |
| wrun port vs Python, 4h-sourced periods and July | differ in the 4th-5th digit: OpenMarket's candles differ from Binance REST |
| wrun port vs the running kScript | pY VAH 3890.32 (= 2998.83 + 891.492) and pW VAL 2668.83: identical |
| History reach | 5,000-candle streams: 2024 PY unavailable (the kScript's 8,001 x 4h reached it) |
| 0.2.0 "Current levels for every shown unit" (off by default) | 4h, Monthly focus: current Y VAH 2574.93 vs the kScript's Yearly-focus Y VAH 2574.27 read earlier the same day (live data moved); Q current drawn |

## ATR + Day Range (`wrun/swordfish-atr-day-range.ts`)

| Check | Result |
| --- | --- |
| wrun port vs the running kScript table, 00:30 UTC | ATR(30m) 6.4326, Range/ATR 7.95%, avg vol 3.15M, quote 8.42B, yday@time 17.35K, vs yday -8.08%: identical; RVOL 0.52% vs 0.53% (read a minute apart while today's volume grew) |

## Indicator slots (OpenMarket plan limit, 10 per layout)

A kScript costs 1 slot whatever it requests. A wrun indicator costs one slot per distinct market and interval it
reads; a candle stream at the chart's own interval shares the chart's slot, and `view: "forming"` twins are free.
On a 30m chart: Composites 1, Calendar VWAP 2 (1 with "Quarterly/yearly source" set to 30m), ATR + Day Range 3.

## OpenMarket data defect: March 2024 volume (found 2026-10-07)

OpenMarket's ETHUSDT 1d and 12h candles for 1-31 March 2024 carry exactly 2x or 3x Binance's volume on every day
(1-6 and 26-27 March x3, the rest x2; prices match). Jul, Aug, Oct and Dec 2024 are 2-4% high. With "Quarterly/yearly
source" = 1d the 2024 yearly VWAP reads 3121.81 sd 506.38; Binance gives 3063.91 sd 502.34 (1d) and 3063.05 sd 507.24
(4h, the kScript method). The layout stays on 4h, where 2024 is out of reach (5,000 x 4h = about 833 days).

## MMT data probe (2026-10-14, Pro plan, scripts in mmt/)

`mmt/data-probe-2024.m5` (4h ETH perps per venue) and `mmt/data-probe-30m.m5`, run through the m5 MCP:

| Check | MMT | Exchange's own API |
| --- | --- | --- |
| Binance 2024 yearly VWAP (HLC3 x volume, 4h) | 3063.02 sd 507.24 | 3063.05 sd 507.24 |
| Binance March 2024 volume | 98.258M ETH | 98.25M |
| Bybit 2024 yearly VWAP | 3069.59 sd 506.73 | 3069.59 sd 506.73 |
| Bybit March 2024 volume | 26.684M | 26.684M |
| Binance + Bybit 2024 VWAP | 3064.63 sd 507.12 | |
| 4h candles in 2024 | 2,196 of 2,196 (Binance, Bybit) | |
| Earliest 4h candle returned | Binance and Bybit 2022-06-12; Hyperliquid 2025-03-29; OKX 2026-01-10 | |
| 30m reach (history: 50000 asked) | 29,998 bars from 2025-01-26, 0 gaps | OpenMarket wrun: 5,000 (about 104 days) |

## MMT Calendar VWAP port (`mmt/swordfish-calendar-vwap.m5`, MMT script "Swordfish Calendar VWAP", 2026-10-14)

ETH perps, Binance venue, Weekly focus on a 30m chart, read through `mmt/vwap-validate.m5` (the port plus plotted values):

| Period | MMT port | Binance REST (`vwap_ref.py` method) |
| --- | --- | --- |
| pW (week of 05/10/2026) | 2569.39 sd 94.072 | 2569.38 sd 94.072 |
| pM (September 2026) | 2556.26 sd 116.015 | 2556.22 sd 116.001 |
| pQ (Q3 2026) | 2176.77 sd 345.99 | 2176.75 sd 345.998 |
| pY (2025) | 2998.74 sd 891.531 | 2998.96 sd 891.493 |
| 2024 PY | 3063.02 sd 507.241 | 3063.05 sd 507.239 |
| Current week (developing) | 2509.94 sd 37.898 | 2509.95 sd 37.899 |

The 2025 difference is one candle: MMT's Binance 4h candle of 2025-10-10 20:00 UTC (the liquidation cascade) carries
5.32M ETH against Binance's 5.86M; every other 2025 month matches Binance's volume and VWAP to the cent
(`mmt/data-probe-2025-months.m5`, `mmt/data-probe-oct2025.m5`). MMT returns no candles for a combined
`markets.agg(...)` exchange, so the port pools venues itself.

## MMT Composites port (`mmt/swordfish-composites.m5`, MMT script "Swordfish Composites v2", 2026-10-14)

BTCUSDT perps (Binance), MMT 30m candles, read through `mmt/composites-validate.m5`, against `composites_ref.py`
(the kScript port) on Binance REST 30m candles with the same watermark (2026-10-13 22:30 UTC):

| Run | MMT port | Reference |
| --- | --- | --- |
| Daily, rolling 30 days, floor bins | row 50, calc from 13/09, 30 closed, 7 composites | identical: all 7 (dates, members, VAH, POC, VAL) |
| Weekly, rolling 13 weeks, floor bins | row 20, calc from 13/07, 13 closed, 4 composites | identical: all 4 |

Dan's earlier MMT port ("Swordfish Composites", rev 42, kept in `mmt/swordfish-composites-rev42.m5`) applies the same
merge rules but differs in three places that change results: nearest-row binning after tick rounding (the kScript
floors), row size from the first loaded close (BTC Daily: row 20 against the kScript's 50), and streaming over all
loaded history instead of rebuilding from the rolling or fixed calculation start. Not ported: manual merges/splits
(MMT settings have no text field).

## Swordfish Offside and Bar Stats liquidations (2026-10-15)

- MMT liquidation side: on 1m bars over 3,000 minutes (4-perp aggregate), buyLiq-weighted return -14.9 bp, sellLiq-weighted +15.6 bp, mean -0.01 bp. So buyLiq = longs liquidated, sellLiq = shorts liquidated. Units are coins (30m Binance values 0-300 BTC).
- Trapped-wick thresholds from the last 200 BTC 30m bars: wick >= 35% and wick net delta >= 3x the typical largest row gave about 2.4 markers a day; over 1,001 bars of snapshots, 24 trapped-long and 44 trapped-short markers. Liquidations: $2M was about the 90th percentile of bars.
- Forward 4-bar returns after markers in that 200-bar sample: trapped longs -19, +42, -28, +28, -60 bp; trapped shorts +3, +184, +29, +64, -84 bp. Too few to judge an edge.

## Trapped-marker backtest, one year (2026-10-15)

- Data: Binance BTCUSDT perp aggTrades from data.binance.vision, 2025-10-01 to 2026-10-13, rebuilt into 30m x $10 rows (offside_rows.py, outputs in data/offside/), regrouped to the script's step (per-month auto step). OI from Binance daily metrics (5m sum_open_interest).
- Cross-check: the script run in MMT with venue = binancef (21 days) vs the rebuild: trapped longs 20/20, trapped shorts 30/30 (2 more in MMT on 14 Oct, not yet published by Binance), wick dollars and ref identical.
- Result (offside_backtest.py, default thresholds): 390 trapped longs, 406 trapped shorts; 8-bar mean in trade direction -0.8 bp and -3.1 bp, |t| < 0.5; no better than wick-only controls; no wick/mult setting with |t| > 1.7; quarter signs flip. Liquidations untested (no Binance history).
- Fuel (offside_fuel.py): after 4 bars with trap unbroken, least-unwound tercile +7.7 bp over next 12 bars (t 0.9), most-unwound -5.0 bp (t -0.5).

## Binance + Bybit pooled VWAPs (2026-10-15)

- Rolling VWAP (pooled, rvwap_pooled_ref.py) at bar 1792036800: 7D 82,583.20 vs 82,583.29; 30D 82,809.70 vs 82,809.65; 365D 77,716.35 vs 77,710.91.
- Calendar VWAP weekly (pooled) at bar 1792038600: VWAP 82,736.90 vs 82,736.97; +1 SD 83,623.48 vs 83,623.54; -1 SD 81,850.33 vs 81,850.40.
- Built-in OI and delta_volume panes: dataSource {"mode": "venue_basket", "venueMarketIds": [1, 4, 5, 16]} = Binance, Bybit, OKX, Hyperliquid BTC perps. (2026-10-15: Hyperliquid removed everywhere; panes and scripts now use Binance, Bybit and OKX. Checks above that pooled four venues predate this.)

## Workshop-11 traps vs wick markers (2026-10-15)

offside_traps.py, Binance BTCUSDT perps 5m (data/offside/k5, Oct 2025 to 13 Oct 2026, 108,864 bars) with Binance 5m OI. Trap = level, 5m break by >= 0.03%, 5m close back within 60 min, 15-min hold (3 x 5m closes on the reclaimed side, flush extreme not taken); entry at the hold's last close, stop beyond the flush.
- 30m swing levels (most events): failed breakdowns n 389, +2h -0.6 bp; failed breakouts n 395, -3.6 bp. Noise, like the wick markers.
- 4h swing levels alone: trapped shorts n 78, +2h +14.8 bp (t 1.7), +4h +19.6 bp, 1R exp +0.13; trapped longs n 72, +30m +10.7 bp (t 2.1), 1R exp +0.12.
- All higher-timeframe levels (4h and daily swings, 3-day, prior day/week/month): trapped shorts n 136, 1R exp +0.11; trapped longs n 125, +0.03. Baseline 1R exp about 0.
- Reclaim volume >= break volume did not help; more new positions trapped helped a little on both sides (1R +0.11/+0.17 vs +0.12/-0.11). Nothing reaches t 2 over the year except the 4h-swing failed-breakout 30-min return.

## Traps at composite and VWAP levels (2026-10-15)

offside_traps_levels.py (two-sided levels, side set by the break; composites point in time via composites_ref.kscript_composites, newest 4) and offside_traps_holdout.py (thresholds from Oct 2025-Mar 2026, results Apr-Oct 2026).
- Daily composite VAH/VAL, failed breakdowns: all n 265, 1R +0.01; with new shorts trapped above median n 132, +2h +18.1 bp (t 3.1), 2R +0.30. Holdout second half, threshold 140 BTC from first half: n 67, +2h +14.9 bp (t 1.9), 1R +0.14, 2R +0.39. Failed breakouts at composites: negative in both halves.
- Weekly composite VAH/VAL n 24-28, daily composite POC, prior week VAH/VAL, developing weekly VWAP reclaim (6/12/24h lean): nothing.
- Prior week VWAP failed breakdowns: n 17, +4h +40.6 bp (t 3.0); halves n 9 / 8, both positive at 4h. Too few to rely on.
- 4h swing points (two-sided): failed breakouts 1R +0.25 / +0.16 in the two halves; failed breakdowns +0.25 / +0.07.

## Traps at higher-timeframe VWAP levels, 21 months (2026-10-15)

offside_traps_htf.py, Binance BTCUSDT perps 5m Jan 2025 - 13 Oct 2026 (187,488 bars), halves split 2025-12-01.
- Prior month / quarter / year VWAP and +/-1 SD, older quarters: 0-12 events per side in 21 months; too few to judge.
- Developing week / month / quarter / year VWAP and bands (day-start snapshots): first half mostly negative, second half mostly positive; no consistent edge. Prior week VWAP n 24/37, mixed halves.
- Weekly composite VAH/VAL: nothing consistent. Daily composite VAH/VAL with many new shorts trapped: first half 1R -0.08, second +0.09; the earlier one-year result was period-specific.
- 4h swing points: the only set positive in both halves: failed breakdowns 1R +0.04 / +0.15, failed breakouts +0.16 / +0.17; with many new positions trapped, failed breakouts +0.15 / +0.06 and +2h +11.7 / +12.4 bp.
