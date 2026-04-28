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


def test_render_email_html_contains_summary_and_compact_amounts():
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
    assert "今日重點" in html
    assert "估值變化" in html
    assert "最大買進標的" in html
    assert "+32 萬" in html
    assert "股數 / 估值" in html
    assert "排名 / 代號" in html
    assert "MoneyDJ" not in html  # source keeps the configured lowercase label
    assert "moneydj" in html


def test_render_email_html_marks_stale_data_and_empty_state():
    previous = [_row("2303", "聯電", 1000, 1.0)]
    current = [_row("2303", "聯電", 1200, 1.2)]
    diff = comparer.compare(previous, current, "2026-04-27", "2026-04-28")
    comparer.enrich_with_prices(diff, {"2303": 75.1})
    qc = reporter.quality_check(
        rows=current,
        scrape_ok=True,
        is_new_data=False,
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

    assert "非新資料" in html
    assert "今日無減持紀錄" in html
    assert "今日無清倉紀錄" in html
