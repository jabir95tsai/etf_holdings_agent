"""Export ETF holdings snapshots to static JSON files for the website."""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import prices
from src.comparer import DiffReport, DiffRow, compare, enrich_with_prices, top_holdings_change
from src.config import DEFAULT_DB_PATH
from src.reporter import build_summary, quality_check

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = REPO_ROOT / "site" / "data"
SCHEMA_VERSION = 1

ETF_NAMES = {
    "00981A": "統一台灣高息動能",
    "0050": "元大台灣50",
    "006208": "富邦台50",
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _list_etfs(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT etf_code FROM holdings_daily ORDER BY etf_code"
    ).fetchall()
    return [str(row["etf_code"]) for row in rows]


def _latest_dates(conn: sqlite3.Connection, etf_code: str, limit: int = 2) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT date FROM holdings_daily
        WHERE etf_code = ?
        ORDER BY date DESC
        LIMIT ?
        """,
        (etf_code, limit),
    ).fetchall()
    return [str(row["date"]) for row in rows]


def _holdings(conn: sqlite3.Connection, etf_code: str, date: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT date, etf_code, stock_code, stock_name, weight_pct, shares,
               source_url, raw_source, scraped_at
        FROM holdings_daily
        WHERE etf_code = ? AND date = ?
        ORDER BY weight_pct DESC NULLS LAST
        """,
        (etf_code, date),
    ).fetchall()
    return [dict(row) for row in rows]


def _date_summaries(conn: sqlite3.Connection, etf_code: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT date,
               COUNT(*) AS rows_count,
               ROUND(SUM(COALESCE(weight_pct, 0)), 4) AS weight_total,
               MAX(raw_source) AS source_used,
               MAX(scraped_at) AS scraped_at
        FROM holdings_daily
        WHERE etf_code = ?
        GROUP BY date
        ORDER BY date DESC
        """,
        (etf_code,),
    ).fetchall()
    return [
        {
            "date": row["date"],
            "rows_count": row["rows_count"],
            "weight_total": row["weight_total"],
            "source_used": row["source_used"],
            "scraped_at": row["scraped_at"],
        }
        for row in rows
    ]


def _latest_run(
    conn: sqlite3.Connection,
    etf_code: str,
    data_date: str | None,
) -> dict[str, Any] | None:
    if data_date:
        row = conn.execute(
            """
            SELECT run_at, status, message, source_used, data_date, rows_count, report_path
            FROM run_logs
            WHERE etf_code = ? AND data_date = ?
            ORDER BY run_at DESC
            LIMIT 1
            """,
            (etf_code, data_date),
        ).fetchone()
        if row:
            return _run_payload(row)

    row = conn.execute(
        """
        SELECT run_at, status, message, source_used, data_date, rows_count, report_path
        FROM run_logs
        WHERE etf_code = ?
        ORDER BY run_at DESC
        LIMIT 1
        """,
        (etf_code,),
    ).fetchone()
    return _run_payload(row) if row else None


def _run_payload(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    report_path = payload.pop("report_path", None)
    payload["report_file"] = Path(report_path).name if report_path else None
    return payload


def _fmt_money_compact(value: float | None) -> str | None:
    if value is None:
        return None
    sign = "+" if value > 0 else "-" if value < 0 else ""
    amount = abs(value)
    if amount >= 100_000_000:
        return f"{sign}{amount / 100_000_000:.2f} 億"
    if amount >= 10_000:
        return f"{sign}{amount / 10_000:.0f} 萬"
    return f"{sign}{amount:,.0f}"


def _fmt_delta_int(value: int | None) -> str | None:
    if value is None:
        return None
    sign = "+" if value > 0 else ""
    return f"{sign}{int(value):,}"


def _row_identity(row: DiffRow | None) -> dict[str, Any] | None:
    if row is None:
        return None
    payload = _diff_row_payload(row)
    return {
        key: payload[key]
        for key in (
            "stock_code",
            "stock_name",
            "delta_shares",
            "delta_shares_label",
            "current_weight_pct",
            "previous_weight_pct",
            "delta_weight_bp",
            "estimated_change_amount",
            "estimated_change_amount_label",
            "close_price",
        )
    }


def _top_amount(rows: list[DiffRow], *, reverse: bool) -> DiffRow | None:
    rows_with_amount = [row for row in rows if row.estimated_change_amount is not None]
    if rows_with_amount:
        return sorted(
            rows_with_amount,
            key=lambda row: row.estimated_change_amount or 0,
            reverse=reverse,
        )[0]
    rows_with_shares = [row for row in rows if row.delta_shares is not None]
    if rows_with_shares:
        return sorted(
            rows_with_shares,
            key=lambda row: row.delta_shares or 0,
            reverse=reverse,
        )[0]
    return None


def _diff_row_payload(row: DiffRow) -> dict[str, Any]:
    data = row.to_dict()
    data["delta_shares_label"] = _fmt_delta_int(row.delta_shares)
    data["estimated_change_amount_label"] = _fmt_money_compact(
        row.estimated_change_amount
    )
    return data


def _holding_payload(row: dict[str, Any], rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "stock_code": row.get("stock_code"),
        "stock_name": row.get("stock_name"),
        "weight_pct": row.get("weight_pct"),
        "shares": row.get("shares"),
        "raw_source": row.get("raw_source"),
        "scraped_at": row.get("scraped_at"),
    }


def _quality_payload(
    rows: list[dict[str, Any]],
    *,
    source_used: str,
    last_run: dict[str, Any] | None,
) -> dict[str, Any]:
    qc = quality_check(
        rows,
        scrape_ok=bool(rows),
        is_new_data=(last_run or {}).get("status") == "ok",
        source_used=source_used,
        has_data_date=bool(rows and rows[0].get("date")),
    )
    return {
        "scrape_ok": qc.scrape_ok,
        "is_new_data": qc.is_new_data,
        "rows_count": qc.rows_count,
        "weight_total": qc.weight_total,
        "weight_total_ok": qc.weight_total_ok,
        "missing_codes": qc.missing_codes,
        "missing_names": qc.missing_names,
        "duplicate_codes": qc.duplicate_codes,
        "weight_unparseable": qc.weight_unparseable,
        "shares_unparseable": qc.shares_unparseable,
        "source_used": qc.source_used,
        "notes": qc.notes,
    }


def _brief(
    diff: DiffReport,
    summary: dict[str, Any],
    top_buy: DiffRow | None,
    top_sell: DiffRow | None,
) -> str:
    buy_text = (
        f"最大買進為 {top_buy.stock_code} {top_buy.stock_name}"
        f"（{_fmt_money_compact(top_buy.estimated_change_amount) or '估值待補'}）"
        if top_buy
        else "今日無明顯買進金額"
    )
    sell_text = (
        f"最大賣出為 {top_sell.stock_code} {top_sell.stock_name}"
        f"（{_fmt_money_compact(top_sell.estimated_change_amount) or '估值待補'}）"
        if top_sell
        else "今日無明顯賣出金額"
    )
    return (
        f"今日持股 {summary['current_count']} 檔，"
        f"新建倉 {summary['new_count']} 檔、清倉 {summary['sold_count']} 檔，"
        f"增持 {summary['increased_count']} 檔、減持 {summary['decreased_count']} 檔。"
        f"{buy_text}；{sell_text}。"
    )


def _source_used(rows: list[dict[str, Any]], last_run: dict[str, Any] | None) -> str:
    if last_run and last_run.get("source_used"):
        return str(last_run["source_used"])
    for row in rows:
        if row.get("raw_source"):
            return str(row["raw_source"])
    return ""


def build_etf_payload(
    conn: sqlite3.Connection,
    etf_code: str,
    *,
    include_prices: bool = True,
) -> dict[str, Any] | None:
    dates = _latest_dates(conn, etf_code, limit=2)
    if not dates:
        return None

    current_date = dates[0]
    previous_date = dates[1] if len(dates) > 1 else None
    current_rows = _holdings(conn, etf_code, current_date)
    previous_rows = _holdings(conn, etf_code, previous_date) if previous_date else []
    last_run = _latest_run(conn, etf_code, current_date)
    source_used = _source_used(current_rows, last_run)

    diff = compare(
        previous=previous_rows,
        current=current_rows,
        previous_date=previous_date,
        current_date=current_date,
    )
    if include_prices and current_date:
        stock_codes = [row.stock_code for row in diff.all_rows if row.stock_code]
        close_prices = prices.fetch_close_prices(current_date, stock_codes)
        enrich_with_prices(diff, close_prices)

    summary = build_summary(diff, len(current_rows), len(previous_rows))
    top_buy = _top_amount(diff.new_positions + diff.increased, reverse=True)
    top_sell = _top_amount(diff.sold_out + diff.decreased, reverse=False)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "etf": {
            "code": etf_code,
            "name": ETF_NAMES.get(etf_code, etf_code),
        },
        "dates": {
            "current": current_date,
            "previous": previous_date,
            "available": [item["date"] for item in _date_summaries(conn, etf_code)],
        },
        "source": {
            "source_used": source_used,
            "last_run": last_run,
        },
        "summary": summary,
        "brief": _brief(diff, summary, top_buy, top_sell),
        "highlights": {
            "top_buy": _row_identity(top_buy),
            "top_sell": _row_identity(top_sell),
        },
        "quality": _quality_payload(
            current_rows,
            source_used=source_used,
            last_run=last_run,
        ),
        "sections": {
            "new_positions": [_diff_row_payload(row) for row in diff.new_positions],
            "sold_out": [_diff_row_payload(row) for row in diff.sold_out],
            "increased": [_diff_row_payload(row) for row in diff.increased],
            "decreased": [_diff_row_payload(row) for row in diff.decreased],
            "top_holdings": top_holdings_change(previous_rows, current_rows, n=10),
        },
        "current_holdings": [
            _holding_payload(row, rank)
            for rank, row in enumerate(current_rows, start=1)
        ],
        "history": _date_summaries(conn, etf_code),
    }


def export_etf(
    db_path: Path,
    output_dir: Path,
    etf_code: str,
    *,
    include_prices: bool = True,
) -> Path | None:
    with _connect(db_path) as conn:
        payload = build_etf_payload(conn, etf_code, include_prices=include_prices)

    if payload is None:
        logger.warning("No holdings found for %s; skipping site export.", etf_code)
        return None

    etf_dir = output_dir / etf_code
    etf_dir.mkdir(parents=True, exist_ok=True)
    latest_path = etf_dir / "latest.json"
    latest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return latest_path


def write_manifest(output_dir: Path) -> Path:
    entries: list[dict[str, Any]] = []
    for latest_path in sorted(output_dir.glob("*/latest.json")):
        try:
            payload = json.loads(latest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("Skipping invalid JSON %s: %s", latest_path, exc)
            continue
        etf = payload.get("etf", {})
        dates = payload.get("dates", {})
        code = etf.get("code") or latest_path.parent.name
        entries.append(
            {
                "code": code,
                "name": etf.get("name") or ETF_NAMES.get(code, code),
                "latest_date": dates.get("current"),
                "previous_date": dates.get("previous"),
                "path": f"data/{code}/latest.json",
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "etfs": entries,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def export_site_data(
    db_path: Path,
    output_dir: Path,
    etfs: list[str] | None = None,
    *,
    include_prices: bool = True,
) -> list[Path]:
    with _connect(db_path) as conn:
        selected = etfs or _list_etfs(conn)

    paths: list[Path] = []
    for etf_code in selected:
        path = export_etf(
            db_path,
            output_dir,
            etf_code,
            include_prices=include_prices,
        )
        if path:
            paths.append(path)
    paths.append(write_manifest(output_dir))
    return paths


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export static website JSON data.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--etf",
        action="append",
        dest="etfs",
        help="ETF code to export. Repeat to export multiple ETFs. Defaults to all.",
    )
    parser.add_argument(
        "--skip-prices",
        action="store_true",
        help="Do not fetch close prices while exporting.",
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Only rebuild manifest.json from existing ETF JSON files.",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = _parse_args()
    db_path = Path(args.db_path)
    output_dir = Path(args.output_dir)

    if args.manifest_only:
        path = write_manifest(output_dir)
        print(f"[site-data] manifest={path}")
        return 0

    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    paths = export_site_data(
        db_path,
        output_dir,
        args.etfs,
        include_prices=not args.skip_prices,
    )
    for path in paths:
        print(f"[site-data] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
