"""Synthetic feeds execute the actual M5 tape helpers and close handler via Node.

These checks cover accounting and state transitions, not MMT syntax, feed scheduling,
volume-unit compatibility, rendering, or load performance.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(bars, state=None):
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node.js 18+ is required for the production M5 accounting tests")
    result = subprocess.run(
        [node, str(ROOT / "tests/m5_offside_harness.cjs"), str(ROOT / "indicators/swordfish/swordfish-offside.m5")],
        input=json.dumps({"bars": bars, "state": state or {}}), text=True, capture_output=True, check=False, timeout=10,
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


@pytest.mark.parametrize("missing", ["first_bar", "venue", "side", "misaligned", "late", "overflow"])
def test_incomplete_trade_measurements_are_withheld(missing):
    first = bar(300, 101, [(99, 100, False)], low=98)
    state = {}
    if missing == "first_bar":
        first["candle"]["sellVolume"] = 200
    elif missing == "venue":
        state = {"useChart": False, "lsBb": True}
        first["trades"][0]["venue"] = 0
        first["bb5"] = {"buyVolume": 1, "sellVolume": 0}
    elif missing == "side":
        first["candle"]["buyVolume"] = 1
    elif missing == "misaligned":
        state = {"useChart": False}
        first["trades"][0]["venue"] = 0
        first["bn5"] = {"time": 0}
    elif missing == "late":
        first["trades"][0]["time"] = 0
    else:
        # Exhaust the production 3,000-row capacity while raw candle totals still match.
        first = bar(300, 101, [(99 + i * 0.0102, 1, False) for i in range(3001)], low=98, high=131)
    bars = [first] + [bar(t, 102, [(101, 1, True)]) for t in (600, 900, 1200)]
    event, = run(bars, state)["events"]
    assert not event["tradeOk"]


def test_complete_bar_survives_first_trade_of_next_bar():
    first = bar(300, 101, [(99, 100, False)], low=98)
    first["trades"].append(dict(price=101, size=1, buy=True, time=600))
    # The future trade is not part of the closing candle.
    first["candle"]["buyVolume"] = 0
    bars = [first, bar(600, 102), bar(900, 102, [(101, 1, True)]), bar(1200, 102, [(101, 1, True)])]
    bars[1]["candle"]["buyVolume"] = 1
    event, = run(bars)["events"]
    assert event["tradeOk"]
    assert event["pressed"] == 100


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


@pytest.mark.parametrize("chart,all_venues", [(True, False), (False, False), (False, True)])
def test_complete_selected_venues_are_accepted(chart, all_venues):
    ids = [4] if chart else list(range(3 if all_venues else 2))
    bars = []
    for t in (300, 600, 900, 1200):
        buy = t != 300
        b = bar(t, 101 if t == 300 else 102, low=98 if t == 300 else 99)
        b["trades"] = [dict(price=101 if buy else 99, size=i + 1, buy=buy, venue=i) for i in ids]
        for i, venue in enumerate(("bn5", "bb5", "ok5")):
            b[venue] = {"buyVolume": i + 1 if buy else 0, "sellVolume": 0 if buy else i + 1}
        b["candle"].update(buyVolume=sum(i + 1 for i in ids) if buy else 0,
                           sellVolume=0 if buy else sum(i + 1 for i in ids))
        bars.append(b)
    state = {"useChart": chart, "useAll": all_venues, "lsBb": True, "lsOk": True}
    event, = run(bars, state)["events"]
    assert event["tradeOk"]
    assert event["pressed"] == sum(i + 1 for i in ids)


def test_missing_hold_bar_withholds_whole_trap_trade_readings():
    first = bar(300, 101, [(99, 100, False)], low=98)
    hold = bar(600, 102, [(101, 5, True)])
    hold["candle"]["buyVolume"] = 10
    bars = [first, hold] + [bar(t, 102, [(101, 1, True)]) for t in (900, 1200)]
    event, = run(bars)["events"]
    assert not event["tradeOk"]


def test_pooled_totals_cannot_hide_missing_volume_at_one_venue():
    first = bar(300, 101, low=98)
    # Total is 100 on both tapes and candles, but each venue is wrong by 10.
    first["trades"] = [dict(price=99, size=60, buy=False, venue=0),
                       dict(price=99, size=40, buy=False, venue=1)]
    first["bn5"] = first["bb5"] = {"buyVolume": 0, "sellVolume": 50}
    bars = [first] + [bar(t, 102) for t in (600, 900, 1200)]
    event, = run(bars, {"useChart": False, "lsBb": True})["events"]
    assert not event["tradeOk"]


@pytest.mark.parametrize("cover_pct,ok", [(90, True), (100, False)])
def test_feed_shortfall_within_coverage_setting_is_accepted(cover_pct, ok):
    # MMT's trade feed runs a few percent short of candle volume on some venues (Bybit about 95%).
    first = bar(300, 101, [(99, 95, False)], low=98)
    first["candle"]["sellVolume"] = 100
    bars = [first] + [bar(t, 102, [(101, 1, True)]) for t in (600, 900, 1200)]
    event, = run(bars, {"coverPct": cover_pct})["events"]
    assert event["tradeOk"] is ok
    if ok:
        assert event["pressed"] == 95
        assert abs(event["cover"] - 98 / 103) < 1e-9


@pytest.mark.parametrize("short,ok", [(0.5, True), (3, False)])
def test_small_venue_noise_within_one_percent_of_pooled_volume_is_accepted(short, ok):
    first = bar(300, 101, low=98)
    first["trades"] = [dict(price=99, size=100, buy=False, venue=0),
                       dict(price=99, size=4 - short, buy=False, venue=1)]
    first["bn5"] = {"buyVolume": 0, "sellVolume": 100}
    first["bb5"] = {"buyVolume": 0, "sellVolume": 4}
    bars = [first]
    for t in (600, 900, 1200):
        hold = bar(t, 102)
        hold["trades"] = [dict(price=101, size=1, buy=True, venue=0)]
        hold["bn5"] = {"buyVolume": 1, "sellVolume": 0}
        hold["bb5"] = {"buyVolume": 0, "sellVolume": 0}
        bars.append(hold)
    event, = run(bars, {"useChart": False, "lsBb": True})["events"]
    assert event["tradeOk"] is ok


@pytest.mark.parametrize("traded,ok", [(85, True), (75, False), (105, False)])
def test_size_filtered_trades_must_cover_most_of_the_candle_without_exceeding_it(traded, ok):
    # Trades below the size floor are not loaded, so the tape covers less than the candle.
    first = bar(300, 101, [(99, traded, False)], low=98)
    first["candle"]["sellVolume"] = 100
    bars = [first] + [bar(t, 102, [(101, 1, True)]) for t in (600, 900, 1200)]
    event, = run(bars)["events"]
    assert event["tradeOk"] is ok


def test_trades_below_the_dollar_minimum_count_for_coverage_only():
    # $99 and $9,900 sells below the level; only the larger one is pressing at a $1,000 minimum.
    first = bar(300, 101, [(99, 1, False), (99, 100, False)], low=98)
    bars = [first] + [bar(t, 102, [(101, 20, True)]) for t in (600, 900, 1200)]
    event, = run(bars, {"minUsd": 1000})["events"]
    assert event["tradeOk"]
    assert event["pressed"] == 100
    assert event["cover"] == 1
