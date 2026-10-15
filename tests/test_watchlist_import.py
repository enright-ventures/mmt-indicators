import json
import sys
from pathlib import Path

import pytest

import tv_watchlist_import as importer


class WatchlistService:
    def __init__(self, fail_add: bool = False, fail_symbol: str | None = None, fail_remove: bool = False) -> None:
        self.markets = {("binancef", "btc/usd")}
        self.fail_add = fail_add
        self.fail_symbol = fail_symbol
        self.fail_remove = fail_remove
        self.removals = 0

    def call(self, name, args):
        if name == "m5_get_status":
            return {"sessions": [{"tabId": "test", "lastSeenAt": "now", "widgets": [{"type": "watchlist", "widgetId": 1}]}]}
        if name == "watchlist_list":
            return {"ok": True, "data": {"markets": [{"exchange": ex, "symbol": sym} for ex, sym in self.markets]}}
        market = args["market"]
        key = (market["exchange"], market["symbol"])
        if name == "watchlist_add":
            if self.fail_add or key[1] == self.fail_symbol:
                return {"ok": False, "message": "Unavailable market"}
            self.markets.add(key)
        if name == "watchlist_remove":
            if self.fail_remove:
                return {"ok": False, "message": "Removal rejected"}
            self.removals += 1
            self.markets.remove(key)
        return {"ok": True}


@pytest.mark.parametrize("symbol", ["BTCFDUSD.P", "BTCBUSD.P", "BTCUSD.P", "BTCUSDT.P", "BTCUSDC.P"])
def test_quote_suffix_maps_correct_base(symbol: str) -> None:
    market, reason = importer.to_mmt("BINANCE:" + symbol)

    assert market == ("binancef", "btc/usd")
    assert reason is None


def test_unsupported_only_import_keeps_watchlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "list.txt"
    source.write_text("NASDAQ:AAPL")
    service = WatchlistService()
    monkeypatch.setattr(importer, "M5", lambda: service)
    monkeypatch.setattr(sys, "argv", ["importer", str(source)])

    with pytest.raises(SystemExit):
        importer.main()

    assert service.markets == {("binancef", "btc/usd")}
    assert service.removals == 0


def test_failed_add_keeps_original_markets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "list.txt"
    source.write_text("BINANCE:ETHUSDT.P")
    service = WatchlistService(fail_add=True)
    monkeypatch.setattr(importer, "M5", lambda: service)
    monkeypatch.setattr(sys, "argv", ["importer", str(source)])

    with pytest.raises(SystemExit):
        importer.main()

    assert service.markets == {("binancef", "btc/usd")}
    assert service.removals == 0


def test_successful_replacement_saves_recovery_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "list.txt"
    source.write_text("BINANCE:ETHUSDT.P")
    service = WatchlistService()
    monkeypatch.setattr(importer, "M5", lambda: service)
    monkeypatch.setattr(sys, "argv", ["importer", str(source), "--tab", "test"])

    importer.main()

    assert service.markets == {("binancef", "eth/usd")}
    backup = next(tmp_path.glob("*.mmt-backup-*.json"))
    assert json.loads(backup.read_text())["markets"] == [{"exchange": "binancef", "symbol": "btc/usd"}]


def test_partial_add_failure_keeps_original_and_successful_additions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "list.txt"
    source.write_text("BINANCE:ETHUSDT.P,BINANCE:SOLUSDT.P")
    service = WatchlistService(fail_symbol="sol/usd")
    monkeypatch.setattr(importer, "M5", lambda: service)
    monkeypatch.setattr(sys, "argv", ["importer", str(source)])

    with pytest.raises(SystemExit, match="all original markets were retained"):
        importer.main()

    assert service.markets == {("binancef", "btc/usd"), ("binancef", "eth/usd")}
    assert service.removals == 0


def test_failed_removal_reports_recovery_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "list.txt"
    source.write_text("BINANCE:ETHUSDT.P")
    service = WatchlistService(fail_remove=True)
    monkeypatch.setattr(importer, "M5", lambda: service)
    monkeypatch.setattr(sys, "argv", ["importer", str(source)])

    with pytest.raises(SystemExit, match="Recover using") as failure:
        importer.main()

    backup = next(tmp_path.glob("*.mmt-backup-*.json"))
    assert str(backup) in str(failure.value)
    assert service.markets == {("binancef", "btc/usd"), ("binancef", "eth/usd")}


def test_retained_market_is_not_added_or_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "list.txt"
    source.write_text("BINANCE:BTCFDUSD.P")
    service = WatchlistService(fail_add=True, fail_remove=True)
    monkeypatch.setattr(importer, "M5", lambda: service)
    monkeypatch.setattr(sys, "argv", ["importer", str(source)])

    importer.main()

    assert "added 0 markets" in capsys.readouterr().out
    assert service.markets == {("binancef", "btc/usd")}
