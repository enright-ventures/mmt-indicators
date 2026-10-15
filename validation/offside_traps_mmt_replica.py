"""Replica of Swordfish Offside's trap engine (4h swing levels), to cross-check MMT event by event.

Mirrors the MMT script: swing levels from 4h bars (3 each side, usable from the 7th bar's close for 14 days); a fixed
side level breaks only from the right side (previous 5m close beyond it); hold = 3 closes; reclaim within 12 bars;
one trap per side per hour. Usage: python3 offside_traps_mmt_replica.py <data dir with k5/ and m/> [from YYYY-MM-DD]
Prints events as DDHHmm + S/L (S = trapped shorts), the confirming 5m bar's open time, UTC.
"""
import datetime as dt
import glob
import os
import sys

import numpy as np
import polars as pl

d = sys.argv[1]
since = sys.argv[2] if len(sys.argv) > 2 else None
k = pl.concat([pl.read_csv(p) for p in sorted(glob.glob(os.path.join(d, "k5", "*.csv")))]).unique("open_time").sort("open_time")
t = (k["open_time"].to_numpy() // 1000).astype(np.int64)
o, h, l, c, v, tb = (k[x].to_numpy().astype(float) for x in ("open", "high", "low", "close", "volume", "taker_buy_volume"))
n = len(t)
# 4h bars
k4 = t // 14400
st = np.flatnonzero(np.r_[True, k4[1:] != k4[:-1]])
en = np.r_[st[1:], n]
H = np.array([h[s:e].max() for s, e in zip(st, en)])
L = np.array([l[s:e].min() for s, e in zip(st, en)])
levels = []  # (avail_index, price, side, expires_unix)
for i in range(3, len(H) - 3):
    avail = en[i + 3] if i + 3 < len(en) else n
    exp = (k4[st[i + 3]] * 14400) + 14400 + 14 * 86400
    if L[i] < L[i - 3:i].min() and L[i] <= L[i + 1:i + 4].min():
        levels.append((avail, L[i], 1, exp))
    if H[i] > H[i - 3:i].max() and H[i] >= H[i + 1:i + 4].max():
        levels.append((avail, H[i], -1, exp))
levels.sort()
poke, hold, reclaim = 0.0003, 3, 12
active, events, li = [], [], 0
last = {1: -1e18, -1: -1e18}
start_k = 0
if since:
    start_k = int(np.searchsorted(t, int(dt.datetime.fromisoformat(since).replace(tzinfo=dt.timezone.utc).timestamp())))
for j in range(1, n):
    while li < len(levels) and levels[li][0] <= j:
        a, p, s, e = levels[li]
        if not any(x["state"] != 3 and abs(x["p"] / p - 1) < 0.0002 and x["side"] == s for x in active):
            active.append(dict(p=p, side=s, exp=e, state=0))
        li += 1
    for x in active:
        if x["state"] == 3:
            continue
        P, s = x["p"], x["side"]
        if x["state"] == 0:
            if t[j] >= x["exp"]:
                x["state"] = 3
                continue
            down = s >= 0 and c[j - 1] > P and l[j] < P * (1 - poke)
            up = s <= 0 and c[j - 1] < P and h[j] > P * (1 + poke)
            dr = 1 if down else -1 if up else 0
            if dr:
                x.update(state=1, dir=dr, flush=l[j] if dr > 0 else h[j], bars=1, held=0)
                if (c[j] > P) if dr > 0 else (c[j] < P):
                    x["state"] = 2
            continue
        dr = x["dir"]
        back = (c[j] > P) if dr > 0 else (c[j] < P)
        x["bars"] += 1
        if x["state"] == 1:
            x["flush"] = min(x["flush"], l[j]) if dr > 0 else max(x["flush"], h[j])
            if back:
                x.update(state=2, held=0)
            elif x["bars"] > reclaim:
                x["state"] = 3
        else:
            flushed = (l[j] < x["flush"]) if dr > 0 else (h[j] > x["flush"])
            if flushed or not back:
                if not flushed and x["bars"] <= reclaim:
                    x["state"] = 1
                else:
                    x["state"] = 3
            else:
                x["held"] += 1
                if x["held"] >= hold:
                    x["state"] = 3
                    if t[j] - last[dr] >= 3600:
                        last[dr] = t[j]
                        if j >= start_k:
                            events.append((t[j], dr, P, x["flush"]))
print(" ".join(dt.datetime.fromtimestamp(int(a), dt.timezone.utc).strftime("%d%H%M") + ("S" if s > 0 else "L") for a, s, p, f in events))
for a, s, p, f in events:
    print(dt.datetime.fromtimestamp(int(a), dt.timezone.utc).strftime("%m-%d %H:%M"), "trapped shorts" if s > 0 else "trapped longs", "level %.4f flush %.4f" % (p, f))
