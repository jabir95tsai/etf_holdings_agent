"""Scrapers for ETF holdings.

Strategy: try configured sources in order.
Saves raw payloads to data/raw/ for traceability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests

from . import parser

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 20
DEFAULT_SOURCE_ORDER = ["moneydj", "ezmoney", "official", "twse"]
EZMONEY_EXCEL_URL = (
    "https://www.ezmoney.com.tw/ETF/Fund/AssetExcelNPOI?FundCode=49YTW"
)
EZMONEY_REFERER_URL = "https://www.ezmoney.com.tw/ETF/Fund/Info?FundCode=49YTW"


@dataclass
class ScrapeResult:
    source: str  # official | moneydj | twse | other
    source_url: str
    data_date: str | None
    rows: list[dict]
    raw_path: Path | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.rows)


@dataclass(frozen=True)
class SourceSpec:
    name: str
    scrape: Callable[[], ScrapeResult]


def _save_raw(raw_dir: Path, source: str, etf_code: str, content: bytes, ext: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = raw_dir / f"{etf_code}_{source}_{ts}.{ext}"
    path.write_bytes(content)
    return path


def _http_get(url: str, **kwargs) -> requests.Response:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }
    headers.update(kwargs.pop("headers", {}) or {})
    resp = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT,
                        verify=False, **kwargs)
    resp.raise_for_status()
    return resp


# ---------- Source-specific scrapers ----------
def scrape_upamc(etf_code: str, raw_dir: Path, url: str) -> ScrapeResult:
    result = ScrapeResult(source="official", source_url=url, data_date=None, rows=[])
    try:
        resp = _http_get(url)
        ctype = resp.headers.get("Content-Type", "").lower()
        if "json" in ctype:
            raw = _save_raw(raw_dir, "official", etf_code, resp.content, "json")
            data_date, rows = parser.parse_upamc_json(resp.text)
        else:
            raw = _save_raw(raw_dir, "official", etf_code, resp.content, "html")
            data_date, rows = parser.parse_upamc_html(resp.text)
        result.raw_path = raw
        result.data_date = data_date
        result.rows = rows
        if not rows:
            result.errors.append("UPAMC returned no parseable rows")
    except Exception as e:
        logger.warning("UPAMC scrape failed: %s", e)
        result.errors.append(f"upamc: {e}")
    return result


def scrape_moneydj(etf_code: str, raw_dir: Path, url: str) -> ScrapeResult:
    result = ScrapeResult(source="moneydj", source_url=url, data_date=None, rows=[])
    try:
        resp = _http_get(url)
        # MoneyDJ pages often use Big5; let requests guess via apparent_encoding
        if resp.encoding and resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or "utf-8"
        raw = _save_raw(raw_dir, "moneydj", etf_code, resp.content, "html")
        data_date, rows = parser.parse_moneydj_html(resp.text)
        result.raw_path = raw
        result.data_date = data_date
        result.rows = rows
        if not rows:
            result.errors.append("MoneyDJ returned no parseable rows")
    except Exception as e:
        logger.warning("MoneyDJ scrape failed: %s", e)
        result.errors.append(f"moneydj: {e}")
    return result


def scrape_twse(etf_code: str, raw_dir: Path, url: str) -> ScrapeResult:
    result = ScrapeResult(source="twse", source_url=url, data_date=None, rows=[])
    try:
        resp = _http_get(url)
        ctype = resp.headers.get("Content-Type", "").lower()
        if "json" in ctype:
            raw = _save_raw(raw_dir, "twse", etf_code, resp.content, "json")
            data_date, rows = parser.parse_twse_json(resp.text)
        else:
            raw = _save_raw(raw_dir, "twse", etf_code, resp.content, "html")
            data_date, rows = parser.parse_moneydj_html(resp.text)
        result.raw_path = raw
        result.data_date = data_date
        result.rows = rows
        if not rows:
            result.errors.append("TWSE returned no parseable rows")
    except Exception as e:
        logger.warning("TWSE scrape failed: %s", e)
        result.errors.append(f"twse: {e}")
    return result


def scrape_ezmoney_excel(
    etf_code: str,
    raw_dir: Path,
    url: str = EZMONEY_EXCEL_URL,
    referer_url: str = EZMONEY_REFERER_URL,
) -> ScrapeResult:
    """Download ezmoney Excel holdings file (most reliable source)."""
    result = ScrapeResult(source="ezmoney", source_url=url, data_date=None, rows=[])
    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": referer_url,
        }
        resp = requests.get(url, headers=headers, verify=False,
                            timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()

        # Extract date from Content-Disposition filename if present
        cd = resp.headers.get("Content-Disposition", "")
        filename_date: str | None = None
        import re
        m = re.search(r"(\d{8})\.xlsx", cd)
        if m:
            ds = m.group(1)
            from .parser import _normalize_date
            filename_date = _normalize_date(f"{ds[:4]}-{ds[4:6]}-{ds[6:]}")

        raw = _save_raw(raw_dir, "ezmoney", etf_code, resp.content, "xlsx")
        data_date, rows = parser.parse_ezmoney_xlsx(resp.content)

        result.raw_path = raw
        result.data_date = data_date or filename_date
        result.rows = rows
        if not rows:
            result.errors.append("ezmoney Excel returned no parseable rows")
    except Exception as e:
        logger.warning("ezmoney Excel scrape failed: %s", e)
        result.errors.append(f"ezmoney: {e}")
    return result


# ---------- Orchestrator ----------
def build_source_specs(
    *,
    etf_code: str,
    raw_dir: Path,
    upamc_url: str,
    moneydj_url: str,
    twse_url: str,
    ezmoney_excel_url: str = EZMONEY_EXCEL_URL,
    ezmoney_referer_url: str = EZMONEY_REFERER_URL,
) -> dict[str, SourceSpec]:
    return {
        "ezmoney": SourceSpec(
            "ezmoney",
            lambda: scrape_ezmoney_excel(
                etf_code,
                raw_dir,
                ezmoney_excel_url,
                ezmoney_referer_url,
            ),
        ),
        "official": SourceSpec(
            "official",
            lambda: scrape_upamc(etf_code, raw_dir, upamc_url),
        ),
        "moneydj": SourceSpec(
            "moneydj",
            lambda: scrape_moneydj(etf_code, raw_dir, moneydj_url),
        ),
        "twse": SourceSpec(
            "twse",
            lambda: scrape_twse(etf_code, raw_dir, twse_url),
        ),
    }


def _ordered_sources(
    specs: dict[str, SourceSpec],
    source_order: list[str] | None,
) -> list[SourceSpec]:
    ordered: list[SourceSpec] = []
    seen: set[str] = set()
    for source_name in source_order or DEFAULT_SOURCE_ORDER:
        key = source_name.strip().lower()
        if not key or key in seen:
            continue
        spec = specs.get(key)
        if spec is None:
            logger.warning("Unknown source in SOURCE_ORDER ignored: %s", source_name)
            continue
        ordered.append(spec)
        seen.add(key)
    return ordered


def scrape_holdings(
    etf_code: str,
    raw_dir: Path,
    upamc_url: str,
    moneydj_url: str,
    twse_url: str,
    ezmoney_excel_url: str = EZMONEY_EXCEL_URL,
    ezmoney_referer_url: str = EZMONEY_REFERER_URL,
    source_order: list[str] | None = None,
) -> ScrapeResult:
    """Try configured sources until one returns parseable rows."""
    specs = build_source_specs(
        etf_code=etf_code,
        raw_dir=raw_dir,
        upamc_url=upamc_url,
        moneydj_url=moneydj_url,
        twse_url=twse_url,
        ezmoney_excel_url=ezmoney_excel_url,
        ezmoney_referer_url=ezmoney_referer_url,
    )
    sources = _ordered_sources(specs, source_order)

    if not sources:
        return ScrapeResult(
            source="other",
            source_url="",
            data_date=None,
            rows=[],
            errors=["No enabled data sources"],
        )

    last: ScrapeResult | None = None
    accumulated_errors: list[str] = []
    for source in sources:
        result = source.scrape()
        accumulated_errors.extend(result.errors)
        if result.ok:
            result.errors = accumulated_errors
            return result
        last = result
    # All failed
    if last is None:
        last = ScrapeResult(source="other", source_url="", data_date=None, rows=[])
    last.errors = accumulated_errors
    return last


def to_holdings_rows(
    result: ScrapeResult,
    etf_code: str,
    fallback_date: str | None = None,
) -> list[dict]:
    """Convert ScrapeResult rows to DB-ready dicts."""
    scraped_at = datetime.now().isoformat(timespec="seconds")
    data_date = result.data_date or fallback_date
    out: list[dict] = []
    for r in result.rows:
        out.append(
            {
                "date": data_date,
                "etf_code": etf_code,
                "stock_code": r.get("stock_code"),
                "stock_name": r.get("stock_name"),
                "weight_pct": r.get("weight_pct"),
                "shares": r.get("shares"),
                "source_url": result.source_url,
                "raw_source": result.source,
                "scraped_at": scraped_at,
            }
        )
    return out
