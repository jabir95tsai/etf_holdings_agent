"""Reporter rendering tests."""

from __future__ import annotations

from datetime import datetime

from src import comparer, reporter


def _row(code, name, shares, weight):
    return {
        "stock_code": code,
        "stock_name": name,
        "shares": shares,
        "weight_pct": weight,
    }


def test_render_email_html_contains_kpis_and_amount_column():
    previous = [_row("2303", "聯電", 1000, 1.0)]
    current = [
        _row("2303", "聯電", 1200, 1.2),
        _row("2337", "旺宏", 2000, 0.2),
    ]
    diff = comparer.compare(previous, current, "2026-04-27", "2026-04-28")
    comparer.enrich_with_prices(diff, {"2303": 75.1, "2337": 159.5})
    qc = reporter.quality_check(
        rows=current,
        scrape_ok=True,
        is_new_data=True,
        source_used="moneydj",
        has_data_date=True,
    )

    html = reporter.render_email_html(
        etf_code="00981A",
        run_at=datetime(2026, 4, 28, 12, 0),
        diff=diff,
        current_rows=current,
        previous_rows=previous,
        qc=qc,
        source_used="moneydj",
    )

    assert "ETF 持股報告" in html
    assert "估計金額" in html
    assert "估計買進最大" in html
    assert "+319,000" in html
    assert "MoneyDJ" not in html  # source keeps the configured lowercase label
    assert "moneydj" in html
