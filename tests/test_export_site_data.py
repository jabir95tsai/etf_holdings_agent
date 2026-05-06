"""Static website JSON export tests."""

from __future__ import annotations

import json

from scripts.export_site_data import export_site_data, write_manifest
from src.db import HoldingsDB


def _row(date, etf, code, name, shares, weight):
    return {
        "date": date,
        "etf_code": etf,
        "stock_code": code,
        "stock_name": name,
        "weight_pct": weight,
        "shares": shares,
        "source_url": "https://example.test",
        "raw_source": "moneydj",
        "scraped_at": f"{date}T15:00:00",
    }


def test_export_site_data_writes_latest_and_manifest(tmp_path):
    db_path = tmp_path / "holdings.sqlite"
    db = HoldingsDB(db_path)
    db.upsert_holdings(
        [
            _row("2026-05-04", "00981A", "2330", "台積電", 1000, 9.0),
            _row("2026-05-04", "00981A", "2303", "聯電", 2000, 1.0),
            _row("2026-05-05", "00981A", "2330", "台積電", 1200, 9.5),
            _row("2026-05-05", "00981A", "2454", "聯發科", 300, 4.0),
        ]
    )
    db.log_run(
        etf_code="00981A",
        status="ok",
        message="test",
        source_used="moneydj",
        data_date="2026-05-05",
        rows_count=2,
    )

    output_dir = tmp_path / "site-data"
    paths = export_site_data(
        db_path,
        output_dir,
        ["00981A"],
        include_prices=False,
    )

    latest_path = output_dir / "00981A" / "latest.json"
    manifest_path = output_dir / "manifest.json"
    assert latest_path in paths
    assert manifest_path in paths

    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["etf"]["code"] == "00981A"
    assert payload["dates"]["current"] == "2026-05-05"
    assert payload["dates"]["previous"] == "2026-05-04"
    assert payload["summary"]["new_count"] == 1
    assert payload["summary"]["sold_count"] == 1
    assert payload["summary"]["increased_count"] == 1
    assert payload["sections"]["top_holdings"][0]["stock_code"] == "2330"
    assert payload["quality"]["source_used"] == "moneydj"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["etfs"][0]["code"] == "00981A"
    assert manifest["etfs"][0]["path"] == "data/00981A/latest.json"


def test_write_manifest_skips_invalid_json(tmp_path):
    valid_dir = tmp_path / "0050"
    valid_dir.mkdir()
    (valid_dir / "latest.json").write_text(
        json.dumps(
            {
                "etf": {"code": "0050", "name": "元大台灣50"},
                "dates": {"current": "2026-05-05", "previous": "2026-05-04"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    invalid_dir = tmp_path / "BROKEN"
    invalid_dir.mkdir()
    (invalid_dir / "latest.json").write_text("{", encoding="utf-8")

    manifest_path = write_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert [entry["code"] for entry in manifest["etfs"]] == ["0050"]
