"""Generate Markdown + CSV reports and quality-check summaries."""

from __future__ import annotations

import csv
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
        lines.append("| 股票代號 | 股票名稱 | 今日權重 | 今日股數 |")
        lines.append("|---|---|---:|---:|")
        for r in diff.new_positions:
            lines.append(
                f"| {r.stock_code or '-'} | {r.stock_name or '-'} | "
                f"{_fmt_pct(r.current_weight_pct)} | {_fmt_int(r.current_shares)} |"
            )
    else:
        lines.append("無")
    lines.append("")

    lines.append("## 三、清倉")
    if diff.sold_out:
        lines.append("| 股票代號 | 股票名稱 | 前次權重 | 前次股數 |")
        lines.append("|---|---|---:|---:|")
        for r in diff.sold_out:
            lines.append(
                f"| {r.stock_code or '-'} | {r.stock_name or '-'} | "
                f"{_fmt_pct(r.previous_weight_pct)} | {_fmt_int(r.previous_shares)} |"
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


def _render_change_table(rows: list[DiffRow]) -> list[str]:
    if not rows:
        return ["無"]
    out = [
        "| 股票代號 | 股票名稱 | 前次股數 | 今日股數 | 股數變化 | 前次權重 | 今日權重 | 權重變化 bp |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        out.append(
            f"| {r.stock_code or '-'} | {r.stock_name or '-'} | "
            f"{_fmt_int(r.previous_shares)} | {_fmt_int(r.current_shares)} | "
            f"{_fmt_delta_int(r.delta_shares)} | "
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
