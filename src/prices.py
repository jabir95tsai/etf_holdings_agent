"""Fetch daily close prices for Taiwan stocks."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import requests

from .scraper import DEFAULT_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text or text in {"-", "--", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _roc_date(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{dt.year - 1911:03d}/{dt.month:02d}/{dt.day:02d}"


def fetch_twse_close_prices(date_str: str) -> dict[str, float]:
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
    params = {
        "response": "json",
        "date": date_str.replace("-", ""),
        "type": "ALLBUT0999",
    }
    resp = requests.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=DEFAULT_TIMEOUT,
        verify=False,
    )
    resp.raise_for_status()
    payload = resp.json()

    prices: dict[str, float] = {}
    for table in payload.get("tables", []):
        fields = table.get("fields", [])
        if "證券代號" not in fields or "收盤價" not in fields:
            continue
        code_idx = fields.index("證券代號")
        close_idx = fields.index("收盤價")
        for row in table.get("data", []):
            if len(row) <= max(code_idx, close_idx):
                continue
            price = _to_float(row[close_idx])
            if price is not None:
                prices[str(row[code_idx]).strip()] = price
    return prices


def fetch_tpex_close_prices(date_str: str) -> dict[str, float]:
    url = (
        "https://www.tpex.org.tw/web/stock/aftertrading/"
        "daily_close_quotes/stk_quote_result.php"
    )
    params = {
        "l": "zh-tw",
        "o": "json",
        "d": _roc_date(date_str),
        "s": "0,asc,0",
    }
    resp = requests.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=DEFAULT_TIMEOUT,
        verify=False,
    )
    resp.raise_for_status()
    payload = resp.json()

    prices: dict[str, float] = {}
    for table in payload.get("tables", []):
        fields = [str(f).strip() for f in table.get("fields", [])]
        if "代號" not in fields or "收盤" not in fields:
            continue
        code_idx = fields.index("代號")
        close_idx = fields.index("收盤")
        for row in table.get("data", []):
            if len(row) <= max(code_idx, close_idx):
                continue
            price = _to_float(row[close_idx])
            if price is not None:
                prices[str(row[code_idx]).strip()] = price
    return prices


def fetch_close_prices(date_str: str, stock_codes: list[str]) -> dict[str, float]:
    """Fetch close prices from TWSE and TPEx, returning only requested codes."""
    wanted = {code for code in stock_codes if code}
    prices: dict[str, float] = {}
    for source_name, fetcher in (
        ("twse", fetch_twse_close_prices),
        ("tpex", fetch_tpex_close_prices),
    ):
        try:
            source_prices = fetcher(date_str)
            prices.update({k: v for k, v in source_prices.items() if k in wanted})
        except Exception as e:
            logger.warning("Failed to fetch %s close prices for %s: %s", source_name, date_str, e)
    missing = sorted(wanted - set(prices))
    if missing:
        logger.warning(
            "Missing close prices for %d codes on %s: %s",
            len(missing),
            date_str,
            ", ".join(missing[:10]),
        )
    return prices
