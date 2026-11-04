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
