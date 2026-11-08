# Swordfish on the Apple Watch

Complications for the **Modular Ultra** face that summarise the Swordfish chart, fed by a small server that recomputes
the Swordfish numbers from exchange data, so nothing depends on MMT being open.

```
Binance + Bybit REST ──> watch/server (Python, every 2 min) ──> GET /v1/snapshot ──> watch app + complications
```

## The complications

| Complication | Families | Shows |
|---|---|---|
| **Swordfish Levels** | rectangular, inline | Price and 24h change; price against the daily composite (above VAH / in value / below VAL); weekly VWAP in SD; nearest untested 4h swing support and resistance |
| **Swordfish Offside** | rectangular, circular, corner | The newest failed breakdown (blue, up) or failed breakout (red, down): level, holding or why it ended, stop, age |
| **Swordfish Delta** | circular, corner | The forming 30m bar's net taker buying or selling as a share of its volume, gauge −100% to +100% |
| **Swordfish Weekly VWAP** | circular, corner | Price against this week's pooled VWAP in SD, gauge −2σ to +2σ |
| **Swordfish Price** | circular, corner, inline | Last price, ring placing it between the daily composite's VAL and VAH |

A suggested Modular Ultra layout: **Levels** or **Offside** in the large centre slot, **Delta**, **Weekly VWAP** and
**Offside** (circular) in the round slots. Faces dim when the data is over an hour old. The app itself shows every
number: composites, all four calendar VWAPs, rolling VWAPs, traps, and 30m flow.

Complications refresh on WidgetKit's budget: each asks to reload every 15 minutes and they share one cached snapshot,
so expect readings up to 15–20 minutes old. Open the app for a fresh one.

## How the numbers relate to the chart

| Number | Method | Matches the chart? |
|---|---|---|
| Rolling VWAP 7D/30D/365D | `validation/rvwap_pooled_ref.py`'s windows, Binance + Bybit pooled | Same method and venues |
| Calendar VWAP W/M/Q/Y | Pooled HLC3 × volume and SD, `vwap_ref.period_start`, withheld on any gap | Same method and venues (current period only) |
| Composites, daily and weekly | `composites_ref.kscript_composites` on Binance 30m | The method the m5 script ports |
| Traps | `offside_fixed.find_traps` on Binance 5m, 4h swings as the m5 script builds them, tracked 24h | Same rules on Binance's candles only; no pressed size, reclaim ×, liquidations or flow totals (those need MMT's profiles and streams) |
| Delta, dOI, +L / +S | Binance taker volume and open interest only | The chart pools Binance, Bybit and OKX, so these are a single-venue reading |

Liquidations are not shown: the exchanges don't publish them over REST.

## Server

```bash
cd watch/server
uv run --no-project --with pytest --with numpy --with polars pytest -q -c pyproject.toml   # tests
SWORDFISH_VALIDATION=../../validation python3 -m swordfish_feed                            # serve on :8080
```

Binance and Bybit refuse US hosts (HTTP 451/403), so deploy outside the US. `fly.toml` targets Sydney:

```bash
fly launch --no-deploy --config watch/server/fly.toml        # from the repo root, once
fly secrets set FEED_TOKEN=$(openssl rand -hex 16) --config watch/server/fly.toml   # optional
docker build -f watch/server/Dockerfile -t swordfish-feed .   # or: fly deploy --config watch/server/fly.toml
```

Settings: `PORT` (8080), `REFRESH_SECONDS` (120), `FEED_TOKEN` (optional bearer token), `SYMBOL` (BTCUSDT).

### Snapshot fields

`price`, `change_24h_pct`; `rolling.{d7,d30,d365}`; `calendar.{W,M,Q,Y}.{vwap,sd,start}`;
`composites.{daily,weekly}.{c0,c1}.{vah,poc,val,start,end,members}`;
`flow.{bar_time,delta,volume,oi,d_oi,plus_l,plus_s,forming_delta,forming_volume}`;
`traps.{failed_breakdown,failed_breakout}.{level,stop,time,status,ended,break_vwap}`, `traps.{support,resistance}`.
Times are unix seconds; a withheld number is `null`.

## Watch app

Needs a Mac with Xcode 16+ and [XcodeGen](https://github.com/yonaskolb/XcodeGen).

```bash
cd watch/app
brew install xcodegen
xcodegen generate            # set DEVELOPMENT_TEAM and SWORDFISH_FEED_URL in project.yml first, or in Xcode
open SwordfishWatch.xcodeproj
```

Run the **SwordfishWatch** scheme on the Ultra. It's a watch-only app (no iPhone app). The feed URL and token can be
set or changed in the app under Feed settings. Then long-press the Modular Ultra face, Edit, and pick the Swordfish
complications for each slot.
