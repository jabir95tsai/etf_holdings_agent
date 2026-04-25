"""Gmail SMTP notifier. Never crashes on missing credentials."""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from .config import GmailConfig

logger = logging.getLogger(__name__)


def _build_message(
    cfg: GmailConfig,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    attachments: list[Path] | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.sender or ""
    msg["To"] = cfg.receiver or ""
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    for path in attachments or []:
        try:
            data = Path(path).read_bytes()
            msg.add_attachment(
                data,
                maintype="text",
                subtype="markdown",
                filename=Path(path).name,
            )
        except Exception as e:
            logger.warning("Failed to attach %s: %s", path, e)
    return msg


def send_email(
    cfg: GmailConfig,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    attachments: list[Path] | None = None,
) -> bool:
    """Send an email. Returns True on success, False otherwise. Never raises."""
    if not cfg.is_configured:
        logger.warning(
            "Gmail not configured (sender/app_password/receiver missing). "
            "Skipping email."
        )
        return False
    msg = _build_message(cfg, subject, body_text, body_html, attachments)
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(cfg.sender, cfg.app_password)
            smtp.send_message(msg)
        logger.info("Email sent: %s", subject)
        return True
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        return False


# ---------- Subject builders ----------
def subject_diff(etf_code: str, date: str, summary: dict) -> str:
    return (
        f"[{etf_code}持股變化] {date} "
        f"新建倉 {summary['new_count']} 檔、清倉 {summary['sold_count']} 檔、"
        f"增持 {summary['increased_count']} 檔、減持 {summary['decreased_count']} 檔"
    )


def subject_no_update(etf_code: str, date: str) -> str:
    return f"[{etf_code}持股變化] {date} 尚無新資料"


def subject_failure(etf_code: str, date: str) -> str:
    return f"[{etf_code}持股追蹤失敗] {date} 請檢查資料來源或程式錯誤"


# ---------- HTML body wrapper for mobile ----------
def md_to_simple_html(md_text: str) -> str:
    """Very lightweight Markdown -> HTML for mobile-friendly viewing.
    We do not pull a full markdown lib; we wrap in <pre> for fidelity.
    """
    safe = (
        md_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return (
        "<html><body style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
        "font-size:14px;line-height:1.5;'>"
        f"<pre style='white-space:pre-wrap;word-break:break-word;'>{safe}</pre>"
        "</body></html>"
    )


# ---------- Test email ----------
def send_test(cfg: GmailConfig) -> bool:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return send_email(
        cfg,
        subject="[ETF Agent] Gmail 測試通知",
        body_text=f"This is a Gmail SMTP test from the ETF holdings agent at {now}.",
        body_html=f"<p>Gmail SMTP test OK at <b>{now}</b>.</p>",
    )
