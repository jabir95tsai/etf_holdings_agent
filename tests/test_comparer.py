"""Comparer tests covering each change classification."""

from __future__ import annotations

from src import comparer


def _row(code, name, shares, weight):
    return {
        "stock_code": code,
        "stock_name": name,
        "shares": shares,
        "weight_pct": weight,
    }


def test_classifies_new_sold_inc_dec_unchanged():
    previous = [
        _row("2330", "台積電", 100_000, 8.0),    # decreased
        _row("2317", "鴻海", 500_000, 5.0),      # unchanged
        _row("2454", "聯發科", 30_000, 4.0),     # sold out
        _row("2308", "台達電", 80_000, 3.5),     # increased
    ]
    current = [
        _row("2330", "台積電", 90_000, 7.6),
        _row("2317", "鴻海", 500_000, 5.0),
        _row("2308", "台達電", 100_000, 4.2),
        _row("2412", "中華電", 60_000, 2.0),     # new
    ]

    diff = comparer.compare(previous, current, "2026-04-23", "2026-04-24")

    assert {r.stock_code for r in diff.new_positions} == {"2412"}
    assert {r.stock_code for r in diff.sold_out} == {"2454"}
    assert {r.stock_code for r in diff.increased} == {"2308"}
    assert {r.stock_code for r in diff.decreased} == {"2330"}
    assert {r.stock_code for r in diff.unchanged} == {"2317"}


def test_increased_decreased_sort_order():
    previous = [_row("A", "A", 100, 1.0), _row("B", "B", 100, 1.0)]
    current = [_row("A", "A", 200, 2.0), _row("B", "B", 150, 1.5)]

    diff = comparer.compare(previous, current, "x", "y")
    # Largest weight increase first
    assert diff.increased[0].stock_code == "A"
    assert diff.increased[1].stock_code == "B"


def test_top_holdings_change_ranks_currently_held_top_n():
    previous = [
        _row("2330", "台積電", 100, 30.0),
        _row("2317", "鴻海", 100, 20.0),
        _row("2454", "聯發科", 100, 15.0),
    ]
    current = [
        _row("2317", "鴻海", 100, 25.0),    # now #1
        _row("2330", "台積電", 100, 24.0),  # now #2
        _row("2412", "中華電", 100, 10.0),  # new top-N entrant
    ]
    top = comparer.top_holdings_change(previous, current, n=3)
    assert top[0]["stock_code"] == "2317"
    assert top[0]["current_rank"] == 1
    assert top[0]["previous_rank"] == 2
    assert top[2]["stock_code"] == "2412"
    assert top[2]["previous_rank"] is None


def test_delta_weight_bp_is_pct_times_100():
    previous = [_row("X", "X", 100, 1.0)]
    current = [_row("X", "X", 110, 1.5)]
    diff = comparer.compare(previous, current, None, None)
    row = diff.increased[0]
    assert abs(row.delta_weight_pct - 0.5) < 1e-6
    assert abs(row.delta_weight_bp - 50.0) < 1e-6
