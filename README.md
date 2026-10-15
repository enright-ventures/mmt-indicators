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
| [`indicators/third-party/`](indicators/third-party) | FLIMP BTC Aquarium v5, by FLIMP, with this repo's data-feed changes (see below) |
| [`tools/`](tools) | TradingView watchlist importer and the source of the "Import to MMT" Mac app |
| [`docs/swordfish-guide.html`](docs/swordfish-guide.html) | The guide: what each indicator draws, how to read it, settings, data and checks |
| [`validation/`](validation) | Reference implementations, cross-checks and backtests, with results in [`validation/README.md`](validation/README.md) |

## The Swordfish indicators

| Script | Draws | Data |
|---|---|---|
| **Swordfish Composites v2** (`swordfish-composites.m5`) | TPO value areas of balanced days or weeks, merged when they overlap by 50%; POC, VAH, VAL extended as levels | 30m candles, Binance perps |
| **Swordfish Calendar VWAP** (`swordfish-calendar-vwap.m5`) | Weekly, monthly, quarterly and yearly VWAPs with ±1 SD (VAH/VAL), current, previous and older periods, labelled (e.g. `2026 Q1 VAH`) | 30m (W/M) and 4h (Q/Y) candles, Binance + Bybit perps pooled |
| **Swordfish Rolling VWAP** (`swordfish-rolling-vwap.m5`) | Trailing 7D, 30D and 365D VWAPs | 30m and daily candles, Binance + Bybit perps pooled |
| **Swordfish Delta Heat** (`swordfish-delta-heat.m5`) | A delta ladder on every candle: net aggressive buying or selling per price row, in dollars, length relative to the candle's largest row, colour against a typical bar | MMT volume snapshots, Binance + Bybit + OKX + Hyperliquid perps |
| **Swordfish Offside** (`swordfish-offside.m5`) | Failed breakdowns and breakouts, break VWAP and signed flow/counterflow proxies; delta divergences, reaction zones and flow-weighted prices | 5m candles, open interest and liquidations, four perps |
| **Swordfish Bar Stats** (`swordfish-bar-stats.m5`) | A table under the chart: long and short liquidations, signed +L and +S flow proxies, volume split with net delta | Open interest, liquidations and candles, four perps |

### Offside's trap definition

From the Stable workshop on failed breakdowns and traps: a level that matters breaks, price reclaims it, and the
reclaim holds. On 5m bars, whatever the chart timeframe:

1. **Level**: 4h swing highs and lows by default (optional: weekly to yearly VWAP levels).
2. **Break**: a 5m bar trades through it by at least 0.03%.
3. **Reclaim**: a 5m close back on the original side within 60 minutes.
4. **Hold** (the trigger): three 5m closes stay on that side without taking the flush extreme.
5. **Flow context**: positive parts of `NS = (dOI - D) / 2` or `NL = (dOI + D) / 2`, including the reclaim bar. These are signed flow proxies, not counts of new or trapped positions. **Break VWAP**: HLC3 weighted by chart volume. **Stop**: the flush extreme.
6. **Counterflow**: the opposite-signed proxy after confirmation, shown as an absolute amount. It cannot establish how much of a trapped cohort has closed; it does not end tracking.

Missing or misaligned candles/OI on any selected venue withhold flow readings. A gap during the break makes its total unavailable; a later gap makes counterflow unavailable for that trap. Price-pattern detection continues. Flow-weighted prices reset after a data gap and are not participant entries or P&L.

The marker sits beyond the flush extreme on the bar where the hold completed. The level line and the pain line carry
short captions ("4h swing low 80,345 | failed breakdown | holding", "break VWAP (not entry)"). The newest trap on each
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
  - MMT's built-in **Open Interest** and **Delta Volume** panes, each set to the four perps: the pane's gear, then
    Aggregate, then Markets.
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

## FLIMP BTC Aquarium

`indicators/third-party/flimp-btc-aquarium-v5.m5` is FLIMP's script, included for reference. It has these changes:
- four venues: Binance and Bybit perps, Binance and Coinbase spot;
- live-only feeds; only these four venues have controls and appear in the status readout;
- order books every 30 seconds instead of 5, because MMT keeps every full-depth snapshot and at 5 seconds the tank froze
  within hours.

All credit for the design is FLIMP's.

## Regression checks

Run `uv run --with pytest --with numpy --with polars pytest -q`. Tests exercise watchlist failure recovery and the fixed-side trap engine. MMT `script_check` validates indicator syntax/types; it does not prove live feed synchronization or chart rendering.
