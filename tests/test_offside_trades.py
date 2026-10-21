"""Synthetic feeds execute the actual M5 helpers and 5m close handler via Node; each bar's 5m volume profile is built
from its listed trades, summed by price.

These checks cover accounting and state transitions, not MMT syntax, feed scheduling,
rendering, or load performance.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(bars, state=None, calls=None, read=None):
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node.js 18+ is required for the production M5 accounting tests")
    result = subprocess.run(
        [node, str(ROOT / "tests/m5_offside_harness.cjs"), str(ROOT / "indicators/swordfish/swordfish-offside.m5")],
        input=json.dumps({"bars": bars, "state": state or {}, "calls": calls or [], "read": read or []}), text=True,
        capture_output=True, check=False, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def bar(t, close, trades=(), low=99, high=103, **extra):
    return {"time": t, "trades": [dict(price=p, size=s, buy=b) for p, s, b in trades],
            "candle": {"close": close, "low": low, "high": high,
                       "buyVolume": sum(s for _, s, b in trades if b),
                       "sellVolume": sum(s for _, s, b in trades if not b)}, **extra}


@pytest.mark.parametrize("side", [1, -1])
def test_only_successful_reclaim_and_hold_supply_back_volume(side):
    bars = [bar(300, 99, [(99, 100, False)], low=98),
            bar(600, 99, [(101, 400, True)], low=98),
            bar(900, 101, [(101, 100, True)])]
    bars += [bar(t, 102, [(101, 10, True), (99, 1, False)]) for t in (1200, 1500, 1800)]
    state = {}
    if side < 0:
        state = {"lvSide": [-1], "prevC5": 99}
        for b in bars:
            c = b["candle"]
            c["high"], c["low"], c["close"] = 200 - c["low"], 200 - c["high"], 200 - c["close"]
            c["buyVolume"], c["sellVolume"] = c["sellVolume"], c["buyVolume"]
            for tr in b["trades"]:
                tr["price"], tr["buy"] = 200 - tr["price"], not tr["buy"]
    event, = run(bars, state)["events"]
    assert event["tradeOk"]
    assert event["pressed"] == 100  # Hold-bar pressing does not enter the denominator.
    assert event["back"] == 130  # Excludes the 400 traded before the reclaim.
    assert event["fill"] == (99 if side > 0 else 101)


def test_failed_reclaim_volume_does_not_leak_into_next_attempt():
    bars = [bar(300, 99, [(99, 100, False)], low=98),
            bar(600, 101, [(101, 500, True)]),
            bar(900, 102, [(101, 200, True)]),
            bar(1200, 99, [(99, 50, False)]),
            bar(1500, 101, [(101, 100, True)])]
    bars += [bar(t, 102, [(101, 10, True)]) for t in (1800, 2100, 2400)]
    event, = run(bars)["events"]
    assert event["pressed"] == 150
    assert event["back"] == 130


@pytest.mark.parametrize("qty", [0, 1, 100])
def test_counterflow_never_ends_price_tracking(qty):
    state = {"showTraps": False, "fSide": [1], "fLive": [True], "fDone": [0],
             "fFlowOk": [True], "fCounterOk": [True], "fNet": [0], "fQty": [qty],
             "fLvl": [100], "fExt": [98], "fWick": [False], "fTime": [0], "fStatus": ["holding"]}
    result = run([bar(300, 102, [(101, 1000, True)])], state)
    assert result["fDone"] == [500]
    assert result["fLive"] == [True]
    assert result["fStatus"] == ["holding"]


@pytest.mark.parametrize("close,low,t", [(99, 99, 300), (102, 97, 300), (102, 99, 86400)])
def test_price_failure_flush_and_expiry_still_end_tracking(close, low, t):
    state = {"showTraps": False, "fSide": [1], "fLive": [True], "fDone": [0],
             "fFlowOk": [True], "fCounterOk": [True], "fNet": [0], "fQty": [1],
             "fLvl": [100], "fExt": [98], "fWick": [False], "fTime": [0]}
    assert run([bar(t, close, low=low)], state)["fLive"] == [False]


def test_missing_hold_bar_withholds_whole_trap_trade_readings():
    first = bar(300, 101, [(99, 100, False)], low=98)
    hold = bar(600, 102, [(101, 5, True)])
    hold["profile"] = False
    bars = [first, hold] + [bar(t, 102, [(101, 1, True)]) for t in (900, 1200)]
    event, = run(bars)["events"]
    assert not event["tradeOk"]


# Review of 21 October 2026, findings 1-5.

def test_opposite_side_aggression_cannot_pull_trades_across_the_level():
    # Finding 4: a big buy just below support and a sell just above it share a 0.01% row; only the sell at 98 is
    # genuinely below the level.
    first = bar(300, 101, [(99.995, 1000, True), (100.002, 100, False), (98, 1, False)], low=98)
    bars = [first] + [bar(t, 102, [(101, 1, True)]) for t in (600, 900, 1200)]
    event, = run(bars)["events"]
    assert event["tradeOk"]
    assert event["pressed"] == 1


def test_a_missing_5m_bar_drops_the_break():
    # Finding 2: break at 300, nothing until a reclaim at 7500 (two hours later), then three holds: no trap.
    bars = [bar(300, 99, [(99, 10, False)], low=98), bar(7500, 101, [(101, 1, True)])]
    bars += [bar(t, 102, [(101, 1, True)]) for t in (7800, 8100, 8400)]
    assert run(bars)["events"] == []


def test_unready_bar_resets_flow_weighted_prices():
    # Finding 5: a bar without aligned feeds clears the +L/+S weights instead of carrying them over the gap.
    seeded = {"lQty": 100, "lCost": 10000, "sQty": 50, "sCost": 5000}
    out = run([], seeded, calls=[{"fn": "flowStep", "args": [False, 0, 0, 100, 1]}],
              read=["lQty", "lCost", "sQty", "sCost"])
    assert out["read"] == {"lQty": 0, "lCost": 0, "sQty": 0, "sCost": 0}
    out = run([], seeded, calls=[{"fn": "flowStep", "args": [True, 10, -25, 110, 1]}],
              read=["lQty", "lCost", "sQty", "sCost"])
    assert out["read"] == {"lQty": 110, "lCost": 11100, "sQty": 25, "sCost": 2500}


@pytest.mark.parametrize("bybit_time,oi_time,ready", [(600, 600, True), (300, 600, False), (600, 300, False)])
def test_live_export_needs_every_venue_and_open_interest_on_the_bar(bybit_time, oi_time, ready):
    # Finding 1: Bybit still on the previous bar (or stale open interest) must not be summed as current.
    state = {"useChart": False, "lsBb": True,
             "bnC": {"forming": {"time": 600, "buyVolume": 200, "sellVolume": 0}},
             "bbC": {"forming": {"time": bybit_time, "buyVolume": 0, "sellVolume": 400}},
             "oiAgg": {"forming": {"time": oi_time, "open": 10, "close": 10}}}
    out = run([], state, calls=[{"fn": "liveFlowReady", "args": [600]}])
    assert out["calls"] == [ready]


@pytest.mark.parametrize("profile", ["missing", "misaligned"])
def test_a_break_bar_without_its_profile_withholds_the_readings(profile):
    first = bar(300, 101, [(99, 100, False)], low=98)
    first.update({"profile": False} if profile == "missing" else {"profileTime": 0})
    bars = [first] + [bar(t, 102, [(101, 1, True)]) for t in (600, 900, 1200)]
    event, = run(bars)["events"]
    assert not event["tradeOk"]


def test_volume_at_the_level_counts_on_neither_side():
    # Sells exactly at the support price are not "below" it; buys exactly at it are not "back above".
    first = bar(300, 101, [(100, 50, False), (99, 10, False)], low=98)
    bars = [first] + [bar(t, 102, [(100, 5, True), (101, 1, True)]) for t in (600, 900, 1200)]
    event, = run(bars)["events"]
    assert event["tradeOk"]
    assert event["pressed"] == 10
    assert event["back"] == 3


# PR #5 review: pooled profiles are not clipped to the chart candle, and the average uses native level prices.

@pytest.mark.parametrize("side", [1, -1])
def test_pooled_volume_outside_the_chart_candle_still_counts(side):
    # Support at 100 (or resistance at 100, mirrored). The chart candle ranges 98-103, but another selected venue sold
    # 100 at 97.5; in the holds the chart ranges 100-103 while the pool also bought 10 at 104.
    m = (lambda p: p) if side > 0 else (lambda p: 200 - p)
    first = bar(300, m(101), low=98 if side > 0 else 97, high=103 if side > 0 else 102)
    first["levels"] = [(m(97.5), 0, 100) if side > 0 else (m(97.5), 100, 0), (m(99), 0, 1) if side > 0 else (m(99), 1, 0)]
    holds = []
    for t in (600, 900, 1200):
        h = bar(t, m(102), low=100 if side > 0 else 97, high=103 if side > 0 else 100)
        h["levels"] = [(m(101), 1, 0), (m(104), 10, 0)] if side > 0 else [(m(101), 0, 1), (m(104), 0, 10)]
        holds.append(h)
    state = {} if side > 0 else {"lvSide": [-1], "prevC5": 99}
    event, = run([first] + holds, state)["events"]
    assert event["tradeOk"]
    assert event["pressed"] == 101
    assert event["back"] == 33
    assert event["fill"] == pytest.approx((97.5 * 100 + 99) / 101 if side > 0 else (102.5 * 100 + 101) / 101)


def test_average_fill_uses_native_level_prices_inside_a_bin():
    # Support at 100.5 inside the $2.50 bin [100, 102.5): 10 sold at the native level 100 is below the support, and
    # its average is 100, not a bin midpoint above the support.
    first = bar(300, 101, [(100, 10, False)], low=99)
    bars = [first] + [bar(t, 102, [(101, 1, True)]) for t in (600, 900, 1200)]
    event, = run(bars, {"lvP": [100.5]})["events"]
    assert event["tradeOk"]
    assert event["pressed"] == 10
    assert event["fill"] == 100
