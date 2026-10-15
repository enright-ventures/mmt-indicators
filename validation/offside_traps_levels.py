"""Workshop-11 traps at composite VAH/VAL and weekly VWAP levels (Binance BTCUSDT perps, 5m, one year).

Same trap rules as offside_traps.py (break by >= 0.03%, 5m close back within 60 min, 15-min hold, stop beyond the flush,
entry at the hold's last close). These levels can be approached from either side, so the side is set by the break:
a level price was above and broke under is a failed breakdown (trapped shorts) if reclaimed and held, and the mirror.
A level accepted on the other side (break longer than 60 min) re-arms for the other direction.

Levels, point in time (only data available at the time):
- composite VAH / VAL / POC: Swordfish Composites (composites_ref.kscript_composites, the validated method), Daily
  (30-day window) recomputed at each UTC day start, Weekly (13-week window) at each week start; the newest 4 composites
  (the indicator's rays) are the levels until the next recompute;
- prior week VWAP and +/-1 SD (HLC3 x volume of last week's 5m bars), active through the current week;
- developing weekly VWAP: price closes on one side for at least `lean` bars, then closes back through and holds 3 bars
  (workshop 11's late-session VWAP reclaim after a full day on the other side). Stop = the extreme of the 12 bars before.
"""
import datetime as dt
import math
import sys

import numpy as np

import composites_ref as cr
from offside_traps import load, outcome, summarise, swings

M5 = 300
DAY_BARS = 288


def brackets_30m(b):
    t = b["t"]
    k30 = t // 1800
    st = np.flatnonzero(np.r_[True, k30[1:] != k30[:-1]])
    en = np.r_[st[1:], len(t)]
    return [[int(k30[s] * 1800), float(b["o"][s]), float(b["h"][s:e].max()), float(b["l"][s:e].min()), float(b["c"][e - 1]), float(b["v"][s:e].sum())]
            for s, e in zip(st, en)], st


def composite_levels(b, cadence):
    """[(from_index, to_index, price, kind)] for the newest 4 composites' VAH/VAL/POC, recomputed per period."""
    br, st30 = brackets_30m(b)
    t = b["t"]
    n = len(t)
    period = 86400 if cadence == "Daily" else 7 * 86400
    off = 0 if cadence == "Daily" else 4 * 86400
    key = (t + off) // period
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    ends = np.r_[starts[1:], n]
    out = []
    bi = 0
    for s, e in zip(starts, ends):
        # brackets strictly before this period start, plus a stand-in forming bracket at the start
        while bi < len(br) and br[bi][0] < t[s]:
            bi += 1
        if bi < 48 * 8:
            continue
        hist = br[:bi] + [[int(t[s]), b["o"][s], b["o"][s], b["o"][s], b["o"][s], 0.0]]
        res = cr.kscript_composites(hist, cadence=cadence)
        if not res or res["fault"]:
            continue
        step = res["row_price"]
        for p in res["completed"][-4:]:
            for name, val in (("VAH", p.vah), ("VAL", p.val), ("POC", p.poc)):
                out.append((s, e, val * step, f"{cadence.lower()} composite {name}"))
    return out


def prior_week_vwap_levels(b):
    t, h, l, c, v = b["t"], b["h"], b["l"], b["c"], b["v"]
    n = len(t)
    key = (t + 4 * 86400) // (7 * 86400)
    st = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    en = np.r_[st[1:], n]
    out = []
    for j in range(1, len(st)):
        s0, e0 = st[j - 1], en[j - 1]
        p = (h[s0:e0] + l[s0:e0] + c[s0:e0]) / 3
        w = v[s0:e0]
        m = (p * w).sum() / w.sum()
        sd = math.sqrt((w * (p - m) ** 2).sum() / w.sum())
        for name, val in (("VWAP", m), ("VAH", m + sd), ("VAL", m - sd)):
            out.append((st[j], en[j], val, f"prior week {name}"))
    return out


def two_sided_traps(b, levels, hold=3, max_break=12, poke=0.0003):
    """levels: (from, to, price, kind). Returns trap events like offside_traps.find_traps."""
    t, h, l, c, v, ns, nl = b["t"], b["h"], b["l"], b["c"], b["v"], b["ns"], b["nl"]
    n = len(t)
    levels = sorted(levels)
    events = []
    active = []
    li = 0
    for k in range(1, n):
        while li < len(levels) and levels[li][0] <= k:
            f, to, price, kind = levels[li]
            active.append(dict(price=price, kind=kind, to=to, state="idle"))
            li += 1
        keep = []
        for s in active:
            if k >= s["to"] and s["state"] == "idle":
                continue
            L = s["price"]
            if s["state"] == "idle":
                if c[k - 1] > L and l[k] < L * (1 - poke):
                    s.update(state="break", side=1, start=k, flush=l[k], bars=[k])
                elif c[k - 1] < L and h[k] > L * (1 + poke):
                    s.update(state="break", side=-1, start=k, flush=h[k], bars=[k])
                else:
                    keep.append(s)
                    continue
                if (c[k] > L) if s["side"] > 0 else (c[k] < L):
                    s.update(state="hold", reclaim=k, held=0)
                keep.append(s)
                continue
            side = s["side"]
            close_back = (c[k] > L) if side > 0 else (c[k] < L)
            if s["state"] == "break":
                s["bars"].append(k)
                s["flush"] = min(s["flush"], l[k]) if side > 0 else max(s["flush"], h[k])
                if close_back:
                    s.update(state="hold", reclaim=k, held=0)
                elif k - s["start"] >= max_break:
                    s["state"] = "idle"  # accepted on the other side: re-arm for the other direction
                keep.append(s)
                continue
            if s["state"] == "hold":
                if k == s["reclaim"]:
                    keep.append(s)
                    continue
                broke_flush = (l[k] < s["flush"]) if side > 0 else (h[k] > s["flush"])
                if broke_flush or not close_back:
                    if k - s["start"] < max_break and not broke_flush:
                        s["state"] = "break"
                        s["bars"].append(k)
                    else:
                        s["state"] = "idle"
                    keep.append(s)
                    continue
                s["held"] += 1
                if s["held"] >= hold:
                    br = [x for x in s["bars"] if x < s["reclaim"]] or [s["start"]]
                    trapped = float(np.nansum(np.maximum(ns[br], 0))) if side > 0 else float(np.nansum(np.maximum(nl[br], 0)))
                    events.append(dict(k=k, side=side, kind=s["kind"], level=L, flush=s["flush"], trapped=trapped,
                                       rvol=v[s["reclaim"]] / max(v[br].mean(), 1e-9)))
                    continue  # level used
                keep.append(s)
        active = keep
    events.sort(key=lambda e: e["k"])
    out, last = [], {1: -10**9, -1: -10**9}
    for e in events:
        if e["k"] - last[e["side"]] >= 12:
            out.append(e)
            last[e["side"]] = e["k"]
    return out


def vwap_reclaim(b, lean=144, hold=3):
    """Developing weekly VWAP: lean bars closed on one side, then a close through and a hold."""
    t, h, l, c, v = b["t"], b["h"], b["l"], b["c"], b["v"]
    n = len(t)
    key = (t + 4 * 86400) // (7 * 86400)
    vw = np.empty(n)
    pv = vol = 0.0
    for k in range(n):
        if k == 0 or key[k] != key[k - 1]:
            pv = vol = 0.0
        p = (h[k] + l[k] + c[k]) / 3
        pv += p * v[k]
        vol += v[k]
        vw[k] = pv / vol if vol > 0 else c[k]
    events = []
    below = above = 0
    k = 1
    while k < n - hold:
        if c[k - 1] < vw[k - 1]:
            below += 1
            above = 0
        else:
            above += 1
            below = 0
        side = 0
        if below >= lean and c[k] > vw[k]:
            side = 1
        elif above >= lean and c[k] < vw[k]:
            side = -1
        if side:
            flush = l[max(0, k - 12):k + 1].min() if side > 0 else h[max(0, k - 12):k + 1].max()
            ok = True
            for j in range(k + 1, k + 1 + hold):
                if (c[j] <= vw[j] or l[j] < flush) if side > 0 else (c[j] >= vw[j] or h[j] > flush):
                    ok = False
                    break
            if ok:
                events.append(dict(k=k + hold, side=side, kind="weekly VWAP reclaim", level=vw[k], flush=flush, trapped=0.0, rvol=1.0))
                below = above = 0
                k += hold + 1
                continue
        k += 1
    return events


if __name__ == "__main__":
    b = load()
    header = ("| Group | n | +30m | +1h | +2h | +4h | hit 2h | 1R exp | 1R win | 2R exp | median risk bp |\n"
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    print(header)
    sets = {}
    sets["daily composite VAH/VAL"] = [x for x in composite_levels(b, "Daily") if x[3].endswith(("VAH", "VAL"))]
    sets["weekly composite VAH/VAL"] = [x for x in composite_levels(b, "Weekly") if x[3].endswith(("VAH", "VAL"))]
    sets["daily composite POC"] = [x for x in composite_levels(b, "Daily") if x[3].endswith("POC")]
    sets["prior week VWAP"] = [x for x in prior_week_vwap_levels(b) if x[3].endswith("VWAP")]
    sets["prior week VAH/VAL"] = [x for x in prior_week_vwap_levels(b) if not x[3].endswith("VWAP")]
    # 4h swing levels as two-sided ranges for comparison with the earlier run
    n = len(b["t"])
    sw = swings(b["t"], b["h"], b["l"], n, 4 * 3600, 3, DAY_BARS * 14, "4h swing")
    sets["4h swing (reference)"] = [(a, e, p, k) for a, p, s, k, e in sw]
    all_evs = {}
    for name, lv in sets.items():
        evs = two_sided_traps(b, lv)
        all_evs[name] = evs
        print(f"| **{name}** ({len(lv)} level-periods) |" + " |" * 10)
        for side, lab in ((1, "trapped shorts (failed breakdown), long"), (-1, "trapped longs (failed breakout), short")):
            sel = [e for e in evs if e["side"] == side]
            print(summarise(b, sel, "  " + lab))
            if sel:
                med = np.median([e["trapped"] for e in sel])
                print(summarise(b, [e for e in sel if e["trapped"] > med], "    more new positions trapped"))
    for lean in (72, 144, 288):
        evs = vwap_reclaim(b, lean=lean)
        print(f"| **developing weekly VWAP, {lean * 5 // 60}h on one side then reclaim + 15 min hold** |" + " |" * 10)
        for side, lab in ((1, "reclaim from below (trapped shorts), long"), (-1, "loss from above (trapped longs), short")):
            print(summarise(b, [e for e in evs if e["side"] == side], "  " + lab))
