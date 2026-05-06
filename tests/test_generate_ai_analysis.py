"""AI analysis generation tests."""

from __future__ import annotations

import json

from scripts.generate_ai_analysis import generate_for_file, rule_based_analysis


def _payload():
    return {
        "etf": {"code": "00981A", "name": "統一台灣高息動能"},
        "dates": {"current": "2026-05-05", "previous": "2026-05-04"},
        "summary": {
            "current_count": 51,
            "new_count": 1,
            "sold_count": 0,
            "increased_count": 2,
            "decreased_count": 1,
        },
        "highlights": {
            "top_buy": {
                "stock_code": "2330",
                "stock_name": "台積電",
                "estimated_change_amount": 250_000_000,
            },
            "top_sell": None,
        },
        "quality": {"notes": [], "source_used": "moneydj"},
        "sections": {
            "top_holdings": [
                {
                    "stock_code": "2330",
                    "stock_name": "台積電",
                    "delta_weight_bp": 25.0,
                }
            ],
            "increased": [],
            "decreased": [],
            "new_positions": [],
            "sold_out": [],
        },
    }


def test_rule_based_analysis_contains_core_fields():
    analysis = rule_based_analysis(_payload())

    assert analysis["provider"] == "rule_based"
    assert "00981A" in analysis["headline"]
    assert any("2330 台積電" in item for item in analysis["bullets"])
    assert analysis["disclaimer"]


def test_generate_for_file_writes_ai_analysis(tmp_path):
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(_payload(), ensure_ascii=False), encoding="utf-8")

    analysis = generate_for_file(
        path,
        api_key=None,
        model="gpt-test",
        force_rule_based=True,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert analysis["provider"] == "rule_based"
    assert payload["ai_analysis"]["headline"] == analysis["headline"]
