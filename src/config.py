"""Configuration loader for the ETF holdings agent.

Loads values from environment / .env. Never hard-codes secrets.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = os.getenv("ENV_FILE")
load_dotenv(ENV_FILE if ENV_FILE else None, override=bool(ENV_FILE))

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "etf_holdings.sqlite"
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "data" / "reports"
DEFAULT_SOURCE_ORDER = ["moneydj", "ezmoney", "official", "twse"]

# EZMoney uses internal FundCodes that differ from ETF codes.
# Add entries here when you need EZMoney support for a new ETF.
# Unknown ETFs fall back to moneydj/official/twse (ezmoney skipped).
EZMONEY_FUND_CODES: dict[str, str] = {
    "00981A": "49YTW",
}

TIMEZONE = os.getenv("TIMEZONE", "Asia/Taipei")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logger = logging.getLogger(__name__)


def _bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _email_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [
        email.strip()
        for chunk in value.split(";")
        for email in chunk.split(",")
        if email.strip()
    ]


def _list(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default.copy()
    items = [
        item.strip()
        for chunk in value.split(";")
        for item in chunk.split(",")
        if item.strip()
    ]
    return items or default.copy()


@dataclass
class GmailConfig:
    smtp_host: str
    smtp_port: int
    sender: str | None
    app_password: str | None
    receivers: list[str]
    notify_on_no_update: bool

    @property
    def is_configured(self) -> bool:
        return bool(self.sender and self.app_password and self.receivers)


@dataclass
class AppConfig:
    etf_code: str
    db_path: Path
    raw_dir: Path
    report_dir: Path
    timezone: str
    gmail: GmailConfig
    upamc_url: str
    moneydj_url: str
    twse_url: str
    ezmoney_excel_url: str
    ezmoney_referer_url: str
    source_order: list[str]


def load_config(etf_code: str = "00981A") -> AppConfig:
    configured_etf = os.getenv("ETF_CODE", etf_code)

    # EZMoney FundCode: env override → lookup table → None (skip ezmoney)
    ezmoney_fund_code: str | None = os.getenv("EZMONEY_FUND_CODE") or EZMONEY_FUND_CODES.get(configured_etf)

    db_path = Path(os.getenv("DB_PATH", str(DEFAULT_DB_PATH)))
    raw_dir = Path(os.getenv("RAW_DIR", str(DEFAULT_RAW_DIR)))
    report_dir = Path(os.getenv("REPORT_DIR", str(DEFAULT_REPORT_DIR)))

    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    gmail = GmailConfig(
        smtp_host=os.getenv("GMAIL_SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(os.getenv("GMAIL_SMTP_PORT", "587")),
        sender=os.getenv("GMAIL_SENDER_EMAIL"),
        app_password=os.getenv("GMAIL_APP_PASSWORD"),
        receivers=_email_list(
            os.getenv("GMAIL_RECEIVER_EMAILS")
            or os.getenv("GMAIL_RECEIVER_EMAIL")
        ),
        notify_on_no_update=_bool("NOTIFY_ON_NO_UPDATE", True),
    )

    # Build source_order: remove ezmoney if no fund code is known
    source_order = _list(os.getenv("SOURCE_ORDER"), DEFAULT_SOURCE_ORDER)
    if not ezmoney_fund_code and "ezmoney" in source_order:
        source_order = [s for s in source_order if s != "ezmoney"]
        logger.debug("ezmoney skipped for %s: no FundCode mapping", configured_etf)

    return AppConfig(
        etf_code=configured_etf,
        db_path=db_path,
        raw_dir=raw_dir,
        report_dir=report_dir,
        timezone=TIMEZONE,
        gmail=gmail,
        upamc_url=os.getenv(
            "UPAMC_URL",
            f"https://www.uitc.com.tw/ETF/ETFHolding?etfId={configured_etf}",
        ),
        moneydj_url=os.getenv(
            "MONEYDJ_URL",
            f"https://www.moneydj.com/etf/x/Basic/Basic0007B.xdjhtm?etfid={configured_etf}.TW",
        ),
        twse_url=os.getenv(
            "TWSE_URL",
            f"https://www.ezmoney.com.tw/ETF/Fund/Info?FundCode={ezmoney_fund_code or configured_etf}",
        ),
        ezmoney_excel_url=os.getenv(
            "EZMONEY_EXCEL_URL",
            "https://www.ezmoney.com.tw/ETF/Fund/AssetExcelNPOI"
            f"?FundCode={ezmoney_fund_code}",
        ) if ezmoney_fund_code else "",
        ezmoney_referer_url=os.getenv(
            "EZMONEY_REFERER_URL",
            "https://www.ezmoney.com.tw/ETF/Fund/Info"
            f"?FundCode={ezmoney_fund_code}",
        ) if ezmoney_fund_code else "",
        source_order=source_order,
    )


def setup_logging() -> None:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
