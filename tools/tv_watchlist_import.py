"""Import a TradingView watchlist export into the MMT watchlist, replacing what is on it.

TradingView's "Export list" file is comma-separated EXCHANGE:SYMBOL entries; ".P" marks a perpetual and "###Name"
starts a section. MMT watchlists have no sections, so sections are listed in the report only, and the markets are
added in file order.

Usage:
  python3 tv_watchlist_import.py                 # pick the file in a macOS dialog (opens in Downloads)
  python3 tv_watchlist_import.py <file.txt>
  python3 tv_watchlist_import.py <file.txt> --dry-run    # show the mapping, change nothing
  options: --tab <MMT browser tab id> (default: the most recently active session), --widget <watchlist widget id>,
           --summary (only the counts, skipped and failed lines; used by the "Import to MMT" app)

Talks to MMT through the m5 MCP endpoint, using the server entry Claude Code stores for this project in ~/.claude.json.
MMT must be open in a browser. Adding to a watchlist opens one when none is open.
"""
import json
import os
import subprocess
import sys
import urllib.request

PROJECT = "/Users/Shared/Projects/stable-workshop"

# TradingView exchange -> MMT exchange id (perpetual, spot)
EXCHANGES = {
    "BINANCE": ("binancef", "binance"),
    "BYBIT": ("bybitf", "bybit"),
    "OKX": ("okxf", "okx"),
    "HYPERLIQUID": ("hyperliquid", "hyperliquid"),
    "COINBASE": (None, "coinbase"),
    "KRAKEN": (None, "kraken"),
    "BITGET": ("bitgetf", "bitget"),
}
QUOTES = ("USDT", "USDC", "USD", "FDUSD", "BUSD")


def endpoint():
    cfg = json.load(open(os.path.expanduser("~/.claude.json")))
    server = cfg["projects"][PROJECT]["mcpServers"]["m5"]
    return server["url"], server.get("headers", {})


class M5:
    def __init__(self):
        self.url, self.headers = endpoint()
        self.session = None
        self.n = 0

    def call(self, name, args):
        self.n += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self.n, "method": "tools/call", "params": {"name": name, "arguments": args}}).encode()
        h = dict(self.headers)
        h.update({"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        if self.session:
            h["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, data=body, headers=h)
        with urllib.request.urlopen(req, timeout=60) as r:
            self.session = r.headers.get("Mcp-Session-Id") or self.session
            text = r.read().decode()
        lines = [x[5:] for x in text.splitlines() if x.startswith("data:")]
        d = json.loads(lines[-1] if lines else text)
        if "error" in d:
            raise RuntimeError(d["error"])
        out = "".join(c.get("text", "") for c in d.get("result", {}).get("content", []))
        try:
            return json.loads(out)
        except ValueError:
            return out


def pick_file():
    script = 'POSIX path of (choose file with prompt "TradingView watchlist to import into MMT" of type {"txt", "public.plain-text"} default location (path to downloads folder))'
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("No file chosen.")
    return r.stdout.strip()


def parse(text):
    """[(section, tv_symbol)] in file order."""
    out, section = [], ""
    for raw in text.replace("\n", ",").split(","):
        item = raw.strip()
        if not item:
            continue
        if item.startswith("###"):
            section = item[3:].strip()
            continue
        out.append((section, item))
    return out


def to_mmt(tv):
    """TradingView 'EXCHANGE:SYMBOL[.P]' -> (exchange, symbol) for MMT, or None with a reason."""
    if ":" not in tv:
        return None, "no exchange prefix"
    ex, sym = tv.split(":", 1)
    perp = sym.endswith(".P")
    sym = sym[:-2] if perp else sym
    pair = EXCHANGES.get(ex.upper())
    if not pair:
        return None, f"exchange {ex} not mapped"
    mmt_ex = pair[0] if perp else pair[1]
    if not mmt_ex:
        return None, f"no {ex} perpetuals on MMT"
    for q in QUOTES:
        if sym.upper().endswith(q) and len(sym) > len(q):
            base = sym[: -len(q)]
            # MMT names USD-margined perps and USD spot as base/usd
            return (mmt_ex, f"{base.lower()}/usd"), None
    return None, "quote currency not recognised"


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    summary = "--summary" in args
    tab = args[args.index("--tab") + 1] if "--tab" in args else None
    widget = int(args[args.index("--widget") + 1]) if "--widget" in args else None
    files = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in ("--tab", "--widget"))]
    path = files[0] if files else pick_file()
    items = parse(open(path, encoding="utf-8").read())
    mapped, skipped, seen = [], [], set()
    for section, tv in items:
        m, why = to_mmt(tv)
        if m is None:
            skipped.append((tv, why))
        elif m not in seen:
            seen.add(m)
            mapped.append((section, tv, m))
    print(f"{os.path.basename(path)}: {len(items)} symbols, {len(mapped)} to import, {len(skipped)} skipped")
    sections = sorted({sec for sec, _, _ in mapped if sec})
    if summary:
        if sections:
            print("Sections (not kept: MMT watchlists have none): " + ", ".join(sections))
    else:
        for section, tv, (ex, sym) in mapped:
            print(f"  {section or '-':22s} {tv:28s} -> {ex} {sym}")
    for tv, why in skipped:
        print(f"  skipped {tv}: {why}")
    if dry:
        return
    m5 = M5()
    if tab is None:
        status = m5.call("m5_get_status", {})
        sessions = sorted(status.get("sessions", []), key=lambda s: s.get("lastSeenAt", ""))
        if not sessions:
            sys.exit("MMT is not open in a browser.")
        tab = sessions[-1]["tabId"]
        if widget is None:
            for w in sessions[-1].get("widgets", []):
                if w.get("type") == "watchlist":
                    widget = w["widgetId"]
    base = {"targetTabId": tab}
    if widget is not None:
        base["widgetId"] = widget
    current = m5.call("watchlist_list", base) if widget is not None else {}
    rows = (current.get("data", current) or {}).get("markets", []) if isinstance(current, dict) else []
    for r in rows:
        mk = r.get("market", r)
        m5.call("watchlist_remove", dict(base, market={"exchange": mk["exchange"], "symbol": mk["symbol"]}))
    print(f"removed {len(rows)} markets from the watchlist")
    failed = []
    for section, tv, (ex, sym) in mapped:
        res = m5.call("watchlist_add", dict(base, market={"exchange": ex, "symbol": sym}))
        ok = isinstance(res, dict) and res.get("ok", True) is not False
        if not ok:
            failed.append((tv, res.get("message") if isinstance(res, dict) else res))
        if widget is None and isinstance(res, dict):
            widget = (res.get("data") or {}).get("widgetId", widget)
            if widget is not None:
                base["widgetId"] = widget
    print(f"added {len(mapped) - len(failed)} markets" + (f", {len(failed)} failed:" if failed else ""))
    for tv, msg in failed:
        print(f"  {tv}: {msg}")


if __name__ == "__main__":
    main()
