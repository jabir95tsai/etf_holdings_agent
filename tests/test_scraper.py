"""Scraper orchestration tests."""

from __future__ import annotations

from src import scraper


def test_scrape_holdings_uses_configured_source_order(monkeypatch, tmp_path):
    calls: list[str] = []

    def fail_ezmoney(*_args, **_kwargs):
        calls.append("ezmoney")
        return scraper.ScrapeResult(
            source="ezmoney",
            source_url="",
            data_date=None,
            rows=[],
            errors=["ezmoney failed"],
        )

    def ok_moneydj(*_args, **_kwargs):
        calls.append("moneydj")
        return scraper.ScrapeResult(
            source="moneydj",
            source_url="",
            data_date="2026-04-24",
            rows=[{"stock_code": "2330", "stock_name": "台積電"}],
        )

    monkeypatch.setattr(scraper, "scrape_ezmoney_excel", fail_ezmoney)
    monkeypatch.setattr(scraper, "scrape_moneydj", ok_moneydj)

    result = scraper.scrape_holdings(
        etf_code="00981A",
        raw_dir=tmp_path,
        upamc_url="official-url",
        moneydj_url="moneydj-url",
        twse_url="twse-url",
        source_order=["ezmoney", "moneydj"],
    )

    assert calls == ["ezmoney", "moneydj"]
    assert result.source == "moneydj"
    assert result.errors == ["ezmoney failed"]


def test_scrape_holdings_stops_after_first_success(monkeypatch, tmp_path):
    calls: list[str] = []

    def ok_moneydj(*_args, **_kwargs):
        calls.append("moneydj")
        return scraper.ScrapeResult(
            source="moneydj",
            source_url="",
            data_date="2026-04-24",
            rows=[{"stock_code": "2330"}],
        )

    def fail_twse(*_args, **_kwargs):
        calls.append("twse")
        return scraper.ScrapeResult(
            source="twse",
            source_url="",
            data_date=None,
            rows=[],
            errors=["should not run"],
        )

    monkeypatch.setattr(scraper, "scrape_moneydj", ok_moneydj)
    monkeypatch.setattr(scraper, "scrape_twse", fail_twse)

    result = scraper.scrape_holdings(
        etf_code="00981A",
        raw_dir=tmp_path,
        upamc_url="official-url",
        moneydj_url="moneydj-url",
        twse_url="twse-url",
        source_order=["moneydj", "twse"],
    )

    assert calls == ["moneydj"]
    assert result.ok


def test_scrape_holdings_reports_no_enabled_sources(tmp_path):
    result = scraper.scrape_holdings(
        etf_code="00981A",
        raw_dir=tmp_path,
        upamc_url="official-url",
        moneydj_url="moneydj-url",
        twse_url="twse-url",
        source_order=["unknown"],
    )

    assert not result.ok
    assert result.errors == ["No enabled data sources"]
