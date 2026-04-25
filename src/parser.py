"""Parsers turning raw HTML / JSON into a standardized list[dict] of holdings.

Each parser returns a tuple: (data_date_str, list_of_rows).
Each row keys: stock_code, stock_name, weight_pct, shares.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


_NUM_RE = re.compile(r"[-+]?\d*\.?\d+")


def _to_float(s: Any) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).replace(",", "").replace("%", "").strip()
    if not s or s in {"-", "--", "N/A"}:
        return None
    m = _NUM_RE.search(s)
    return float(m.group()) if m else None


def _to_int(s: Any) -> int | None:
    f = _to_float(s)
    return int(f) if f is not None else None


def _normalize_date(s: str) -> str | None:
    """Accept 2026/04/24, 2026-4-24, 民國 115/04/24, etc. Return YYYY-MM-DD."""
    if not s:
        return None
    s = s.strip()
    # Try YYYY-MM-DD or YYYY/MM/DD
    m = re.search(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            return None
    # ROC-format: 115/04/24  -> 2026/04/24
    m = re.search(r"(\d{2,3})[/\-.](\d{1,2})[/\-.](\d{1,2})", s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        if y < 1911:
            y += 1911
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def _clean_code(code: Any) -> str | None:
    if code is None:
        return None
    code = str(code).strip().upper()
    if not code or code in {"-", "N/A"}:
        return None
    # Strip suffixes like .TW
    code = code.split(".")[0]
    return code or None


def _clean_name(name: Any) -> str | None:
    if name is None:
        return None
    name = str(name).strip()
    return name or None


# ---------- UPAMC (統一投信) ----------
def parse_upamc_html(html: str) -> tuple[str | None, list[dict]]:
    """Parse 統一投信 holdings page. Best-effort table-based parser."""
    soup = BeautifulSoup(html, "lxml")
    data_date = _extract_date_from_text(soup.get_text(" ", strip=True))

    rows: list[dict] = []
    for table in soup.find_all("table"):
        header = _table_header(table)
        if not header:
            continue
        if not _looks_like_holdings_header(header):
            continue
        col_idx = _map_columns(header)
        if col_idx.get("name") is None:
            continue
        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if not cells or len(cells) < 2:
                continue
            row = _row_from_cells(cells, col_idx)
            if row and (row["stock_code"] or row["stock_name"]):
                rows.append(row)
        if rows:
            break
    return data_date, rows


def parse_upamc_json(payload: Any) -> tuple[str | None, list[dict]]:
    """Parse a JSON payload from UPAMC if such an endpoint exists."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None, []

    data_date = None
    items: list[Any] = []

    if isinstance(payload, dict):
        for key in ("data", "Data", "result", "items", "list"):
            v = payload.get(key)
            if isinstance(v, list):
                items = v
                break
        for key in ("date", "asOfDate", "dataDate", "Date"):
            v = payload.get(key)
            if v:
                data_date = _normalize_date(str(v))
                break
    elif isinstance(payload, list):
        items = payload

    rows: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "stock_code": _clean_code(
                    item.get("stockCode") or item.get("code") or item.get("symbol")
                ),
                "stock_name": _clean_name(
                    item.get("stockName") or item.get("name") or item.get("Name")
                ),
                "weight_pct": _to_float(
                    item.get("weight") or item.get("Weight") or item.get("ratio")
                ),
                "shares": _to_int(
                    item.get("shares") or item.get("Shares") or item.get("quantity")
                ),
            }
        )
    return data_date, rows


# ---------- MoneyDJ ----------
def parse_moneydj_html(html: str) -> tuple[str | None, list[dict]]:
    soup = BeautifulSoup(html, "lxml")
    data_date = _extract_date_from_text(soup.get_text(" ", strip=True))

    rows: list[dict] = []
    for table in soup.find_all("table"):
        header = _table_header(table)
        if not header or not _looks_like_holdings_header(header):
            continue
        col_idx = _map_columns(header)
        if col_idx.get("name") is None:
            continue
        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            row = _row_from_cells(cells, col_idx)
            if row and (row["stock_code"] or row["stock_name"]):
                rows.append(row)
        if rows:
            break
    return data_date, rows


# ---------- TWSE ----------
def parse_twse_json(payload: Any) -> tuple[str | None, list[dict]]:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None, []
    if not isinstance(payload, dict):
        return None, []

    data_date = None
    for key in ("date", "asOfDate", "Date"):
        if payload.get(key):
            data_date = _normalize_date(str(payload[key]))
            break

    rows: list[dict] = []
    items = payload.get("data") or payload.get("aaData") or []
    fields = payload.get("fields") or payload.get("columns") or []
    fmap = {f: i for i, f in enumerate(fields)} if fields else {}

    for item in items:
        if isinstance(item, list):
            row = {
                "stock_code": _clean_code(
                    item[fmap.get("股票代號", 0)] if fmap else (item[0] if item else None)
                ),
                "stock_name": _clean_name(
                    item[fmap.get("股票名稱", 1)] if fmap else (item[1] if len(item) > 1 else None)
                ),
                "shares": _to_int(item[fmap.get("持有股數", 2)] if fmap else (item[2] if len(item) > 2 else None)),
                "weight_pct": _to_float(
                    item[fmap.get("佔淨值比例", 3)] if fmap else (item[3] if len(item) > 3 else None)
                ),
            }
        elif isinstance(item, dict):
            row = {
                "stock_code": _clean_code(item.get("stockCode") or item.get("code")),
                "stock_name": _clean_name(item.get("stockName") or item.get("name")),
                "shares": _to_int(item.get("shares")),
                "weight_pct": _to_float(item.get("weight")),
            }
        else:
            continue
        if row["stock_code"] or row["stock_name"]:
            rows.append(row)
    return data_date, rows


# ---------- Helpers ----------
def _table_header(table) -> list[str]:
    first_row = table.find("tr")
    if not first_row:
        return []
    return [c.get_text(" ", strip=True) for c in first_row.find_all(["th", "td"])]


_HOLDINGS_HEADER_HINTS = (
    "股票代號",
    "證券代號",
    "代號",
    "股票名稱",
    "證券名稱",
    "名稱",
    "持有股數",
    "股數",
    "投資比例",
    "佔淨值比例",
    "佔淨值",
    "比例",
    "權重",
)


def _looks_like_holdings_header(header: list[str]) -> bool:
    joined = " ".join(header)
    return any(h in joined for h in _HOLDINGS_HEADER_HINTS)


def _map_columns(header: list[str]) -> dict[str, int]:
    idx: dict[str, int] = {}
    for i, h in enumerate(header):
        h_clean = h.replace(" ", "")
        if any(k in h_clean for k in ("股票代號", "證券代號")) and "name" not in idx:
            idx["code"] = i
        elif h_clean in {"代號", "代碼"} and "code" not in idx:
            idx["code"] = i
        elif any(k in h_clean for k in ("股票名稱", "證券名稱")):
            idx["name"] = i
        elif h_clean == "名稱" and "name" not in idx:
            idx["name"] = i
        elif "股數" in h_clean or "持股" in h_clean:
            idx.setdefault("shares", i)
        elif any(k in h_clean for k in ("比例", "權重", "佔淨值")):
            idx.setdefault("weight", i)
    return idx


def _row_from_cells(cells: list[str], col_idx: dict[str, int]) -> dict | None:
    def get(key: str) -> str | None:
        i = col_idx.get(key)
        return cells[i] if i is not None and i < len(cells) else None

    return {
        "stock_code": _clean_code(get("code")),
        "stock_name": _clean_name(get("name")),
        "weight_pct": _to_float(get("weight")),
        "shares": _to_int(get("shares")),
    }


def _extract_date_from_text(text: str) -> str | None:
    # Search for a date in the page text
    candidates = re.findall(r"\d{2,4}[/\-.]\d{1,2}[/\-.]\d{1,2}", text)
    for c in candidates:
        d = _normalize_date(c)
        if d:
            return d
    return None
