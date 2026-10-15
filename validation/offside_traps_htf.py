"""Workshop-11 traps at higher-timeframe VWAP levels, as the Swordfish Calendar VWAP draws them (Binance BTCUSDT perps 5m,
Jan 2025 to Oct 2026). Same trap rules as offside_traps_levels.two_sided_traps.

Levels (HLC3 x volume of 5m bars, weighted mean and SD, point in time):
- prior week / month / quarter / year: VWAP, VAH (+1 SD), VAL (-1 SD), active through the following period;
- older quarters: the 2nd to 4th quarter back, VWAP/VAH/VAL, active through the current quarter;
- developing week / month / quarter / year: VWAP and +/-1 SD so far, snapshotted at each UTC day start and held for the
  day (they move slowly; the 5m-level move inside a day is ignored);
- weekly composites VAH/VAL (newest 4) and daily composites VAH/VAL, for comparison.
Each group is shown for the whole period and for each half (split 2025-12-01), so consistency can be read directly.
"""
import datetime as dt
import math

import numpy as np

from offside_traps import load, summarise, swings
from offside_traps_levels import composite_levels, two_sided_traps, DAY_BARS


def period_keys(t, unit):
    if unit == "week":
        return (t + 4 * 86400) // (7 * 86400)
    d = [dt.datetime.fromtimestamp(int(x), dt.timezone.utc) for x in t]
    if unit == "month":
        return np.array([x.year * 12 + x.month - 1 for x in d])
    if unit == "quarter":
        return np.array([x.year * 4 + (x.month - 1) // 3 for x in d])
    return np.array([x.year for x in d])


def vwap_sd(b, s, e):
    p = (b["h"][s:e] + b["l"][s:e] + b["c"][s:e]) / 3
    w = b["v"][s:e]
    if w.sum() <= 0:
        return None
    m = (p * w).sum() / w.sum()
    return m, math.sqrt((w * (p - m) ** 2).sum() / w.sum())


def calendar_levels(b, unit, keys_cache={}):
    """prior (one back), older (2-4 back, quarter only) and developing levels for a calendar unit."""
    t = b["t"]
    n = len(t)
    if unit not in keys_cache:
        keys_cache[unit] = period_keys(t, unit)
    key = keys_cache[unit]
    st = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    en = np.r_[st[1:], n]
    prior, older, dev = [], [], []
    stats = []
    for s, e in zip(st, en):
        stats.append(vwap_sd(b, s, e))
    for j in range(1, len(st)):
        for back, bucket in ((1, prior), (2, older), (3, older), (4, older)):
            if j - back < 0 or stats[j - back] is None:
                continue
            if back > 1 and unit != "quarter":
                continue
            # skip a first period that does not start at its calendar start (data begins mid-period)
            if j - back == 0 and unit != "week" and dt.datetime.fromtimestamp(int(t[st[0]]), dt.timezone.utc).day != 1:
                continue
            m, sd = stats[j - back]
            for name, val in (("VWAP", m), ("VAH", m + sd), ("VAL", m - sd)):
                bucket.append((st[j], en[j], val, f"{unit} back {back} {name}"))
    # developing, snapshot at each day start
    day = t // 86400
    ds = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    de = np.r_[ds[1:], n]
    pstart = {}
    for s in st:
        pstart[key[s]] = s
    for s, e in zip(ds, de):
        p0 = pstart[key[s]]
        if s - p0 < DAY_BARS:  # at least a day into the period
            continue
        r = vwap_sd(b, p0, s)
        if r is None:
            continue
        m, sd = r
        for name, val in (("VWAP", m), ("VAH", m + sd), ("VAL", m - sd)):
            dev.append((s, e, val, f"developing {unit} {name}"))
    return prior, older, dev


def row(b, evs, label, split):
    first = [e for e in evs if e["k"] < split]
    second = [e for e in evs if e["k"] >= split]
    return [summarise(b, evs, label), summarise(b, first, "    first half"), summarise(b, second, "    second half")]


if __name__ == "__main__":
    b = load()
    n = len(b["t"])
    split = int(np.searchsorted(b["t"], int(dt.datetime(2025, 12, 1, tzinfo=dt.timezone.utc).timestamp())))
    print(f"Binance BTCUSDT perps 5m, {dt.datetime.fromtimestamp(int(b['t'][0]), dt.timezone.utc):%Y-%m-%d} to "
          f"{dt.datetime.fromtimestamp(int(b['t'][-1]), dt.timezone.utc):%Y-%m-%d}, {n} bars; halves split 2025-12-01")
    print("| Group | n | +30m | +1h | +2h | +4h | hit 2h | 1R exp | 1R win | 2R exp | median risk bp |\n"
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    sets = {}
    for unit in ("week", "month", "quarter", "year"):
        prior, older, dev = calendar_levels(b, unit)
        sets[f"prior {unit} VWAP"] = [x for x in prior if x[3].endswith("VWAP")]
        sets[f"prior {unit} VAH/VAL"] = [x for x in prior if not x[3].endswith("VWAP")]
        if older:
            sets[f"older quarters (2-4 back) VWAP + VAH/VAL"] = older
        sets[f"developing {unit} VWAP"] = [x for x in dev if x[3].endswith("VWAP")]
        sets[f"developing {unit} VAH/VAL"] = [x for x in dev if not x[3].endswith("VWAP")]
    sets["weekly composite VAH/VAL"] = [x for x in composite_levels(b, "Weekly") if x[3].endswith(("VAH", "VAL"))]
    sets["daily composite VAH/VAL"] = [x for x in composite_levels(b, "Daily") if x[3].endswith(("VAH", "VAL"))]
    sets["4h swing"] = [(a, e, p, k) for a, p, s, k, e in swings(b["t"], b["h"], b["l"], n, 4 * 3600, 3, DAY_BARS * 14, "4h swing")]
    allhtf = []
    for name, lv in sets.items():
        evs = two_sided_traps(b, lv)
        if name.startswith(("prior", "older", "developing")):
            allhtf += lv
        print(f"| **{name}** ({len(lv)} level-periods) |" + " |" * 10)
        for side, lab in ((1, "failed breakdown, long"), (-1, "failed breakout, short")):
            sel = [e for e in evs if e["side"] == side]
            for line in row(b, sel, "  " + lab, split):
                print(line)
    evs = two_sided_traps(b, allhtf)
    print(f"| **all calendar VWAP levels together** ({len(allhtf)} level-periods) |" + " |" * 10)
    for side, lab in ((1, "failed breakdown, long"), (-1, "failed breakout, short")):
        sel = [e for e in evs if e["side"] == side]
        for line in row(b, sel, "  " + lab, split):
            print(line)
        first = [e for e in sel if e["k"] < split]
        med = np.median([e["trapped"] for e in first]) if first else 0
        print(summarise(b, [e for e in sel if e["k"] >= split and e["trapped"] > med], f"    second half, more trapped (first-half median {med:,.0f} BTC)"))
