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

from offside_fixed import Bar, Level, find_traps

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
bars = [Bar(int(at), float(hi), float(lo), float(close), float(vol)) for at, hi, lo, close, vol in zip(t, h, l, c, v)]
fixed = [Level(int(a), float(p), int(side), int(expires)) for a, p, side, expires in levels]
start_time = int(dt.datetime.fromisoformat(since).replace(tzinfo=dt.timezone.utc).timestamp()) if since else 0
events = [event for event in find_traps(bars, fixed) if bars[event.index].time >= start_time]
print(" ".join(dt.datetime.fromtimestamp(bars[event.index].time, dt.timezone.utc).strftime("%d%H%M") + ("S" if event.side > 0 else "L") for event in events))
for event in events:
    print(dt.datetime.fromtimestamp(bars[event.index].time, dt.timezone.utc).strftime("%m-%d %H:%M"), "trapped shorts" if event.side > 0 else "trapped longs", "level %.4f flush %.4f" % (event.level, event.flush))
