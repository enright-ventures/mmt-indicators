"""Workshop-11 traps (failed breakdown / failed breakout with a hold) on Binance BTCUSDT perps, 5m, one year.

Definition (Stable workshop 11, "Trading Failed Breakdowns and Traps"):
- a level that matters: 30m swing lows/highs (5 bars each side), the prior UTC day's low/high, the prior week's low/high;
- the break: a 5m bar trades through the level (by at least `poke` of price);
- the reclaim: a 5m close back on the level's side within `max_break` bars of the first break bar;
- the hold: the next `hold` 5m bars all close on the reclaimed side and none takes out the flush extreme.
  The trigger is the end of the hold (entry at that bar's close), the stop is beyond the flush extreme;
- conviction: reclaim-bar volume against the break bars' average volume ("weak reclaim" when lower);
- who is trapped: new shorts opened during the break, sum of max(NS, 0) with NS = (dOI - D) / 2 (OI from Binance 5m
  metrics, D = taker buy - sell); for a failed breakout, new longs, sum of max(NL, 0);
- pain point: the break bars' VWAP (where the trapped side traded).
A break that stays beyond the level longer than `max_break` bars is acceptance: the level is dropped.
Outcomes: returns from the entry in the trap's direction at 6, 12, 24, 48 bars (30 min to 4 h), and R outcomes with the
stop at the flush extreme, targets 1R and 2R, first touch within 96 bars (8 h; a bar touching both counts as the stop).

Usage: python3 offside_traps.py
"""
import glob
import math
import os

import numpy as np
import polars as pl

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "offside")
M5 = 300


def load():
    k = pl.concat([pl.read_csv(p) for p in sorted(glob.glob(os.path.join(DATA, "k5", "*.csv")))])
    k = k.unique("open_time").sort("open_time")
    t = (k["open_time"].to_numpy() // 1000).astype(np.int64)
    o, h, l, c, v, tb = (k[x].to_numpy().astype(float) for x in ("open", "high", "low", "close", "volume", "taker_buy_volume"))
    d = 2 * tb - v
    files = sorted(glob.glob(os.path.join(DATA, "metrics_*.csv")))
    m = pl.concat([pl.read_csv(p, columns=["create_time", "sum_open_interest"], schema_overrides={"sum_open_interest": pl.Float64}) for p in files])
    m = m.with_columns(pl.col("create_time").str.to_datetime("%Y-%m-%d %H:%M:%S").dt.epoch("s").alias("ts")).unique("ts").sort("ts")
    oi = dict(zip(m["ts"].to_list(), m["sum_open_interest"].to_list()))
    oi_open = np.array([oi.get(int(x), np.nan) for x in t])
    oi_close = np.array([oi.get(int(x) + M5, np.nan) for x in t])
    doi = oi_close - oi_open
    nl = (doi + d) / 2
    ns = (doi - d) / 2
    return dict(t=t, o=o, h=h, l=l, c=c, v=v, d=d, nl=nl, ns=ns)


def swings(t, h, l, n, bucket, side_bars, life_bars, kind):
    """Swing lows/highs on `bucket`-second bars built from 5m bars, side_bars each side; usable once confirmed."""
    out = []
    kb = t // bucket
    starts = np.flatnonzero(np.r_[True, kb[1:] != kb[:-1]])
    ends = np.r_[starts[1:], n]
    H = np.array([h[s:e].max() for s, e in zip(starts, ends)])
    L = np.array([l[s:e].min() for s, e in zip(starts, ends)])
    m = side_bars
    for i in range(m, len(H) - m):
        avail = ends[i + m] if i + m < len(ends) else n
        exp = min(n, avail + life_bars)
        if L[i] < L[i - m:i].min() and L[i] <= L[i + 1:i + m + 1].min():
            out.append((avail, L[i], 1, kind, exp))
        if H[i] > H[i - m:i].max() and H[i] >= H[i + 1:i + m + 1].max():
            out.append((avail, H[i], -1, kind, exp))
    return out


def levels(b, kinds=("swing", "prior day", "prior week")):
    """(available_from_index, price, side, kind, expires_index). side +1 support (traps shorts), -1 resistance."""
    t, h, l = b["t"], b["h"], b["l"]
    n = len(t)
    out = []
    day = 12 * 24
    if "swing" in kinds:
        out += swings(t, h, l, n, 1800, 5, day * 7, "swing")
    if "4h swing" in kinds:
        out += swings(t, h, l, n, 4 * 3600, 3, day * 14, "4h swing")
    if "daily swing" in kinds:
        out += swings(t, h, l, n, 86400, 2, day * 30, "daily swing")
    for period, kind, life, off in ((86400, "prior day", 86400, 0), (7 * 86400, "prior week", 7 * 86400, 4 * 86400),
                                    (None, "prior month", 31 * 86400, 0)):
        if kind not in kinds:
            continue
        if period is None:
            import datetime as dt
            key = np.array([dt.datetime.fromtimestamp(int(x), dt.timezone.utc).year * 12 + dt.datetime.fromtimestamp(int(x), dt.timezone.utc).month for x in t])
        else:
            key = (t + off) // period
        st = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
        en = np.r_[st[1:], n]
        for j in range(1, len(st)):
            s0, e0 = st[j - 1], en[j - 1]
            avail = st[j]
            exp = min(n, avail + life // M5)
            out.append((avail, l[s0:e0].min(), 1, kind, exp))
            out.append((avail, h[s0:e0].max(), -1, kind, exp))
    if "3-day" in kinds:
        key = t // 86400
        st = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
        for j in range(3, len(st)):
            s0, e0 = st[j - 3], st[j]
            exp = min(n, st[j] + day)
            out.append((st[j], l[s0:e0].min(), 1, "3-day", exp))
            out.append((st[j], h[s0:e0].max(), -1, "3-day", exp))
    out.sort(key=lambda x: x[0])
    return out


def find_traps(b, hold=3, max_break=12, poke=0.0003, need_volume=False, kinds=("swing", "prior day", "prior week")):
    t, o, h, l, c, v = b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]
    ns, nl = b["ns"], b["nl"]
    n = len(t)
    lv = levels(b, kinds)
    events, failed = [], []
    active = []  # dicts
    li = 0
    for k in range(n):
        while li < len(lv) and lv[li][0] <= k:
            a, price, side, kind, exp = lv[li]
            active.append(dict(price=price, side=side, kind=kind, exp=exp, state="idle"))
            li += 1
        keep = []
        for s in active:
            if k >= s["exp"] and s["state"] == "idle":
                continue
            L, side = s["price"], s["side"]
            beyond_low = (l[k] < L * (1 - poke)) if side > 0 else (h[k] > L * (1 + poke))
            close_back = (c[k] > L) if side > 0 else (c[k] < L)
            if s["state"] == "idle":
                if beyond_low:
                    s.update(state="break", start=k, flush=(l[k] if side > 0 else h[k]), bars=[k])
                    if close_back:  # broke and reclaimed in the same bar
                        s.update(state="hold", reclaim=k, held=0)
                keep.append(s)
                continue
            if s["state"] == "break":
                s["bars"].append(k)
                s["flush"] = min(s["flush"], l[k]) if side > 0 else max(s["flush"], h[k])
                if close_back:
                    s.update(state="hold", reclaim=k, held=0)
                elif k - s["start"] >= max_break:
                    continue  # accepted beyond the level: drop it
                keep.append(s)
                continue
            if s["state"] == "hold":
                if k == s["reclaim"]:
                    keep.append(s)
                    continue
                broke_flush = (l[k] < s["flush"]) if side > 0 else (h[k] > s["flush"])
                if broke_flush or not close_back:
                    failed.append(dict(k=k, side=side, kind=s["kind"], level=L, why="flush" if broke_flush else "close back"))
                    # back to the break phase while there is time, else drop
                    if k - s["start"] < max_break and not broke_flush:
                        s["state"] = "break"
                        s["bars"].append(k)
                        keep.append(s)
                    continue
                s["held"] += 1
                if s["held"] >= hold:
                    br = [x for x in s["bars"] if x < s["reclaim"]] or [s["start"]]
                    brv = v[br].mean()
                    rv = v[s["reclaim"]]
                    p = (h[br] + l[br] + c[br]) / 3
                    pain = float((p * v[br]).sum() / max(v[br].sum(), 1e-9))
                    trapped = float(np.nansum(np.maximum(ns[br], 0))) if side > 0 else float(np.nansum(np.maximum(nl[br], 0)))
                    doi = float(np.nansum(ns[br] + nl[br]))
                    ev = dict(k=k, side=side, kind=s["kind"], level=L, flush=s["flush"], start=s["start"], reclaim=s["reclaim"],
                              break_bars=len(br), depth=abs(s["flush"] / L - 1), rvol=rv / max(brv, 1e-9), trapped=trapped,
                              doi=doi, pain=pain)
                    if not need_volume or ev["rvol"] >= 1.0:
                        events.append(ev)
                    continue  # level used
                keep.append(s)
                continue
        active = keep
    # one event per side per hour (levels cluster)
    events.sort(key=lambda e: e["k"])
    out, last = [], {1: -10**9, -1: -10**9}
    for e in events:
        if e["k"] - last[e["side"]] >= 12:
            out.append(e)
            last[e["side"]] = e["k"]
    return out, failed


def outcome(b, e, horizons=(6, 12, 24, 48)):
    c, h, l = b["c"], b["h"], b["l"]
    n = len(c)
    k, side = e["k"], e["side"]
    r = {}
    for hz in horizons:
        r[hz] = side * (c[k + hz] - c[k]) / c[k] * 1e4 if k + hz < n else np.nan
    stop = e["flush"]
    risk = abs(c[k] - stop)
    for name, m in (("R1", 1.0), ("R2", 2.0)):
        res = np.nan
        if risk > 0:
            tgt = c[k] + side * m * risk
            for j in range(k + 1, min(n, k + 97)):
                hs = l[j] <= stop if side > 0 else h[j] >= stop
                ht = h[j] >= tgt if side > 0 else l[j] <= tgt
                if hs:
                    res = -1.0
                    break
                if ht:
                    res = m
                    break
            else:
                j = min(n - 1, k + 96)
                res = side * (c[j] - c[k]) / risk
        r[name] = res
    r["risk_bp"] = risk / c[k] * 1e4
    return r


def summarise(b, evs, label):
    if not evs:
        return f"| {label} | 0 |" + " |" * 8
    rs = [outcome(b, e) for e in evs]
    cols = []
    for hz in (6, 12, 24, 48):
        x = np.array([r[hz] for r in rs])
        x = x[~np.isnan(x)]
        t = x.mean() / (x.std(ddof=1) / math.sqrt(len(x))) if len(x) > 2 else float("nan")
        cols.append(f"{x.mean():+.1f} ({t:+.1f})")
    r1 = np.array([r["R1"] for r in rs])
    r2 = np.array([r["R2"] for r in rs])
    hit = np.nanmean(np.array([r[24] for r in rs]) > 0)
    risk = np.nanmedian([r["risk_bp"] for r in rs])
    return (f"| {label} | {len(evs)} | " + " | ".join(cols) + f" | {hit:.0%} | {np.nanmean(r1):+.2f} | {np.nanmean(r1 >= 1):.0%} | {np.nanmean(r2):+.2f} | {risk:.0f} |")


if __name__ == "__main__":
    b = load()
    n = len(b["t"])
    print(f"Binance BTCUSDT perps 5m, {n} bars")
    header = ("| Group | n | +30m | +1h | +2h | +4h | hit 2h | 1R exp | 1R win | 2R exp | median risk bp |\n"
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    print(header)
    # baseline: every 12th bar, long and short
    base = [dict(k=k, side=s, flush=b["l"][k] if s > 0 else b["h"][k]) for k in range(300, n - 100, 12) for s in (1, -1)]
    # baseline R uses a stop the same median distance as traps, set below
    evs, failed = find_traps(b)
    for side, name in ((1, "Trapped shorts (failed breakdown), long"), (-1, "Trapped longs (failed breakout), short")):
        sel = [e for e in evs if e["side"] == side]
        print(summarise(b, sel, name))
        strong = [e for e in sel if e["rvol"] >= 1.0]
        weak = [e for e in sel if e["rvol"] < 1.0]
        print(summarise(b, strong, "  reclaim volume >= break volume"))
        print(summarise(b, weak, "  weak reclaim (wick)"))
        for kind in ("swing", "prior day", "prior week"):
            print(summarise(b, [e for e in sel if e["kind"] == kind], f"  level: {kind}"))
        med = np.median([e["trapped"] for e in sel]) if sel else 0
        print(summarise(b, [e for e in sel if e["trapped"] > med], "  more new positions trapped (above median)"))
        print(summarise(b, [e for e in sel if e["trapped"] <= med], "  fewer trapped (below median)"))
        # baseline with the same median risk distance
        med_risk = np.median([abs(b["c"][e["k"]] - e["flush"]) / b["c"][e["k"]] for e in sel])
        bl = [dict(k=x["k"], side=side, flush=b["c"][x["k"]] * (1 - side * med_risk)) for x in base if x["side"] == side]
        print(summarise(b, bl, "  baseline: every hour, same side, same stop distance"))
    for hold in (1, 6):
        e2, _ = find_traps(b, hold=hold)
        for side, name in ((1, f"Hold {hold * 5} min: trapped shorts"), (-1, f"Hold {hold * 5} min: trapped longs")):
            print(summarise(b, [e for e in e2 if e["side"] == side], name))
    # reclaims that did not hold (no trade per the workshop)
    nf = [dict(k=f["k"], side=f["side"], flush=b["c"][f["k"]] * (1 - f["side"] * 0.003)) for f in failed]
    print(summarise(b, [f for f in nf if f["side"] == 1], "Reclaim failed its hold, long anyway"))
    print(summarise(b, [f for f in nf if f["side"] == -1], "Reclaim failed its hold, short anyway"))
    # higher-timeframe levels only, each kind on its own (levels of one kind do not compete with others)
    print("\nHigher-timeframe levels, each kind run on its own")
    print(header)
    for kind in ("4h swing", "daily swing", "3-day", "prior day", "prior week", "prior month"):
        e3, _ = find_traps(b, kinds=(kind,))
        for side, name in ((1, f"{kind}: trapped shorts, long"), (-1, f"{kind}: trapped longs, short")):
            print(summarise(b, [e for e in e3 if e["side"] == side], name))
    htf = ("4h swing", "daily swing", "3-day", "prior day", "prior week", "prior month")
    e4, _ = find_traps(b, kinds=htf)
    for side, name in ((1, "All HTF levels: trapped shorts, long"), (-1, "All HTF levels: trapped longs, short")):
        sel = [e for e in e4 if e["side"] == side]
        print(summarise(b, sel, name))
        print(summarise(b, [e for e in sel if e["rvol"] >= 1.0], "  reclaim volume >= break volume"))
        med = np.median([e["trapped"] for e in sel]) if sel else 0
        print(summarise(b, [e for e in sel if e["trapped"] > med], "  more new positions trapped"))
        print(summarise(b, [e for e in sel if e["trapped"] <= med], "  fewer trapped"))
    # by quarter
    q = lambda k: f"{(b['t'][k] // 86400)}"
    import datetime as dt
    print("\nBy quarter (+2h mean bp, n)")
    for side in (1, -1):
        rows = {}
        for e in [e for e in evs if e["side"] == side]:
            d = dt.datetime.fromtimestamp(int(b["t"][e["k"]]), dt.timezone.utc)
            key = f"{d.year}-Q{(d.month - 1) // 3 + 1}"
            rows.setdefault(key, []).append(outcome(b, e)[24])
        print("shorts trapped" if side > 0 else "longs trapped", {k: (round(float(np.nanmean(v)), 1), len(v)) for k, v in sorted(rows.items())})
