"""Swordfish Liquidity Profile: the gap finder and side helpers, run through the generic Node harness.

These cover the arithmetic on the profile's rows, not MMT's rolling profile, scheduling or rendering.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "indicators/swordfish/swordfish-liquidity-profile.m5"


def run(volumes, calls, width=10.0, start=100.0):
    """Rows `width` tall from `start`, each row's volume split evenly between buys and sells."""
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node.js 18+ is required for the production M5 harness tests")
    lows = [start + i * width for i in range(len(volumes))]
    spec = {"blocks": ["fn findGaps(", "fn firstAbove(", "fn insideGap("],
            "context": {"rLo": {"rolling": 200, "items": lows},
                        "rHi": {"rolling": 200, "items": [x + width for x in lows]},
                        "rBuy": {"rolling": 200, "items": [v / 2 for v in volumes]},
                        "rSell": {"rolling": 200, "items": [v / 2 for v in volumes]},
                        "gLo": {"rolling": 64}, "gHi": {"rolling": 64}},
            "calls": calls, "read": ["gLo", "gHi"]}
    result = subprocess.run([node, str(ROOT / "tests/m5_script_harness.cjs"), str(SCRIPT)], input=json.dumps(spec),
                            text=True, capture_output=True, check=False, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def gaps(volumes, thr=10.0, min_height=0.0):
    out = run(volumes, [{"fn": "findGaps", "args": [thr, min_height]}])["read"]
    return list(zip(out["gLo"], out["gHi"]))


def test_a_thin_run_between_heavy_rows_is_a_gap():
    # rows 100-110 ... : heavy, heavy, thin, thin, heavy
    assert gaps([50, 50, 1, 1, 50]) == [(120, 140)]


def test_thin_tails_at_the_top_and_bottom_are_not_gaps():
    assert gaps([1, 1, 50, 50, 1, 1]) == []


def test_each_separate_run_is_its_own_gap():
    assert gaps([50, 1, 50, 1, 1, 50]) == [(110, 120), (130, 150)]


def test_a_run_shorter_than_the_minimum_height_is_ignored():
    assert gaps([50, 1, 50, 1, 1, 50], min_height=15.0) == [(130, 150)]


def test_a_row_exactly_at_the_threshold_is_not_thin():
    assert gaps([50, 10, 50]) == []


def test_no_heavy_rows_means_no_gaps():
    assert gaps([1, 1, 1]) == []


def test_sides_of_price():
    calls = [{"fn": "findGaps", "args": [10.0, 0.0]},
             {"fn": "firstAbove", "args": [105.0]}, {"fn": "insideGap", "args": [105.0]},
             {"fn": "firstAbove", "args": [125.0]}, {"fn": "insideGap", "args": [125.0]},
             {"fn": "firstAbove", "args": [145.0]}, {"fn": "insideGap", "args": [145.0]},
             {"fn": "firstAbove", "args": [175.0]}, {"fn": "insideGap", "args": [175.0]}]
    # gaps 110-120 (index 0) and 130-150 (index 1)
    results = run([50, 1, 50, 1, 1, 50, 50, 50], calls)["results"]
    assert results[1:] == [0, -1, 1, -1, 2, 1, 2, -1]


def swings_spec(periods, calls, read):
    """periods: (t, high, low) oldest first."""
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node.js 18+ is required for the production M5 harness tests")
    spec = {"blocks": ["fn findSwings(", "fn chooseStart("],
            "context": {"pT": {"rolling": 1300, "items": [p[0] for p in periods]},
                        "pH": {"rolling": 1300, "items": [p[1] for p in periods]},
                        "pL": {"rolling": 1300, "items": [p[2] for p in periods]},
                        "swT": {"rolling": 300}, "swP": {"rolling": 300}, "fromT": 0.0, "fromP": 0.0},
            "calls": calls, "read": read}
    result = subprocess.run([node, str(ROOT / "tests/m5_script_harness.cjs"), str(SCRIPT)], input=json.dumps(spec),
                            text=True, capture_output=True, check=False, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


DAY = 86400
# A rise to 200 (day 4), a fall to 150 (day 8), a rise to 180 so far (day 11): 10% swings.
PATH = [(0, 102, 100), (DAY, 120, 110), (2 * DAY, 160, 120), (3 * DAY, 190, 160), (4 * DAY, 200, 190),
        (5 * DAY, 190, 175), (6 * DAY, 175, 160), (7 * DAY, 160, 152), (8 * DAY, 158, 150),
        (9 * DAY, 165, 155), (10 * DAY, 172, 165), (11 * DAY, 180, 172)]


def test_major_swings_alternate_and_exclude_the_running_extreme():
    out = swings_spec(PATH, [{"fn": "findSwings", "args": [0.10]}], ["swT", "swP"])["read"]
    assert out["swP"] == [100, 200, 150]
    assert out["swT"] == [0, 4 * DAY, 8 * DAY]


def test_small_moves_are_not_major_swings():
    flat = [(i * DAY, 101 + (i % 2), 100) for i in range(10)]
    out = swings_spec(flat, [{"fn": "findSwings", "args": [0.10]}], ["swT"])["read"]
    assert out["swT"] == []


@pytest.mark.parametrize("legs,expect_t,expect_p", [(1, 8 * DAY, 150), (2, 4 * DAY, 200), (3, 0, 100)])
def test_lookback_reaches_back_by_legs(legs, expect_t, expect_p):
    out = swings_spec(PATH, [{"fn": "findSwings", "args": [0.10]},
                             {"fn": "chooseStart", "args": [legs, 12 * DAY, DAY]}], ["fromT", "fromP"])["read"]
    assert out == {"fromT": expect_t, "fromP": expect_p}


def test_a_too_recent_swing_steps_back_to_meet_the_minimum_span():
    # One leg back is the day-8 low, 4 days ago; a 7-day minimum steps back to the day-4 high (8 days ago).
    out = swings_spec(PATH, [{"fn": "findSwings", "args": [0.10]},
                             {"fn": "chooseStart", "args": [1, 12 * DAY, 7 * DAY]}], ["fromT", "fromP"])["read"]
    assert out == {"fromT": 4 * DAY, "fromP": 200}


def test_without_enough_swings_the_window_uses_all_available_history():
    out = swings_spec(PATH, [{"fn": "findSwings", "args": [0.10]},
                             {"fn": "chooseStart", "args": [5, 12 * DAY, DAY]}], ["fromT", "fromP"])["read"]
    assert out == {"fromT": 0, "fromP": 0}


def area(volumes):
    node = shutil.which("node")
    lows = [100.0 + i * 10 for i in range(len(volumes))]
    spec = {"blocks": ["fn computeArea("],
            "context": {"rLo": {"rolling": 200, "items": lows}, "rHi": {"rolling": 200, "items": [x + 10 for x in lows]},
                        "rBuy": {"rolling": 200, "items": [v / 2 for v in volumes]},
                        "rSell": {"rolling": 200, "items": [v / 2 for v in volumes]}, "poc": 0.0, "vah": 0.0, "val": 0.0},
            "calls": [{"fn": "computeArea"}], "read": ["poc", "vah", "val"]}
    result = subprocess.run([node, str(ROOT / "tests/m5_script_harness.cjs"), str(SCRIPT)], input=json.dumps(spec),
                            text=True, capture_output=True, check=False, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["read"]


def test_value_area_grows_from_the_point_of_control_to_70_percent():
    # Total 100: POC row 130-140 holds 40; adding 20 (up) then 10 (down) reaches 70.
    assert area([5, 5, 10, 40, 20, 10, 5, 5]) == {"poc": 135, "val": 120, "vah": 150}


def test_value_area_of_a_single_row():
    assert area([10]) == {"poc": 105, "val": 100, "vah": 110}
