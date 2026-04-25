"""SQLite persistence layer (raw sqlite3 — minimal dependency)."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

logger = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS holdings_daily (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT    NOT NULL,
    etf_code     TEXT    NOT NULL,
    stock_code   TEXT,
    stock_name   TEXT,
    weight_pct   REAL,
    shares       INTEGER,
    source_url   TEXT,
    raw_source   TEXT,
    scraped_at   TEXT    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(date, etf_code, stock_code)
);

CREATE INDEX IF NOT EXISTS idx_holdings_date_etf
    ON holdings_daily(date, etf_code);

CREATE TABLE IF NOT EXISTS run_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at       TEXT    NOT NULL,
    etf_code     TEXT    NOT NULL,
    status       TEXT    NOT NULL,
    message      TEXT,
    source_used  TEXT,
    data_date    TEXT,
    rows_count   INTEGER,
    report_path  TEXT,
    error_detail TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    etf_code     TEXT    NOT NULL,
    alert_type   TEXT    NOT NULL,
    severity     TEXT    NOT NULL,
    message      TEXT    NOT NULL,
    data_date    TEXT
);
"""


class HoldingsDB:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self.conn() as c:
            c.executescript(SCHEMA)

    # ---------- holdings ----------
    def upsert_holdings(self, rows: Iterable[dict]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = """
            INSERT INTO holdings_daily
                (date, etf_code, stock_code, stock_name, weight_pct,
                 shares, source_url, raw_source, scraped_at)
            VALUES
                (:date, :etf_code, :stock_code, :stock_name, :weight_pct,
                 :shares, :source_url, :raw_source, :scraped_at)
            ON CONFLICT(date, etf_code, stock_code) DO UPDATE SET
                stock_name = excluded.stock_name,
                weight_pct = excluded.weight_pct,
                shares     = excluded.shares,
                source_url = excluded.source_url,
                raw_source = excluded.raw_source,
                scraped_at = excluded.scraped_at
        """
        with self.conn() as c:
            c.executemany(sql, rows)
        return len(rows)

    def latest_dates(self, etf_code: str, limit: int = 2) -> list[str]:
        sql = """
            SELECT DISTINCT date FROM holdings_daily
            WHERE etf_code = ?
            ORDER BY date DESC
            LIMIT ?
        """
        with self.conn() as c:
            return [r["date"] for r in c.execute(sql, (etf_code, limit))]

    def get_holdings(self, etf_code: str, date: str) -> list[dict]:
        sql = """
            SELECT * FROM holdings_daily
            WHERE etf_code = ? AND date = ?
            ORDER BY weight_pct DESC NULLS LAST
        """
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, (etf_code, date))]

    def has_date(self, etf_code: str, date: str) -> bool:
        with self.conn() as c:
            row = c.execute(
                "SELECT 1 FROM holdings_daily WHERE etf_code=? AND date=? LIMIT 1",
                (etf_code, date),
            ).fetchone()
        return row is not None

    # ---------- run logs ----------
    def log_run(
        self,
        etf_code: str,
        status: str,
        message: str = "",
        source_used: str | None = None,
        data_date: str | None = None,
        rows_count: int | None = None,
        report_path: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        sql = """
            INSERT INTO run_logs
                (run_at, etf_code, status, message, source_used,
                 data_date, rows_count, report_path, error_detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.conn() as c:
            c.execute(
                sql,
                (
                    datetime.now().isoformat(timespec="seconds"),
                    etf_code,
                    status,
                    message,
                    source_used,
                    data_date,
                    rows_count,
                    report_path,
                    error_detail,
                ),
            )

    # ---------- alerts ----------
    def add_alert(
        self,
        etf_code: str,
        alert_type: str,
        severity: str,
        message: str,
        data_date: str | None = None,
    ) -> None:
        sql = """
            INSERT INTO alerts
                (etf_code, alert_type, severity, message, data_date)
            VALUES (?, ?, ?, ?, ?)
        """
        with self.conn() as c:
            c.execute(sql, (etf_code, alert_type, severity, message, data_date))
