"""Reference implementation of the kScript "Swordfish Calendar VWAP" period loop.

Prints each enabled period's HLC3 x volume VWAP and sigma the way the wrun port's
Console does, so the two can be compared number for number.

Usage:
  python3 vwap_ref.py fetch                  # ETHUSDT 30m (125 days) and 4h (1400 days) klines
  python3 vwap_ref.py levels [Weekly|Monthly|Quarterly|Yearly] [weeks months quarters years]
"""

import json
import math
import os
import sys

from composites_ref import DATA, civil, fetch_klines, utc_start

HALF, FOUR = 1800, 14400
MODES = ["Weekly", "Monthly", "Quarterly", "Yearly"]


def period_start(ts, mode):
    if mode == 0:
        return (math.floor((math.floor(ts / 86400) + 3) / 7) * 7 - 3) * 86400
    y, m, _ = civil(ts)
    first = 1 if mode == 3 else (math.floor((m - 1) / 3) * 3 + 1 if mode == 2 else m)
    return utc_start(y * 10000 + first * 100 + 1)


def code(mode, ts, age):
    if age == 1:
        return ["pW", "pM", "pQ", "pY"][mode]
    y, m, d = civil(ts)
    if mode == 3:
        return "%d PY" % y
    if mode == 2:
        return "%d Q%d" % (y, math.floor((m - 1) / 3) + 1)
    if mode == 1:
        return "%d M%02d" % (y, m)
    return "Week %02d/%02d/%d" % (d, m, y)


def vwap(rows, start, end, block, strict=True):
    weight = mean = m2 = 0.0
    prior = start - block
    complete = len(rows) > 0 and rows[0][0] <= start
    for row in rows:
        ts = row[0]
        if ts >= end:
            break
        if ts < start:
            continue
        if ts <= prior or (strict and ts != prior + block):
            complete = False
        prior = ts
        price = (row[2] + row[3] + row[4]) / 3
        volume = row[5]
        if not price > 0 or not volume >= 0 or row[2] < row[3]:
            complete = False
        if volume > 0:
            delta = price - mean
            weight += volume
            mean += delta * volume / weight
            m2 += volume * delta * (price - mean)
    if strict and prior != end - block:
        complete = False
    if not (complete and weight > 0):
        return None
    return mean, math.sqrt(max(0.0, m2 / weight))


def levels(short, year, focus_mode, counts):
    """short and year include the forming candle last, as requestBars(anchor: latest) does."""
    reference = short[-1][0]
    out = []
    ends = [period_start(reference, f) for f in range(4)]
    entries = [(f, ends[f], 1) for f in range(4)]
    for f in range(4):
        limit = max(1, min(5 if f == 3 else 12, counts[f]))
        end = period_start(ends[f] - 1, f)
        for age in range(2, limit + 1):
            entries.append((f, end, age))
            end = period_start(end - 1, f)
    for mode, end, age in entries:
        rows, block = (year, FOUR) if mode >= 2 else (short, HALF)
        result = vwap(rows, period_start(end - 1, mode), end, block)
        if result is not None:
            out.append("%s %s sd %s" % (code(mode, period_start(end - 1, mode), age), fmt(result[0]), fmt(result[1])))
    current_rows, block = (year, FOUR) if focus_mode >= 2 else (short, HALF)
    latest = current_rows[-1][0]
    current = vwap(current_rows, period_start(reference, focus_mode), latest + block, block)
    return out, current


def fmt(value):
    """The kScript's priceText: six significant digits, trailing zeros dropped."""
    if value == 0:
        return "0"
    scale = 10 ** max(0, 5 - math.floor(math.log10(abs(value))))
    text = ("%.*f" % (max(0, 5 - math.floor(math.log10(abs(value)))), math.floor(value * scale + 0.5) / scale))
    return text.rstrip("0").rstrip(".") if "." in text else text


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "levels"
    if command == "fetch":
        short = fetch_klines("ETHUSDT", "30m", 125)
        with open(os.path.join(DATA, "ETHUSDT_30m_125d.json"), "w") as handle:
            json.dump(short, handle)
        year = fetch_klines_4h(1400)
        with open(os.path.join(DATA, "ETHUSDT_4h.json"), "w") as handle:
            json.dump(year, handle)
        print(len(short), len(year))
        return
    focus = MODES.index(sys.argv[2]) if len(sys.argv) > 2 else 0
    counts = [int(x) for x in sys.argv[3:7]] if len(sys.argv) > 6 else [4, 3, 4, 2]
    with open(os.path.join(DATA, "ETHUSDT_30m_125d.json")) as handle:
        short = json.load(handle)
    with open(os.path.join(DATA, "ETHUSDT_4h.json")) as handle:
        year = json.load(handle)
    out, current = levels(short, year, focus, counts)
    print("reference forming 30m:", short[-1][0], "4h:", year[-1][0])
    for line in out:
        print(line)
    if current:
        print("current %s VWAP %s sd %s" % (MODES[focus], fmt(current[0]), fmt(current[1])))


def fetch_klines_4h(days):
    import time
    import urllib.request
    end_ms = int(time.time() * 1000)
    cursor = end_ms - days * 86400 * 1000
    rows = []
    while cursor < end_ms:
        url = "https://fapi.binance.com/fapi/v1/klines?symbol=ETHUSDT&interval=4h&limit=1500&startTime=%d" % cursor
        with urllib.request.urlopen(url, timeout=30) as response:
            batch = json.loads(response.read())
        if not batch:
            break
        for k in batch:
            rows.append([k[0] // 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])])
        cursor = batch[-1][0] + FOUR * 1000
        if len(batch) < 1500:
            break
    return rows


if __name__ == "__main__":
    main()
