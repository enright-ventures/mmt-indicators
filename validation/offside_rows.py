"""Build 30m x $10 price-row taker buy/sell volume for Binance BTCUSDT perps from data.binance.vision aggTrades.

Usage: python3 offside_rows.py 2025-10 2025-11 ...      (monthly files)
       python3 offside_rows.py 2026-10-01 2026-10-02 ...  (daily files)

Writes data/offside/rows_<period>.parquet (bar, row10, buy, sell) and data/offside/ohlc_<period>.parquet
(bar, open, high, low, close) and deletes the downloaded zip and CSV. bar = open time in ms // 1,800,000.
Taker side: is_buyer_maker true means the aggressor sold. Also fetches the daily metrics files (5m open interest)
for the same days into data/offside/metrics_<day>.csv.
"""
import calendar
import os
import subprocess
import sys
import zipfile

import polars as pl

BASE = "https://data.binance.vision/data/futures/um"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "offside")
TMP = os.environ.get("OFFSIDE_TMP", "/tmp")
BAR_MS = 1_800_000


def fetch(url: str, path: str) -> bool:
    r = subprocess.run(["curl", "-sf", "-o", path, url])
    return r.returncode == 0 and os.path.exists(path)


def build(period: str) -> None:
    rows_path = os.path.join(OUT, f"rows_{period}.parquet")
    if os.path.exists(rows_path):
        print(period, "already built", flush=True)
        return
    kind = "monthly" if len(period) == 7 else "daily"
    name = f"BTCUSDT-aggTrades-{period}"
    zpath = os.path.join(TMP, name + ".zip")
    if not fetch(f"{BASE}/{kind}/aggTrades/BTCUSDT/{name}.zip", zpath):
        print(period, "download failed", flush=True)
        return
    with zipfile.ZipFile(zpath) as z:
        member = z.namelist()[0]
        z.extract(member, TMP)
    os.remove(zpath)
    cpath = os.path.join(TMP, member)
    with open(cpath) as f:
        has_header = not f.readline()[0].isdigit()
    cols = ["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id", "transact_time", "is_buyer_maker"]
    df = pl.scan_csv(cpath, has_header=has_header, new_columns=cols if not has_header else None,
                     schema_overrides={"price": pl.Float64, "quantity": pl.Float64, "transact_time": pl.Int64})
    maker = pl.col("is_buyer_maker").cast(pl.Utf8).str.to_lowercase() == "true"
    df = df.with_columns(
        (pl.col("transact_time") // BAR_MS).alias("bar"),
        (pl.col("price") / 10.0).floor().cast(pl.Int64).alias("row10"),
        pl.when(maker).then(0.0).otherwise(pl.col("quantity")).alias("buy"),
        pl.when(maker).then(pl.col("quantity")).otherwise(0.0).alias("sell"),
    )
    rows = df.group_by(["bar", "row10"]).agg(pl.col("buy").sum(), pl.col("sell").sum()).collect()
    ohlc = (df.sort(["transact_time", "agg_trade_id"]).group_by("bar", maintain_order=True)
            .agg(pl.col("price").first().alias("open"), pl.col("price").max().alias("high"),
                 pl.col("price").min().alias("low"), pl.col("price").last().alias("close"))
            .collect())
    os.makedirs(OUT, exist_ok=True)
    rows.write_parquet(rows_path)
    ohlc.write_parquet(os.path.join(OUT, f"ohlc_{period}.parquet"))
    os.remove(cpath)
    print(period, "bars", ohlc.height, "row cells", rows.height, flush=True)


def metrics(period: str) -> None:
    if len(period) == 7:
        y, m = map(int, period.split("-"))
        days = [f"{period}-{d:02d}" for d in range(1, calendar.monthrange(y, m)[1] + 1)]
    else:
        days = [period]
    for day in days:
        cpath = os.path.join(OUT, f"metrics_{day}.csv")
        if os.path.exists(cpath):
            continue
        zpath = os.path.join(TMP, f"metrics_{day}.zip")
        if fetch(f"{BASE}/daily/metrics/BTCUSDT/BTCUSDT-metrics-{day}.zip", zpath):
            with zipfile.ZipFile(zpath) as z:
                with open(cpath, "wb") as f:
                    f.write(z.read(z.namelist()[0]))
            os.remove(zpath)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for p in sys.argv[1:]:
        build(p)
        metrics(p)
