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


def test_fetch_close_prices_prefers_requested_date(monkeypatch):
    calls: list[str] = []

    def fake_twse(date):
        calls.append(date)
        return {"2330": 999.0}

    monkeypatch.setattr(prices, "fetch_twse_close_prices", fake_twse)
    monkeypatch.setattr(prices, "fetch_tpex_close_prices", lambda _date: {})

    # 2026-01-07 is a Wednesday; price is found immediately, no fallback.
    assert prices.fetch_close_prices("2026-01-07", ["2330"]) == {"2330": 999.0}
    assert calls == ["2026-01-07"]


def test_fetch_close_prices_falls_back_to_earlier_day(monkeypatch):
    # Requested date has no quotes yet; the previous trading day does.
    def fake_twse(date):
        return {"2330": 1000.0} if date == "2026-01-06" else {}

    monkeypatch.setattr(prices, "fetch_twse_close_prices", fake_twse)
    monkeypatch.setattr(prices, "fetch_tpex_close_prices", lambda _date: {})

    assert prices.fetch_close_prices("2026-01-07", ["2330"]) == {"2330": 1000.0}


def test_fetch_close_prices_lookback_fills_per_code(monkeypatch):
    # One code resolves on the requested date, the other only on an earlier day.
    def fake_twse(date):
        if date == "2026-01-07":
            return {"2330": 1000.0}
        if date == "2026-01-06":
            return {"2317": 200.0}
        return {}

    monkeypatch.setattr(prices, "fetch_twse_close_prices", fake_twse)
    monkeypatch.setattr(prices, "fetch_tpex_close_prices", lambda _date: {})

    assert prices.fetch_close_prices("2026-01-07", ["2330", "2317"]) == {
        "2330": 1000.0,
        "2317": 200.0,
    }


def test_fetch_close_prices_skips_weekend(monkeypatch):
    fetched: list[str] = []

    def fake_twse(date):
        fetched.append(date)
        return {"2330": 500.0} if date == "2026-01-09" else {}

    monkeypatch.setattr(prices, "fetch_twse_close_prices", fake_twse)
    monkeypatch.setattr(prices, "fetch_tpex_close_prices", lambda _date: {})

    # 2026-01-10 is a Saturday: skip straight to Friday without fetching weekend.
    assert prices.fetch_close_prices("2026-01-10", ["2330"]) == {"2330": 500.0}
    assert "2026-01-10" not in fetched and "2026-01-11" not in fetched


def test_fetch_close_prices_gives_up_after_lookback(monkeypatch):
    monkeypatch.setattr(prices, "fetch_twse_close_prices", lambda _date: {})
    monkeypatch.setattr(prices, "fetch_tpex_close_prices", lambda _date: {})

    assert prices.fetch_close_prices("2026-01-07", ["2330"], lookback_days=2) == {}
