"""Public REST candles and open interest from Binance and Bybit USDT perps, the venues the Swordfish VWAPs pool.

Every fetcher returns candles oldest first as `Candle` rows, the last one being the forming candle (both exchanges
return it), as MMT's requestBars(anchor: latest) does. Binance and Bybit refuse requests from some regions (US cloud
hosts get HTTP 451 / 403), so run the feed from somewhere they serve.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable

BINANCE = "https://fapi.binance.com"
BYBIT = "https://api.bybit.com"

BINANCE_INTERVAL = {300: "5m", 1800: "30m", 14400: "4h", 86400: "1d"}
BYBIT_INTERVAL = {300: "5", 1800: "30", 14400: "240", 86400: "D"}


@dataclass(frozen=True, slots=True)
class Candle:
    time: int  # open, unix seconds
    open: float
    high: float
    low: float
    close: float
    volume: float  # base coin
    taker_buy: float = float("nan")  # base coin bought by takers (Binance only)


Getter = Callable[[str], object]


def http_get(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": "swordfish-feed/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def binance_klines(symbol: str, step: int, start: int, get: Getter = http_get, now: float | None = None) -> list[Candle]:
    end_ms = int((now if now is not None else time.time()) * 1000)
    cursor = start * 1000
    out: list[Candle] = []
    while cursor < end_ms:
        rows = get(f"{BINANCE}/fapi/v1/klines?symbol={symbol}&interval={BINANCE_INTERVAL[step]}&startTime={cursor}&limit=1500")
        assert isinstance(rows, list)
        if not rows:
            break
        for k in rows:
            out.append(Candle(int(k[0]) // 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[9])))
        cursor = int(rows[-1][0]) + step * 1000
        if len(rows) < 1500:
            break
    return dedupe(out)


def bybit_klines(symbol: str, step: int, start: int, get: Getter = http_get, now: float | None = None) -> list[Candle]:
    """Bybit pages newest first; walk back from now to `start`."""
    end_ms = int((now if now is not None else time.time()) * 1000)
    out: list[Candle] = []
    while end_ms >= start * 1000:
        payload = get(f"{BYBIT}/v5/market/kline?category=linear&symbol={symbol}&interval={BYBIT_INTERVAL[step]}&start={start * 1000}&end={end_ms}&limit=1000")
        assert isinstance(payload, dict)
        rows = payload["result"]["list"]
        if not rows:
            break
        for k in rows:
            out.append(Candle(int(k[0]) // 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])))
        end_ms = int(rows[-1][0]) - 1
        if len(rows) < 1000:
            break
    return dedupe(out)


def binance_open_interest(symbol: str, step: int, limit: int, get: Getter = http_get) -> dict[int, float]:
    """Open interest in coins at each `step` boundary (Binance stamps the reading at the period's end)."""
    rows = get(f"{BINANCE}/futures/data/openInterestHist?symbol={symbol}&period={BINANCE_INTERVAL[step]}&limit={limit}")
    assert isinstance(rows, list)
    return {int(r["timestamp"]) // 1000: float(r["sumOpenInterest"]) for r in rows}


def dedupe(rows: list[Candle]) -> list[Candle]:
    by_time = {row.time: row for row in rows}
    return [by_time[t] for t in sorted(by_time)]
