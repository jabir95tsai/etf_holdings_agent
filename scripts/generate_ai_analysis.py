"""Generate AI-ready analysis blocks for static ETF JSON files."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = REPO_ROOT / "site" / "data"
DEFAULT_MODEL = "gpt-5.2"
DISCLAIMER = "本分析僅為資料整理與解讀，不構成投資建議。"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _fmt_money(value: float | int | None) -> str:
    if value is None:
        return "估值待補"
    sign = "+" if value > 0 else "-" if value < 0 else ""
    amount = abs(float(value))
    if amount >= 100_000_000:
        return f"{sign}{amount / 100_000_000:.2f} 億"
    if amount >= 10_000:
        return f"{sign}{amount / 10_000:.0f} 萬"
    return f"{sign}{amount:,.0f}"


def _fmt_bp(value: float | int | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{float(value):.1f} bp"


def _stock(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    code = row.get("stock_code") or "-"
    name = row.get("stock_name") or "-"
    return f"{code} {name}"


def _compact_input(payload: dict[str, Any]) -> dict[str, Any]:
    sections = payload.get("sections", {})
    return {
        "etf": payload.get("etf"),
        "dates": payload.get("dates"),
        "summary": payload.get("summary"),
        "brief": payload.get("brief"),
        "highlights": payload.get("highlights"),
        "quality": payload.get("quality"),
        "top_increased": (sections.get("increased") or [])[:5],
        "top_decreased": (sections.get("decreased") or [])[:5],
        "new_positions": (sections.get("new_positions") or [])[:5],
        "sold_out": (sections.get("sold_out") or [])[:5],
        "top_holdings": (sections.get("top_holdings") or [])[:10],
    }


def rule_based_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    etf = payload.get("etf", {})
    summary = payload.get("summary", {})
    highlights = payload.get("highlights", {})
    quality = payload.get("quality", {})
    sections = payload.get("sections", {})
    dates = payload.get("dates", {})

    code = etf.get("code") or "ETF"
    current_count = summary.get("current_count", 0)
    new_count = summary.get("new_count", 0)
    sold_count = summary.get("sold_count", 0)
    inc_count = summary.get("increased_count", 0)
    dec_count = summary.get("decreased_count", 0)
    top_buy = highlights.get("top_buy")
    top_sell = highlights.get("top_sell")

    headline = (
        f"{code} 今日持股 {current_count} 檔，"
        f"新建倉 {new_count}、清倉 {sold_count}，"
        f"增持 {inc_count}、減持 {dec_count}。"
    )

    bullets: list[str] = []
    if top_buy:
        bullets.append(
            f"最大買進觀察為 {_stock(top_buy)}，估值變化 "
            f"{_fmt_money(top_buy.get('estimated_change_amount'))}。"
        )
    else:
        bullets.append("今日沒有明顯買進金額。")

    if top_sell:
        bullets.append(
            f"最大賣出觀察為 {_stock(top_sell)}，估值變化 "
            f"{_fmt_money(top_sell.get('estimated_change_amount'))}。"
        )
    else:
        bullets.append("今日沒有明顯賣出金額。")

    top_holdings = sections.get("top_holdings") or []
    if top_holdings:
        largest_weight = max(
            top_holdings,
            key=lambda row: abs(row.get("delta_weight_bp") or 0),
        )
        bullets.append(
            f"前十大中權重變化最大的是 {_stock(largest_weight)}，"
            f"變化 {_fmt_bp(largest_weight.get('delta_weight_bp'))}。"
        )

    if dates.get("previous") is None:
        bullets.append("目前沒有前次基準資料，第一筆資料會以全新持股呈現。")

    watchlist: list[str] = []
    for row in [top_buy, top_sell, *top_holdings[:3]]:
        label = _stock(row)
        if label and label not in watchlist:
            watchlist.append(label)

    risk_notes = list(quality.get("notes") or [])
    if not risk_notes:
        risk_notes.append("資料品質檢查未出現明顯異常。")
    risk_notes.append("持股變化不等於投資建議，仍需搭配市場與個人風險承受度判斷。")

    return {
        "provider": "rule_based",
        "model": None,
        "generated_at": _now_iso(),
        "headline": headline,
        "bullets": bullets[:4],
        "watchlist": watchlist[:5],
        "risk_notes": risk_notes[:4],
        "confidence": "medium" if dates.get("previous") else "low",
        "disclaimer": DISCLAIMER,
    }


def _extract_output_text(response: dict[str, Any]) -> str:
    if response.get("output_text"):
        return str(response["output_text"])

    chunks: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(str(content["text"]))
    return "\n".join(chunks).strip()


def _parse_json_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.S)
    if fenced:
        cleaned = fenced.group(1).strip()
    return json.loads(cleaned)


def openai_analysis(
    payload: dict[str, Any],
    *,
    api_key: str,
    model: str,
) -> dict[str, Any]:
    request_body = {
        "model": model,
        "instructions": (
            "你是台灣 ETF 持股資料分析助理。請根據輸入資料產生繁體中文解讀。"
            "請保持中立，不提供買賣建議，不預測報酬。"
            "只輸出 JSON，欄位必須包含 headline, bullets, watchlist, risk_notes, confidence。"
            "bullets、watchlist、risk_notes 都是字串陣列；confidence 只能是 low, medium, high。"
        ),
        "input": json.dumps(_compact_input(payload), ensure_ascii=False),
        "max_output_tokens": 900,
    }
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=request_body,
        timeout=60,
    )
    response.raise_for_status()
    model_payload = _parse_json_text(_extract_output_text(response.json()))

    fallback = rule_based_analysis(payload)
    return {
        "provider": "openai",
        "model": model,
        "generated_at": _now_iso(),
        "headline": str(model_payload.get("headline") or fallback["headline"]),
        "bullets": _as_list(model_payload.get("bullets")) or fallback["bullets"],
        "watchlist": _as_list(model_payload.get("watchlist")) or fallback["watchlist"],
        "risk_notes": _as_list(model_payload.get("risk_notes")) or fallback["risk_notes"],
        "confidence": (
            model_payload.get("confidence")
            if model_payload.get("confidence") in {"low", "medium", "high"}
            else fallback["confidence"]
        ),
        "disclaimer": DISCLAIMER,
    }


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()][:5]


def generate_analysis(
    payload: dict[str, Any],
    *,
    api_key: str | None,
    model: str,
    force_rule_based: bool = False,
) -> dict[str, Any]:
    if not api_key or force_rule_based:
        return rule_based_analysis(payload)

    try:
        return openai_analysis(payload, api_key=api_key, model=model)
    except Exception as exc:
        analysis = rule_based_analysis(payload)
        analysis["provider"] = "rule_based"
        analysis["fallback_reason"] = f"OpenAI analysis failed: {exc}"
        return analysis


def generate_for_file(
    path: Path,
    *,
    api_key: str | None,
    model: str,
    force_rule_based: bool = False,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["ai_analysis"] = generate_analysis(
        payload,
        api_key=api_key,
        model=model,
        force_rule_based=force_rule_based,
    )
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload["ai_analysis"]


def _target_files(input_dir: Path, etfs: list[str] | None) -> list[Path]:
    if etfs:
        return [input_dir / etf / "latest.json" for etf in etfs]
    return sorted(input_dir.glob("*/latest.json"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate static ETF AI analysis.")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--etf", action="append", dest="etfs")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--force-rule-based", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    input_dir = Path(args.input_dir)
    api_key = os.getenv("OPENAI_API_KEY")

    for path in _target_files(input_dir, args.etfs):
        if not path.exists():
            print(f"[ai-analysis] skip missing {path}")
            continue
        analysis = generate_for_file(
            path,
            api_key=api_key,
            model=args.model,
            force_rule_based=args.force_rule_based,
        )
        print(
            f"[ai-analysis] wrote {path} "
            f"provider={analysis['provider']} confidence={analysis['confidence']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
