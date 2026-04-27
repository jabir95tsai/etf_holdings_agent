"""Parser tests against the local sample fixture."""

from __future__ import annotations

from pathlib import Path

from src import parser

FIXTURE = Path(__file__).parent / "sample_holdings.html"


def test_parse_upamc_html_extracts_date_and_rows():
    html = FIXTURE.read_text(encoding="utf-8")
    data_date, rows = parser.parse_upamc_html(html)

    assert data_date == "2026-04-24"
    assert len(rows) == 5

    first = rows[0]
    assert first["stock_code"] == "2330"
    assert first["stock_name"] == "台積電"
    assert first["shares"] == 120000
    assert abs(first["weight_pct"] - 8.52) < 1e-6


def test_parse_moneydj_uses_same_table_logic():
    html = FIXTURE.read_text(encoding="utf-8")
    _date, rows = parser.parse_moneydj_html(html)
    codes = [r["stock_code"] for r in rows]
    assert "2330" in codes
    assert "2412" in codes


def test_parse_moneydj_extracts_code_from_name_cell():
    html = """
    <table>
      <tr><td>個股名稱</td><td>投資比例(%)</td><td>持有股數</td></tr>
      <tr><td>台積電(2330.TW)</td><td>9.46</td><td>9,693,000</td></tr>
    </table>
    """

    _date, rows = parser.parse_moneydj_html(html)

    assert rows == [
        {
            "stock_code": "2330",
            "stock_name": "台積電",
            "weight_pct": 9.46,
            "shares": 9693000,
        }
    ]


def test_parse_upamc_json_basic():
    payload = {
        "asOfDate": "2026/04/24",
        "data": [
            {"stockCode": "2330", "stockName": "台積電", "weight": "8.52", "shares": "120000"},
            {"stockCode": "2317.TW", "stockName": "鴻海", "weight": 5.1, "shares": 500000},
        ],
    }
    data_date, rows = parser.parse_upamc_json(payload)
    assert data_date == "2026-04-24"
    assert rows[0]["stock_code"] == "2330"
    assert rows[1]["stock_code"] == "2317"
    assert rows[1]["weight_pct"] == 5.1
    assert rows[1]["shares"] == 500000


def test_normalize_handles_roc_date():
    assert parser._normalize_date("115/04/24") == "2026-04-24"
    assert parser._normalize_date("2026-4-9") == "2026-04-09"
    assert parser._normalize_date("garbage") is None
