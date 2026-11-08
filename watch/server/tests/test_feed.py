"""Feed checks on synthetic candles: each metric against an independent calculation or the repo's references."""
from __future__ import annotations

import json
import math
import random
from urllib.parse import parse_qs, urlparse

import pytest

from swordfish_feed import app
from swordfish_feed.exchanges import Candle, binance_klines, bybit_klines
from swordfish_feed.metrics import (DAY, FOUR, HALF, bar_flow, calendar_vwap, composites, rolling_vwap, snapshot,
                                    swing_levels, track, traps)
from vwap_ref import vwap as ref_vwap

NOW = 1_762_560_000 + 7 * 3600 + 1234  # 2025-11-08 07:20:34 UTC, inside a forming 30m bar


def walk(step: int, start: int, end: int, seed: int, price: float = 100_000.0) -> list[Candle]:
    rng = random.Random(seed)
    out = []
    for t in range(start - start % step, end, step):
        o = price
        c = o * (1 + rng.gauss(0, 0.002 * math.sqrt(step / 300)))
        h, l = max(o, c) * (1 + abs(rng.gauss(0, 0.001))), min(o, c) * (1 - abs(rng.gauss(0, 0.001)))
        v = rng.uniform(50, 500) * step / 300
        out.append(Candle(t, o, h, l, c, v, v * rng.uniform(0.3, 0.7)))
        price = c
    return out


def series(seed: int) -> dict[str, list[Candle]]:
    return {f"{step}": walk(step, NOW - 400 * DAY, NOW, seed + step) for step in (300, HALF, FOUR, DAY)}


# ---------------------------------------------------------------- VWAPs

def test_rolling_vwap_matches_direct_sum_and_withholds_on_gap() -> None:
    a, b = series(1), series(2)
    got = rolling_vwap([a["1800"], b["1800"]], [a["86400"], b["86400"]])
    pv = sum((c.high + c.low + c.close) / 3 * c.volume for src in (a, b) for c in src["1800"][-336:])
    vol = sum(c.volume for src in (a, b) for c in src["1800"][-336:])
    assert got["d7"] == pytest.approx(pv / vol, rel=1e-12)
    assert got["d365"] is not None
    holed = a["1800"][:-500] + a["1800"][-499:]
    assert rolling_vwap([holed, b["1800"]], [a["86400"], b["86400"]])["d7"] is not None  # hole older than 7D
    assert rolling_vwap([holed, b["1800"]], [a["86400"], b["86400"]])["d30"] is None


def test_calendar_vwap_single_venue_equals_reference() -> None:
    a = series(3)
    got = calendar_vwap([a["1800"]], [a["14400"]])
    rows = [[c.time, c.open, c.high, c.low, c.close, c.volume] for c in a["1800"]]
    start = got["W"]["start"]
    ref = ref_vwap(rows, start, a["1800"][-1].time + HALF, HALF)
    assert ref is not None
    assert got["W"]["vwap"] == pytest.approx(ref[0], rel=1e-10)
    assert got["W"]["sd"] == pytest.approx(ref[1], rel=1e-6)
    assert start % DAY == 0 and (start // DAY + 3) % 7 == 0  # a UTC Monday
    for unit in "MQY":
        assert got[unit] is not None and got[unit]["sd"] > 0


def test_calendar_vwap_withholds_when_a_venue_misses_the_period_start() -> None:
    a, b = series(4), series(5)
    late = [c for c in b["1800"] if c.time > b["1800"][-1].time - 3 * HALF]
    got = calendar_vwap([a["1800"], late], [a["14400"], b["14400"]])
    assert got["W"] is None and got["M"] is None
    assert got["Q"] is not None


# ---------------------------------------------------------------- composites, flow

def test_composites_return_ordered_value_areas() -> None:
    a = series(6)
    for cadence in ("Daily", "Weekly"):
        got = composites(a["1800"][-110 * 48:], cadence)
        assert got is not None
        c0 = got["c0"]
        assert c0["val"] <= c0["poc"] <= c0["vah"]
        assert c0["members"] >= 1
        if got["c1"]:
            assert got["c1"]["end"] <= c0["start"]


def test_bar_flow_proxies() -> None:
    bars = [Candle(0, 1, 1, 1, 1, 10, 7), Candle(HALF, 1, 1, 1, 1, 4, 1)]
    got = bar_flow(bars, {0: 100.0, HALF: 103.0})
    assert got["delta"] == 4 and got["d_oi"] == 3
    assert got["plus_l"] == 3.5 and got["plus_s"] == -0.5
    assert got["forming_delta"] == -2
    assert bar_flow(bars, {})["plus_l"] is None


# ---------------------------------------------------------------- traps

def h4(t: int, high: float, low: float) -> Candle:
    return Candle(t, (high + low) / 2, high, low, (high + low) / 2, 1)


def test_swing_rule_matches_m5() -> None:
    lows = [10, 9, 8, 5, 6, 7, 5]  # equal low after counts ("not below")
    bars = [h4(i * FOUR, 20, lo) for i, lo in enumerate(lows)]
    got = swing_levels(bars)
    assert [(s.price, s.side) for s in got] == [(5, 1)]
    assert got[0].available == 7 * FOUR and got[0].expires == 7 * FOUR + 14 * DAY
    lows[6] = 4.9
    assert swing_levels([h4(i * FOUR, 20, lo) for i, lo in enumerate(lows)]) == []


def test_failed_breakdown_then_status() -> None:
    lows = [110, 108, 106, 100, 104, 105, 106]
    swing = [h4(i * FOUR, 120, lo) for i, lo in enumerate(lows)]
    t0 = 7 * FOUR
    m5 = [Candle(t0 + i * 300, 103, 104, 102, 103, 1) for i in range(6)]
    t = m5[-1].time + 300
    m5.append(Candle(t, 102, 102.5, 98.0, 99.0, 5))           # break 100 by more than 0.03%
    m5.append(Candle(t + 300, 99, 101.5, 98.5, 101.0, 5))     # reclaim
    m5 += [Candle(t + 600 + i * 300, 101, 102, 100.5, 101.5, 2) for i in range(3)]  # hold
    got = traps(m5, swing)
    trap = got["failed_breakdown"]
    assert trap is not None and trap["level"] == 100 and trap["stop"] == 98.0
    assert trap["status"] == "holding"
    assert got["failed_breakout"] is None
    later = m5 + [Candle(m5[-1].time + 300, 101, 101, 99.5, 99.6, 1)]
    assert traps(later, swing)["failed_breakdown"]["ended"] == "closed back through"
    stopped = m5 + [Candle(m5[-1].time + 300, 101, 101, 97.0, 100.5, 1)]
    assert traps(stopped, swing)["failed_breakdown"]["ended"] == "stop taken"


def test_track_time_limit() -> None:
    class Event:
        index, side, level, flush, break_vwap = 0, -1, 100.0, 103.0, 101.0
    bars = [Candle(i * 300, 99, 99.5, 98.5, 99, 1) for i in range(300)]
    assert track(Event, bars, 24)["ended"] == "time limit"


def test_nearest_untested_levels() -> None:
    lows = [110, 108, 106, 100, 104, 105, 106]
    highs = [120, 122, 124, 130, 126, 125, 124]
    swing = [Candle(i * FOUR, 0, hi, lo, 0, 1) for i, (lo, hi) in enumerate(zip(lows, highs))]
    m5 = [Candle(7 * FOUR + i * 300, 115, 116, 114, 115, 1) for i in range(10)]
    got = traps(m5, swing)
    assert got["support"] == 100 and got["resistance"] == 130


# ---------------------------------------------------------------- end to end through the fetchers

def fake_exchange(url: str) -> object:
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    if "openInterestHist" in url:
        step = HALF
        last = NOW - NOW % step
        return [{"timestamp": (last - i * step) * 1000, "sumOpenInterest": str(80_000 + i)} for i in range(6)][::-1]
    if "binance" in url:
        step = {"5m": 300, "30m": HALF, "4h": FOUR, "1d": DAY}[q["interval"]]
        rows = walk(step, int(q["startTime"]) // 1000, NOW, 11)[:1500]
        return [[c.time * 1000, c.open, c.high, c.low, c.close, c.volume, 0, 0, 0, c.taker_buy, 0, 0] for c in rows]
    step = {"5": 300, "30": HALF, "240": FOUR, "D": DAY}[q["interval"]]
    rows = [c for c in walk(step, int(q["start"]) // 1000, NOW, 12) if c.time * 1000 <= int(q["end"])][-1000:]
    return {"result": {"list": [[str(c.time * 1000), c.open, c.high, c.low, c.close, c.volume, 0] for c in reversed(rows)]}}


def test_fetchers_page_to_the_forming_candle() -> None:
    bn = binance_klines("BTCUSDT", HALF, NOW - 110 * DAY, fake_exchange, NOW)
    by = bybit_klines("BTCUSDT", HALF, NOW - 33 * DAY, fake_exchange, NOW)
    for rows in (bn, by):
        assert rows[-1].time == NOW - NOW % HALF
        assert all(b.time - a.time == HALF for a, b in zip(rows, rows[1:]))
    assert len(bn) > 1500 and len(by) > 1000


def test_snapshot_is_strict_json_with_every_section() -> None:
    snap = snapshot(app.fetch(NOW, fake_exchange), NOW)
    body = json.dumps(app.clean(snap), allow_nan=False)
    back = json.loads(body)
    assert back["price"] > 0
    assert set(back["rolling"]) == {"d7", "d30", "d365"} and all(back["rolling"].values())
    assert all(back["calendar"][u] for u in "WMQY")
    assert back["composites"]["daily"] and back["composites"]["weekly"]
    assert back["flow"]["plus_l"] is not None
    assert set(back["traps"]) == {"failed_breakdown", "failed_breakout", "support", "resistance"}
