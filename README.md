# MMT indicators

Order-flow and positioning indicators for [MMT](https://mmt.gg), written in MMT Scripting v3, plus the guide, the
backtests behind them, and a TradingView watchlist importer. They make up the **Swordfish** chart: one 30m BTC/USD
perpetuals chart that shows where the market has accepted price, who traded where, and who is caught offside.

The full reference, with a visual key for every line and marker, is [`docs/swordfish-guide.html`](docs/swordfish-guide.html)
(open it in a browser).

## Contents

| Path | What it is |
|---|---|
| [`indicators/swordfish/`](indicators/swordfish) | The six Swordfish indicators (below) |
| [`indicators/other/`](indicators/other) | Earlier stand-alone scripts kept as they are in MMT: Value Area Levels, OI Delta, Positioning NL/NS/OI, Delta Footprint |
| [`tools/`](tools) | TradingView watchlist importer and the source of the "Import to MMT" Mac app |
| [`docs/swordfish-guide.html`](docs/swordfish-guide.html) | The guide: what each indicator draws, how to read it, settings, data and checks |
| [`validation/`](validation) | Reference implementations, cross-checks and backtests, with results in [`validation/README.md`](validation/README.md) |

## The Swordfish indicators

| Script | Draws | Data |
|---|---|---|
| **Swordfish Composites v2** (`swordfish-composites.m5`) | TPO value areas of balanced days or weeks, merged when they overlap by 50%; POC, VAH, VAL extended as levels | 30m candles, Binance perps |
| **Swordfish Calendar VWAP** (`swordfish-calendar-vwap.m5`) | Weekly, monthly, quarterly and yearly VWAPs with ±1 SD (VAH/VAL), current, previous and older periods, labelled (e.g. `2026 Q1 VAH`) | 30m (W/M) and 4h (Q/Y) candles, Binance + Bybit perps pooled |
| **Swordfish Rolling VWAP** (`swordfish-rolling-vwap.m5`) | Trailing 7D, 30D and 365D VWAPs | 30m and daily candles, Binance + Bybit perps pooled |
| **Swordfish Delta Heat** (`swordfish-delta-heat.m5`) | A delta ladder on every candle: net aggressive buying or selling per price row, in dollars, length relative to the candle's largest row, colour against a typical bar | MMT volume snapshots, Binance + Bybit + OKX perps |
| **Swordfish Offside** (`swordfish-offside.m5`) | Failed breakdowns and breakouts, measured from individual trades (pressed size, average fill, large prints, reclaim volume) with break-flow and counterflow proxies; delta divergences, reaction zones and flow-weighted prices | Trades (MMT Ultra), 5m candles, open interest and liquidations; Binance, Bybit and OKX perps |
| **Swordfish Bar Stats** (`swordfish-bar-stats.m5`) | A table under the chart: long and short liquidations, signed +L and +S flow proxies, volume split with net delta | Open interest, liquidations and candles, Binance, Bybit and OKX perps |

### Offside's trap definition

From the Stable workshop on failed breakdowns and traps: a level that matters breaks, price reclaims it, and the
reclaim holds. On 5m bars, whatever the chart timeframe:

1. **Level**: 4h swing highs and lows by default (optional: weekly to yearly VWAP levels).
2. **Break**: a 5m bar trades through it by at least 0.03%.
3. **Reclaim**: a 5m close back on the original side within 60 minutes (12 consecutive 5m bars from the break bar).
4. **Hold** (the trigger): three consecutive 5m closes stay on that side without taking the flush extreme. A missing
   5m bar drops any break or hold in progress (price in the gap is unknown), ends tracked traps ("ended: 5m data
   gap"), and no break is read on the first bar after it.
5. **Measured from trades** (MMT Ultra, the last 12 hours by default, trades of $1,000 or more): the aggressive selling executed below a broken
   support during the break (or buying above a broken resistance), its volume-weighted average fill, the share in
   prints of $100k or more, and **reclaim x**, the opposite aggression back on the reclaimed side from the reclaim
   through the successful hold divided by the pressed size (workshop 11's reclaim on volume). Pressed covers broken
   bars through the reclaim close; holding bars add only reclaim volume. A failed reclaim resets reclaim volume.
   Venues: Binance, Bybit and OKX perps. The dollar minimum ("Count trades from", $1,000) is checked per trade at its
   own price, so it is the same rule on every coin. MMT can only filter trades by size in coins, fixed before any
   price is known, so to save memory BTC, ETH and SOL load only trades above the dollar minimum at a high price
   (BTC $200k, ETH $5k, SOL $500: 0.005 BTC, 0.2 ETH, 2 SOL); other coins load every print. Coverage counts every
   loaded trade: on every bar each venue's buy and sell totals must reach 80% of its 5m candle (setting) and not exceed
   it by more than 2%. A small venue may also miss by 1% of the pooled volume, but never by more than half its own,
   and a venue or side whose candle has volume must have supplied trades. MMT's trade feeds run slightly short on
   some venues (Bybit about 95%). Each trap shows the share of candle volume its trades covered ("trades 98.4% of
   vol"). Within each 0.01% price row, sells and buys are each placed by their own average price, so buying cannot
   pull selling across the level; only same-side trades within one row of the level can land on the wrong side.
   Without covered trade data a trap falls back to the break VWAP (HLC3 weighted by volume).
6. **Flow proxies from candles and OI**: `+S = (dOI - D) / 2` and `+L = (dOI + D) / 2` cannot identify positions or
   participants. "Break flow proxy" sums the positive proxy over the break, including the reclaim bar; "Counterflow
   proxy" sums its opposite sign after the hold, in coins. Measured net flow since the hold is shown beside it.
   Counterflow never ends price tracking: only a close back through the level, a breach of the flush extreme, or
   the tracking time limit ends a trap. **Stop**: the flush extreme.

Missing or misaligned candles/OI on any selected venue withhold flow readings. A gap during the break makes its total unavailable; a later gap makes counterflow unavailable for that trap. Price-pattern detection continues. Liquidations count only when MMT's liquidation stat is on the same bar; otherwise the trap's liquidation total shows as "n/a". The +L/+S flow-weighted prices reset to unavailable after a missing chart bar or a bar without aligned candles and OI, then rebuild from valid bars; they are not participant entries or P&L. The live-bar values in Bar Stats and Offside's agent export are shown only when every selected venue's forming candle and the open interest are on the current bar; otherwise they are left empty rather than summed from a stale venue.

The marker sits beyond the flush extreme on the bar where the hold completed; it is larger when the pressed size beats
the recent average. The level line and the dotted line carry short captions ("4h swing low 80,345 | failed breakdown |
holding", "sellers' avg fill below level"). The newest trap on each
side is described at the bottom right; every trap is in the script's "Recent traps" window.

## Installing in MMT

1. In MMT, open the script editor, create a new script, paste the file's contents and save. (With the MMT MCP server
   connected, `script_create` with the file's code does the same.)
2. Add it to a chart from Indicators, or with `chart_add_script`.

### The Swordfish chart as used

- One chart only: BTC/USD on Binance perps, 30m. In MMT, scripts that wait for the live bar stalled in two-chart
  layouts, so use a single chart.
- Layers, top to bottom:
  - Swordfish Composites v2, twice: one with **Composite period** set to Daily, one to Weekly.
  - Swordfish Calendar VWAP: **Panel anchor** Weekly, all four units on, **Value areas and labels on older periods** set to All.
  - Swordfish Delta Heat, Swordfish Rolling VWAP and Swordfish Offside, with default settings.
  - Swordfish Bar Stats, in its own pane.
  - MMT's built-in **Open Interest** and **Delta Volume** panes, each set to Binance, Bybit and OKX perps: the pane's
    gear, then Aggregate, then Markets. Hyperliquid is not used anywhere.
- The settings that count bars are set in hours and the ladder's row size scales with the timeframe, so the same chart
  also works on 5m.

## Data notes

- MMT gives scripts no combined candles: `data.ohlcv` with `markets.agg(...)` returns nothing. Buy and sell volume
  across exchanges is therefore each exchange's candles summed. That sum matched MMT's combined volume delta to within
  0.03 BTC per bar. Open interest, liquidations and volume snapshots do have combined streams, and these scripts use
  them.
- In MMT's stats, `buyLiq` is long liquidations and `sellLiq` is short liquidations. This was checked against
  one-minute returns: −15 bp vs +15 bp.
- Rolling VWAP uses 335/1,439 closed 30m candles plus the forming candle, and 364 closed days plus the forming day. These are candle-aligned windows, not an exact intrabar trailing duration.
- Delta Heat's live ladder supports whole-minute charts from 1m through 4h. Other timeframes explicitly show closed bars only.
- MMT keeps per-price volume snapshots for about the last 1,000 bars. The ladder, the reaction zones and the old wick
  markers only exist for that span.
- Offside's trap detection looks back 5 days of 5m bars. Its 4h swing levels use about 50 days of 4h bars.
- Offside's trade layer loads the last 12 hours of trades from the selected perps. All BTC prints over 24 hours (about
  6 million) took about 6.5 minutes from a cold start and coincided with MMT's "script service is at its memory
  limit" errors, hence the shorter default and the coin floors above. Lower "Trade history (hours)" to load faster.
  A minimized or background tab loads far slower, and two MMT tabs on one workspace compete.

## Agent exports (m5)

Composites, Calendar VWAP and Offside also plot hidden numeric series, all titled `x.*`, on a panel inside their own
details window. An agent can read them with m5 `script_get_plot_values` instead of reading the canvas. They draw
nothing on the chart, and they are plotted from the update handler, so the live bar is included.

- Composites: `x.<unit>.c0.*` and `x.<unit>.c1.*` (the newest and prior composite): `vah`, `poc`, `val`,
  `start_min`, `end_min`, `members`. Also `x.<unit>.closed_periods` and `x.<unit>.ok`. The layer title also carries the
  newest and prior VAH/POC/VAL, because `script_get_plot_values` only returns the first layer of a script that is on the
  chart twice (Daily and Weekly).
- Calendar VWAP: `x.{W,M,Q,Y}.vwap` and `.sd` for the current period, and `x.{pW,pM,pQ,pY}.*` for the prior one.
- Offside: `x.trap_longs.*` and `x.trap_shorts.*` (level, stop, status, reclaim_x, flows, trade coverage),
  `x.active.*` (the level being tracked), `x.watch.*`, `x.zone_above.*` and `x.zone_below.*`, divergences
  (`x.div_bull.*`, `x.div_bear.*`), the current bar's flow (`x.bar.*`: buy and sell volume, delta, liquidations, the
  +L and +S proxies, OI), and the Delta Heat ladder summary (`x.heat.*`).

Times (`*_min`) are minutes since 2026-01-01 00:00 UTC. Plot values travel as 32-bit floats, so prices keep about
7 significant digits. Bar Stats and Delta Heat have no exports: adding a window to them opened it as a chart tab and
stalled Offside, so Offside reports those numbers instead.

## Checks and backtests

Everything was checked against exchange data before use (details in [`validation/README.md`](validation/README.md)):

- **Composites**: identical to the Python reference of the original kScript method.
- **Calendar and Rolling VWAP**: within 0.01% of VWAPs computed from Binance and Bybit's own candles.
- **Offside traps**: identical to a Python replica of the rules on Binance's published 5m data, 9 of 9 on STX and 8 of 8
  on BTC.

The recorded historical results used two-sided swing levels and excluded the reclaim bar from flow totals. They do **not** validate the current fixed-side detector. `validation/offside_fixed.py` now supplies the default swing engine to both the event replica and the higher-timeframe backtest, including reclaim-bar flow. The HTF report labels current fixed-side results separately from legacy two-sided comparisons. Historical performance numbers remain for provenance. The corrected run on 187,488 bars produced 266 events; its separate results and limitations are recorded in `validation/README.md`.

Treat traps as price context, not proof of who holds a position or a standalone trading signal.

To rerun the backtests, download the data with `validation/offside_rows.py`, plus Binance's 5m klines and metrics files
from data.binance.vision into `validation/data/offside/`. The scripts' headers give the details.

## Tools

**TradingView watchlist importer**: `tools/tv_watchlist_import.py` replaces the watchlist in the open MMT browser
session with the markets in a TradingView "Export list" file. It converts `BINANCE:TIAUSDT.P` to Binance perps
`tia/usd` and `COINBASE:BTCUSD` to Coinbase `btc/usd`. MMT watchlists have no sections, so `###` section headers only
appear in the importer's report. Empty imports are refused. The importer saves a JSON recovery snapshot beside the input file and adds every new market before removing old ones; a failed addition retains all original markets. Successful additions can remain after a failure. Retained markets keep their existing order. Multiple open watchlists require `--widget`.

```bash
python3 tools/tv_watchlist_import.py                     # file picker
python3 tools/tv_watchlist_import.py list.txt --dry-run  # show the conversion only
```

It talks to MMT through the m5 MCP endpoint, using the server entry Claude Code stores in `~/.claude.json`. The project
path is set in `PROJECT` at the top of the script; change it if your entry lives under another project.

**Import to MMT app**: `tools/import-to-mmt.applescript` is the source of a one-click Mac app. It shows a file picker
and a preview, then replaces the watchlist. Set the paths at the top of the script, then build it:

```bash
osacompile -o ~/Applications/"Import to MMT.app" tools/import-to-mmt.applescript
```

## Regression checks

Run `uv run --with pytest --with numpy --with polars pytest -q`. Tests exercise watchlist failure recovery, the fixed-side trap engine, and Offside trade accounting. Node.js 18+ is required for the trade-accounting harness, which executes the production M5 helpers and 5m handler with synthetic feeds through a limited JavaScript translation; it does not compile M5 or simulate MMT feed scheduling. MMT `script_check` validates indicator syntax/types; it does not prove live feed synchronization or chart rendering.
