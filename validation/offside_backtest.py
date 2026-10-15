"""Backtest of Swordfish Offside's trapped-wick markers on Binance BTCUSDT perps, 30m, from offside_rows.py output.

Replicates the MMT script (mmt/swordfish-offside.m5) rule for rule:
- rows on a grid of `step` (auto: 1/2/2.5/5 x 10^n nearest above 0.06% of price, chosen per calendar month here, as
  if the chart were loaded at the start of each month), row dollars = net delta x row middle;
- ref = average of the previous 200 bars' largest |row dollars|, markers only after 20 bars;
- trapped longs: upper wick >= wickMin of the range and net dollars in rows whose middle is above the body >= mult x ref;
  trapped shorts: the mirror on the lower wick;
- OI+: open interest at the bar's close above its value oiBars bars earlier (Binance metrics, 5m sum_open_interest);
- div: the bar makes a new high (low) of the previous 20 bars, the earlier extreme at least 3 bars back, while
  cumulative delta is below (above) its value then.
Liquidations are not available historically from Binance, so the "liq" confirmation is not tested here.

Usage: python3 offside_backtest.py [--xcheck]
  --xcheck compares markers with the MMT run on binancef (data/offside/mmt_xcheck_binancef.json, $50 rows).
"""
import glob
import json
import math
import os
import sys

import numpy as np
import polars as pl

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "offside")
BAR_MS = 1_800_000
BAR_S = 1800


def nice_step(target: float) -> float:
    magnitude = 10.0 ** math.floor(math.log10(target))
    n = target / magnitude
    return magnitude * (1.0 if n <= 1 else 2.0 if n <= 2 else 2.5 if n <= 2.5 else 5.0 if n <= 5 else 10.0)


def load():
    ohlc = pl.concat([pl.read_parquet(p) for p in sorted(glob.glob(os.path.join(DATA, "ohlc_*.parquet")))])
    rows = pl.concat([pl.read_parquet(p) for p in sorted(glob.glob(os.path.join(DATA, "rows_*.parquet")))])
    ohlc = ohlc.unique("bar").sort("bar")
    rows = rows.group_by(["bar", "row10"]).agg(pl.col("buy").sum(), pl.col("sell").sum())
    return ohlc, rows


def bar_features(ohlc: pl.DataFrame, rows: pl.DataFrame, fixed_step: float | None = None) -> pl.DataFrame:
    # step per calendar month from that month's first close
    o = ohlc.with_columns(pl.from_epoch(pl.col("bar") * BAR_S, time_unit="s").dt.strftime("%Y-%m").alias("month"))
    if fixed_step:
        o = o.with_columns(pl.lit(fixed_step).alias("step"))
    else:
        first = o.group_by("month").agg(pl.col("close").sort_by("bar").first().alias("c0"))
        first = first.with_columns(pl.col("c0").map_elements(lambda c: nice_step(c * 0.0006), return_dtype=pl.Float64).alias("step"))
        o = o.join(first.select("month", "step"), on="month")
    r = rows.join(o.select("bar", "step", "open", "close"), on="bar")
    r = r.with_columns(((pl.col("row10") * 10.0) / pl.col("step") + 1e-9).floor().alias("row"))
    r = r.group_by(["bar", "row"]).agg(pl.col("buy").sum(), pl.col("sell").sum(), pl.col("step").first(),
                                      pl.col("open").first(), pl.col("close").first())
    r = r.with_columns(
        ((pl.col("row") + 0.5) * pl.col("step")).alias("mid"),
        (pl.col("buy") - pl.col("sell")).alias("delta"),
    ).with_columns((pl.col("delta") * pl.col("mid")).alias("usd"))
    top = pl.max_horizontal("open", "close")
    low = pl.min_horizontal("open", "close")
    f = r.group_by("bar").agg(
        pl.col("usd").abs().filter((pl.col("buy") + pl.col("sell")) > 0).max().alias("biggest"),
        pl.col("usd").filter(pl.col("mid") > top).sum().alias("up_usd"),
        pl.col("usd").filter(pl.col("mid") < low).sum().alias("low_usd"),
        pl.col("delta").sum().alias("net"),
    )
    return o.join(f, on="bar", how="left").sort("bar").fill_null(0.0)


def oi_series(bars: np.ndarray) -> np.ndarray:
    files = sorted(glob.glob(os.path.join(DATA, "metrics_*.csv")))
    m = pl.concat([pl.read_csv(p, columns=["create_time", "sum_open_interest"],
                               schema_overrides={"sum_open_interest": pl.Float64}) for p in files])
    m = m.with_columns(pl.col("create_time").str.to_datetime("%Y-%m-%d %H:%M:%S").dt.epoch("s").alias("t")).sort("t")
    t = m["t"].to_numpy()
    v = m["sum_open_interest"].to_numpy()
    ends = (bars + 1) * BAR_S
    i = np.searchsorted(t, ends, side="right") - 1
    out = np.where((i >= 0) & (ends - t[np.clip(i, 0, None)] <= 900), v[np.clip(i, 0, None)], np.nan)
    return out


def signals(f: pl.DataFrame, wick_min=0.35, mult=3.0, oi_bars=5, div_look=20, memory=200):
    bar = f["bar"].to_numpy()
    o, h, l, c = (f[k].to_numpy() for k in ("open", "high", "low", "close"))
    big, up, lo, net = (f[k].to_numpy() for k in ("biggest", "up_usd", "low_usd", "net"))
    oi = oi_series(bar)
    n = len(bar)
    ref = np.full(n, np.nan)
    tl = np.zeros(n, bool)
    ts = np.zeros(n, bool)
    oi_up = np.zeros(n, bool)
    bear = np.zeros(n, bool)
    bull = np.zeros(n, bool)
    wick_up = np.zeros(n)
    wick_lo = np.zeros(n)
    cvd = np.cumsum(net)
    for k in range(n):
        if k >= 20:
            ref[k] = big[max(0, k - memory):k].mean()
        if k > oi_bars and not np.isnan(oi[k]) and not np.isnan(oi[k - oi_bars]):
            oi_up[k] = oi[k] > oi[k - oi_bars]
        a = max(0, k - div_look)
        if k - a >= 4:
            hs, ls, cs = h[a:k], l[a:k], cvd[a:k]
            m = len(hs)
            top, bot = hs.max(), ls.min()
            for i in range(m - 2):
                if hs[i] == top and h[k] > top and cvd[k] < cs[i]:
                    bear[k] = True
                if ls[i] == bot and l[k] < bot and cvd[k] > cs[i]:
                    bull[k] = True
        rng = h[k] - l[k]
        if rng > 0:
            wick_up[k] = (h[k] - max(o[k], c[k])) / rng
            wick_lo[k] = (min(o[k], c[k]) - l[k]) / rng
        if k >= 20 and rng > 0:
            tl[k] = wick_up[k] >= wick_min and up[k] >= mult * ref[k]
            ts[k] = wick_lo[k] >= wick_min and -lo[k] >= mult * ref[k]
    return dict(bar=bar, o=o, h=h, l=l, c=c, ref=ref, up=up, lo=lo, tl=tl, ts=ts, oi_up=oi_up, bear=bear, bull=bull,
                wick_up=wick_up, wick_lo=wick_lo)


def outcomes(s, idx, side, horizons=(1, 2, 4, 8, 16, 48)):
    """side -1 = short (trapped longs), +1 = long (trapped shorts). Entry at the marker bar's close."""
    c, h, l = s["c"], s["h"], s["l"]
    n = len(c)
    res = {f"r{hz}": [] for hz in horizons}
    res.update(R1=[], R2=[], mfe8=[], mae8=[])
    for k in idx:
        for hz in horizons:
            res[f"r{hz}"].append(side * (c[k + hz] - c[k]) / c[k] * 1e4 if k + hz < n else np.nan)
        # stop at the wick extreme, targets 1R and 2R, first touch within 48 bars (same bar: stop first)
        stop = h[k] if side < 0 else l[k]
        risk = abs(stop - c[k])
        for name, mult in (("R1", 1.0), ("R2", 2.0)):
            out = np.nan
            if risk > 0:
                tgt = c[k] + side * mult * risk
                for j in range(k + 1, min(n, k + 49)):
                    hit_stop = h[j] >= stop if side < 0 else l[j] <= stop
                    hit_tgt = l[j] <= tgt if side < 0 else h[j] >= tgt
                    if hit_stop:
                        out = -1.0
                        break
                    if hit_tgt:
                        out = mult
                        break
                else:
                    j = min(n - 1, k + 48)
                    out = side * (c[j] - c[k]) / risk
            res[name].append(out)
        w = slice(k + 1, min(n, k + 9))
        if k + 1 < n:
            res["mfe8"].append(side * ((l[w].min() if side < 0 else h[w].max()) - c[k]) / c[k] * 1e4)
            res["mae8"].append(-side * ((h[w].max() if side < 0 else l[w].min()) - c[k]) / c[k] * 1e4)
    return {k: np.array(v, float) for k, v in res.items()}


def summarise(name, s, idx, side):
    if len(idx) == 0:
        return {"group": name, "n": 0}
    r = outcomes(s, idx, side)
    row = {"group": name, "n": len(idx)}
    for hz in (1, 2, 4, 8, 16, 48):
        x = r[f"r{hz}"][~np.isnan(r[f"r{hz}"])]
        row[f"mean{hz}"] = x.mean()
        row[f"t{hz}"] = x.mean() / (x.std(ddof=1) / math.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else np.nan
        row[f"hit{hz}"] = (x > 0).mean()
    for name2 in ("R1", "R2"):
        x = r[name2][~np.isnan(r[name2])]
        row[f"{name2}_exp"] = x.mean()
        row[f"{name2}_win"] = (x >= (1.0 if name2 == "R1" else 2.0)).mean()
    row["mfe8"] = np.nanmean(r["mfe8"])
    row["mae8"] = np.nanmean(r["mae8"])
    return row


def report(s):
    n = len(s["bar"])
    allidx = np.arange(20, n - 1)
    tl, ts = np.where(s["tl"])[0], np.where(s["ts"])[0]
    groups = []
    groups.append(summarise("All bars, short", s, allidx, -1))
    groups.append(summarise("All bars, long", s, allidx, 1))
    groups.append(summarise("Trapped longs (short)", s, tl, -1))
    groups.append(summarise("  with OI+", s, tl[s["oi_up"][tl]], -1))
    groups.append(summarise("  without OI+", s, tl[~s["oi_up"][tl]], -1))
    groups.append(summarise("  with div", s, tl[s["bear"][tl]], -1))
    wick_only_up = np.where((s["wick_up"] >= 0.35) & ~s["tl"])[0]
    wick_only_up = wick_only_up[wick_only_up >= 20]
    groups.append(summarise("Control: upper wick >= 35%, no trap", s, wick_only_up, -1))
    groups.append(summarise("Trapped shorts (long)", s, ts, 1))
    groups.append(summarise("  with OI+", s, ts[s["oi_up"][ts]], 1))
    groups.append(summarise("  without OI+", s, ts[~s["oi_up"][ts]], 1))
    groups.append(summarise("  with div", s, ts[s["bull"][ts]], 1))
    wick_only_lo = np.where((s["wick_lo"] >= 0.35) & ~s["ts"])[0]
    wick_only_lo = wick_only_lo[wick_only_lo >= 20]
    groups.append(summarise("Control: lower wick >= 35%, no trap", s, wick_only_lo, 1))
    both = np.concatenate([tl, ts])
    sides = np.concatenate([-np.ones(len(tl)), np.ones(len(ts))])
    return groups, both, sides


def fmt(groups):
    lines = ["| Group | n | 1 bar | 2 bars | 4 bars | 8 bars | 16 bars | 48 bars | hit 8 | 1R exp | 1R win | 2R exp | MFE 8 | MAE 8 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for g in groups:
        if g["n"] == 0:
            lines.append(f"| {g['group']} | 0 |" + " |" * 12)
            continue
        cell = lambda hz: f"{g[f'mean{hz}']:+.1f} ({g[f't{hz}']:+.1f})"
        lines.append(f"| {g['group']} | {g['n']} | {cell(1)} | {cell(2)} | {cell(4)} | {cell(8)} | {cell(16)} | {cell(48)} | "
                     f"{g['hit8']:.0%} | {g['R1_exp']:+.2f} | {g['R1_win']:.0%} | {g['R2_exp']:+.2f} | {g['mfe8']:.0f} | {g['mae8']:.0f} |")
    return "\n".join(lines)


def xcheck():
    ohlc, rows = load()
    j = json.load(open(os.path.join(DATA, "mmt_xcheck_binancef.json")))["data"]["series"]
    ser = {x["label"]: {int(t) - BAR_S: v for t, v in x["points"]} for x in j}  # close-handler plots sit at bar end
    lo_t = min(min(ser["xTL"]), min(ser["xTS"]))
    f = bar_features(ohlc, rows, fixed_step=50.0)
    start = int(f["bar"][0])
    # MMT started its run at its first snapshot bar (2026-09-24 03:30 UTC); start the replica there too
    first_mmt = 1790220600
    f = f.filter(pl.col("bar") * BAR_S >= first_mmt)
    s = signals(f)
    py_tl = {int(b) * BAR_S: u for b, u, x in zip(s["bar"], s["up"], s["tl"]) if x}
    py_ts = {int(b) * BAR_S: u for b, u, x in zip(s["bar"], s["lo"], s["ts"]) if x}
    py_ref = {int(b) * BAR_S: r for b, r in zip(s["bar"], s["ref"])}
    out = []
    for name, mm, py in (("trapped longs", ser["xTL"], py_tl), ("trapped shorts", ser["xTS"], py_ts)):
        both = sorted(set(mm) & set(py))
        out.append(f"{name}: MMT {len(mm)}, replica {len(py)}, both {len(both)}, MMT only {sorted(set(mm) - set(py))}, replica only {sorted(set(py) - set(mm))}")
        if both:
            d = [abs(py[t] / mm[t] - 1) for t in both]
            out.append(f"  wick dollars: median |diff| {np.median(d):.2%}, max {max(d):.2%}")
    d = [abs(py_ref[t] / v - 1) for t, v in ser["xRef"].items() if t in py_ref]
    out.append(f"ref (typical largest row): median |diff| {np.median(d):.2%}, max {max(d):.2%} over {len(d)} marker bars")
    return "\n".join(out), lo_t, start


if __name__ == "__main__":
    if "--xcheck" in sys.argv:
        text, _, _ = xcheck()
        print(text)
        sys.exit()
    ohlc, rows = load()
    f = bar_features(ohlc, rows)
    s = signals(f)
    first = pl.from_epoch(pl.Series([int(s["bar"][0]) * BAR_S]), time_unit="s")[0]
    last = pl.from_epoch(pl.Series([int(s["bar"][-1]) * BAR_S]), time_unit="s")[0]
    print(f"Binance BTCUSDT perps 30m, {first} to {last}, {len(s['bar'])} bars; trapped longs {s['tl'].sum()}, trapped shorts {s['ts'].sum()}")
    groups, _, _ = report(s)
    print(fmt(groups))
    # sensitivity: thresholds
    print("\nSensitivity (8-bar mean bp, t-stat, n): wick x mult")
    for w in (0.25, 0.35, 0.5):
        cells = []
        for m in (1.0, 2.0, 3.0, 5.0):
            ss = signals(f, wick_min=w, mult=m)
            g1 = summarise("tl", ss, np.where(ss["tl"])[0], -1)
            g2 = summarise("ts", ss, np.where(ss["ts"])[0], 1)
            cells.append(f"x{m:g}: TL {g1.get('mean8', float('nan')):+.1f} ({g1.get('t8', float('nan')):+.1f}, {g1['n']}) "
                         f"TS {g2.get('mean8', float('nan')):+.1f} ({g2.get('t8', float('nan')):+.1f}, {g2['n']})")
        print(f"wick {w:.2f}: " + " | ".join(cells))
    # stability: by quarter
    print("\nBy quarter (8-bar mean bp, n)")
    q = pl.from_epoch(pl.Series(s["bar"] * BAR_S), time_unit="s").dt.strftime("%Y-Q").to_numpy()
    qq = np.array([f"{x}{(int(m) - 1) // 3 + 1}" for x, m in zip(q, pl.from_epoch(pl.Series(s["bar"] * BAR_S), time_unit="s").dt.month().to_numpy())])
    for quarter in sorted(set(qq)):
        sel = qq == quarter
        a = np.where(s["tl"] & sel)[0]
        b = np.where(s["ts"] & sel)[0]
        base = np.where(sel)[0]
        base = base[(base >= 20) & (base < len(sel) - 9)]
        g1, g2, g0 = summarise("", s, a, -1), summarise("", s, b, 1), summarise("", s, base, 1)
        print(f"{quarter}: TL {g1.get('mean8', float('nan')):+.1f} (n {g1['n']}) | TS {g2.get('mean8', float('nan')):+.1f} (n {g2['n']}) | all bars long {g0.get('mean8', float('nan')):+.1f}")
