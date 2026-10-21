"""Calendar VWAP, Rolling VWAP and Delta Heat: production blocks run through the generic Node harness with stubbed feeds.

These cover period boundaries, feed freshness and time coverage, not MMT syntax, scheduling or rendering. The cases
follow the review of 21 October 2026 (other indicators).
"""
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "indicators/swordfish"
MONDAY = int(dt.datetime(2026, 10, 19, tzinfo=dt.timezone.utc).timestamp())
PREV_MONDAY = MONDAY - 7 * 86400


def run(script, spec):
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node.js 18+ is required for the production M5 harness tests")
    result = subprocess.run([node, str(ROOT / "tests/m5_script_harness.cjs"), str(SCRIPTS / script)],
                            input=json.dumps(spec), text=True, capture_output=True, check=False, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# ---------------------------------------------------------------- Calendar VWAP

POOLED = """function pooled(w, s1, q, ok, missing) {
  const mean = w > 0 ? s1 / w : 0;
  return {ok: ok && missing == 0 && w > 0, w, mean, sigma: w > 0 ? Math.sqrt(Math.max(0, q / w - mean * mean)) : 0, missing};
}
function block(u) { return u < 2 ? 1800 : 14400; }
function unitTf(u) { return 604800; }
function tf(s) { return {"30m": 1800, "4h": 14400}[s]; }"""


def calendar(acc, forming, calls, more=()):
    """One venue (binancef) by default; `more` adds (exchange, accumulator, forming) venues."""
    venues = [("binancef", acc, forming), *more]
    spec = {"blocks": ["fn accKey(", "fn currentStat("], "stubs": [POOLED],
            "context": {"strict": True, "slowTf": 14400,
                        "accs": {"map": {f"{ex}|0": a for ex, a, _ in venues}},
                        "feeds": {"pairs": [[ex, {"fast": {"forming": f}, "slow": {"forming": {}}}] for ex, _, f in venues]}},
            "calls": calls}
    return run("swordfish-calendar-vwap.m5", spec)["results"]


def test_a_new_weeks_forming_candle_is_not_added_to_the_week_before():
    # Last week's accumulator: 100 volume at 100, last candle Sunday 23:30. Monday's first forming candle: 100 at 200.
    acc = {"start": PREV_MONDAY, "prior": MONDAY - 1800, "w": 100, "mean": 100, "m2": 0, "ok": True}
    forming = {"time": MONDAY, "high": 200, "low": 200, "close": 200, "volume": 100}
    last_week, this_week = calendar(acc, forming, [{"fn": "currentStat", "args": [0, PREV_MONDAY, None]},
                                                   {"fn": "currentStat", "args": [0, MONDAY, MONDAY]}])
    assert last_week["ok"] and last_week["mean"] == 100 and last_week["sigma"] == 0
    assert this_week["ok"] and this_week["mean"] == 200


def test_a_missing_forming_candle_withholds_the_live_period():
    acc = {"start": MONDAY, "prior": MONDAY + 1800, "w": 100, "mean": 100, "m2": 0, "ok": True}
    live, history = calendar(acc, {}, [{"fn": "currentStat", "args": [0, MONDAY, MONDAY + 3600]},
                                       {"fn": "currentStat", "args": [0, MONDAY, None]}])
    assert not live["ok"]
    assert history["ok"] and history["mean"] == 100


def test_a_stale_forming_candle_withholds_the_live_period():
    # The venue's forming candle is the one already closed: it has stopped advancing.
    acc = {"start": MONDAY, "prior": MONDAY + 1800, "w": 100, "mean": 100, "m2": 0, "ok": True}
    forming = {"time": MONDAY + 1800, "high": 101, "low": 99, "close": 100, "volume": 5}
    live, = calendar(acc, forming, [{"fn": "currentStat", "args": [0, MONDAY, MONDAY + 3600]}])
    assert not live["ok"]


def candle(t, price=100, volume=10):
    return {"time": t, "high": price, "low": price, "close": price, "volume": volume}


def test_a_venue_lagging_behind_now_withholds_the_live_period():
    # PR #4 review: at 03:00 Binance is current; Bybit's last closed candle is 00:00 and its forming 00:30, a pair that
    # looks continuous on its own but is 150 minutes behind.
    now = MONDAY + 3 * 3600
    bn = {"start": MONDAY, "prior": now - 1800, "w": 100, "mean": 100, "m2": 0, "ok": True}
    bb = {"start": MONDAY, "prior": MONDAY, "w": 100, "mean": 125, "m2": 0, "ok": True}
    live, = calendar(bn, candle(now), [{"fn": "currentStat", "args": [0, MONDAY, now]}],
                     more=[("bybitf", bb, candle(MONDAY + 1800, 125))])
    assert not live["ok"]


def test_a_frozen_single_venue_withholds_the_live_period():
    now = MONDAY + 3 * 3600
    acc = {"start": MONDAY, "prior": MONDAY, "w": 100, "mean": 100, "m2": 0, "ok": True}
    live, = calendar(acc, candle(MONDAY + 1800), [{"fn": "currentStat", "args": [0, MONDAY, now]}])
    assert not live["ok"]


def test_current_venues_show_the_live_period():
    now = MONDAY + 3 * 3600
    bn = {"start": MONDAY, "prior": now - 1800, "w": 100, "mean": 100, "m2": 0, "ok": True}
    bb = {"start": MONDAY, "prior": now - 1800, "w": 100, "mean": 100, "m2": 0, "ok": True}
    live, = calendar(bn, candle(now), [{"fn": "currentStat", "args": [0, MONDAY, now]}],
                     more=[("bybitf", bb, candle(now))])
    assert live["ok"] and live["mean"] == 100


# ---------------------------------------------------------------- Rolling VWAP

FEED = """function feed(times) {
  for (const t of times) {
    bnM = {time: t, high: 101, low: 99, close: 100, volume: 1};
    bbM = {time: t, high: 101, low: 99, close: 100, volume: 1};
    bnM_close();
    bbM_close();
  }
}
function live(t) {
  const c = {time: t, high: 101, low: 99, close: 100, volume: 1};
  bnM = {...bnM, forming: c};
  bbM = {...bbM, forming: c};
  bnD = {forming: {}};
  bbD = {forming: {}};
  chart_update();
}"""


def rolling(spacing, count=335, chart_ahead=0, single=False):
    """`chart_ahead`: how many 30m intervals the chart's forming bar is past the source's forming candle."""
    context = {"useBn": True, "useBb": not single, "show7": True, "show30": False, "show365": False, "labels": False,
               "clockT": 0.0}
    for p in "ab":
        for n, cap in (("7", 335), ("30", 1439), ("365", 364)):
            context[f"{p}Pv{n}"] = {"rolling": cap}
            context[f"{p}V{n}"] = {"rolling": cap}
            context[f"{p}Spv{n}"] = 0.0
            context[f"{p}Sv{n}"] = 0.0
        for s in "MD":
            context[f"{p}Last{s}"] = 0.0
            context[f"{p}Run{s}"] = 0
    times = [MONDAY + i * spacing for i in range(count)]
    context["chart"] = {"isLast": True, "forming": {"time": times[-1] + 1800 * (1 + chart_ahead)}}
    spec = {"blocks": ["fn pvOf(", "fn secs(", "fn fresh(", "fn pooled(", "on bnM.close {", "on bbM.close {",
                       "on chart.update {"],
            "stubs": [FEED], "context": context, "recorders": ["line7", "line30", "line365"],
            "calls": [{"fn": "feed", "args": [times]}, {"fn": "live", "args": [times[-1] + 1800]}]}
    return run("swordfish-rolling-vwap.m5", spec)["plots"]["line7"][-1]


def test_seven_day_window_shows_when_its_candles_are_consecutive():
    assert rolling(1800) == 100


def test_seven_day_window_is_withheld_when_candles_are_missing():
    # 335 candles an hour apart span about 14 days: not a 7-day VWAP.
    assert rolling(3600) is None


def test_venues_frozen_together_are_withheld():
    # PR #4 review: both venues' last closed/forming pairs agree, but the chart has moved a 30m interval past them.
    assert rolling(1800, chart_ahead=1) is None


def test_a_stale_single_venue_is_withheld():
    assert rolling(1800, single=True) == 100
    assert rolling(1800, chart_ahead=1, single=True) is None


# ---------------------------------------------------------------- Delta Heat

SNAPSHOTS = """const rows = [];
function row(lo, hi, usd) { rows.push([lo, hi, usd]); }
function snap(t, lo, hi, delta) {
  return {time: t, length: 1, get: i => ({from: lo, to: hi, delta: delta, total: Math.abs(delta)})};
}
// newest first: minute 2 (+10 coins at 100-150), minute 1 missing, minute 0 (-100 coins at 200-250)
const snaps = [snap(120, 100, 150, 10), null, snap(0, 200, 250, -100)];
minutes = {bucketsByStep: (step, back) => snaps[back] ?? null};
function drawn() { return rows; }"""


def test_live_ladder_keeps_minutes_before_a_missing_one_and_reports_coverage():
    spec = {"blocks": ["fn drawLive(", "on clock.close {"], "stubs": [SNAPSHOTS], "recorders": ["ladder"],
            "context": {"liveSupported": True, "step": 50, "tfSeconds": 1800, "clock": {"time": 120},
                        "peaks": {"rolling": 200, "items": [1000]}, "liveGot": 0, "liveWant": 0,
                        "tStep": 0.0, "tm0": -1.0, "tm1": -1.0},
            "calls": [{"fn": "clock_close"}, {"fn": "drawn"}], "read": ["liveGot", "liveWant"]}
    out = run("swordfish-delta-heat.m5", spec)
    rows = sorted(out["results"][1])
    assert rows == [[100, 150, 10 * 125], [200, 250, -100 * 225]]
    assert out["read"] == {"liveGot": 2, "liveWant": 3}


LIVE = """const rows = [];
function row(lo, hi, usd) { rows.push([lo, hi, usd]); }
function snap(t, lo, hi, delta) {
  return {time: t, length: 1, get: i => ({from: lo, to: hi, delta: delta, total: Math.abs(delta)})};
}
let snaps = [];
minutes = {bucketsByStep: (step, back) => snaps[back] ?? null};
function setSnaps(list) { snaps = list.map(s => s && snap(...s)); }
function trade(p, sz, buy, t) { rows.length = 0; onLiveTrade(p, sz, buy, t); return rows.map(r => r.slice()); }"""

LIVE_CONTEXT = {"liveSupported": True, "step": 50, "tfSeconds": 1800, "peaks": {"rolling": 200, "items": [1000]},
                "liveGot": 0, "liveWant": 0, "tStep": 0.0, "lastLiveSec": 0.0, "tm0": -1.0, "tm1": -1.0,
                "td0": {"map": {}}, "tv0": {"map": {}}, "tk0": {"rolling": 4096},
                "td1": {"map": {}}, "tv1": {"map": {}}, "tk1": {"rolling": 4096}}


def live(calls):
    spec = {"blocks": ["fn drawLive(", "fn onLiveTrade("], "stubs": [LIVE], "recorders": ["ladder"],
            "context": LIVE_CONTEXT, "calls": calls, "read": ["liveGot", "liveWant"]}
    return run("swordfish-delta-heat.m5", spec)


def test_minute_in_progress_comes_from_live_trades():
    # Minute 0 has a snapshot (-100 coins at 200-250); minute 1 is in progress, so only its live trades exist.
    out = live([{"fn": "setSnaps", "args": [[None, [0, 200, 250, -100]]]},
                {"fn": "trade", "args": [120, 10, True, 75]}])
    assert sorted(out["results"][1]) == [[100, 150, 10 * 125], [200, 250, -100 * 225]]
    assert out["read"] == {"liveGot": 2, "liveWant": 2}


def test_a_minutes_snapshot_replaces_its_live_trades_without_double_counting():
    # Minute 1's trades (+10) were live; its snapshot (+12, the full minute) then arrives, while minute 2 trades +1.
    out = live([{"fn": "setSnaps", "args": [[None, [0, 200, 250, -100]]]},
                {"fn": "trade", "args": [120, 10, True, 75]},
                {"fn": "setSnaps", "args": [[None, [60, 100, 150, 12], [0, 200, 250, -100]]]},
                {"fn": "trade", "args": [130, 1, True, 125]}])
    assert sorted(out["results"][3]) == [[100, 150, 13 * 125], [200, 250, -100 * 225]]
    assert out["read"] == {"liveGot": 3, "liveWant": 3}


def test_live_ladder_redraws_at_most_once_a_second():
    out = live([{"fn": "setSnaps", "args": [[None]]},
                {"fn": "trade", "args": [120, 1, True, 75]},
                {"fn": "trade", "args": [120, 1, True, 75]},
                {"fn": "trade", "args": [120, 1, True, 76]}])
    assert out["results"][1] != [] and out["results"][2] == [] and out["results"][3] == [[100, 150, 3 * 125]]
