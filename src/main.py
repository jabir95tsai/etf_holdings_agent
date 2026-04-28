"""Main entry point: orchestrates scrape → store → diff → report → notify."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from datetime import datetime

import pytz

from . import comparer, notifier, prices, reporter, scraper
from .config import AppConfig, load_config, setup_logging
from .db import HoldingsDB
from .reporter import (
    QualityCheck,
    build_summary,
    quality_check,
    render_failure_md,
    render_markdown,
    render_no_update_md,
    report_paths,
    write_csv,
    write_markdown,
)

logger = logging.getLogger(__name__)


def _now(tz: str) -> datetime:
    return datetime.now(pytz.timezone(tz))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="00981A daily holdings tracker")
    p.add_argument("--etf", default="00981A", help="ETF code (default 00981A)")
    p.add_argument(
        "--date",
        default=None,
        help="Override the data date (YYYY-MM-DD) used when persisting "
        "the scraped snapshot (advanced).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write to DB and do not send email.",
    )
    p.add_argument(
        "--notify-test",
        action="store_true",
        help="Send a Gmail test email and exit.",
    )
    p.add_argument(
        "--force-report",
        action="store_true",
        help="Re-generate the report even if no new data.",
    )
    return p.parse_args()


def _persist(db: HoldingsDB, rows: list[dict]) -> int:
    # Drop rows that have no date (cannot satisfy unique constraint)
    rows = [r for r in rows if r.get("date")]
    return db.upsert_holdings(rows)


def run(cfg: AppConfig, args: argparse.Namespace) -> int:
    db = HoldingsDB(cfg.db_path)
    run_at = _now(cfg.timezone)

    if args.notify_test:
        ok = notifier.send_test(cfg.gmail)
        print("Gmail test:", "OK" if ok else "FAILED (check env / app password)")
        return 0 if ok else 1

    source_used = "n/a"
    scraped_date: str | None = None

    # ---------- 1. Scrape ----------
    try:
        result = scraper.scrape_holdings(
            etf_code=cfg.etf_code,
            raw_dir=cfg.raw_dir,
            upamc_url=cfg.upamc_url,
            moneydj_url=cfg.moneydj_url,
            twse_url=cfg.twse_url,
            ezmoney_excel_url=cfg.ezmoney_excel_url,
            ezmoney_referer_url=cfg.ezmoney_referer_url,
            source_order=cfg.source_order,
        )
        source_used = result.source
        scraped_date = result.data_date
    except Exception as e:
        return _handle_failure(
            cfg, db, run_at, stage="scrape", error=str(e), source_used=source_used
        )

    if not result.ok:
        msg = "All data sources failed: " + "; ".join(result.errors)
        return _handle_failure(
            cfg, db, run_at, stage="scrape", error=msg, source_used=source_used
        )

    if not result.data_date and not args.date:
        # No date in payload — treat as data quality issue but still try to compare
        logger.warning("Scraped data has no date; using today as fallback.")

    fallback_date = args.date or run_at.strftime("%Y-%m-%d")
    rows = scraper.to_holdings_rows(result, cfg.etf_code, fallback_date=fallback_date)
    current_date = rows[0]["date"] if rows else None

    # ---------- 2. Compare against previous DB snapshot ----------
    latest_dates = db.latest_dates(cfg.etf_code, limit=2)
    db_latest = latest_dates[0] if latest_dates else None
    is_new_data = bool(current_date and current_date != db_latest)

    qc = quality_check(
        rows=rows,
        scrape_ok=True,
        is_new_data=is_new_data,
        source_used=source_used,
        has_data_date=bool(result.data_date),
    )

    # ---------- 3. Persist (unless dry-run) ----------
    if not args.dry_run and current_date:
        try:
            written = _persist(db, rows)
            logger.info("Persisted %d holding rows for %s", written, current_date)
        except Exception as e:
            logger.error("Persist failed: %s", e)
            db.add_alert(cfg.etf_code, "persist_failed", "high", str(e), current_date)

    for note in qc.notes:
        if not args.dry_run:
            db.add_alert(cfg.etf_code, "quality", "warning", note, current_date)

    # ---------- 4. No new data path ----------
    if not is_new_data and not args.force_report:
        md = render_no_update_md(
            etf_code=cfg.etf_code,
            run_at=run_at,
            db_latest_date=db_latest,
            scraped_date=current_date,
        )
        report_date = run_at.strftime("%Y-%m-%d")
        md_path, _csv_path = report_paths(cfg.report_dir, cfg.etf_code, report_date)
        write_markdown(md_path, md)

        if cfg.gmail.notify_on_no_update and not args.dry_run:
            notifier.send_email(
                cfg.gmail,
                subject=notifier.subject_no_update(cfg.etf_code, report_date),
                body_text=md,
                body_html=notifier.md_to_simple_html(md),
                attachments=[md_path],
            )
        if not args.dry_run:
            db.log_run(
                etf_code=cfg.etf_code,
                status="no_update",
                message="No new data",
                source_used=source_used,
                data_date=current_date,
                rows_count=len(rows),
                report_path=str(md_path),
            )
        print(f"[no-update] db_latest={db_latest} scraped={current_date}")
        return 0

    # ---------- 5. Diff & report ----------
    # Pick previous date: prefer second-latest from DB; if equal to current, fall back.
    previous_date: str | None = None
    if len(latest_dates) >= 1:
        # latest_dates returns newest first; if first == current_date (just inserted),
        # take the next; else first is previous.
        if latest_dates[0] == current_date and len(latest_dates) >= 2:
            previous_date = latest_dates[1]
        elif latest_dates[0] != current_date:
            previous_date = latest_dates[0]

    previous_rows = (
        db.get_holdings(cfg.etf_code, previous_date) if previous_date else []
    )
    current_rows_db = (
        db.get_holdings(cfg.etf_code, current_date)
        if (current_date and not args.dry_run)
        else rows
    )

    diff = comparer.compare(
        previous=previous_rows,
        current=current_rows_db,
        previous_date=previous_date,
        current_date=current_date,
    )
    if current_date:
        stock_codes = [r.stock_code for r in diff.all_rows if r.stock_code]
        close_prices = prices.fetch_close_prices(current_date, stock_codes)
        comparer.enrich_with_prices(diff, close_prices)

    md = render_markdown(
        etf_code=cfg.etf_code,
        run_at=run_at,
        diff=diff,
        current_rows=current_rows_db,
        previous_rows=previous_rows,
        qc=qc,
        source_used=source_used,
    )

    md_path, csv_path = report_paths(
        cfg.report_dir, cfg.etf_code, current_date or run_at.strftime("%Y-%m-%d")
    )
    write_markdown(md_path, md)
    write_csv(csv_path, diff)

    summary = build_summary(diff, len(current_rows_db), len(previous_rows))

    if not args.dry_run:
        notifier.send_email(
            cfg.gmail,
            subject=notifier.subject_diff(cfg.etf_code, current_date or "N/A", summary),
            body_text=md,
            body_html=notifier.md_to_simple_html(md),
            attachments=[md_path],
        )
        db.log_run(
            etf_code=cfg.etf_code,
            status="ok",
            message=(
                f"new={summary['new_count']} sold={summary['sold_count']} "
                f"inc={summary['increased_count']} dec={summary['decreased_count']}"
            ),
            source_used=source_used,
            data_date=current_date,
            rows_count=len(rows),
            report_path=str(md_path),
        )

    print(
        f"[ok] date={current_date} prev={previous_date} "
        f"new={summary['new_count']} sold={summary['sold_count']} "
        f"inc={summary['increased_count']} dec={summary['decreased_count']} "
        f"report={md_path}"
    )
    return 0


def _handle_failure(
    cfg: AppConfig,
    db: HoldingsDB,
    run_at: datetime,
    *,
    stage: str,
    error: str,
    source_used: str,
) -> int:
    logger.error("Run failed at stage=%s: %s", stage, error)
    md = render_failure_md(cfg.etf_code, run_at, stage, error, source_used)
    date_str = run_at.strftime("%Y-%m-%d")
    md_path, _ = report_paths(cfg.report_dir, cfg.etf_code, f"FAIL_{date_str}")
    try:
        write_markdown(md_path, md)
    except Exception:
        md_path = None  # type: ignore

    try:
        notifier.send_email(
            cfg.gmail,
            subject=notifier.subject_failure(cfg.etf_code, date_str),
            body_text=md,
            body_html=notifier.md_to_simple_html(md),
            attachments=[md_path] if md_path else None,
        )
    except Exception as e:
        logger.error("Failed to send failure email: %s", e)

    try:
        db.log_run(
            etf_code=cfg.etf_code,
            status="failed",
            message=f"stage={stage}",
            source_used=source_used,
            error_detail=error,
        )
        db.add_alert(cfg.etf_code, "run_failed", "high", error)
    except Exception:
        pass
    return 1


def main() -> int:
    setup_logging()
    args = _parse_args()
    cfg = load_config(etf_code=args.etf)
    try:
        return run(cfg, args)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Unhandled error: %s\n%s", e, tb)
        # Best-effort failure email
        try:
            db = HoldingsDB(cfg.db_path)
            return _handle_failure(
                cfg,
                db,
                _now(cfg.timezone),
                stage="unhandled",
                error=str(e),
                source_used="n/a",
            )
        except Exception:
            return 1


if __name__ == "__main__":
    sys.exit(main())
