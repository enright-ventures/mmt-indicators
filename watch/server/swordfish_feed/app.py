"""HTTP feed for the Swordfish watch complications.

GET /v1/snapshot  the latest snapshot as JSON (see watch/README.md for the fields)
GET /healthz      200 when the last refresh is under 10 minutes old

Environment: PORT (8080), REFRESH_SECONDS (120), FEED_TOKEN (optional; when set, requests need
`Authorization: Bearer <token>`), SYMBOL (BTCUSDT).
"""
from __future__ import annotations

import calendar
import json
import logging
import math
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import exchanges as ex
from .metrics import DAY, snapshot

log = logging.getLogger("swordfish-feed")

SYMBOL = os.environ.get("SYMBOL", "BTCUSDT")
REFRESH = int(os.environ.get("REFRESH_SECONDS", "120"))
TOKEN = os.environ.get("FEED_TOKEN", "")


def year_start(now: float) -> int:
    return calendar.timegm((time.gmtime(now).tm_year, 1, 1, 0, 0, 0))


def clean(value: Any) -> Any:
    """NaN and infinities become null so the JSON stays strict."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def fetch(now: float, get: ex.Getter = ex.http_get) -> dict[str, Any]:
    four_h_from = min(year_start(now), int(now) - 60 * DAY)
    return {
        "bn_5m": ex.binance_klines(SYMBOL, 300, int(now) - 5 * DAY, get, now),
        "bn_30m": ex.binance_klines(SYMBOL, 1800, int(now) - 110 * DAY, get, now),
        "bn_4h": ex.binance_klines(SYMBOL, 14400, four_h_from, get, now),
        "bn_1d": ex.binance_klines(SYMBOL, 86400, int(now) - 370 * DAY, get, now),
        "bn_oi_30m": ex.binance_open_interest(SYMBOL, 1800, 6, get),
        "by_30m": ex.bybit_klines(SYMBOL, 1800, int(now) - 33 * DAY, get, now),
        "by_4h": ex.bybit_klines(SYMBOL, 14400, four_h_from, get, now),
        "by_1d": ex.bybit_klines(SYMBOL, 86400, int(now) - 370 * DAY, get, now),
    }


class Feed:
    def __init__(self) -> None:
        self.body = b'{"v":1,"asof":null}'
        self.updated = 0.0
        self.lock = threading.Lock()

    def refresh(self) -> None:
        now = time.time()
        snap = snapshot(fetch(now), int(now))
        body = json.dumps(clean(snap), separators=(",", ":"), allow_nan=False, default=str).encode()
        with self.lock:
            self.body, self.updated = body, now
        log.info("refreshed: price %s", snap["price"])

    def loop(self) -> None:
        while True:
            try:
                self.refresh()
            except Exception:  # keep serving the last good snapshot
                log.exception("refresh failed")
            time.sleep(REFRESH)


FEED = Feed()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            ok = time.time() - FEED.updated < 600
            self.reply(200 if ok else 503, b"ok" if ok else b"stale", "text/plain")
            return
        if self.path != "/v1/snapshot":
            self.reply(404, b"not found", "text/plain")
            return
        if TOKEN and self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.reply(401, b"unauthorized", "text/plain")
            return
        with FEED.lock:
            body = FEED.body
        self.reply(200, body, "application/json")

    def reply(self, code: int, body: bytes, kind: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        log.debug(format, *args)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    threading.Thread(target=FEED.loop, daemon=True).start()
    port = int(os.environ.get("PORT", "8080"))
    log.info("serving on :%d", port)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
