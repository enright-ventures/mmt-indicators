"""Pooled (Binance + Bybit BTCUSDT perps) rolling VWAPs from the exchanges' REST candles, to check Swordfish Rolling VWAP.

Value at 30m bar T, as the script plots it on the chart: 7D = the 335 closed 30m candles before T plus candle T,
30D = 1,439 before T plus T; 365D = the 364 closed daily candles before T's day plus T's day so far (built from that
day's 30m candles up to T). HLC3 x volume, both venues summed. Usage: python3 rvwap_pooled_ref.py <T unix seconds>...
"""
import json, sys, urllib.request

def get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)

def binance(interval, end_ms, n):
    out = []
    while len(out) < n:
        rows = get(f"https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval={interval}&endTime={end_ms}&limit=1500")
        if not rows: break
        out = [(r[0] // 1000, float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in rows] + out
        end_ms = rows[0][0] - 1
    return {t: (h, l, c, v) for t, h, l, c, v in out}

def bybit(interval, end_ms, n):
    out = []
    while len(out) < n:
        d = get(f"https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval={interval}&end={end_ms}&limit=1000")
        rows = d["result"]["list"]
        if not rows: break
        out += [(int(r[0]) // 1000, float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in rows]
        end_ms = int(rows[-1][0]) - 1
    return {t: (h, l, c, v) for t, h, l, c, v in out}

def pv(k):
    h, l, c, v = k
    return (h + l + c) / 3 * v, v

for T in map(int, sys.argv[1:]):
    end = (T + 1800) * 1000 - 1
    m = [binance("30m", end, 1500), bybit("30", end, 1500)]
    day0 = T - T % 86400
    d = [binance("1d", day0 * 1000 - 1, 370), bybit("D", day0 * 1000 - 1, 370)]
    res = {}
    for name, n in (("7D", 336), ("30D", 1440)):
        weighted_price = volume = 0.0
        for src in m:
            for t in [T - 1800 * i for i in range(n - 1, -1, -1)]:
                a, b = pv(src[t]); weighted_price += a; volume += b
        res[name] = weighted_price / volume
    weighted_price = volume = 0.0
    for src_d, src_m in zip(d, m):
        for t in [day0 - 86400 * i for i in range(364, 0, -1)]:
            a, b = pv(src_d[t]); weighted_price += a; volume += b
        bars = [src_m[t] for t in range(day0, T + 1, 1800)]
        h = max(x[0] for x in bars); l = min(x[1] for x in bars); c = bars[-1][2]; v = sum(x[3] for x in bars)
        a, b = pv((h, l, c, v)); weighted_price += a; volume += b
    res["365D"] = weighted_price / volume
    print(T, {k: round(v, 2) for k, v in res.items()})
