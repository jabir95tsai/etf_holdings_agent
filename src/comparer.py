"""Compare two snapshots of holdings and classify changes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

CHANGE_NEW = "New Position"
CHANGE_SOLD = "Sold Out"
CHANGE_INCREASED = "Increased"
CHANGE_DECREASED = "Decreased"
CHANGE_UNCHANGED = "Unchanged"

# Any non-zero share delta counts as a real holding change.
SHARES_EPS = 0


@dataclass
class DiffRow:
    stock_code: str | None
    stock_name: str | None
    previous_shares: int | None
    current_shares: int | None
    delta_shares: int | None
    previous_weight_pct: float | None
    current_weight_pct: float | None
    delta_weight_pct: float | None
    delta_weight_bp: float | None
    change_type: str
    close_price: float | None = None
    estimated_change_amount: float | None = None
    abs_delta_weight_rank: int | None = None
    abs_delta_shares_rank: int | None = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class DiffReport:
    previous_date: str | None
    current_date: str | None
    new_positions: list[DiffRow] = field(default_factory=list)
    sold_out: list[DiffRow] = field(default_factory=list)
    increased: list[DiffRow] = field(default_factory=list)
    decreased: list[DiffRow] = field(default_factory=list)
    unchanged: list[DiffRow] = field(default_factory=list)

    @property
    def all_rows(self) -> list[DiffRow]:
        return (
            self.new_positions
            + self.sold_out
            + self.increased
            + self.decreased
            + self.unchanged
        )


def _key(row: dict) -> str:
    """Prefer stock_code; fall back to stock_name."""
    return (row.get("stock_code") or row.get("stock_name") or "").strip()


def _index(rows: Iterable[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows:
        k = _key(r)
        if not k:
            continue
        # If duplicate, keep the row with the larger weight (defensive)
        existing = out.get(k)
        if existing is None or (r.get("weight_pct") or 0) > (existing.get("weight_pct") or 0):
            out[k] = r
    return out


def _safe_sub(a, b):
    if a is None or b is None:
        return None
    return a - b


def _effective_delta_shares(row: DiffRow) -> int | None:
    if row.delta_shares is not None:
        return row.delta_shares
    if row.change_type == CHANGE_NEW:
        return row.current_shares
    if row.change_type == CHANGE_SOLD and row.previous_shares is not None:
        return -row.previous_shares
    return None


def enrich_with_prices(
    diff: DiffReport,
    close_prices: dict[str, float],
) -> DiffReport:
    """Attach close price and estimated amount change to each diff row."""
    for row in diff.all_rows:
        code = row.stock_code or ""
        close_price = close_prices.get(code)
        delta_shares = _effective_delta_shares(row)
        row.close_price = close_price
        row.estimated_change_amount = (
            delta_shares * close_price
            if delta_shares is not None and close_price is not None
            else None
        )
    return diff


def compare(
    previous: list[dict],
    current: list[dict],
    previous_date: str | None,
    current_date: str | None,
) -> DiffReport:
    prev_idx = _index(previous)
    curr_idx = _index(current)

    report = DiffReport(previous_date=previous_date, current_date=current_date)

    all_keys = set(prev_idx) | set(curr_idx)
    for k in all_keys:
        p = prev_idx.get(k)
        c = curr_idx.get(k)

        prev_shares = p.get("shares") if p else None
        curr_shares = c.get("shares") if c else None
        prev_weight = p.get("weight_pct") if p else None
        curr_weight = c.get("weight_pct") if c else None

        delta_shares = _safe_sub(curr_shares, prev_shares)
        delta_weight = _safe_sub(curr_weight, prev_weight)
        delta_bp = delta_weight * 100 if delta_weight is not None else None

        if p is None and c is not None:
            ctype = CHANGE_NEW
        elif p is not None and c is None:
            ctype = CHANGE_SOLD
        else:
            # both present
            if delta_shares is not None and delta_shares > SHARES_EPS:
                ctype = CHANGE_INCREASED
            elif delta_shares is not None and delta_shares < -SHARES_EPS:
                ctype = CHANGE_DECREASED
            else:
                ctype = CHANGE_UNCHANGED

        row = DiffRow(
            stock_code=(c or p).get("stock_code"),
            stock_name=(c or p).get("stock_name"),
            previous_shares=prev_shares,
            current_shares=curr_shares,
            delta_shares=delta_shares,
            previous_weight_pct=prev_weight,
            current_weight_pct=curr_weight,
            delta_weight_pct=delta_weight,
            delta_weight_bp=delta_bp,
            change_type=ctype,
        )

        if ctype == CHANGE_NEW:
            report.new_positions.append(row)
        elif ctype == CHANGE_SOLD:
            report.sold_out.append(row)
        elif ctype == CHANGE_INCREASED:
            report.increased.append(row)
        elif ctype == CHANGE_DECREASED:
            report.decreased.append(row)
        else:
            report.unchanged.append(row)

    # Sort
    report.new_positions.sort(key=lambda r: -(r.current_weight_pct or 0))
    report.sold_out.sort(key=lambda r: -(r.previous_weight_pct or 0))
    report.increased.sort(
        key=lambda r: (-(r.delta_shares or 0), -abs(r.delta_weight_bp or 0))
    )
    report.decreased.sort(
        key=lambda r: ((r.delta_shares or 0), -abs(r.delta_weight_bp or 0))
    )

    # Rank by abs delta
    by_w = sorted(
        report.all_rows,
        key=lambda r: -abs(r.delta_weight_bp or 0),
    )
    for i, r in enumerate(by_w, start=1):
        r.abs_delta_weight_rank = i
    by_s = sorted(
        report.all_rows,
        key=lambda r: -abs(r.delta_shares or 0),
    )
    for i, r in enumerate(by_s, start=1):
        r.abs_delta_shares_rank = i

    return report


def top_holdings_change(
    previous: list[dict],
    current: list[dict],
    n: int = 10,
) -> list[dict]:
    """Compute top-N holdings change rows (rank delta of top n)."""
    p_sorted = sorted(previous, key=lambda r: -(r.get("weight_pct") or 0))
    c_sorted = sorted(current, key=lambda r: -(r.get("weight_pct") or 0))
    p_rank = {_key(r): i + 1 for i, r in enumerate(p_sorted)}
    p_idx = _index(previous)

    out: list[dict] = []
    for i, r in enumerate(c_sorted[:n], start=1):
        k = _key(r)
        prev = p_idx.get(k)
        out.append(
            {
                "current_rank": i,
                "previous_rank": p_rank.get(k),
                "stock_code": r.get("stock_code"),
                "stock_name": r.get("stock_name"),
                "current_weight_pct": r.get("weight_pct"),
                "previous_weight_pct": prev.get("weight_pct") if prev else None,
                "delta_weight_bp": (
                    ((r.get("weight_pct") or 0) - (prev.get("weight_pct") or 0)) * 100
                    if prev
                    else None
                ),
            }
        )
    return out
