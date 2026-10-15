"""Does the share of a trap that has unwound predict how much further the response runs?

For each trapped marker (offside_backtest.signals), trapped size = the wick's net delta in coins (Binance BTCUSDT perps).
Unwinding after the marker, bar by bar: trapped longs close as long closes, estimated as max(-NL, 0) with NL = (dOI + D) / 2
(OI from Binance 5m metrics, D = bar net delta); trapped shorts as max(-NS, 0), NS = (dOI - D) / 2. The share unwound after
k bars = cumulative closes / trapped size (an upper bound on the trapped cohort: every closing trader counts).
Then: the move from bar k to bar k + 12 in the trap's direction, split by the unwound share at bar k.
No liquidations here (Binance does not publish their history).
"""
import numpy as np
import polars as pl
from offside_backtest import load, bar_features, signals, oi_series

ohlc, rows = load()
f = bar_features(ohlc, rows)
s = signals(f)
net = f["net"].to_numpy()
oi = oi_series(s["bar"])
c, h, l = s["c"], s["h"], s["l"]
d_oi = np.diff(oi, prepend=np.nan)
nl = (d_oi + net) / 2
ns = (d_oi - net) / 2
n = len(c)
rows_out = []
for side, mask, closes, size in ((-1, s["tl"], np.maximum(-nl, 0), s["up"] / c), (1, s["ts"], np.maximum(-ns, 0), -s["lo"] / c)):
    for k0 in np.where(mask)[0]:
        trapped = size[k0]
        if trapped <= 0 or k0 + 30 >= n:
            continue
        for k in (2, 4, 8):
            done = np.nansum(closes[k0 + 1:k0 + 1 + k]) / trapped
            # still valid: price has not retaken the wick extreme
            ext = h[k0] if side < 0 else l[k0]
            seg = slice(k0 + 1, k0 + 1 + k)
            valid = (h[seg].max() < ext) if side < 0 else (l[seg].min() > ext)
            so_far = side * (c[k0 + k] - c[k0]) / c[k0] * 1e4
            later = side * (c[k0 + k + 12] - c[k0 + k]) / c[k0 + k] * 1e4
            rows_out.append(dict(side="TL" if side < 0 else "TS", k=k, unwound=done, valid=bool(valid), so_far=so_far, later=later, trapped=trapped))
df = pl.DataFrame(rows_out)
print("trapped size (coins): median", round(float(df.filter(pl.col("k") == 4)["trapped"].median()), 1))
for k in (2, 4, 8):
    sub = df.filter((pl.col("k") == k) & pl.col("valid"))
    q = sub["unwound"].quantile(0.33), sub["unwound"].quantile(0.67)
    print(f"\nafter {k} bars, trap still valid (n {sub.height}); unwound share terciles at {q[0]:.0%} / {q[1]:.0%}")
    for name, cond in (("least unwound (fuel left)", pl.col("unwound") <= q[0]), ("middle", (pl.col("unwound") > q[0]) & (pl.col("unwound") <= q[1])), ("most unwound (fuel spent)", pl.col("unwound") > q[1])):
        g = sub.filter(cond)
        x = g["later"].to_numpy()
        t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
        print(f"  {name:28s} n {g.height:4d}  move so far {g['so_far'].mean():+6.1f} bp  next 12 bars {x.mean():+6.1f} bp (t {t:+.1f})  hit {np.mean(x > 0):.0%}")
