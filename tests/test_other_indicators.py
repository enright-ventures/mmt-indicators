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
function unitTf(u) { return 604800; }"""


def calendar(acc, forming, calls):
    spec = {"blocks": ["fn accKey(", "fn currentStat("], "stubs": [POOLED],
            "context": {"strict": True, "accs": {"map": {"binancef|0": acc}},
                        "feeds": {"pairs": [["binancef", {"fast": {"forming": forming}, "slow": {"forming": {}}}]]}},
            "calls": calls}
    return run("swordfish-calendar-vwap.m5", spec)["results"]


def test_a_new_weeks_forming_candle_is_not_added_to_the_week_before():
    # Last week's accumulator: 100 volume at 100, last candle Sunday 23:30. Monday's first forming candle: 100 at 200.
    acc = {"start": PREV_MONDAY, "prior": MONDAY - 1800, "w": 100, "mean": 100, "m2": 0, "ok": True}
    forming = {"time": MONDAY, "high": 200, "low": 200, "close": 200, "volume": 100}
    last_week, this_week = calendar(acc, forming, [{"fn": "currentStat", "args": [0, PREV_MONDAY, False]},
                                                   {"fn": "currentStat", "args": [0, MONDAY, True]}])
    assert last_week["ok"] and last_week["mean"] == 100 and last_week["sigma"] == 0
    assert this_week["ok"] and this_week["mean"] == 200


def test_a_missing_forming_candle_withholds_the_live_period():
    acc = {"start": MONDAY, "prior": MONDAY + 1800, "w": 100, "mean": 100, "m2": 0, "ok": True}
    live, history = calendar(acc, {}, [{"fn": "currentStat", "args": [0, MONDAY, True]},
                                       {"fn": "currentStat", "args": [0, MONDAY, False]}])
    assert not live["ok"]
    assert history["ok"] and history["mean"] == 100


def test_a_stale_forming_candle_withholds_the_live_period():
    # The venue's forming candle is the one already closed: it has stopped advancing.
    acc = {"start": MONDAY, "prior": MONDAY + 1800, "w": 100, "mean": 100, "m2": 0, "ok": True}
    forming = {"time": MONDAY + 1800, "high": 101, "low": 99, "close": 100, "volume": 5}
    live, = calendar(acc, forming, [{"fn": "currentStat", "args": [0, MONDAY, True]}])
    assert not live["ok"]


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


def rolling(spacing, count=335):
    context = {"useBn": True, "useBb": True, "show7": True, "show30": False, "show365": False, "labels": False,
               "chart": {"isLast": True}}
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
    spec = {"blocks": ["on clock.close {"], "stubs": [SNAPSHOTS], "recorders": ["ladder"],
            "context": {"liveSupported": True, "step": 50, "tfSeconds": 1800, "clock": {"time": 120},
                        "context": {"timeframe": 1800}, "peaks": {"rolling": 200, "items": [1000]},
                        "liveGot": 0, "liveWant": 0},
            "calls": [{"fn": "clock_close"}, {"fn": "drawn"}], "read": ["liveGot", "liveWant"]}
    out = run("swordfish-delta-heat.m5", spec)
    rows = sorted(out["results"][1])
    assert rows == [[100, 150, 10 * 125], [200, 250, -100 * 225]]
    assert out["read"] == {"liveGot": 2, "liveWant": 3}
