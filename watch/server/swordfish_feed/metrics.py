"""The Swordfish numbers a watch shows, computed from exchange candles with the repo's validated methods.

- Rolling VWAP: as validation/rvwap_pooled_ref.py (Binance + Bybit pooled, 335/1,439 closed 30m + forming; 364 closed
  days + the forming day built from its 30m candles).
- Calendar VWAP: the current week/month (30m) and quarter/year (4h), pooled HLC3 x volume with +/-1 SD, withheld unless
  every venue covers the period from its start with no gaps (validation/vwap_ref.py period boundaries).
- Composites: validation/composites_ref.kscript_composites on Binance 30m, the method the m5 script ports.
- Traps: validation/offside_fixed.find_traps on Binance 5m with 4h swing levels built as the m5 script builds them.
  Pressed size, reclaim x and liquidations need MMT's volume profiles and liquidation stream, so they are not here.
- Bar flow: Binance only. Delta from taker buy volume, dOI from Binance's open interest history, and the
  +L = (dOI + D) / 2, +S = (dOI - D) / 2 proxies, which do not identify positions.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from typing import Any, Sequence

from .exchanges import Candle

sys.path.insert(0, os.environ.get("SWORDFISH_VALIDATION", os.path.join(os.path.dirname(__file__), "..", "..", "..", "validation")))

from composites_ref import kscript_composites  # noqa: E402
from offside_fixed import Bar, Level, find_traps  # noqa: E402
from vwap_ref import period_start  # noqa: E402

HALF, FOUR, DAY = 1800, 14400, 86400
UNITS = ("W", "M", "Q", "Y")


def hlc3(c: Candle) -> float:
    return (c.high + c.low + c.close) / 3


def index(rows: Sequence[Candle]) -> dict[int, Candle]:
    return {c.time: c for c in rows}


# ---------------------------------------------------------------- rolling VWAP

def rolling_vwap(m30: Sequence[Sequence[Candle]], d1: Sequence[Sequence[Candle]]) -> dict[str, float | None]:
    """At the forming 30m candle T of the first venue. A window is None when any venue lacks a candle in it."""
    if not m30 or not m30[0]:
        return {"d7": None, "d30": None, "d365": None}
    T = m30[0][-1].time
    halves = [index(rows) for rows in m30]
    days = [index(rows) for rows in d1]
    out: dict[str, float | None] = {}
    for name, n in (("d7", 336), ("d30", 1440)):
        pv = vol = 0.0
        ok = True
        for src in halves:
            for i in range(n):
                c = src.get(T - HALF * i)
                if c is None:
                    ok = False
                    break
                pv += hlc3(c) * c.volume
                vol += c.volume
        out[name] = pv / vol if ok and vol > 0 else None
    day0 = T - T % DAY
    pv = vol = 0.0
    ok = len(days) == len(halves)
    for src_d, src_m in zip(days, halves):
        for i in range(1, 365):
            c = src_d.get(day0 - DAY * i)
            if c is None:
                ok = False
                break
            pv += hlc3(c) * c.volume
            vol += c.volume
        today = [src_m.get(t) for t in range(day0, T + 1, HALF)]
        if any(c is None for c in today):
            ok = False
            break
        bars = [c for c in today if c is not None]
        h, l, cl, v = max(b.high for b in bars), min(b.low for b in bars), bars[-1].close, sum(b.volume for b in bars)
        pv += (h + l + cl) / 3 * v
        vol += v
    out["d365"] = pv / vol if ok and vol > 0 else None
    return out


# ---------------------------------------------------------------- calendar VWAP

def calendar_vwap(m30: Sequence[Sequence[Candle]], h4: Sequence[Sequence[Candle]]) -> dict[str, dict[str, Any] | None]:
    """Current week and month from 30m, quarter and year from 4h; the period runs from its UTC start to the forming
    candle. A venue must hold every candle from the start through the forming one."""
    out: dict[str, dict[str, Any] | None] = {}
    for mode, unit in enumerate(UNITS):
        venues, block = (h4, FOUR) if mode >= 2 else (m30, HALF)
        if not venues or not venues[0]:
            out[unit] = None
            continue
        forming = venues[0][-1].time
        start = int(period_start(forming, mode))
        s0 = s1 = s2 = 0.0
        ok = True
        for rows in venues:
            src = index(rows)
            for t in range(start, forming + 1, block):
                c = src.get(t)
                if c is None or not (c.high >= c.low > 0):
                    ok = False
                    break
                p = hlc3(c)
                s0 += c.volume
                s1 += p * c.volume
                s2 += p * p * c.volume
            if not ok:
                break
        if not ok or s0 <= 0:
            out[unit] = None
            continue
        mean = s1 / s0
        out[unit] = {"vwap": mean, "sd": math.sqrt(max(0.0, s2 / s0 - mean * mean)), "start": start}
    return out


# ---------------------------------------------------------------- composites

def composites(m30_binance: Sequence[Candle], cadence: str) -> dict[str, Any] | None:
    rows = [[c.time, c.open, c.high, c.low, c.close, c.volume] for c in m30_binance]
    result = kscript_composites(rows, cadence=cadence)
    if result is None or result["fault"] or not result["drawn"]:
        return None
    step = result["row_price"]

    def describe(p: Any) -> dict[str, Any]:
        return {"vah": p.vah * step, "poc": p.poc * step, "val": p.val * step, "start": p.start, "end": p.end, "members": p.members}

    drawn = result["drawn"]
    return {"c0": describe(drawn[-1]), "c1": describe(drawn[-2]) if len(drawn) > 1 else None}


# ---------------------------------------------------------------- bar flow (Binance)

def bar_flow(m30_binance: Sequence[Candle], open_interest: dict[int, float]) -> dict[str, Any]:
    """The last closed 30m bar's delta, dOI and +L / +S proxies, and the forming bar's delta so far."""
    out: dict[str, Any] = {"bar_time": None, "delta": None, "volume": None, "oi": None, "d_oi": None, "plus_l": None,
                           "plus_s": None, "forming_delta": None, "forming_volume": None}
    if len(m30_binance) < 2:
        return out
    closed, forming = m30_binance[-2], m30_binance[-1]
    if math.isfinite(forming.taker_buy):
        out["forming_delta"] = 2 * forming.taker_buy - forming.volume
        out["forming_volume"] = forming.volume
    if not math.isfinite(closed.taker_buy):
        return out
    delta = 2 * closed.taker_buy - closed.volume
    out.update(bar_time=closed.time, delta=delta, volume=closed.volume)
    before, after = open_interest.get(closed.time), open_interest.get(closed.time + HALF)
    if after is not None:
        out["oi"] = after
    if before is not None and after is not None:
        d_oi = after - before
        out.update(d_oi=d_oi, plus_l=(d_oi + delta) / 2, plus_s=(d_oi - delta) / 2)
    return out


# ---------------------------------------------------------------- traps (Offside, fixed-side 4h swings)

@dataclass(frozen=True, slots=True)
class Swing:
    available: int  # unix seconds the swing is confirmed (close of the third bar after it)
    price: float
    side: int  # +1 swing low (support, can fail as a breakdown), -1 swing high
    expires: int


def swing_levels(h4_closed: Sequence[Candle]) -> list[Swing]:
    """The m5 rule: the middle of seven 4h bars, below (above) the three before and not above (below) the three
    after; usable from the seventh bar's close for 14 days."""
    out: list[Swing] = []
    for i in range(6, len(h4_closed)):
        w = h4_closed[i - 6:i + 1]
        if any(w[j + 1].time - w[j].time != FOUR for j in range(6)):
            continue
        avail = w[6].time + FOUR
        expires = avail + 14 * DAY
        mid = w[3]
        if mid.low < min(c.low for c in w[:3]) and mid.low <= min(c.low for c in w[4:]):
            out.append(Swing(avail, mid.low, 1, expires))
        if mid.high > max(c.high for c in w[:3]) and mid.high >= max(c.high for c in w[4:]):
            out.append(Swing(avail, mid.high, -1, expires))
    return out


def traps(m5_closed: Sequence[Candle], h4_closed: Sequence[Candle], track_hours: int = 24) -> dict[str, Any]:
    """The newest failed breakdown and failed breakout, each with its tracking status, and the nearest untested
    swing level on each side of price."""
    out: dict[str, Any] = {"failed_breakdown": None, "failed_breakout": None, "support": None, "resistance": None}
    if not m5_closed:
        return out
    swings = swing_levels(h4_closed)
    times = [c.time for c in m5_closed]
    levels: list[Level] = []
    for s in swings:
        if s.expires <= times[0] or s.available > times[-1]:
            continue
        first = next(i for i, t in enumerate(times) if t >= s.available)
        levels.append(Level(first, s.price, s.side, s.expires))
    bars = [Bar(c.time, c.high, c.low, c.close, c.volume) for c in m5_closed]
    events = find_traps(bars, levels)
    for side, key in ((1, "failed_breakdown"), (-1, "failed_breakout")):
        newest = next((e for e in reversed(events) if e.side == side), None)
        if newest is not None:
            out[key] = track(newest, m5_closed, track_hours)
    price = m5_closed[-1].close
    now = m5_closed[-1].time + 300
    for s in swings:
        if not (s.available <= now < s.expires):
            continue
        after = [c for c in m5_closed if c.time >= s.available]
        if s.side > 0 and s.price < price and all(c.low >= s.price for c in after):
            if out["support"] is None or s.price > out["support"]:
                out["support"] = s.price
        if s.side < 0 and s.price > price and all(c.high <= s.price for c in after):
            if out["resistance"] is None or s.price < out["resistance"]:
                out["resistance"] = s.price
    return out


def track(event: Any, m5: Sequence[Candle], track_hours: int) -> dict[str, Any]:
    """After the hold: ended by a close back through the level, a breach of the flush extreme (the stop), or the
    tracking time limit; otherwise holding."""
    start = m5[event.index].time
    status, ended = "holding", None
    for c in m5[event.index + 1:]:
        if c.time - start >= track_hours * 3600:
            status, ended = "ended", "time limit"
            break
        breached = c.low < event.flush if event.side > 0 else c.high > event.flush
        back = c.close < event.level if event.side > 0 else c.close > event.level
        if breached:
            status, ended = "ended", "stop taken"
            break
        if back:
            status, ended = "ended", "closed back through"
            break
    return {"level": event.level, "stop": event.flush, "time": start, "status": status, "ended": ended,
            "break_vwap": event.break_vwap}


# ---------------------------------------------------------------- snapshot

def snapshot(data: dict[str, Any], now: int) -> dict[str, Any]:
    """`data` holds the fetched candles: bn_5m, bn_30m, bn_4h, bn_1d, by_30m, by_4h, by_1d, bn_oi_30m."""
    bn30: list[Candle] = data["bn_30m"]
    price = bn30[-1].close if bn30 else None
    day_ago = index(bn30).get(bn30[-1].time - DAY) if bn30 else None
    m5_closed = [c for c in data["bn_5m"] if c.time + 300 <= now]
    h4_closed = [c for c in data["bn_4h"] if c.time + FOUR <= now]
    return {
        "v": 1,
        "asof": now,
        "symbol": "BTC",
        "price": price,
        "change_24h_pct": (price / day_ago.open - 1) * 100 if price and day_ago else None,
        "rolling": rolling_vwap([bn30, data["by_30m"]], [data["bn_1d"], data["by_1d"]]),
        "calendar": calendar_vwap([bn30, data["by_30m"]], [data["bn_4h"], data["by_4h"]]),
        "composites": {"daily": composites(bn30, "Daily"), "weekly": composites(bn30, "Weekly")},
        "flow": bar_flow(bn30, data["bn_oi_30m"]),
        "traps": traps(m5_closed, h4_closed),
    }
