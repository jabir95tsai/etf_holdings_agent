"""Generate Markdown + CSV reports and quality-check summaries."""

from __future__ import annotations

import csv
import html
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .comparer import DiffReport, DiffRow, top_holdings_change

logger = logging.getLogger(__name__)

DISCLAIMER = "本報告僅為資料整理，不構成投資建議。"


@dataclass
class QualityCheck:
    scrape_ok: bool = False
    has_data_date: bool = False
    is_new_data: bool = False
    rows_count: int = 0
    weight_total: float | None = None
    weight_total_ok: bool = False
    missing_codes: int = 0
    missing_names: int = 0
    duplicate_codes: int = 0
    weight_unparseable: int = 0
    shares_unparseable: int = 0
    source_used: str = ""
    notes: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        return [
            f"- 是否成功抓取：{'是' if self.scrape_ok else '否'}",
            f"- 是否為新資料：{'是' if self.is_new_data else '否'}",
            f"- 持股檔數：{self.rows_count}",
            f"- 權重總和：{self.weight_total:.2f}%" if self.weight_total is not None else "- 權重總和：N/A",
            f"- 是否有缺漏欄位：代號缺 {self.missing_codes} / 名稱缺 {self.missing_names}",
            f"- 是否有重複股票：{self.duplicate_codes}",
            f"- 使用資料來源：{self.source_used or 'N/A'}",
            f"- 異常提醒：{'; '.join(self.notes) if self.notes else '無'}",
        ]


def quality_check(
    rows: list[dict],
    *,
    scrape_ok: bool,
    is_new_data: bool,
    source_used: str,
    has_data_date: bool,
) -> QualityCheck:
    qc = QualityCheck(
        scrape_ok=scrape_ok,
        has_data_date=has_data_date,
        is_new_data=is_new_data,
        rows_count=len(rows),
        source_used=source_used,
    )

    weights = [r.get("weight_pct") for r in rows if r.get("weight_pct") is not None]
    qc.weight_unparseable = sum(1 for r in rows if r.get("weight_pct") is None)
    qc.shares_unparseable = sum(1 for r in rows if r.get("shares") is None)
    if weights:
        qc.weight_total = round(sum(weights), 4)
        # ETF holdings often add to ~95-100% (some cash); accept 80-105
        qc.weight_total_ok = 80 <= qc.weight_total <= 105

    qc.missing_codes = sum(1 for r in rows if not r.get("stock_code"))
    qc.missing_names = sum(1 for r in rows if not r.get("stock_name"))

    seen: dict[str, int] = {}
    for r in rows:
        c = r.get("stock_code")
        if c:
            seen[c] = seen.get(c, 0) + 1
    qc.duplicate_codes = sum(1 for v in seen.values() if v > 1)

    if not has_data_date:
        qc.notes.append("資料日期缺失")
    if qc.rows_count == 0:
        qc.notes.append("持股檔數為 0")
    elif qc.rows_count < 5:
        qc.notes.append(f"持股檔數異常少 ({qc.rows_count})")
    if qc.weight_total is not None and not qc.weight_total_ok:
        qc.notes.append(f"權重總和異常 ({qc.weight_total}%)")
    if qc.missing_codes > 0:
        qc.notes.append(f"{qc.missing_codes} 檔缺股票代號")
    if qc.duplicate_codes > 0:
        qc.notes.append(f"{qc.duplicate_codes} 檔股票代號重複")
    return qc


# ---------- Formatters ----------
def _fmt_int(v) -> str:
    if v is None:
        return "-"
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_pct(v) -> str:
    if v is None:
        return "-"
    return f"{v:.2f}%"


def _fmt_bp(v) -> str:
    if v is None:
        return "-"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.1f} bp"


def _fmt_delta_int(v) -> str:
    if v is None:
        return "-"
    sign = "+" if v > 0 else ""
    return f"{sign}{int(v):,}"


def _fmt_price(v) -> str:
    if v is None:
        return "-"
    return f"{v:.2f}"


def _fmt_money(v) -> str:
    if v is None:
        return "-"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:,.0f}"


def _fmt_money_compact(v) -> str:
    if v is None:
        return "-"
    sign = "+" if v > 0 else "-" if v < 0 else ""
    abs_v = abs(v)
    if abs_v >= 100_000_000:
        return f"{sign}{abs_v / 100_000_000:.2f} 億"
    if abs_v >= 10_000:
        return f"{sign}{abs_v / 10_000:.0f} 萬"
    return f"{sign}{abs_v:,.0f}"


def _html(v) -> str:
    return html.escape(str(v if v is not None else "-"))


def _amount_color(v) -> str:
    if v is None:
        return "#111111"
    if v > 0:
        return "#16a34a"
    if v < 0:
        return "#dc2626"
    return "#111111"


# ---------- Summary ----------
def build_summary(
    diff: DiffReport,
    current_count: int,
    previous_count: int,
) -> dict:
    def top(rows: list[DiffRow], key, reverse=True) -> DiffRow | None:
        if not rows:
            return None
        return sorted(rows, key=key, reverse=reverse)[0]

    increased_w = top(diff.increased, key=lambda r: r.delta_weight_bp or 0)
    decreased_w = top(diff.decreased, key=lambda r: r.delta_weight_bp or 0, reverse=False)
    increased_s = top(diff.increased, key=lambda r: r.delta_shares or 0)
    decreased_s = top(diff.decreased, key=lambda r: r.delta_shares or 0, reverse=False)

    def fmt(r: DiffRow | None, kind: str) -> str:
        if r is None:
            return "-"
        if kind == "weight":
            return f"{r.stock_code or ''} {r.stock_name or ''} ({_fmt_bp(r.delta_weight_bp)})"
        return f"{r.stock_code or ''} {r.stock_name or ''} ({_fmt_delta_int(r.delta_shares)})"

    return {
        "current_count": current_count,
        "previous_count": previous_count,
        "new_count": len(diff.new_positions),
        "sold_count": len(diff.sold_out),
        "increased_count": len(diff.increased),
        "decreased_count": len(diff.decreased),
        "top_increased_weight": fmt(increased_w, "weight"),
        "top_decreased_weight": fmt(decreased_w, "weight"),
        "top_increased_shares": fmt(increased_s, "shares"),
        "top_decreased_shares": fmt(decreased_s, "shares"),
    }


# ---------- Markdown ----------
def render_markdown(
    *,
    etf_code: str,
    run_at: datetime,
    diff: DiffReport,
    current_rows: list[dict],
    previous_rows: list[dict],
    qc: QualityCheck,
    source_used: str,
) -> str:
    summary = build_summary(diff, len(current_rows), len(previous_rows))
    top_changes = top_holdings_change(previous_rows, current_rows, n=10)

    lines: list[str] = []
    lines.append(f"# {etf_code} 每日持股變化報告\n")
    lines.append(f"- 執行時間：{run_at.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- 最新資料日期：{diff.current_date or 'N/A'}")
    lines.append(
        f"- 比較基準：{diff.current_date or 'N/A'} vs {diff.previous_date or 'N/A'}"
    )
    lines.append(f"- 資料來源：{source_used}")
    lines.append("")

    lines.append("## 一、摘要")
    lines.append(f"- 今日持股檔數：{summary['current_count']}")
    lines.append(f"- 前次持股檔數：{summary['previous_count']}")
    lines.append(f"- 新建倉：{summary['new_count']}")
    lines.append(f"- 清倉：{summary['sold_count']}")
    lines.append(f"- 增持：{summary['increased_count']}")
    lines.append(f"- 減持：{summary['decreased_count']}")
    lines.append(f"- 權重變化最大增持：{summary['top_increased_weight']}")
    lines.append(f"- 權重變化最大減持：{summary['top_decreased_weight']}")
    lines.append(f"- 股數變化最大增持：{summary['top_increased_shares']}")
    lines.append(f"- 股數變化最大減持：{summary['top_decreased_shares']}")
    lines.append("")

    lines.append("## 二、新建倉")
    if diff.new_positions:
        lines.append("| 股票代號 | 股票名稱 | 今日權重 | 今日股數 | 收盤價 | 估計變化金額 |")
        lines.append("|---|---|---:|---:|---:|---:|")
        for r in diff.new_positions:
            lines.append(
                f"| {r.stock_code or '-'} | {r.stock_name or '-'} | "
                f"{_fmt_pct(r.current_weight_pct)} | {_fmt_int(r.current_shares)} | "
                f"{_fmt_price(r.close_price)} | {_fmt_money(r.estimated_change_amount)} |"
            )
    else:
        lines.append("無")
    lines.append("")

    lines.append("## 三、清倉")
    if diff.sold_out:
        lines.append("| 股票代號 | 股票名稱 | 前次權重 | 前次股數 | 收盤價 | 估計變化金額 |")
        lines.append("|---|---|---:|---:|---:|---:|")
        for r in diff.sold_out:
            lines.append(
                f"| {r.stock_code or '-'} | {r.stock_name or '-'} | "
                f"{_fmt_pct(r.previous_weight_pct)} | {_fmt_int(r.previous_shares)} | "
                f"{_fmt_price(r.close_price)} | {_fmt_money(r.estimated_change_amount)} |"
            )
    else:
        lines.append("無")
    lines.append("")

    lines.append("## 四、增持 Top 10")
    lines.extend(_render_change_table(diff.increased[:10]))
    lines.append("")

    lines.append("## 五、減持 Top 10")
    lines.extend(_render_change_table(diff.decreased[:10]))
    lines.append("")

    lines.append("## 六、前十大持股變化")
    if top_changes:
        lines.append(
            "| 今日排名 | 前次排名 | 股票代號 | 股票名稱 | 今日權重 | 前次權重 | 權重變化 bp |"
        )
        lines.append("|---:|---:|---|---|---:|---:|---:|")
        for r in top_changes:
            lines.append(
                f"| {r['current_rank']} | {r['previous_rank'] or '-'} | "
                f"{r['stock_code'] or '-'} | {r['stock_name'] or '-'} | "
                f"{_fmt_pct(r['current_weight_pct'])} | {_fmt_pct(r['previous_weight_pct'])} | "
                f"{_fmt_bp(r['delta_weight_bp'])} |"
            )
    else:
        lines.append("無資料")
    lines.append("")

    lines.append("## 七、資料品質檢查")
    lines.extend(qc.summary_lines())
    lines.append("")

    lines.append("## 八、免責聲明")
    lines.append(DISCLAIMER)
    lines.append("")

    return "\n".join(lines)


def render_email_html(
    *,
    etf_code: str,
    run_at: datetime,
    diff: DiffReport,
    current_rows: list[dict],
    previous_rows: list[dict],
    qc: QualityCheck,
    source_used: str,
) -> str:
    """Render an email-client-friendly HTML report."""
    summary = build_summary(diff, len(current_rows), len(previous_rows))
    top_changes = top_holdings_change(previous_rows, current_rows, n=10)
    report_date = diff.current_date or run_at.strftime("%Y-%m-%d")

    top_buy = _top_amount(diff.new_positions + diff.increased, reverse=True)
    top_sell = _top_amount(diff.sold_out + diff.decreased, reverse=False)

    parts: list[str] = []
    parts.append(
        "<!DOCTYPE html><html lang='zh-Hant'><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        f"<title>{_html(etf_code)} 每日持股變化報告</title></head>"
        "<body style=\"margin:0;padding:0;background:#f5f5f0;"
        "font-family:'Helvetica Neue',Arial,sans-serif;\">"
        "<table width='100%' cellpadding='0' cellspacing='0' border='0' "
        "style='background:#f5f5f0;padding:24px 0;'><tr><td align='center'>"
        "<table width='620' cellpadding='0' cellspacing='0' border='0' "
        "style='width:620px;max-width:620px;background:#ffffff;border-radius:8px;overflow:hidden;'>"
    )
    parts.append(_render_email_header(etf_code, run_at, diff, source_used, report_date, qc.is_new_data))
    parts.append(_render_email_brief(diff, summary, top_buy, top_sell))
    parts.append(_render_email_kpis(summary))
    parts.append(_render_email_highlights(top_buy, top_sell))
    parts.append(_render_email_position_table("新建倉", diff.new_positions, "NEW", "#dcfce7", "#166534"))
    parts.append(_render_email_position_table("清倉", diff.sold_out, "OUT", "#fee2e2", "#991b1b"))
    parts.append(_render_email_change_table("增持 Top 10", diff.increased[:10], "#16a34a"))
    parts.append(_render_email_change_table("減持 Top 10", diff.decreased[:10], "#dc2626"))
    parts.append(_render_email_top_holdings(top_changes))
    parts.append(_render_email_quality(qc))
    parts.append(
        "<tr><td style='padding:20px 28px 24px;'>"
        "<div style='border-top:1px solid #eeeeee;padding-top:16px;"
        "font-size:11px;color:#aaaaaa;line-height:1.6;'>"
        f"{_html(DISCLAIMER)}<br>"
        f"自動產生 by Python · 資料來源：{_html(source_used or 'N/A')}"
        "</div></td></tr></table></td></tr></table></body></html>"
    )
    return "".join(parts)


def _render_email_header(
    etf_code: str,
    run_at: datetime,
    diff: DiffReport,
    source_used: str,
    report_date: str,
    is_new_data: bool,
) -> str:
    stale_badge = (
        "<span style='background:#fff7ed;color:#c2410c;font-size:11px;"
        "font-weight:600;padding:4px 7px;border-radius:4px;margin-left:8px;'>非新資料</span>"
        if not is_new_data else ""
    )
    return (
        "<tr><td style='background:#111111;padding:24px 28px;'>"
        "<table width='100%' cellpadding='0' cellspacing='0' border='0'><tr>"
        "<td><span style='font-size:11px;font-weight:600;letter-spacing:.12em;"
        "color:#888888;text-transform:uppercase;'>ETF 持股報告</span><br>"
        f"<span style='font-size:22px;font-weight:600;color:#ffffff;'>{_html(etf_code)}</span>"
        f"<span style='font-size:15px;font-weight:600;color:#cfcfcf;margin-left:8px;'>每日持股變化</span>{stale_badge}</td>"
        f"<td align='right' valign='bottom'><span style='font-size:12px;color:#777777;'>報告日期：{_html(report_date)}</span></td>"
        "</tr></table>"
        "<table width='100%' cellpadding='0' cellspacing='0' border='0' "
        "style='margin-top:12px;border-top:1px solid #2a2a2a;padding-top:12px;'><tr>"
        f"<td style='font-size:11px;color:#777777;'>比較基準：{_html(diff.current_date or 'N/A')} vs {_html(diff.previous_date or 'N/A')}</td>"
        f"<td align='right' style='font-size:11px;color:#777777;'>來源：{_html(source_used or 'N/A')}　執行：{_html(run_at.strftime('%H:%M'))}</td>"
        "</tr></table></td></tr>"
    )


def _render_email_brief(
    diff: DiffReport,
    summary: dict,
    top_buy: DiffRow | None,
    top_sell: DiffRow | None,
) -> str:
    buy_text = (
        f"最大買進為 {top_buy.stock_code} {top_buy.stock_name}，{_estimated_text(top_buy)}"
        if top_buy else "今日無明顯買進金額"
    )
    sell_text = (
        f"最大賣出為 {top_sell.stock_code} {top_sell.stock_name}，{_estimated_text(top_sell)}"
        if top_sell else "今日無明顯賣出金額"
    )
    text = (
        f"今日持股 {summary['current_count']} 檔，前次 {summary['previous_count']} 檔；"
        f"新建倉 {summary['new_count']} 檔、清倉 {summary['sold_count']} 檔，"
        f"實際股數增持 {summary['increased_count']} 檔、減持 {summary['decreased_count']} 檔。"
        f"{buy_text}；{sell_text}。"
    )
    return (
        "<tr><td style='padding:18px 28px 0;'>"
        "<div style='background:#f8f8f6;border-left:3px solid #111111;"
        "border-radius:0 6px 6px 0;padding:12px 14px;"
        "font-size:13px;line-height:1.7;color:#333333;'>"
        f"<span style='font-weight:600;color:#111111;'>今日重點：</span>{_html(text)}"
        "</div></td></tr>"
    )


def _estimated_text(row: DiffRow) -> str:
    if row.estimated_change_amount is None:
        return "估值待補"
    return f"估計 {_fmt_money_compact(row.estimated_change_amount)}"


def _render_email_kpis(summary: dict) -> str:
    cells = [
        ("今日持股", str(summary["current_count"]), f"前次 {summary['previous_count']} 檔", "#111111"),
        ("新建倉", f"+{summary['new_count']}", "檔新增", "#16a34a"),
        ("清倉", f"-{summary['sold_count']}", "檔出清", "#dc2626"),
        (
            "增 / 減持",
            (
                f"<span style='color:#16a34a;font-size:18px;'>增 {summary['increased_count']}</span>"
                "<span style='color:#cccccc;font-size:16px;padding:0 5px;'>/</span>"
                f"<span style='color:#dc2626;font-size:18px;'>減 {summary['decreased_count']}</span>"
            ),
            "檔異動",
            "#111111",
        ),
    ]
    out = ["<tr><td style='padding:20px 28px 0;'><table width='100%' cellpadding='0' cellspacing='0' border='0'><tr>"]
    for i, (label, value, note, color) in enumerate(cells):
        pad = "padding-right:8px;" if i < len(cells) - 1 else ""
        out.append(
            f"<td width='25%' style='{pad}'><table width='100%' cellpadding='0' cellspacing='0' border='0' "
            "style='background:#f8f8f6;border-radius:6px;'><tr><td style='padding:14px 16px;'>"
            f"<div style='font-size:10px;color:#999999;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px;'>{_html(label)}</div>"
            f"<div style=\"font-size:24px;font-weight:600;color:{color};font-family:'Courier New',monospace;\">{value}</div>"
            f"<div style='font-size:11px;color:#aaaaaa;margin-top:3px;'>{_html(note)}</div>"
            "</td></tr></table></td>"
        )
    out.append("</tr></table></td></tr>")
    return "".join(out)


def _top_amount(rows: list[DiffRow], *, reverse: bool) -> DiffRow | None:
    rows_with_amount = [r for r in rows if r.estimated_change_amount is not None]
    if rows_with_amount:
        return sorted(
            rows_with_amount,
            key=lambda r: r.estimated_change_amount or 0,
            reverse=reverse,
        )[0]
    rows_with_shares = [r for r in rows if _effective_shares_value(r) is not None]
    if not rows_with_shares:
        return None
    return sorted(
        rows_with_shares,
        key=lambda r: _effective_shares_value(r) or 0,
        reverse=reverse,
    )[0]


def _render_email_highlights(top_buy: DiffRow | None, top_sell: DiffRow | None) -> str:
    return (
        "<tr><td style='padding:12px 28px 0;'><table width='100%' cellpadding='0' cellspacing='0' border='0'><tr>"
        + _highlight_cell("最大買進標的", top_buy, "#f0fdf4", "#16a34a", "#166534")
        + _highlight_cell("最大賣出標的", top_sell, "#fef2f2", "#dc2626", "#991b1b", left_pad=True)
        + "</tr></table></td></tr>"
    )


def _highlight_cell(
    label: str,
    row: DiffRow | None,
    bg: str,
    border: str,
    label_color: str,
    *,
    left_pad: bool = False,
) -> str:
    pad = "padding-left:6px;" if left_pad else "padding-right:6px;"
    name = f"{row.stock_code or ''} {row.stock_name or ''}" if row else "-"
    amount = (
        _fmt_money_compact(row.estimated_change_amount)
        if row and row.estimated_change_amount is not None
        else "估值待補"
        if row
        else "無紀錄"
    )
    detail = ""
    if row:
        shares = _effective_shares_text(row)
        weight = row.current_weight_pct if row.current_weight_pct is not None else row.previous_weight_pct
        detail = f"股數：{shares}　權重：{_fmt_pct(weight)}"
    return (
        f"<td width='50%' style='{pad}'><table width='100%' cellpadding='0' cellspacing='0' border='0' "
        f"style='background:{bg};border-left:3px solid {border};border-radius:0 6px 6px 0;'>"
        "<tr><td style='padding:12px 14px;'>"
        f"<div style='font-size:10px;color:{label_color};text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px;'>{_html(label)}</div>"
        f"<div style='font-size:13px;font-weight:600;color:#111111;'>{_html(name.strip() or '-')}</div>"
        f"<div style=\"font-size:16px;font-weight:600;color:{border};font-family:'Courier New',monospace;\">{_html(amount)}</div>"
        f"<div style='font-size:11px;color:#777777;margin-top:3px;'>{_html(detail)}</div>"
        "</td></tr></table></td>"
    )


def _effective_shares_text(row: DiffRow) -> str:
    if row.delta_shares is not None:
        return _fmt_delta_int(row.delta_shares)
    if row.change_type == "New Position":
        return _fmt_delta_int(row.current_shares)
    if row.change_type == "Sold Out" and row.previous_shares is not None:
        return _fmt_delta_int(-row.previous_shares)
    return "-"


def _effective_shares_value(row: DiffRow) -> int | None:
    if row.delta_shares is not None:
        return row.delta_shares
    if row.change_type == "New Position" and row.current_shares is not None:
        return row.current_shares
    if row.change_type == "Sold Out" and row.previous_shares is not None:
        return -row.previous_shares
    return None


def _render_email_position_table(
    title: str,
    rows: list[DiffRow],
    badge: str,
    badge_bg: str,
    badge_color: str,
) -> str:
    if not rows:
        return _empty_email_section(title)
    out = [
        _section_start(title),
        "<tr style='background:#f8f8f6;'>",
        _th("代號"), _th("名稱"), _th("權重", right=True), _th("股數", right=True),
        _th("估值變化", right=True),
        "</tr>",
    ]
    for i, r in enumerate(rows):
        border = "border-bottom:1px solid #f0f0f0;" if i < len(rows) - 1 else ""
        shares = r.current_shares if r.change_type == "New Position" else r.previous_shares
        weight = r.current_weight_pct if r.change_type == "New Position" else r.previous_weight_pct
        out.append(
            "<tr>"
            f"<td style='font-size:13px;padding:8px 8px;{border}'>"
            f"<span style='background:{badge_bg};color:{badge_color};font-size:10px;font-weight:600;padding:2px 5px;border-radius:3px;margin-right:6px;'>{badge}</span>{_html(r.stock_code or '-')}"
            "</td>"
            + _td(r.stock_name, border=border)
            + _td(_fmt_pct(weight), right=True, mono=True, border=border)
            + _td(_fmt_int(shares), right=True, mono=True, border=border)
            + _td(_fmt_money_compact(r.estimated_change_amount), right=True, mono=True, color=_amount_color(r.estimated_change_amount), border=border)
            + "</tr>"
        )
    out.append("</table></td></tr>")
    return "".join(out)


def _render_email_change_table(title: str, rows: list[DiffRow], color: str) -> str:
    if not rows:
        return _empty_email_section(title)
    out = [
        _section_start(title),
        "<tr style='background:#f8f8f6;'>",
        _th("代號"), _th("名稱"), _th("股數 / 估值", right=True),
        _th("權重", right=True), _th("變化", right=True),
        "</tr>",
    ]
    for i, r in enumerate(rows):
        border = "border-bottom:1px solid #f0f0f0;" if i < len(rows) - 1 else ""
        out.append(
            "<tr>"
            + _td(r.stock_code, border=border)
            + _td(r.stock_name, border=border)
            + _td_stacked(
                _fmt_delta_int(r.delta_shares),
                _fmt_money_compact(r.estimated_change_amount),
                right=True,
                color=color,
                sub_color=_amount_color(r.estimated_change_amount),
                border=border,
            )
            + _td(_fmt_pct(r.current_weight_pct), right=True, mono=True, border=border)
            + _td(_fmt_bp(r.delta_weight_bp), right=True, mono=True, color=_amount_color(r.delta_weight_bp), border=border)
            + "</tr>"
        )
    out.append("</table></td></tr>")
    return "".join(out)


def _render_email_top_holdings(rows: list[dict]) -> str:
    if not rows:
        return _empty_email_section("前十大持股")
    out = [
        _section_start("前十大持股"),
        "<tr style='background:#f8f8f6;'>",
        _th("排名 / 代號"), _th("名稱"), _th("今日權重", right=True),
        _th("前次權重", right=True), _th("變化", right=True),
        "</tr>",
    ]
    for i, r in enumerate(rows):
        border = "border-bottom:1px solid #f0f0f0;" if i < len(rows) - 1 else ""
        bp = r.get("delta_weight_bp")
        out.append(
            "<tr>"
            + _td_html(_rank_code_cell(r), mono=True, border=border)
            + _td(r.get("stock_name"), border=border)
            + _td(_fmt_pct(r.get("current_weight_pct")), right=True, mono=True, color="#111111", border=border)
            + _td(_fmt_pct(r.get("previous_weight_pct")), right=True, mono=True, color="#aaaaaa", border=border)
            + _td(_fmt_bp(bp), right=True, mono=True, color=_amount_color(bp), border=border)
            + "</tr>"
        )
    out.append("</table></td></tr>")
    return "".join(out)


def _rank_code_cell(row: dict) -> str:
    rank = row.get("current_rank")
    code = row.get("stock_code") or "-"
    return (
        "<span style='display:inline-block;min-width:18px;color:#111111;text-align:right;"
        f"margin-right:7px;'>{_html(rank)}</span>"
        f"{_rank_badge_html(row)}"
        "<span style='display:inline-block;margin-left:7px;color:#333333;'>"
        f"{_html(code)}</span>"
    )


def _rank_badge(row: dict) -> str:
    current_rank = row.get("current_rank")
    previous_rank = row.get("previous_rank")
    if current_rank is None:
        return "-"
    if previous_rank is None:
        return "NEW"
    delta = previous_rank - current_rank
    if delta > 0:
        return f"▲{delta}"
    if delta < 0:
        return f"▼{abs(delta)}"
    return "-"


def _rank_badge_color(row: dict) -> str:
    badge = _rank_badge(row)
    if badge.startswith("▲") or badge == "NEW":
        return "#16a34a"
    if badge.startswith("▼"):
        return "#dc2626"
    return "#999999"


def _rank_badge_html(row: dict) -> str:
    badge = _rank_badge(row)
    if badge.startswith("▲") or badge == "NEW":
        bg = "#dcfce7"
        color = "#166534"
    elif badge.startswith("▼"):
        bg = "#fee2e2"
        color = "#991b1b"
    else:
        bg = "#f1f5f9"
        color = "#64748b"
    return (
        f"<span style='display:inline-block;min-width:28px;text-align:center;"
        f"background:{bg};color:{color};font-size:11px;font-weight:600;"
        "padding:2px 5px;border-radius:4px;'>"
        f"{_html(badge)}</span>"
    )


def _render_email_quality(qc: QualityCheck) -> str:
    left = [
        ("成功抓取", _quality_value("是" if qc.scrape_ok else "否", "#16a34a" if qc.scrape_ok else "#dc2626")),
        ("持股檔數", _html(str(qc.rows_count))),
        ("權重總和", _html(f"{qc.weight_total:.2f}%" if qc.weight_total is not None else "N/A")),
    ]
    right = [
        (
            "是否為新資料",
            _quality_badge("是", "#dcfce7", "#166534") if qc.is_new_data
            else _quality_badge("非新資料", "#ffedd5", "#c2410c"),
        ),
        ("缺漏欄位", _html(f"代號 {qc.missing_codes} / 名稱 {qc.missing_names}")),
        (
            "重複股票",
            _quality_value(str(qc.duplicate_codes), "#16a34a" if qc.duplicate_codes == 0 else "#dc2626"),
        ),
    ]
    return (
        "<tr><td style='padding:24px 28px 0;'>"
        "<div style='font-size:10px;font-weight:600;letter-spacing:.1em;color:#888888;text-transform:uppercase;border-bottom:1px solid #eeeeee;padding-bottom:8px;'>"
        "<span style='border-bottom:2px solid #64748b;padding-bottom:7px;'>資料品質</span></div>"
        "<table width='100%' cellpadding='0' cellspacing='0' border='0'><tr>"
        f"<td width='50%' style='vertical-align:top;padding-right:12px;'>{_quality_table(left)}</td>"
        f"<td width='50%' style='vertical-align:top;padding-left:12px;'>{_quality_table(right)}</td>"
        "</tr></table></td></tr>"
    )


def _quality_value(value: str, color: str) -> str:
    return f"<span style='color:{color};font-weight:600;'>{_html(value)}</span>"


def _quality_badge(value: str, bg: str, color: str) -> str:
    return (
        f"<span style='background:{bg};color:{color};font-size:11px;"
        "font-weight:600;padding:3px 7px;border-radius:4px;'>"
        f"{_html(value)}</span>"
    )


def _quality_table(rows: list[tuple[str, str]]) -> str:
    out = ["<table width='100%' cellpadding='0' cellspacing='0' border='0'>"]
    for i, (label, value) in enumerate(rows):
        border = "border-bottom:1px solid #f0f0f0;" if i < len(rows) - 1 else ""
        out.append(
            "<tr>"
            f"<td style='font-size:12px;color:#888888;padding:5px 0;{border}'>{_html(label)}</td>"
            f"<td align='right' style='font-size:12px;color:#111111;font-weight:600;padding:5px 0;{border}'>{value}</td>"
            "</tr>"
        )
    out.append("</table>")
    return "".join(out)


def _section_start(title: str) -> str:
    accent = _section_accent(title)
    return (
        "<tr><td style='padding:24px 28px 0;'>"
        "<div style='font-size:10px;font-weight:600;letter-spacing:.1em;color:#888888;text-transform:uppercase;"
        "border-bottom:1px solid #eeeeee;padding-bottom:8px;margin-bottom:4px;'>"
        f"<span style='border-bottom:2px solid {accent};padding-bottom:7px;'>{_html(title)}</span></div>"
        "<table width='100%' cellpadding='0' cellspacing='0' border='0'>"
    )


def _section_accent(title: str) -> str:
    if "新建" in title or "增持" in title:
        return "#16a34a"
    if "清倉" in title or "減持" in title:
        return "#dc2626"
    if "資料" in title:
        return "#64748b"
    return "#111111"


def _empty_email_section(title: str) -> str:
    message = _empty_message(title)
    accent = _section_accent(title)
    bg = "#f0fdf4" if "減持" in title else "#f8f8f6"
    color = "#166534" if "減持" in title else "#777777"
    return (
        _section_start(title)
        + f"<tr><td style='font-size:13px;color:{color};padding:12px 14px;background:{bg};"
        + f"border-left:3px solid {accent};border-radius:0 6px 6px 0;'>{_html(message)}</td></tr>"
        + "</table></td></tr>"
    )


def _empty_message(title: str) -> str:
    if "減持" in title:
        return "今日無減持紀錄"
    if "增持" in title:
        return "今日無增持紀錄"
    if "新建" in title:
        return "今日無新建倉"
    if "清倉" in title:
        return "今日無清倉紀錄"
    return "目前無資料"


def _th(label: str, *, right: bool = False) -> str:
    align = "right" if right else "left"
    return f"<td align='{align}' style='font-size:11px;color:#999999;padding:7px 8px;'>{_html(label)}</td>"


def _td(
    value,
    *,
    right: bool = False,
    mono: bool = False,
    color: str = "#333333",
    border: str = "",
) -> str:
    align = "right" if right else "left"
    font = "font-family:'Courier New',monospace;" if mono else ""
    return (
        f"<td align='{align}' style='font-size:13px;color:{color};{font}"
        f"padding:8px 8px;{border}'>{_html(value)}</td>"
    )


def _td_html(
    value_html: str,
    *,
    right: bool = False,
    mono: bool = False,
    color: str = "#333333",
    border: str = "",
) -> str:
    align = "right" if right else "left"
    font = "font-family:'Courier New',monospace;" if mono else ""
    return (
        f"<td align='{align}' style='font-size:13px;color:{color};{font}"
        f"padding:8px 8px;{border}'>{value_html}</td>"
    )


def _td_stacked(
    primary,
    secondary,
    *,
    right: bool = False,
    color: str = "#333333",
    sub_color: str = "#777777",
    border: str = "",
) -> str:
    align = "right" if right else "left"
    return (
        f"<td align='{align}' style=\"font-size:13px;color:{color};"
        f"font-family:'Courier New',monospace;padding:8px 8px;{border}\">"
        f"<div>{_html(primary)}</div>"
        f"<div style='font-size:11px;color:{sub_color};margin-top:2px;'>{_html(secondary)}</div>"
        "</td>"
    )


def _render_change_table(rows: list[DiffRow]) -> list[str]:
    if not rows:
        return ["無"]
    out = [
        "| 股票代號 | 股票名稱 | 前次股數 | 今日股數 | 股數變化 | 收盤價 | 估計變化金額 | 前次權重 | 今日權重 | 權重變化 bp |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        out.append(
            f"| {r.stock_code or '-'} | {r.stock_name or '-'} | "
            f"{_fmt_int(r.previous_shares)} | {_fmt_int(r.current_shares)} | "
            f"{_fmt_delta_int(r.delta_shares)} | "
            f"{_fmt_price(r.close_price)} | {_fmt_money(r.estimated_change_amount)} | "
            f"{_fmt_pct(r.previous_weight_pct)} | {_fmt_pct(r.current_weight_pct)} | "
            f"{_fmt_bp(r.delta_weight_bp)} |"
        )
    return out


# ---------- CSV ----------
def write_csv(path: Path, diff: DiffReport) -> None:
    fields = [
        "change_type",
        "stock_code",
        "stock_name",
        "previous_shares",
        "current_shares",
        "delta_shares",
        "previous_weight_pct",
        "current_weight_pct",
        "delta_weight_pct",
        "delta_weight_bp",
        "close_price",
        "estimated_change_amount",
        "abs_delta_weight_rank",
        "abs_delta_shares_rank",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in diff.all_rows:
            writer.writerow({k: r.to_dict().get(k) for k in fields})


def write_markdown(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def report_paths(report_dir: Path, etf_code: str, date: str) -> tuple[Path, Path]:
    md = report_dir / f"{etf_code}_diff_{date}.md"
    csv_p = report_dir / f"{etf_code}_diff_{date}.csv"
    return md, csv_p


# ---------- No-update / failure messages ----------
def render_no_update_md(
    etf_code: str,
    run_at: datetime,
    db_latest_date: str | None,
    scraped_date: str | None,
) -> str:
    return (
        f"# {etf_code} 每日持股追蹤\n\n"
        f"- 執行時間：{run_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"- 資料狀態：尚無新資料\n"
        f"- 目前資料庫最新日期：{db_latest_date or 'N/A'}\n"
        f"- 本次抓到資料日期：{scraped_date or 'N/A'}\n\n"
        f"可能原因：\n"
        f"- 今日為非交易日\n"
        f"- ETF 官方資料尚未更新\n"
        f"- 備援資料源尚未同步\n\n"
        f"{DISCLAIMER}\n"
    )


def render_failure_md(
    etf_code: str,
    run_at: datetime,
    stage: str,
    error: str,
    source_used: str,
) -> str:
    return (
        f"# {etf_code} 持股追蹤執行失敗\n\n"
        f"- 執行時間：{run_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"- 錯誤階段：{stage}\n"
        f"- 錯誤訊息：{error}\n"
        f"- 使用資料來源：{source_used or 'N/A'}\n\n"
        f"建議檢查：\n"
        f"- 資料來源網址是否變更\n"
        f"- GitHub Actions Secrets 是否正確\n"
        f"- Gmail App Password 是否有效\n"
        f"- requirements 是否安裝成功\n\n"
        f"本報告僅為系統錯誤通知，不構成投資建議。\n"
    )
