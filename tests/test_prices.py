"""Price fetcher tests."""

from __future__ import annotations

from src import prices


def test_fetch_twse_close_prices_parses_stock_table(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "tables": [
                    {
                        "fields": ["證券代號", "證券名稱", "收盤價"],
                        "data": [["2330", "台積電", "1,005.00"]],
                    }
                ]
            }

    monkeypatch.setattr(prices.requests, "get", lambda *a, **k: Resp())

    assert prices.fetch_twse_close_prices("2026-04-28") == {"2330": 1005.0}


def test_fetch_tpex_close_prices_parses_stock_table(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "tables": [
                    {
                        "fields": ["代號", "名稱", "收盤"],
                        "data": [["3211", "順達", "210.50"]],
                    }
                ]
            }

    monkeypatch.setattr(prices.requests, "get", lambda *a, **k: Resp())

    assert prices.fetch_tpex_close_prices("2026-04-28") == {"3211": 210.5}


def test_fetch_close_prices_filters_requested_codes(monkeypatch):
    monkeypatch.setattr(
        prices,
        "fetch_twse_close_prices",
        lambda _date: {"2330": 1000.0, "2317": 200.0},
    )
    monkeypatch.setattr(
        prices,
        "fetch_tpex_close_prices",
        lambda _date: {"3211": 210.0},
    )

    assert prices.fetch_close_prices("2026-04-28", ["2330", "3211"]) == {
        "2330": 1000.0,
        "3211": 210.0,
    }
